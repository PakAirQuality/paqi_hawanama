import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta

# Dual-path imports for API container compatibility
try:
    from app.services.ingestion.iqair_service import (
        IQAirClient,
        IQAirError,
        StationNotFound,
        FeatureNotAvailable,
        RateLimited,
        Unauthorized,
        BadRequest,
    )
    from app.services.database import DatabaseService, AsyncSessionLocal
except ImportError:  # running in pure worker repo layout
    from services.iqair_client import (
        IQAirClient,
        IQAirError,
        StationNotFound,
        FeatureNotAvailable,
        RateLimited,
        Unauthorized,
        BadRequest,
    )
    from services.database import DatabaseService, AsyncSessionLocal

logger = logging.getLogger(__name__)

# Optional pandas (for Parquet manifest)
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    pd = None
    _HAVE_PANDAS = False

# ---------- NEW: time helpers ----------
def _norm_hour(dt: datetime) -> datetime:
    """Floor to the exact hour (UTC-aware in/out)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

def _approx_one_hour(a: datetime, b: datetime) -> bool:
    """True if a - b ≈ 1h (tolerates small jitters)."""
    return abs((a - b) - timedelta(hours=1)) <= timedelta(minutes=10)
# ---------------------------------------

# Aliases to fix label mismatches between /stations and /station endpoints.
# Uses shared South Asia config for per-country aliases.
try:
    from app.core.south_asia import get_state_aliases as _get_state_aliases, get_iqair_countries
except ImportError:
    from core.south_asia import get_state_aliases as _get_state_aliases, get_iqair_countries

def _state_aliases(state: Optional[str], country: Optional[str] = None) -> List[str]:
    if not state:
        return []
    if country:
        return _get_state_aliases(country, state)
    # Fallback: no country context, just return [state]
    return [state]


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


class DataIngestionTask:
    """Manifest-driven data ingestion (station endpoint) with backfill from history.pollution."""

    def __init__(self):
        self.iqair_client = IQAirClient()
        self.db_service = DatabaseService()

        # Concurrency and rate limiting
        self._concurrency = int(os.getenv("INGEST_CONCURRENCY", "6"))
        self._sema = asyncio.Semaphore(self._concurrency)
        self._rate = int(os.getenv("IQAIR_MAX_CALLS_PER_MIN", "90"))
        self._limiter = _AsyncRateLimiter(self._rate)

        # Fallback toggles
        self._allow_city_fallback   = os.getenv("ALLOW_CITY_FALLBACK", "false").lower() in {"1", "true", "yes"}
        self._allow_state_alias     = os.getenv("ALLOW_STATE_ALIAS", "true").lower() in {"1", "true", "yes"}
        self._db_station_fallback   = os.getenv("ALLOW_DB_STATION_FALLBACK", "false").lower() in {"1", "true", "yes"}

        # Filters — supports multi-country ingestion via IQAIR_COUNTRIES env var
        self._countries      = get_iqair_countries()
        self._provider_code  = os.getenv("STATION_PROVIDER_CODE", "airvisual")

        # Backfill window (hours)
        self._backfill_hours = int(os.getenv("IQAIR_BACKFILL_HOURS", "48"))

        # Manifest config (written by station_discovery.py)
        self._manifest_dir = Path(os.getenv("STATION_MANIFEST_DIR", "artifacts/station_manifests"))

        # Ingest run output
        ts = datetime.now(timezone.utc).isoformat()
        self._run_id = f"ingest-{ts}"
        self._out_dir = Path(os.getenv("INGEST_OUT_DIR", "artifacts/ingest_runs")) / self._run_id
        self._out_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------- manifest loading ---------------------------

    def _resolve_latest_manifest_path(self) -> Optional[Path]:
        # Always sync from GCS first to avoid stale local manifests across container instances
        try:
            from app.manifest_utils import download_manifest_from_gcs
        except ImportError:
            from manifest_utils import download_manifest_from_gcs

        gcs_prefix = "manifests/station_manifests"
        p_parq = self._manifest_dir / "latest.parquet"
        p_json = self._manifest_dir / "latest.jsonl"

        self._manifest_dir.mkdir(parents=True, exist_ok=True)
        if download_manifest_from_gcs(p_parq, gcs_prefix):
            logger.info("Synced station manifest from GCS → %s", p_parq)
            return p_parq
        if download_manifest_from_gcs(p_json, gcs_prefix):
            logger.info("Synced station manifest from GCS → %s", p_json)
            return p_json

        # Fall back to local file if GCS unavailable
        if p_parq.exists():
            return p_parq
        if p_json.exists():
            return p_json
        return None

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

    async def _list_stations_from_db(self) -> List[Dict[str, Any]]:
        """
        Optional DB fallback: list active provider stations for the target countries.
        Expected output keys align with the station manifest written by discovery.
        """
        from sqlalchemy import text
        async with AsyncSessionLocal() as session:
            q = text("""
                SELECT
                    st.id                     AS station_id,
                    st.source_station_id      AS source_station_id,
                    st.name                   AS iqair_station_name,
                    st.latitude               AS lat,
                    st.longitude              AS lon,
                    st.active                 AS active,
                    co.name                   AS country,
                    s.name                    AS state,
                    c.name                    AS city
                FROM stations st
                JOIN providers p  ON p.id = st.provider_id
                JOIN cities c     ON c.id = st.city_id
                JOIN states s     ON s.id = c.state_id
                JOIN countries co ON co.id = s.country_id
                WHERE p.code = :provider_code
                  AND st.active = true
                ORDER BY co.name, s.name, c.name, st.name
            """)
            rs = await session.execute(q, {"provider_code": self._provider_code})
            out: List[Dict[str, Any]] = []
            for row in rs.fetchall():
                m = dict(row._mapping)
                m["provider_code"] = self._provider_code
                m["latitude"] = m.get("lat")
                m["longitude"] = m.get("lon")
                out.append(m)
            return out

    def _load_manifest(self) -> List[Dict[str, Any]]:
        """
        Load stations from discovery manifest; optionally fallback to DB if allowed.
        """
        p = self._resolve_latest_manifest_path()
        if p:
            logger.info("Using station manifest: %s", p)
            rows = self._read_parquet(p) if p.suffix == ".parquet" else self._read_jsonl(p)
        else:
            logger.error("No station manifest found in %s", self._manifest_dir)
            rows = []

        # Optional: DB fallback (caller handles async DB query)
        if (not rows) and self._db_station_fallback:
            logger.info("Station manifest empty; caller will attempt DB fallback for provider=%s, countries=%s",
                        self._provider_code, self._countries)

        # Normalize a few common field variants for safety
        for r in rows:
            if "iqair_station_name" not in r and "name" in r:
                r["iqair_station_name"] = r["name"]
            if "lat" not in r and "latitude" in r:
                r["lat"] = r["latitude"]
            if "lon" not in r and "longitude" in r:
                r["lon"] = r["longitude"]
        return rows

    # ----------------------------- backfill helpers --------------------------

    async def _fetch_and_merge_history_pollution(
        self,
        station_name: str,
        city: Optional[str],
        state_try: Optional[str],
        country: Optional[str],
        parsed: Dict[str, Any],
    ) -> None:
        """Pull history.pollution for the configured window and merge into `parsed`."""
        end_utc = datetime.now(timezone.utc)
        start_utc = end_utc - timedelta(hours=self._backfill_hours)
        try:
            await self._limiter.wait()
            hist_raw = await self.iqair_client.get_station_history_pollution(
                station=station_name,
                city=city,
                state=state_try,
                country=country,
                start_utc=start_utc,
                end_utc=end_utc,
            )
            hist_list = self.iqair_client.parse_history_pollution(hist_raw) or []
            parsed.setdefault("history", {}).setdefault("pollution", []).extend(hist_list)
        except FeatureNotAvailable:
            logger.info("history.pollution not available for '%s' (%s, %s).", station_name, city, state_try)
        except RateLimited:
            raise
        except Exception as e:
            logger.warning("Failed fetching history.pollution for '%s' (%s, %s): %s",
                           station_name, city, state_try, e)

    async def _fetch_and_merge_history_weather(
        self,
        station_name: str,
        city: Optional[str],
        state_try: Optional[str],
        country: Optional[str],
        parsed: Dict[str, Any],
    ) -> None:
        """Pull history.weather for the configured window and merge into `parsed`."""
        end_utc = datetime.now(timezone.utc)
        start_utc = end_utc - timedelta(hours=self._backfill_hours)
        try:
            await self._limiter.wait()
            hist_raw = await self.iqair_client.get_station_history_weather(
                station=station_name, city=city, state=state_try, country=country,
                start_utc=start_utc, end_utc=end_utc,
            )
            hist_list = self.iqair_client.parse_history_weather(hist_raw) or []
            parsed.setdefault("history", {}).setdefault("weather", []).extend(hist_list)
        except FeatureNotAvailable:
            logger.info("history.weather not available for '%s' (%s, %s).", station_name, city, state_try)
        except RateLimited:
            raise
        except Exception as e:
            logger.warning("Failed fetching history.weather for '%s' (%s, %s): %s",
                           station_name, city, state_try, e)

    @staticmethod
    def _parse_ts(ts: str) -> datetime:
        # Handle both Z and explicit offsets, produce tz-aware UTC
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _build_scope_key(self, s: Dict[str, Any], scope_type: str) -> str:
        # Use hex station_id for stations, keep existing logic for cities
        if scope_type == "station":
            # Prefer hex station_id from manifest
            if s.get("station_id"):
                return s["station_id"]
            # Fallback: generate hex station_id using database service
            try:
                from app.services.database import DatabaseService
            except ImportError:
                from services.database import DatabaseService
            db_service = DatabaseService()
            
            country = (s.get("country") or "").strip()
            state = (s.get("state") or "").strip()
            city = (s.get("city") or "").strip()
            name = (s.get("iqair_station_name") or s.get("name") or "").strip()
            lat = float(s.get("lat", 0))
            lon = float(s.get("lon", 0))
            
            return db_service.generate_station_id(country, state, city, name, lat, lon)
        else:  # city - keep existing pipe-separated format for compatibility
            parts = [
                (s.get("country") or "").strip().lower(),
                (s.get("state") or "").strip().lower(),
                (s.get("city") or "").strip().lower(),
            ]
            return "|".join([p for p in parts if p])

    def _extract_rows_from_parsed(
        self,
        parsed: Dict[str, Any],
        scope_type: str,
        scope_key: str,
        station_blob_for_raw: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Merge current + history for both pollution and weather by timestamp.
        Accepts payload from IQAirClient.parse_* which preserves:
          current.pollution, current.weather
          history.pollution (list), history.weather (list)
        """
        rows: List[Dict[str, Any]] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self._backfill_hours)

        # Aggregate by UTC timestamp
        bucket: Dict[datetime, Dict[str, Any]] = {}

        def _entry(ts: datetime) -> Dict[str, Any]:
            ts = _norm_hour(ts)  # ---------- NEW ----------
            e = bucket.get(ts)
            if e:
                return e
            e = {
                "scope_type": (scope_type or "").strip(),
                "scope_key": scope_key,
                "ts_utc": ts,
                # pollution fields (default None)
                "aqi_us": None, "aqi_cn": None, "main_us": None, "main_cn": None,
                "pm25": None, "pm10": None, "o3": None, "no2": None, "so2": None, "co": None,
                # pollution units (default None)
                "units_pm25": None, "units_pm10": None, "units_o3": None, 
                "units_no2": None, "units_so2": None, "units_co": None,
                # weather fields (default None)
                "temp_c": None, "humidity": None, "pressure_hpa": None,
                "wind_speed_ms": None, "wind_dir_deg": None, "weather_icon": None,
                "heatindex_c": None, "pop_pct": None,
                "source": "airvisual",
                "raw": None,  # Exclude massive API response to prevent SQLAlchemy errors
            }
            bucket[ts] = e
            return e

        def _add_pollution(obj: Dict[str, Any]):
            ts_raw = obj.get("ts")
            if not ts_raw:
                return
            try:
                ts = self._parse_ts(ts_raw)
                ts = _norm_hour(ts)  # ---------- NEW ----------
            except Exception:
                return
            if ts < cutoff:
                return
            aqius = obj.get("aqius")
            aqicn = obj.get("aqicn")
            # Map IQAir pollutant codes to database enum values
            def map_pollutant_code(code):
                if not code:
                    return None
                mapping = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}
                return mapping.get(code, code)
            
            mainus = map_pollutant_code(obj.get("mainus"))
            maincn = map_pollutant_code(obj.get("maincn"))
            def conc(d, k):
                v = d.get(k)
                if isinstance(v, dict):
                    return v.get("conc")
                return v
            entry = _entry(ts)
            entry.update({
                "aqi_us": aqius if aqius is not None else entry["aqi_us"],
                "aqi_cn": aqicn if aqicn is not None else entry["aqi_cn"],
                "main_us": mainus if mainus is not None else entry["main_us"],
                "main_cn": maincn if maincn is not None else entry["main_cn"],
                "pm25": conc(obj, "p2") if conc(obj, "p2") is not None else entry["pm25"],
                "pm10": conc(obj, "p1") if conc(obj, "p1") is not None else entry["pm10"],
                "o3":   conc(obj, "o3") if conc(obj, "o3") is not None else entry["o3"],
                "no2":  conc(obj, "n2") if conc(obj, "n2") is not None else entry["no2"],
                "so2":  conc(obj, "s2") if conc(obj, "s2") is not None else entry["so2"],
                "co":   conc(obj, "co") if conc(obj, "co") is not None else entry["co"],
            })

        def _add_weather(obj: Dict[str, Any]):
            ts_raw = obj.get("ts")
            if not ts_raw:
                return
            try:
                ts = self._parse_ts(ts_raw)
                ts = _norm_hour(ts)  # ---------- NEW ----------
            except Exception:
                return
            if ts < cutoff:
                return
            tp = obj.get("tp")
            pr = obj.get("pr")
            hu = obj.get("hu")
            ws = obj.get("ws")
            wd = obj.get("wd")
            ic = obj.get("ic")
            hi = obj.get("heatIndex") or obj.get("heatindex")  # defensive casing
            pop = obj.get("pop") or obj.get("precipitation_probability")
            entry = _entry(ts)
            entry.update({
                "temp_c": tp if tp is not None else entry["temp_c"],
                "pressure_hpa": pr if pr is not None else entry["pressure_hpa"],
                "humidity": hu if hu is not None else entry["humidity"],
                "wind_speed_ms": ws if ws is not None else entry["wind_speed_ms"],
                "wind_dir_deg": wd if wd is not None else entry["wind_dir_deg"],
                "weather_icon": ic if ic is not None else entry["weather_icon"],
                "heatindex_c": hi if hi is not None else entry["heatindex_c"],
                "pop_pct": pop if pop is not None else entry["pop_pct"],
            })

        # ---- current ----
        cur_p = (parsed.get("current") or {}).get("pollution")
        current_ts = None  # ---------- NEW ----------
        if isinstance(cur_p, dict):
            # capture normalized current ts for robust history skip
            ts_raw = cur_p.get("ts")
            if ts_raw:
                try:
                    current_ts = _norm_hour(self._parse_ts(ts_raw))
                except Exception:
                    current_ts = None
            _add_pollution(cur_p)
        cur_w = (parsed.get("current") or {}).get("weather")
        if isinstance(cur_w, dict):
            _add_weather(cur_w)

        # ---- history ----
        hist_p = (parsed.get("history") or {}).get("pollution") or []
        if isinstance(hist_p, list):
            # IQAir history timestamps are systematically lagged by ~1 hour.
            for p in hist_p:
                if not isinstance(p, dict):
                    continue
                ts_raw = p.get("ts")
                if not ts_raw:
                    continue
                try:
                    original_ts = _norm_hour(self._parse_ts(ts_raw))
                except Exception:
                    continue

                # Skip the history entry that corresponds to "current - 1h"
                if current_ts and _approx_one_hour(current_ts, original_ts):
                    continue

                # Shift forward by +1h (correct the IQAir lag)
                corrected_ts = _norm_hour(original_ts + timedelta(hours=1))

                p_corrected = p.copy()
                p_corrected["ts"] = corrected_ts.isoformat().replace("+00:00", "Z")
                _add_pollution(p_corrected)

        hist_w = (parsed.get("history") or {}).get("weather") or []
        if isinstance(hist_w, list):
            for w in hist_w:
                if isinstance(w, dict):
                    _add_weather(w)

        # Emit combined rows (order not important), clean up for database
        for row in bucket.values():
            # Remove raw field and add missing defaults for database compatibility
            if 'raw' in row:
                del row['raw']
            if 'qc_state' not in row or row['qc_state'] is None:
                row['qc_state'] = 'raw'
        
        rows.extend(bucket.values())
        return rows

    # ---------- NEW: in-run de-dup ----------
    def _dedupe_rows_in_memory(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_key: Dict[tuple, Dict[str, Any]] = {}

        def merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
            # prefer non-null values from b to fill a
            for k, v in b.items():
                if k in ("scope_type", "scope_key", "ts_utc"):
                    continue
                if a.get(k) is None and v is not None:
                    a[k] = v
            return a

        for r in rows:
            # normalize defensively
            r["ts_utc"] = _norm_hour(r["ts_utc"].astimezone(timezone.utc))
            key = (r["scope_key"], r["ts_utc"])
            if key in by_key:
                by_key[key] = merge(by_key[key], r)
            else:
                by_key[key] = r
        return list(by_key.values())
    # ----------------------------------------

    # ---------- NEW: drop rows that already exist in DB ----------
    async def _drop_existing_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return rows

        # Group rows by scope_key for efficient range queries
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            grouped.setdefault(r["scope_key"], []).append(r)

        keep: List[Dict[str, Any]] = []
        from sqlalchemy import text  # import here to avoid global dependency
        async with AsyncSessionLocal() as sess:
            for scope_key, grp in grouped.items():
                # compute a loose window to minimize roundtrips
                ts_vals = sorted([_norm_hour(x["ts_utc"]) for x in grp])
                min_ts, max_ts = ts_vals[0], ts_vals[-1]

                q = text("""
                    SELECT ts_utc
                    FROM readings
                    WHERE scope_key = :scope_key
                      AND ts_utc >= :min_ts
                      AND ts_utc <= :max_ts
                """)
                rs = await sess.execute(q, {"scope_key": scope_key, "min_ts": min_ts, "max_ts": max_ts})
                existing = { _norm_hour(row[0].astimezone(timezone.utc)) for row in rs.fetchall() }

                for r in grp:
                    tsn = _norm_hour(r["ts_utc"])
                    if tsn not in existing:
                        keep.append(r)
        return keep
    # -------------------------------------------------------------

    # ----------------------------- public API --------------------------------

    async def fetch_station_readings(self) -> Dict[str, Any]:
        """
        Station-only ingestion (optionally city-fallback). Reads stations from manifest,
        or from DB if ALLOW_DB_STATION_FALLBACK=true and no manifest is present.
        Backfills using history.pollution within IQAIR_BACKFILL_HOURS.
        """
        logger.info(
            "Starting station ingestion (manifest mode). concurrency=%d, rate<=%d/min, "
            "fallback=%s, alias=%s, db_station_fallback=%s",
            self._concurrency, self._rate, self._allow_city_fallback, self._allow_state_alias, self._db_station_fallback
        )

        rows = self._load_manifest()
        if (not rows) and self._db_station_fallback:
            rows = await self._list_stations_from_db()

        if not rows:
            return {
                "status": "success",
                "stations_processed": 0,
                "readings_fetched": 0,
                "readings_failed": 0,
                "run_id": self._run_id,
                "report_dir": str(self._out_dir),
            }

        # Filter to active <countries,provider> and dedupe (station_name, city, state, country)
        country_set = {c.lower() for c in self._countries}
        seen = set()
        stations: List[Dict[str, Any]] = []
        for r in rows:
            if r.get("provider_code") != self._provider_code:
                continue
            if (r.get("country") or "").lower() not in country_set:
                continue
            if r.get("active") is False:
                continue
            tup = (r.get("iqair_station_name") or r.get("name"), r.get("city"), r.get("state"), r.get("country"))
            if None in tup:
                continue
            if tup in seen:
                continue
            seen.add(tup)
            stations.append(r)

        logger.info("Will request station endpoint for %d stations.", len(stations))

        tasks = [self._fetch_one(s) for s in stations]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        total_rows, failed = 0, 0
        buf: List[Dict[str, Any]] = []
        failures: List[Dict[str, Any]] = []

        for i, res in enumerate(results):
            meta = {
                "source_station_id": stations[i].get("source_station_id"),
                "station": stations[i].get("iqair_station_name") or stations[i].get("name"),
                "city": stations[i].get("city"),
                "state": stations[i].get("state"),
                "country": stations[i].get("country", ""),
            }
            if isinstance(res, Exception):
                failed += 1
                failures.append({**meta, "error": f"{type(res).__name__}: {res}"})
            elif isinstance(res, list):
                if res:
                    buf.extend(res)
                    total_rows += len(res)
                else:
                    failures.append({**meta, "error": "no_points_in_response"})
                    failed += 1
            else:
                failures.append({**meta, "error": "unexpected_result_type"})
                failed += 1

        # ---------- NEW: de-dup and drop-existing before bulk write ----------
        if buf:
            buf = self._dedupe_rows_in_memory(buf)
            buf = await self._drop_existing_rows(buf)
            if buf:
                await self._bulk_write_readings(buf)
                logger.info("Bulk upserted %d readings after de-dup.", len(buf))
            else:
                logger.info("Nothing new to upsert after de-dup.")
        # ---------------------------------------------------------------------

        # write a small report for transparency
        self._write_report(success_count=total_rows, fail_entries=failures)

        logger.info("Ingestion complete. Stations=%d Rows=%d FailedStations=%d (out: %s)",
                    len(stations), total_rows, failed, self._out_dir)
        return {
            "status": "success",
            "stations_processed": len(stations),
            "readings_fetched": total_rows,
            "readings_failed": failed,
            "run_id": self._run_id,
            "report_dir": str(self._out_dir),
        }

    # --------------------------- fetch + write helpers -----------------------

    async def _fetch_one(self, s: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """
        Single station fetch using /v2/station. Optional state-alias retry and city fallback.
        Returns a LIST of upsert rows (history + current) or raises.
        """
        async with self._sema:
            station_name = s.get("iqair_station_name") or s.get("name")
            city = s.get("city")
            state = s.get("state")
            country = s.get("country") or ""

            # Try: exact state first, then aliases (if allowed)
            states_to_try = [state] if state else []
            if self._allow_state_alias:
                for a in _state_aliases(state, country)[1:]:
                    states_to_try.append(a)

            last_exc: Optional[Exception] = None

            for idx, state_try in enumerate(states_to_try or [state]):
                try:
                    await self._limiter.wait()
                    raw = await self.iqair_client.get_station_data(
                        station=station_name, city=city, state=state_try, country=country
                    )
                    parsed = self.iqair_client.parse_station_data(raw)
                    # History data is already included in the station response

                    scope_type = "station"
                    scope_key = self._build_scope_key(s, scope_type)
                    rows = self._extract_rows_from_parsed(
                        parsed, scope_type, scope_key, parsed.get("raw_response", parsed)
                    )
                    return rows if rows else []
                except StationNotFound as e:
                    last_exc = e
                    logger.info(
                        "Station not found: '%s' in %s, %s (try %d/%d).",
                        station_name, city, state_try, idx + 1, len(states_to_try or [state])
                    )
                except FeatureNotAvailable as e:
                    last_exc = e
                    logger.info("Feature not available for station '%s' (%s).", station_name, e)
                    break
                except RateLimited as e:
                    logger.warning("Rate limited while fetching station '%s': %s", station_name, e)
                    raise
                except (Unauthorized, BadRequest) as e:
                    logger.error("Auth/BadRequest for '%s', %s, %s: %s", station_name, city, state_try, e)
                    raise
                except IQAirError as e:
                    last_exc = e
                    logger.warning("IQAir error for '%s', %s, %s: %s", station_name, city, state_try, e)
                except Exception as e:
                    last_exc = e
                    logger.warning("Unexpected error for '%s', %s, %s: %s", station_name, city, state_try, e)

            # If we reach here, station lookups (incl. aliases) failed.
            # Optional: city fallback
            if self._allow_city_fallback:
                try:
                    await self._limiter.wait()
                    raw = await self.iqair_client.get_city_data(city=city, state=state, country=country)
                    parsed = self.iqair_client.parse_city_data(raw)
                    # History data is already included in the city response if available

                    scope_type = "city"
                    scope_key = self._build_scope_key(s, scope_type)
                    rows = self._extract_rows_from_parsed(
                        parsed, scope_type, scope_key, parsed.get("raw_response", parsed)
                    )
                    return rows if rows else []
                except Exception as e2:
                    logger.warning("City fallback failed for '%s' (%s, %s): %s", station_name, city, state, e2)
                    raise (last_exc or e2)

            if last_exc:
                raise last_exc
            raise StationNotFound(f"Unable to resolve station '{station_name}' in {city}, {state}")

    async def _bulk_write_readings(self, rows: List[Dict[str, Any]]) -> None:
        try:
            async with AsyncSessionLocal() as sess:
                n = await self.db_service.upsert_readings_bulk(sess, rows)
                await sess.commit()
                logger.info("Upserted %d readings.", n)
        except Exception as e:
            logger.error("Bulk write failed: %s", e)
            raise

    def _write_report(self, success_count: int, fail_entries: List[Dict[str, Any]]) -> None:
        try:
            self._out_dir.mkdir(parents=True, exist_ok=True)
            metrics = {
                "run_id": self._run_id,
                "started_utc": self._run_id.replace("ingest-", ""),
                "success_count": success_count,
                "fail_count": len(fail_entries),
                "rate_limit_per_min": self._rate,
                "concurrency": self._concurrency,
                "allow_city_fallback": self._allow_city_fallback,
                "allow_state_alias": self._allow_state_alias,
                "db_station_fallback": self._db_station_fallback,
                "countries": self._countries,
                "provider_code": self._provider_code,
                "backfill_hours": self._backfill_hours,
            }
            with open(self._out_dir / "metrics.json", "w", encoding="utf-8") as f:
                f.write(json.dumps(metrics, indent=2))

            if fail_entries:
                with open(self._out_dir / "failures.jsonl", "w", encoding="utf-8") as f:
                    for row in fail_entries:
                        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Failed writing ingest report: %s", e)


# small runner to match run_task.py expectations
async def station_ingestion():
    return await DataIngestionTask().fetch_station_readings()

if __name__ == "__main__":
    # Allow direct execution for ad-hoc runs
    asyncio.run(station_ingestion())
