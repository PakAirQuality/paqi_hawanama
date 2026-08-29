"""
Station Discovery Tasks
Handles comprehensive discovery of monitoring stations from IQAir API
Now also writes a structured station manifest (Parquet or JSONL) per run, plus an atomic "latest" pointer.
Also derives and writes a CITY manifest (unique country/state/city tuples) with an atomic "latest".
"""

import asyncio
import logging
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

from sqlalchemy import text

# Dual-path imports for API container compatibility
try:
    from app.services.ingestion.iqair_service import IQAirClient
    from app.services.database import DatabaseService, AsyncSessionLocal
    from app.manifest_utils import finalize_union_manifest, upload_manifest_to_gcs
except ImportError:  # running in pure worker repo layout
    from services.iqair_client import IQAirClient
    from services.database import DatabaseService, AsyncSessionLocal
    from manifest_utils import finalize_union_manifest, upload_manifest_to_gcs

logger = logging.getLogger(__name__)

# Optional pandas dependency (preferred for Parquet). Falls back to JSONL if missing.
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:  # pragma: no cover
    pd = None
    _HAVE_PANDAS = False

try:
    from app.core.south_asia import get_iqair_countries, get_state_aliases
except ImportError:
    from core.south_asia import get_iqair_countries, get_state_aliases

def _slug(*parts):
    s = "|".join((p or "").strip().replace("'","'") for p in parts)
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")

def _scope_key(country: str, state: str, city: str) -> str:
    return f"{country.lower()}|{state.lower()}|{city.lower()}"

