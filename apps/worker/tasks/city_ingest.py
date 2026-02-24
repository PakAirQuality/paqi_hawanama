"""
City-Level Hourly Ingestion (manifest-driven, city endpoint)
Consumes the *derived city manifest* produced by station_discovery.py.

- Primary source: artifacts/city_manifests/latest.(parquet|jsonl)
- Automatic fallback: derive unique (country,state,city[,lat,lon]) from
  artifacts/station_manifests/latest.(parquet|jsonl) if city manifest missing.
- Optional fallback: query DB for cities if ALLOW_DB_CITY_FALLBACK=true.
- Strictly uses the IQAir /v2/city endpoint (with optional state-alias retries).
- Optional fallback to /v2/nearest_city when enabled and coords exist.
- Global rate limiter (default 90/min) + bounded concurrency (default 6).
- Writes a per-run ingest report (metrics + failures).
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# --- PATH SHIM: allows `python tasks/run_city_now.py` to import `services.*` ---
import sys as _sys, pathlib as _pl
_root = str(_pl.Path(__file__).resolve().parents[1])
if _root not in _sys.path:
    _sys.path.insert(0, _root)
# ------------------------------------------------------------------------------------

# Dual-path imports for API container compatibility
try:
    from app.services.ingestion.iqair_service import IQAirClient
    from app.services.database import DatabaseService, AsyncSessionLocal
except ImportError:  # running in pure worker repo layout
    from services.iqair_client import IQAirClient
    from services.database import DatabaseService, AsyncSessionLocal

# -------- logging: ensure something shows up even if caller didn't configure --------
if not logging.getLogger().handlers:
    _lvl = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, _lvl, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
logger = logging.getLogger(__name__)

# Optional pandas (for Parquet manifest)
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    pd = None
    _HAVE_PANDAS = False

# ---- aliasing to deal with label mismatches between /cities and /city endpoints ----
# Uses shared South Asia config for per-country aliases.
try:
    from app.core.south_asia import get_state_aliases as _get_state_aliases_sa, get_iqair_countries
except ImportError:
    from core.south_asia import get_state_aliases as _get_state_aliases_sa, get_iqair_countries

def _state_aliases(state: Optional[str], country: Optional[str] = None) -> List[str]:
    if not state:
        return []
    if country:
        return _get_state_aliases_sa(country, state)
    return [state]

def _scope_key(country: str, state: str, city: str) -> str:
    return f"{country.lower()}|{state.lower()}|{city.lower()}"

# ---------- Time helpers (copied from station worker) ----------
def _norm_hour(dt: datetime) -> datetime:
    """Floor to the exact hour (UTC-aware in/out)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

def _approx_one_hour(a: datetime, b: datetime) -> bool:
    """True if a - b ≈ 1h (tolerates small jitters)."""
    return abs((a - b) - timedelta(hours=1)) <= timedelta(minutes=10)
# ----------------------------------------------------------------------

class _AsyncRateLimiter:
    """
    Smooth global rate limiter (token spacing). Guarantees average <= rate/min.
    """
    def __init__(self, per_minute: int):
        per_minute = max(1, per_minute)
        self._interval = 60.0 / float(per_minute)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self):
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self._next <= now:
                self._next = now + self._interval
                return
            delay = self._next - now
            self._next += self._interval
        await asyncio.sleep(delay)


class CityIngestionTask:
    """Manifest-driven city-level ingestion (IQAir /v2/city)."""

    def __init__(self):
        self.iqair_client = IQAirClient()
        self.db_service = DatabaseService()

        # Concurrency and rate limiting
        self._concurrency = int(os.getenv("INGEST_CONCURRENCY", "6"))
        self._sema = asyncio.Semaphore(self._concurrency)
        self._rate = int(os.getenv("IQAIR_MAX_CALLS_PER_MIN", "90"))
        self._limiter = _AsyncRateLimiter(self._rate)

        # Toggles
        self._allow_state_alias      = os.getenv("ALLOW_STATE_ALIAS", "true").lower() in {"1", "true", "yes"}
        self._allow_nearest_fallback = os.getenv("ALLOW_NEAREST_FALLBACK", "false").lower() in {"1", "true", "yes"}
        self._db_city_fallback       = os.getenv("ALLOW_DB_CITY_FALLBACK", "false").lower() in {"1", "true", "yes"}

        # Manifest locations (produced by station_discovery.py)
        self._city_manifest_dir    = Path(os.getenv("CITY_MANIFEST_DIR", "artifacts/city_manifests"))
        self._station_manifest_dir = Path(os.getenv("STATION_MANIFEST_DIR", "artifacts/station_manifests"))

        # Ingest run output
        ts = datetime.now(timezone.utc).isoformat()
        self._run_id = f"ingest-city-{ts}"
        self._out_dir = Path(os.getenv("INGEST_OUT_DIR", "artifacts/ingest_runs")) / self._run_id
        self._out_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------- manifest loading ---------------------------

    def _prefer_existing(self, base: Path, gcs_prefix: str = "") -> Optional[Path]:
        """Return latest.parquet if exists else latest.jsonl if exists, else try GCS, else None."""
        p_parq = base / "latest.parquet"
        p_json = base / "latest.jsonl"
        if p_parq.exists():
            return p_parq
        if p_json.exists():
            return p_json

        # GCS fallback: try downloading if local files missing
        if gcs_prefix:
            try:
                from app.manifest_utils import ensure_latest_from_gcs
            except ImportError:
                from manifest_utils import ensure_latest_from_gcs
            gcs_result = ensure_latest_from_gcs(base, "parquet", gcs_prefix)
            if gcs_result:
                logger.info("Recovered manifest from GCS: %s", gcs_result)
                return gcs_result

        return None

    def _resolve_latest_city_manifest_path(self) -> Optional[Path]:
        return self._prefer_existing(self._city_manifest_dir, gcs_prefix="manifests/city_manifests")

    def _resolve_latest_station_manifest_path(self) -> Optional[Path]:
        return self._prefer_existing(self._station_manifest_dir, gcs_prefix="manifests/station_manifests")

    def _read_parquet(self, path: Path) -> List[Dict[str, Any]]:
        if not _HAVE_PANDAS:
            logger.error("pandas is required to read parquet manifest: %s", path)
            return []
        try:
            df = pd.read_parquet(path)
            return df.to_dict("records")
        except Exception as e:
            logger.error("Failed reading parquet %s: %s", path, e)
            return []

    def _read_jsonl(self, path: Path) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rows.append(json.loads(line))
                    except Exception as e:
                        logger.warning("Skipping malformed JSONL line in %s: %s", path, e)
        except FileNotFoundError:
            logger.error("JSONL manifest not found: %s", path)
        return rows

    def _load_city_manifest(self) -> List[Dict[str, Any]]:
        """
        Try city manifest first (preferred). If missing, derive from station manifest:
        group by (country,state,city), compute simple centroid of lat/lon, build rows compatible
        with station_discovery's derived city manifest keys.
        """
        p = self._resolve_latest_city_manifest_path()
        if p:
            logger.info("Using city manifest: %s", p)
            rows = self._read_parquet(p) if p.suffix == ".parquet" else self._read_jsonl(p)
            return rows

        # Fallback: derive from station manifest
        ps = self._resolve_latest_station_manifest_path()
        if not ps:
            logger.error("No city manifest at %s and no station manifest at %s", self._city_manifest_dir, self._station_manifest_dir)
            return []

        logger.info("Deriving city list from station manifest: %s", ps)
        srows = self._read_parquet(ps) if ps.suffix == ".parquet" else self._read_jsonl(ps)
        if not srows:
            logger.error("Station manifest is empty or unreadable: %s", ps)
            return []

        groups = defaultdict(list)  # (country,state,city) -> [(lat,lon), ...]
        for r in srows:
            if r.get("active") is False:
                continue
            country, state, city = r.get("country"), r.get("state"), r.get("city")
            if not (country and state and city):
                continue
            lat = r.get("lat") if r.get("lat") is not None else r.get("latitude")
            lon = r.get("lon") if r.get("lon") is not None else r.get("longitude")
            try:
                lat_f = float(lat) if lat is not None else None
                lon_f = float(lon) if lon is not None else None
            except Exception:
                lat_f, lon_f = None, None
            groups[(country, state, city)].append((lat_f, lon_f))

        out: List[Dict[str, Any]] = []
        for (country, state, city), coords in groups.items():
            lats = [la for la, _ in coords if la is not None]
            lons = [lo for _, lo in coords if lo is not None]
            lat = sum(lats) / len(lats) if lats else None
            lon = sum(lons) / len(lons) if lons else None
            out.append({
                "run_id": "derived-from-stations",
                "country": country,
                "state": state,
                "city": city,
                "lat": lat,
                "lon": lon,
                "active": True,
                "scope_key": _scope_key(country, state, city),
                "last_seen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })

        logger.info("Derived %d unique cities from station manifest.", len(out))
        return out

    async def _list_cities_from_db(self, country: str) -> List[Dict[str, Any]]:
        """
        Optional DB fallback if both manifests are missing/empty and ALLOW_DB_CITY_FALLBACK=true.
        Returns dicts with keys: country, state, city, lat, lon, active (assume True), scope_key
        """
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            q = text("""
                SELECT 
                    co.name  AS country,
                    s.name   AS state,
                    c.name   AS city,
                    c.latitude AS lat,
                    c.longitude AS lon
                FROM cities c
                JOIN states s   ON c.state_id = s.id
                JOIN countries co ON s.country_id = co.id
                WHERE LOWER(co.name) = LOWER(:country)
                ORDER BY c.name
            """)
            rs = await session.execute(q, {"country": country})
            out: List[Dict[str, Any]] = []
            for row in rs.fetchall():
                m = dict(row._mapping)
                m["active"] = True
                m["scope_key"] = _scope_key(m["country"], m["state"], m["city"])
                out.append(m)
            return out

    # ----------------------------- public API --------------------------------

    async def fetch_city_readings_hourly(self, country: Optional[str] = None) -> Dict[str, Any]:
        """
        Hourly city ingestion job – reads cities from manifest (or derives from station manifest / DB),
        fetches /v2/city for each, normalizes, and bulk upserts readings.

        If country is None, ingests all countries from IQAIR_COUNTRIES config.
        If country is provided, ingests only that single country (backwards-compatible).
        """
        target_countries = [country] if country else get_iqair_countries()
        country_set = {c.lower() for c in target_countries}

        logger.info(
            "Starting city ingestion (manifest mode). countries=%s, concurrency=%d, rate<=%d/min, "
            "alias=%s, nearest_fallback=%s, db_city_fallback=%s",
            target_countries, self._concurrency, self._rate, self._allow_state_alias, self._allow_nearest_fallback, self._db_city_fallback
        )

        rows = self._load_city_manifest()
        if not rows and self._db_city_fallback:
            logger.info("City manifest empty → using DB fallback for countries=%s", target_countries)
            for tc in target_countries:
                rows.extend(await self._list_cities_from_db(tc))

        if not rows:
            return {
                "status": "success",
                "countries": target_countries,
                "cities_processed": 0,
                "readings_ingested": 0,
                "errors": 0,
                "run_id": self._run_id,
                "report_dir": str(self._out_dir),
            }

        # Filter to target countries + active, dedupe (city,state,country)
        seen = set()
        cities: List[Dict[str, Any]] = []
        for r in rows:
            if (r.get("country") or "").lower() not in country_set:
                continue
            if r.get("active") is False:
                continue
            tup = (r.get("city"), r.get("state"), r.get("country"))
            if None in tup:
                continue
            if tup in seen:
                continue
            seen.add(tup)
            # standardize keys we need later
            r["scope_key"] = r.get("scope_key") or _scope_key(r["country"], r["state"], r["city"])
            cities.append(r)

        logger.info("Will request city endpoint for %d cities.", len(cities))

        tasks = [self._fetch_one_city(c) for c in cities]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        ingested, failed = 0, 0
        buf: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        for i, res in enumerate(results):
            meta = {
                "scope_key": cities[i]["scope_key"],
                "city": cities[i]["city"],
                "state": cities[i]["state"],
                "country": cities[i]["country"],
            }
            if isinstance(res, Exception):
                failed += 1
                failures.append({**meta, "error": f"{type(res).__name__}: {res}"})
            elif res:
                ingested += 1
                # res is now a list of readings, extend buf with all readings
                if isinstance(res, list):
                    buf.extend(res)
                else:
                    buf.append(res)
            else:
                failed += 1
                failures.append({**meta, "error": "empty_result"})

        if buf:
            await self._bulk_write_readings(buf)
            logger.info("Bulk upserted %d city readings.", len(buf))

        self._write_report(success_count=ingested, fail_entries=failures)

        logger.info("City ingestion complete. Cities=%d Readings=%d Failed=%d (out: %s)", ingested, len(buf), failed, self._out_dir)
        return {
            "status": "success",
            "cities_processed": len(cities),
            "readings_ingested": len(buf),
            "errors": failed,
            "run_id": self._run_id,
            "report_dir": str(self._out_dir),
        }

    # --------------------------- helpers -------------------------------------

    async def _fetch_one_city(self, row: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch one city via /v2/city with optional state-alias retries.
        If enabled and lat/lon present, fallback to /v2/nearest_city.
        """
        async with self._sema:
            city = row.get("city")
            state = row.get("state")
            country = row.get("country") or ""
            scope_key = row["scope_key"]

            states_to_try = [state] if state else []
            if self._allow_state_alias:
                for a in _state_aliases(state, country)[1:]:
                    states_to_try.append(a)

            last_exc: Optional[Exception] = None

            # Try exact + alias states
            for idx, state_try in enumerate(states_to_try or [state]):
                try:
                    await self._limiter.wait()
                    raw = await self.iqair_client.get_city_data(city=city, state=state_try, country=country)
                    parsed = self.iqair_client.parse_city_data(raw)
                    readings = self._normalize_city_readings(parsed, scope_key)
                    return readings
                except Exception as e:
                    last_exc = e
                    emsg = str(e).lower()
                    if "not_found" in emsg or "city_not_found" in emsg:
                        logger.info(
                            "City not found: '%s, %s, %s' (try %d/%d).",
                            city, state_try, country, idx + 1, len(states_to_try or [state])
                        )
                        continue
                    logger.warning("City API error for %s (%s, %s): %s", city, state_try, country, e)
                    # Continue trying aliases unless it's clearly unrecoverable.

            # Optional nearest_city fallback
            if self._allow_nearest_fallback:
                lat = row.get("lat") or row.get("latitude")
                lon = row.get("lon") or row.get("longitude")
                if lat is not None and lon is not None:
                    try:
                        await self._limiter.wait()
                        raw = await self.iqair_client.get_nearest_city_data(lat=float(lat), lon=float(lon))
                        parsed = self.iqair_client.parse_city_data(raw)
                        readings = self._normalize_city_readings(parsed, scope_key)
                        logger.info("Used nearest_city fallback for %s (%.4f, %.4f)", scope_key, lat, lon)
                        return readings
                    except Exception as e2:
                        logger.warning("Nearest-city fallback failed for %s: %s", scope_key, e2)
                        if last_exc:
                            raise last_exc
                        raise e2

            if last_exc:
                raise last_exc
            return None

    def _normalize_city_current(self, parsed: Dict[str, Any], scope_key: str) -> Optional[Dict[str, Any]]:
        """
        Normalize IQAir city parsed payload (from IQAirClient.parse_city_data)
        into the new Timescale schema (scope_type='city').
        """
        try:
            # Extract from current data (city API provides current + history structure)
            current = parsed.get("current", {}) or {}
            pollution = current.get("pollution", {}) or {}
            weather = current.get("weather", {}) or {}
            ts_str = pollution.get("ts") or parsed.get("timestamp")

            if ts_str:
                try:
                    if ts_str.endswith("Z"):
                        ts_utc = datetime.fromisoformat(ts_str[:-1]).replace(tzinfo=timezone.utc)
                    else:
                        ts_utc = datetime.fromisoformat(ts_str.replace("Z", "")).replace(tzinfo=timezone.utc)
                except Exception:
                    ts_utc = datetime.now(timezone.utc)
            else:
                ts_utc = datetime.now(timezone.utc)

            ts_utc = ts_utc.replace(minute=0, second=0, microsecond=0)  # hour-floor

            # Map main pollutant codes p1->pm10, p2->pm25 like station path
            pollutant_mapping = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}
            main_us = pollution.get("mainus")
            main_cn = pollution.get("maincn")

            # Some IQAir plans expose p2/p1 details as {conc:...} under pollution; your parser already surfaces:
            # Extract PM2.5 from the nested p2 structure that IQAir uses
            pm25 = (pollution.get("p2") or {}).get("conc")
            # Fallback to direct key if nested structure not available  
            if pm25 is None:
                pm25 = pollution.get("pm25_conc")
            # Extract PM10 from the nested p1 structure
            pm10 = (pollution.get("p1") or {}).get("conc")
            if pm10 is None:
                pm10 = pollution.get("pm10_conc")

            # If your parse_city_data didn’t materialize *_conc, try fallback keys:
            # Remove redundant fallback code (already handled above)

            return {
                "scope_type": "city",
                "scope_key": scope_key,
                "ts_utc": ts_utc,

                # AQI
                "aqi_us": pollution.get("aqius"),
                "aqi_cn": pollution.get("aqicn"),
                "main_us": pollutant_mapping.get(main_us, main_us) if main_us else None,
                "main_cn": pollutant_mapping.get(main_cn, main_cn) if main_cn else None,

                # Pollutants (concentrations)
                "pm25": pm25,
                "pm10": pm10,
                "o3": pollution.get("o3_conc"),
                "no2": pollution.get("no2_conc"),
                "so2": pollution.get("so2_conc"),
                "co": pollution.get("co_conc"),

                # Units
                "units_pm25": "µg/m³",
                "units_pm10": "µg/m³",
                "units_o3": "ppb",
                "units_no2": "ppb",
                "units_so2": "ppb",
                "units_co": "ppm",

                # Weather
                "temp_c": weather.get("tp"),  # IQAir uses 'tp' for temperature
                "humidity": weather.get("hu"),  # IQAir uses 'hu' for humidity
                "pressure_hpa": weather.get("pr"),  # IQAir uses 'pr' for pressure
                "wind_speed_ms": weather.get("ws"),  # IQAir uses 'ws' for wind speed
                "wind_dir_deg": weather.get("wd"),  # IQAir uses 'wd' for wind direction
                "weather_icon": weather.get("ic"),  # IQAir uses 'ic' for icon
                "heatindex_c": weather.get("heatIndex"),  # IQAir uses 'heatIndex'
                "pop_pct": weather.get("precipitation_probability"),

                # QC + provenance
                "qc_state": "OK",
                "source": "airvisual",
                "raw": json.dumps(parsed.get("raw_response", {})),
            }
        except Exception as e:
            logger.warning("Failed to normalize city payload for %s: %s", scope_key, e)
            return None

    def _normalize_city_readings(self, parsed: Dict[str, Any], scope_key: str) -> List[Dict[str, Any]]:
        """
        Normalize IQAir city parsed payload into multiple readings from both current and history.pollution.
        Includes lag handling to prevent duplicates between current and historical data.
        Returns a list of readings for all available timestamps.
        """
        readings = []
        
        try:
            # Get raw response for fallback data
            raw_response = parsed.get("raw_response", {})
            
            # Process current reading first and extract its timestamp
            current = parsed.get("current", {}) or {}
            current_ts = None
            if current:
                reading = self._normalize_single_city_reading(current, scope_key, raw_response, is_current=True)
                if reading:
                    readings.append(reading)
                    current_ts = reading["ts_utc"]
            
            # Process historical readings from history.pollution with lag handling
            history = raw_response.get("history", {}) if raw_response else {}
            pollution_history = history.get("pollution", []) if history else []
            weather_history = history.get("weather", []) if history else []
            
            # Create weather lookup by timestamp for matching
            weather_by_ts = {}
            for w in weather_history:
                ts = w.get("ts")
                if ts:
                    weather_by_ts[ts] = w
            
            # Process each historical pollution reading with lag handling
            for pollution_entry in pollution_history:
                ts_str = pollution_entry.get("ts")
                if not ts_str:
                    continue
                
                # Parse original timestamp
                try:
                    if ts_str.endswith("Z"):
                        original_ts = datetime.fromisoformat(ts_str[:-1]).replace(tzinfo=timezone.utc)
                    else:
                        original_ts = datetime.fromisoformat(ts_str.replace("Z", "")).replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                
                # Skip the history entry that corresponds to "current - 1h" (lag handling)
                if current_ts and _approx_one_hour(current_ts, original_ts):
                    logger.debug("Skipping historical entry at %s (overlaps with current at %s)", original_ts, current_ts)
                    continue
                
                # Shift forward by +1h (correct the IQAir lag) - same as station worker
                corrected_ts = _norm_hour(original_ts + timedelta(hours=1))
                
                # Find matching weather data for this timestamp
                weather_entry = weather_by_ts.get(ts_str, {})
                
                # Create combined reading entry with corrected timestamp
                combined_reading = {
                    "pollution": pollution_entry.copy(),
                    "weather": weather_entry
                }
                # Update the timestamp in pollution data to corrected one
                combined_reading["pollution"]["ts"] = corrected_ts.isoformat().replace("+00:00", "Z")
                
                reading = self._normalize_single_city_reading(combined_reading, scope_key, raw_response, is_current=False)
                if reading:
                    # Ensure the corrected timestamp is used
                    reading["ts_utc"] = corrected_ts
                    readings.append(reading)
            
            logger.debug("Normalized %d readings for city %s (%d current + %d historical after lag handling)", 
                        len(readings), scope_key, 1 if current else 0, len([r for r in readings if not getattr(r, 'is_current', True)]))
            
            return readings
            
        except Exception as e:
            logger.warning("Failed to normalize city readings for %s: %s", scope_key, e)
            return []

    def _normalize_single_city_reading(self, reading_data: Dict[str, Any], scope_key: str, 
                                     raw_response: Dict[str, Any], is_current: bool = False) -> Optional[Dict[str, Any]]:
        """
        Normalize a single city reading entry (current or historical) into the Timescale schema.
        """
        try:
            # Extract pollution and weather data
            pollution = reading_data.get("pollution", {}) or {}
            weather = reading_data.get("weather", {}) or {}
            
            # Get timestamp
            ts_str = pollution.get("ts") or weather.get("ts")
            if not ts_str:
                if is_current:
                    ts_utc = datetime.now(timezone.utc)
                else:
                    return None  # Skip historical entries without timestamps
            else:
                try:
                    if ts_str.endswith("Z"):
                        ts_utc = datetime.fromisoformat(ts_str[:-1]).replace(tzinfo=timezone.utc)
                    else:
                        ts_utc = datetime.fromisoformat(ts_str.replace("Z", "")).replace(tzinfo=timezone.utc)
                except Exception:
                    if is_current:
                        ts_utc = datetime.now(timezone.utc)
                    else:
                        return None

            # Floor to hour for consistency using station worker's helper
            ts_utc = _norm_hour(ts_utc)

            # Map main pollutant codes
            pollutant_mapping = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}
            main_us = pollution.get("mainus")
            main_cn = pollution.get("maincn")

            # Extract PM2.5 and PM10 concentrations
            pm25 = None
            pm10 = None
            
            # Try nested p2 structure first
            p2_data = pollution.get("p2")
            if isinstance(p2_data, dict):
                pm25 = p2_data.get("conc")
            
            # Try nested p1 structure
            p1_data = pollution.get("p1")
            if isinstance(p1_data, dict):
                pm10 = p1_data.get("conc")
            
            # Fallback to direct keys
            if pm25 is None:
                pm25 = pollution.get("pm25_conc") or pollution.get("conc")
            if pm10 is None:
                pm10 = pollution.get("pm10_conc")

            return {
                "scope_type": "city",
                "scope_key": scope_key,
                "ts_utc": ts_utc,

                # AQI
                "aqi_us": pollution.get("aqius"),
                "aqi_cn": pollution.get("aqicn"),
                "main_us": pollutant_mapping.get(main_us, main_us) if main_us else None,
                "main_cn": pollutant_mapping.get(main_cn, main_cn) if main_cn else None,

                # Pollutants (concentrations)
                "pm25": pm25,
                "pm10": pm10,
                "o3": pollution.get("o3_conc"),
                "no2": pollution.get("no2_conc"),
                "so2": pollution.get("so2_conc"),
                "co": pollution.get("co_conc"),

                # Units
                "units_pm25": "µg/m³",
                "units_pm10": "µg/m³",
                "units_o3": "ppb",
                "units_no2": "ppb",
                "units_so2": "ppb",
                "units_co": "ppm",

                # Weather
                "temp_c": weather.get("tp"),  # IQAir uses 'tp' for temperature
                "humidity": weather.get("hu"),  # IQAir uses 'hu' for humidity
                "pressure_hpa": weather.get("pr"),  # IQAir uses 'pr' for pressure
                "wind_speed_ms": weather.get("ws"),  # IQAir uses 'ws' for wind speed
                "wind_dir_deg": weather.get("wd"),  # IQAir uses 'wd' for wind direction
                "weather_icon": weather.get("ic"),  # IQAir uses 'ic' for icon
                "heatindex_c": weather.get("heatIndex"),  # IQAir uses 'heatIndex'
                "pop_pct": weather.get("precipitation_probability"),

                # QC + provenance
                "qc_state": "OK",
                "source": "airvisual",
                "raw": json.dumps({"timestamp": ts_str, "is_current": is_current}),
            }
        except Exception as e:
            logger.warning("Failed to normalize single city reading for %s: %s", scope_key, e)
            return None

    # ---------- NEW: in-memory deduplication (copied from station worker) ----------
    def _dedupe_readings_in_memory(self, readings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        In-memory deduplication by (scope_key, ts_utc). Merges non-null values when duplicates found.
        """
        by_key: Dict[tuple, Dict[str, Any]] = {}

        def merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
            """Prefer non-null values from b to fill a"""
            for k, v in b.items():
                if k in ("scope_type", "scope_key", "ts_utc"):
                    continue
                if a.get(k) is None and v is not None:
                    a[k] = v
            return a

        for reading in readings:
            # Normalize timestamp defensively
            reading["ts_utc"] = _norm_hour(reading["ts_utc"])
            key = (reading["scope_key"], reading["ts_utc"])
            if key in by_key:
                by_key[key] = merge(by_key[key], reading)
                logger.debug("Merged duplicate reading for %s at %s", reading["scope_key"], reading["ts_utc"])
            else:
                by_key[key] = reading
        
        logger.info("Deduplication: %d → %d readings", len(readings), len(by_key))
        return list(by_key.values())

    # ---------- NEW: drop rows that already exist in DB (copied from station worker) ----------
    async def _drop_existing_readings(self, readings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Check database and filter out readings that already exist.
        """
        if not readings:
            return readings

        # Group readings by scope_key for efficient range queries
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in readings:
            grouped.setdefault(r["scope_key"], []).append(r)

        keep: List[Dict[str, Any]] = []
        from sqlalchemy import text  # import here to avoid global dependency
        
        async with AsyncSessionLocal() as sess:
            for scope_key, grp in grouped.items():
                # Compute a loose window to minimize roundtrips
                ts_vals = sorted([_norm_hour(x["ts_utc"]) for x in grp])
                min_ts, max_ts = ts_vals[0], ts_vals[-1]

                q = text("""
                    SELECT ts_utc
                    FROM readings
                    WHERE scope_key = :scope_key
                      AND scope_type = 'city'
                      AND ts_utc >= :min_ts
                      AND ts_utc <= :max_ts
                """)
                rs = await sess.execute(q, {"scope_key": scope_key, "min_ts": min_ts, "max_ts": max_ts})
                existing = { _norm_hour(row[0].astimezone(timezone.utc)) for row in rs.fetchall() }

                for r in grp:
                    tsn = _norm_hour(r["ts_utc"])
                    if tsn not in existing:
                        keep.append(r)
                    else:
                        logger.debug("Skipping existing reading for %s at %s", r["scope_key"], tsn)
        
        logger.info("Existence check: %d → %d new readings", len(readings), len(keep))
        return keep
    # ---------------------------------------------------------------------------------

    async def _bulk_write_readings(self, rows: List[Dict[str, Any]]) -> None:
        """
        Apply deduplication and existence filtering before bulk writing to database.
        """
        try:
            if not rows:
                logger.info("No readings to write.")
                return
            
            logger.info("Starting bulk write with %d raw readings", len(rows))
            
            # Apply in-memory deduplication first
            deduplicated_rows = self._dedupe_readings_in_memory(rows)
            
            # Filter out readings that already exist in database
            new_rows = await self._drop_existing_readings(deduplicated_rows)
            
            if not new_rows:
                logger.info("No new readings to insert after deduplication and existence check.")
                return
            
            # Bulk insert the remaining new readings
            async with AsyncSessionLocal() as sess:
                n = await self.db_service.upsert_readings_bulk(sess, new_rows)
                await sess.commit()
                logger.info("Successfully upserted %d new city readings.", n)
                
        except Exception as e:
            logger.error("Bulk write failed: %s", e)
            raise

    def _write_report(self, success_count: int, fail_entries: List[Dict[str, Any]]) -> None:
        try:
            self._out_dir.mkdir(parents=True, exist_ok=True)
            metrics = {
                "run_id": self._run_id,
                "started_utc": self._run_id.replace("ingest-city-", ""),
                "success_count": success_count,
                "fail_count": len(fail_entries),
                "rate_limit_per_min": self._rate,
                "concurrency": self._concurrency,
                "allow_state_alias": self._allow_state_alias,
                "allow_nearest_fallback": self._allow_nearest_fallback,
            }
            with open(self._out_dir / "metrics.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(metrics, indent=2))

            if fail_entries:
                with open(self._out_dir / "failures.jsonl", "w", encoding="utf-8") as f:
                    for row in fail_entries:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed writing ingest report: %s", e)