class StationDiscoveryTask:
    """Task handler for station discovery operations"""

    def __init__(self):
        self.iqair_client = IQAirClient()
        self.db_service = DatabaseService()

        # Station manifest configuration (directory and format)
        self.manifest_root = Path(os.getenv("STATION_MANIFEST_DIR", "artifacts/station_manifests"))
        self.manifest_format = os.getenv("STATION_MANIFEST_FORMAT", "parquet").lower()  # parquet|jsonl
        if self.manifest_format not in {"parquet", "jsonl"}:
            logger.warning("Unknown STATION_MANIFEST_FORMAT=%s, falling back to parquet", self.manifest_format)
            self.manifest_format = "parquet"
        if self.manifest_format == "parquet" and not _HAVE_PANDAS:
            logger.warning("pandas not available; switching station manifest format to jsonl")
            self.manifest_format = "jsonl"

        # City manifest configuration (defaults to its own dir; format defaults to station format)
        self.city_manifest_root = Path(os.getenv("CITY_MANIFEST_DIR", "artifacts/city_manifests"))
        self.city_manifest_format = os.getenv("CITY_MANIFEST_FORMAT", self.manifest_format).lower()
        if self.city_manifest_format not in {"parquet", "jsonl"}:
            self.city_manifest_format = self.manifest_format
        if self.city_manifest_format == "parquet" and not _HAVE_PANDAS:
            logger.warning("pandas not available; switching city manifest format to jsonl")
            self.city_manifest_format = "jsonl"

    async def discover_all_stations_comprehensive(self, country: Optional[str] = None):
        """
        Comprehensive discovery of ALL monitoring stations across South Asia.
        Follows API hierarchy: countries -> states -> cities -> stations
        Also writes a run-scoped manifest and updates an atomic 'latest' pointer.

        Args:
            country: If provided, limit discovery to this single country.
                     Takes precedence over DISCOVERY_COUNTRY env var.
        """
        try:
            countries = get_iqair_countries()
            logger.info("Starting comprehensive station discovery for %d countries: %s",
                        len(countries), countries)

            # Progress tracking
            total_stations_discovered = 0
            total_stations_created = 0
            total_stations_updated = 0
            total_cities_processed = 0
            total_states_processed = 0
            skipped_states: List[Dict[str, Any]] = []
            skipped_cities: List[Dict[str, Any]] = []

            # Collect rows for manifest
            manifest_rows: List[Dict[str, Any]] = []

            progress_id = f"discovery-{datetime.now(timezone.utc).isoformat()}"

            # Optionally limit to a single country — query param takes precedence over env var
            only_country = country or os.getenv("DISCOVERY_COUNTRY")
            if only_country:
                countries = [c for c in countries if c.lower() == only_country.lower()]
                logger.info("Limiting discovery to country=%s", only_country)

            for country in countries:
                logger.info("Starting discovery run %s for %s", progress_id, country)

                try:
                    # Step 1: Get all states
                    logger.info("Step 1: Discovering states in %s", country)
                    states = await self.iqair_client.get_states(country)
                    logger.info("Found %d states in %s: %s", len(states), country, [s.get('state') for s in states])

                    # Optionally limit to a single state for quick re-runs
                    only_state = os.getenv("DISCOVERY_STATE")
                    if only_state:
                        states = [s for s in states if s.get("state", "").lower() == only_state.lower()]
                        logger.info("Limiting discovery to state=%s (via DISCOVERY_STATE)", only_state)

                    for state_data in states:
                        state = state_data["state"]
                        logger.info("Step 2: Processing state: %s (%s)", state, country)

                        # Try original + aliases, tolerate per-attempt failures
                        candidate_states = get_state_aliases(country, state)
                        cities = None
                        used_state_label = None
                        attempt_errors = []

                        for cand in candidate_states:
                            try:
                                tmp = await self.iqair_client.get_cities(country, cand)
                                if tmp:
                                    cities = tmp
                                    used_state_label = cand
                                    break
                            except Exception as e:
                                attempt_errors.append(f"{cand}:{type(e).__name__}")
                                continue

                        if not cities:
                            logger.warning("No cities processed for state=%s (tried=%s)", state, ", ".join(attempt_errors) or "none")
                            skipped_states.append({"state": state, "country": country, "reason": "aliases_exhausted"})
                            continue

                        if used_state_label and used_state_label != state:
                            logger.info("Using alias for state '%s' -> '%s'", state, used_state_label)
                            state = used_state_label

                        logger.info("Found %d cities in %s", len(cities), state)

                        for city_data in cities:
                            city = city_data["city"]
                            logger.info("Step 3: Processing city: %s, %s (%s)", city, state, country)

                            try:
                                # Upsert hierarchy
                                async with AsyncSessionLocal() as geo_session:
                                    country_id = await self.db_service.upsert_country(geo_session, {'name': country})
                                    state_id = await self.db_service.upsert_state(geo_session, {
                                        'country_id': country_id, 'name': state
                                    })
                                    city_id = await self.db_service.upsert_city(geo_session, {
                                        'country_id': country_id, 'state_id': state_id, 'name': city
                                    })
                                    await geo_session.commit()

                                # Fetch stations
                                stations = await self.iqair_client.get_stations(city, state, country)
                                if not stations:
                                    logger.info("No stations found in %s, %s", city, state)
                                    continue

                                logger.info("Found %d stations in %s, %s", len(stations), city, state)
                                total_stations_discovered += len(stations)

                                seen_source_ids = set()
                                seen_names = set()
                                batch_size = 20
                                station_infos: List[Dict[str, Any]] = []

                                for i, station_data in enumerate(stations):
                                    station_name = station_data.get("station")
                                    coords = station_data.get("location", {}).get("coordinates", [])

                                    if not station_name or len(coords) != 2:
                                        logger.warning("Invalid station data: %s", station_data)
                                        continue

                                    lon, lat = coords  # IQAir returns [lon, lat]
                                    norm_name = station_name.strip()
                                    source_station_id = _slug("iqair", country, state, city, norm_name)
                                    seen_source_ids.add(source_station_id)
                                    seen_names.add(norm_name)

                                    station_info = {
                                        'provider_code': 'airvisual',
                                        'country_id': country_id,
                                        'state_id': state_id,
                                        'city_id': city_id,
                                        'country': country,
                                        'state': state,
                                        'city': city,
                                        'name': norm_name,
                                        'lat': lat,
                                        'lon': lon,
                                        'source_station_id': source_station_id,
                                        'metadata_json': {
                                            'iqair_station_name': norm_name,
                                            'iqair_city': city,
                                            'iqair_state': state,
                                            'iqair_country': country,
                                            'location_type': 'Point',
                                            'data_source': 'iqair_stations_endpoint',
                                            'last_updated_utc': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                                            'discovery_method': 'apscheduler'
                                        },
                                        'active': True,
                                        'last_seen_at': datetime.now(timezone.utc)
                                    }
                                    station_infos.append(station_info)

                                    # Batch upsert
                                    if len(station_infos) >= batch_size or i == len(stations) - 1:
                                        async with AsyncSessionLocal() as station_session:
                                            for info in station_infos:
                                                # Always record in manifest (tracks IQAir discovery, not DB state)
                                                manifest_rows.append({
                                                    "run_id": progress_id,
                                                    "provider_code": "airvisual",
                                                    "station_id": None,
                                                    "source_station_id": info["source_station_id"],
                                                    "country": info["country"],
                                                    "state": info["state"],
                                                    "city": info["city"],
                                                    "iqair_station_name": info["name"],
                                                    "lat": info["lat"],
                                                    "lon": info["lon"],
                                                    "active": True,
                                                    "last_seen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                                                })
                                                try:
                                                    result = await self.db_service.upsert_station(station_session, info)
                                                    returned_station_id = (result.get("station_id") if isinstance(result, dict) else None)
                                                    if returned_station_id:
                                                        manifest_rows[-1]["station_id"] = returned_station_id

                                                    if result.get('created'):
                                                        total_stations_created += 1
                                                        logger.info("Created station: %s at (%s,%s)", info['name'], info['lat'], info['lon'])
                                                    elif result.get('updated'):
                                                        total_stations_updated += 1
                                                        logger.info("Updated station: %s at (%s,%s)", info['name'], info['lat'], info['lon'])
                                                except Exception as station_error:
                                                    logger.error("Error upserting station %s: %s", info['name'], station_error)
                                                    continue
                                            await station_session.commit()
                                        station_infos = []
                                        await asyncio.sleep(0.5)

                                # Note: No longer deactivating missing stations - using union manifest approach

                                total_cities_processed += 1
                                logger.info("Completed city %s: %d stations processed", city, len(stations))
                                await asyncio.sleep(1.0)

                            except Exception as city_error:
                                logger.error("Error processing city %s, %s: %s", city, state, city_error)
                                skipped_cities.append({
                                    "city": city, "state": state, "country": country, "reason": type(city_error).__name__
                                })
                                continue

                        # after finishing all cities in state
                        total_states_processed += 1
                        logger.info("Completed state %s (%s): %d cities processed", state, country, len(cities))
                        await asyncio.sleep(2.0)

                    logger.info("Finished country %s", country)

                except Exception as country_error:
                    logger.error("Discovery for country %s failed: %s", country, country_error)
                    # Continue with next country instead of aborting entire run
                    continue

            # completion (after all countries)
            completion_time = datetime.now(timezone.utc).isoformat()
            logger.info("Discovery run %s completed at %s", progress_id, completion_time)
            final_summary = {
                'status': 'success',
                'countries': countries,
                'states_processed': total_states_processed,
                'cities_processed': total_cities_processed,
                'stations_discovered': total_stations_discovered,
                'stations_created': total_stations_created,
                'stations_updated': total_stations_updated,
                'completion_time_utc': completion_time,
                'states_skipped': skipped_states,
                'cities_skipped': skipped_cities,
            }
            logger.info("Final summary: %s", json.dumps(final_summary))

            # --- Write union manifest & summary artifacts (station + derived city) ---
            cities_successfully_fetched = {_scope_key(r['country'], r['state'], r['city']) for r in manifest_rows}
            self._write_union_manifest_and_summary(progress_id, manifest_rows, final_summary, cities_successfully_fetched)
            # ------------------------------------------------------------------

            return final_summary

        except Exception as exc:
            logger.error("Comprehensive station discovery failed: %s", exc)
            raise

    def _write_union_manifest_and_summary(self, run_id: str, rows: List[Dict[str, Any]], summary: Dict[str, Any], cities_successfully_fetched: set) -> None:
        """
        Writes union manifest using manifest_utils.finalize_union_manifest:
          - artifacts/station_manifests/<run_id>/stations.(parquet|jsonl)
          - artifacts/station_manifests/<run_id>/summary.json
          - artifacts/station_manifests/latest.(parquet|jsonl)  (atomic union pointer)
          - artifacts/city_manifests/<run_id>/cities.(parquet|jsonl)  (derived)
          - artifacts/city_manifests/latest.(parquet|jsonl)          (atomic pointer)
        Uses union logic that preserves historical stations and tracks liveness.
        """
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        run_dir = self.manifest_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Filter to active rows just in case
        rows = [r for r in rows if r.get("active") is True]

        if not rows:
            logger.warning("No rows to write to manifest for run_id=%s", run_id)

        # ---- Station manifest (union logic) ----
        station_gcs_prefix = "manifests/station_manifests"
        try:
            final_union_rows = finalize_union_manifest(
                path_root=self.manifest_root,
                run_dir=run_dir,
                fmt=self.manifest_format,
                discovered_rows=rows,
                cities_successfully_fetched=cities_successfully_fetched,
                gcs_prefix=station_gcs_prefix
            )
            logger.info("📦 Wrote union station manifest: %d total stations (%d discovered this run)",
                       len(final_union_rows), len(rows))
        except Exception as e:
            logger.error("Failed to write union manifest: %s", e)
            # Fallback to simple write if union fails
            logger.warning("Falling back to simple manifest write")
            if self.manifest_format == "parquet":
                df = pd.DataFrame(rows)
                latest_path = self.manifest_root / "latest.parquet"
                df.to_parquet(latest_path, index=False)
            else:
                latest_path = self.manifest_root / "latest.jsonl"
                with open(latest_path, "w", encoding="utf-8") as f:
                    for r in rows:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
            final_union_rows = rows
            # Still try to upload fallback manifest to GCS
            upload_manifest_to_gcs(latest_path, station_gcs_prefix)

        # ---- Derived city manifest (run-scoped + latest) ----
        city_gcs_prefix = "manifests/city_manifests"
        try:
            self._write_city_manifest_from_station_rows(run_id, final_union_rows, city_gcs_prefix)
        except Exception as e:
            logger.warning("Failed writing derived city manifest: %s", e)

        # ---- Discovery summary (run-scoped) ----
        summary_path = run_dir / "summary.json"
        tmp_summary = run_dir / "summary.json.tmp"
        with open(tmp_summary, "w", encoding="utf-8") as f:
            f.write(json.dumps({**summary, "run_id": run_id}, indent=2))
        os.replace(tmp_summary, summary_path)
        logger.info("🧾 Wrote discovery summary: %s", summary_path)

    def _write_city_manifest_from_station_rows(self, run_id: str, station_rows: List[Dict[str, Any]], gcs_prefix: str = "") -> None:
        """
        Derive a city manifest from station rows of the same discovery run.
        Writes:
          - artifacts/city_manifests/<run_id>/cities.(parquet|jsonl)
          - artifacts/city_manifests/latest.(parquet|jsonl) (atomic pointer)
        """
        city_root = self.city_manifest_root
        fmt = self.city_manifest_format

        city_root.mkdir(parents=True, exist_ok=True)
        run_dir = city_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # group stations by (country, state, city) and compute a simple centroid
        groups: Dict[Tuple[str, str, str], List[Tuple[Optional[float], Optional[float]]]] = defaultdict(list)
        for r in station_rows:
            if not r.get("active"):
                continue
            country, state, city = r.get("country"), r.get("state"), r.get("city")
            lat, lon = r.get("lat"), r.get("lon")
            if country and state and city:
                try:
                    lat_f = float(lat) if lat is not None else None
                    lon_f = float(lon) if lon is not None else None
                except Exception:
                    lat_f, lon_f = None, None
                groups[(country, state, city)].append((lat_f, lon_f))

        city_rows: List[Dict[str, Any]] = []
        for (country, state, city), coords in groups.items():
            # centroid (ignore None)
            lats = [lat for lat, _ in coords if lat is not None]
            lons = [lon for _, lon in coords if lon is not None]
            lat = sum(lats) / len(lats) if lats else None
            lon = sum(lons) / len(lons) if lons else None

            city_rows.append({
                "run_id": run_id,
                "country": country,
                "state": state,
                "city": city,
                "lat": lat,
                "lon": lon,
                "active": True,
                "scope_key": _scope_key(country, state, city),
                "last_seen_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            })

        if fmt == "parquet" and _HAVE_PANDAS:
            df = pd.DataFrame(city_rows) if city_rows else pd.DataFrame([], columns=[
                "run_id","country","state","city","lat","lon","active","scope_key","last_seen_at_utc"
            ])
            run_path = run_dir / "cities.parquet"
            tmp_run  = run_dir / "cities.parquet.tmp"
            df.to_parquet(tmp_run, index=False)
            os.replace(tmp_run, run_path)

            latest = city_root / "latest.parquet"
            tmp_latest = latest.with_suffix(".tmp")
            df.to_parquet(tmp_latest, index=False)
            os.replace(tmp_latest, latest)
            logger.info("📦 Wrote city manifest (parquet): %s", run_path)
            logger.info("📌 Updated latest city manifest pointer: %s", latest)
        else:
            run_path = run_dir / "cities.jsonl"
            tmp_run  = run_dir / "cities.jsonl.tmp"
            with open(tmp_run, "w", encoding="utf-8") as f:
                for row in city_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp_run, run_path)

            latest = city_root / "latest.jsonl"
            tmp_latest = latest.with_suffix(".tmp")
            with open(tmp_latest, "w", encoding="utf-8") as f:
                for row in city_rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(tmp_latest, latest)
            logger.info("📦 Wrote city manifest (jsonl): %s", run_path)
            logger.info("📌 Updated latest city manifest pointer: %s", latest)

        # Upload city manifest to GCS
        if gcs_prefix:
            upload_manifest_to_gcs(latest, gcs_prefix)

    async def _deactivate_missing_city_stations(
        self,
        city_id: int,
        provider_code: str,
        seen_source_ids: set,
        seen_names: Optional[set] = None
    ):
        """
        Mark stations not returned in this discovery run as inactive.
        Uses both source_station_id and name guards to avoid deactivating freshly-updated rows
        when legacy rows have different source_station_id.
        """
        try:
            async with AsyncSessionLocal() as session:
                seen_ids = list(seen_source_ids) if seen_source_ids else []
                seen_names_list = list(seen_names or [])
                params = {'city_id': city_id, 'provider_code': provider_code}

                id_clause = ""
                name_clause = ""

                if seen_ids:
                    id_placeholders = ",".join([f":id{i}" for i in range(len(seen_ids))])
                    for i, sid in enumerate(seen_ids):
                        params[f"id{i}"] = sid
                    # allow rows with NULL source_station_id to be considered "not seen"
                    id_clause = f"AND (source_station_id IS NULL OR source_station_id NOT IN ({id_placeholders}))"

                if seen_names_list:
                    nm_placeholders = ",".join([f":nm{i}" for i in range(len(seen_names_list))])
                    for i, nm in enumerate(seen_names_list):
                        params[f"nm{i}"] = nm
                    # don’t deactivate rows we just touched by name
                    name_clause = f"AND name NOT IN ({nm_placeholders})"

                query = text(f"""
                    UPDATE stations
                    SET active=false, last_seen_at=NOW(), updated_at=NOW()
                    WHERE city_id=:city_id
                      AND provider_id=(SELECT id FROM providers WHERE code=:provider_code)
                      AND active=true
                      {id_clause}
                      {name_clause}
                    RETURNING station_id, name, source_station_id
                """)
                result = await session.execute(query, params)
                deactivated = result.fetchall()
                await session.commit()
                if deactivated:
                    logger.info("Deactivated %d stations no longer available from %s", len(deactivated), provider_code)
                    for st in deactivated:
                        logger.debug("Deactivated station: %s (%s)", st.name, st.source_station_id)
        except Exception as exc:
            logger.error("Error deactivating missing city stations: %s", exc)

    # Note: _deactivate_missing_city_stations method removed
    # Now using union manifest approach that preserves all stations with liveness tracking
