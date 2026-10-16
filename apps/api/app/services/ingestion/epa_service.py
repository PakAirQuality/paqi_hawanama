"""
Punjab EPA ingestion (aqipunjab.com), an independent connector with its own
credential and endpoint. It is never routed through IQAir.

Changes from the original:
  * async httpx through the shared client (the old code called requests.get and
    time.sleep inside an async function, blocking the event loop)
  * per-station isolation: one bad station (HTTP error, missing coordinates,
    unparseable row) is recorded as an entity failure and the run continues;
    the old loop raised TypeError on float(None) before its own null check
  * one commit per station, explicitly; readings go through the field-aware
    reconcile (no NULL-overwrites, exact replays are no-ops)
  * every payload is archived (credentials stripped) and each row carries
    provenance in readings.raw.prov; the provider's own AQI is stored as
    reported with raw.prov.aqi.source = 'provider_reported'
  * units stay NULL — the endpoint's units are not attested
  * returns a RunOutcome (success / partial / failed) like the other tasks
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as _default_settings
from app.ingestion.db import AsyncSessionLocal, DatabaseService
from app.ingestion.http import default_timeout, get_shared_async_client, register_secret
from app.ingestion.leases import LeaseManager, holder_id, lease_key_for
from app.ingestion.raw_archive import RawPayloadArchiver
from app.ingestion.reconcile import ReconcilePolicy
from app.ingestion.runs import EntityFailure, RunOutcome, RunRecorder, new_run_id
from app.ingestion.units import apply_units
from app.ingestion.validation import validate_reading

logger = logging.getLogger(__name__)

PROVIDER_CODE = "punjab"
PROVIDER_DISPLAY_NAME = "Punjab EPA"
PARSER_VERSION = "punjab_hourly_v2"
DEFAULT_TZ = "Asia/Karachi"
COUNTRY_NAME = "Pakistan"


def station_id_for_punjab(source_station_id: str) -> str:
    """Deterministic char(16) id derived from the provider's station code (unchanged)."""
    import hashlib
    return f"pb_{hashlib.sha256(f'punjab:{source_station_id}'.encode()).hexdigest()[:12]}"


def _coerce_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _parse_ts(raw: Any) -> Optional[datetime]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


class PunjabEPAClient:
    """Thin async client for the two endpoints we use."""

    def __init__(self, *, settings=None, http: Optional[httpx.AsyncClient] = None):
        s = settings or _default_settings
        self.base = (s.PUNJAB_EPA_API_BASE or "https://aqipunjab.com/api").rstrip("/")
        self.api_key = s.PUNJAB_EPA_API_KEY or ""
        self.timeout = default_timeout(connect=10.0, read=float(s.PUNJAB_EPA_TIMEOUT_S))
        self._http = http
        if self.api_key:
            register_secret(self.api_key)
        else:
            logger.warning("PUNJAB_EPA_API_KEY not set — Punjab EPA ingestion will fail")

    def _headers(self) -> Dict[str, str]:
        return {
            "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest", "X-API-Key": self.api_key,
            "X-Platform": "web", "Origin": "https://aqipunjab.com", "Referer": "https://aqipunjab.com/",
        }

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        client = self._http or get_shared_async_client()
        resp = await client.get(f"{self.base}/{path}", headers=self._headers(), params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    async def fetch_stations(self) -> List[Dict[str, Any]]:
        data = await self._get("stations")
        if isinstance(data, dict) and data.get("success") and data.get("data"):
            return data["data"][0] if isinstance(data["data"], list) and data["data"] else []
        logger.warning("Unexpected Punjab stations payload shape")
        return []

    async def fetch_station_24h(self, station_code: str, district: str) -> Optional[Dict[str, Any]]:
        data = await self._get("historical/24hours", {"station": station_code, "district": district})
        if isinstance(data, dict) and data.get("success"):
            return data.get("data")
        return None


async def collect_once(db: AsyncSession, *, trigger: str = "http", settings=None, client: Optional[PunjabEPAClient] = None,
                       db_service: Optional[DatabaseService] = None, archiver: Optional[RawPayloadArchiver] = None,
                       recorder: Optional[RunRecorder] = None, leases: Optional[LeaseManager] = None,
                       sleep=asyncio.sleep) -> RunOutcome:
    """One-shot ingestion for all Punjab stations on the given session. Returns a RunOutcome."""
    s = settings or _default_settings
    client = client or PunjabEPAClient(settings=s)
    dbs = db_service or DatabaseService()
    archiver = archiver or RawPayloadArchiver(s)
    recorder = recorder or RunRecorder(AsyncSessionLocal, Path(s.INGEST_OUT_DIR), required=False)
    leases = leases or LeaseManager(AsyncSessionLocal, required=True)

    run_id = new_run_id("punjab-ingest")
    outcome = RunOutcome(run_id=run_id, task="punjab-ingest", provider_code=PROVIDER_CODE, scope="Punjab", trigger=trigger)
    c = outcome.counts
    await recorder.start(outcome)
    lease = None
    try:
        lease = await leases.acquire(lease_key_for("punjab-ingest", PROVIDER_CODE, "all"), holder_id(run_id), int(s.INGEST_LEASE_TTL_S))
        if lease is None:
            outcome.skip("lease_held", "another punjab-ingest run holds the lease")
            return outcome
        outcome.lease_key, outcome.lease_fence = lease.lease_key, lease.fence

        provider_id = await dbs.get_or_create_provider(db, PROVIDER_CODE, PROVIDER_DISPLAY_NAME)
        country_id = await dbs.resolve_country_id(db, COUNTRY_NAME, "PK")
        await db.commit()

        try:
            stations = await client.fetch_stations()
        except Exception as exc:
            outcome.fail("inventory_fetch_failed", f"{type(exc).__name__}: {exc}")
            return outcome
        ref = await archiver.archive(provider=PROVIDER_CODE, stream="stations", native_id="all", payload=stations,
                                     request_meta={"endpoint": "stations"}, fetched_at=datetime.now(timezone.utc),
                                     http_status=200, run_id=run_id, parser_version=PARSER_VERSION)
        await archiver.record(AsyncSessionLocal, ref)
        c.expected = len(stations)
        if not stations:
            outcome.fail("empty_inventory", "Punjab /stations returned no stations")
            return outcome

        now = datetime.now(timezone.utc)
        latest_ts: Optional[datetime] = None
        rejected: Dict[str, int] = {}
        for st in stations:
            code = st.get("station_code")
            district = st.get("district")
            key = str(code or st.get("station_name") or "?")
            c.attempted += 1
            try:
                if not code or not district:
                    raise ValueError("station_code/district missing")
                lat, lon = _coerce_float(st.get("lat")), _coerce_float(st.get("lon"))
                if lat is None or lon is None:
                    raise ValueError("missing or non-numeric coordinates")

                data = await client.fetch_station_24h(code, district)
                if not data:
                    raise ValueError("no data in 24h response")
                pref = await archiver.archive(provider=PROVIDER_CODE, stream="station_24h", native_id=code, payload=data,
                                              request_meta={"endpoint": "historical/24hours", "params": {"station": code, "district": district}},
                                              fetched_at=datetime.now(timezone.utc), http_status=200, run_id=run_id,
                                              parser_version=PARSER_VERSION)
                await archiver.record(AsyncSessionLocal, pref)

                station_id = station_id_for_punjab(code)
                await _upsert_station(db, provider_id=provider_id, country_id=country_id, station_id=station_id,
                                      source_station_id=code, name=st.get("station_name") or code, lat=lat, lon=lon)

                rows: List[Dict[str, Any]] = []
                for _, row in (data.get("hourly_data") or {}).items():
                    ts = _parse_ts(row.get("datetime") or row.get("timestamp"))
                    pol = row.get("pollutants") or {}
                    rng = row.get("aqi_range") or {}
                    r = {
                        "scope_type": "station", "scope_key": station_id, "ts_utc": ts,
                        "pm25": _coerce_float(pol.get("pm25")), "pm10": _coerce_float(pol.get("pm10")),
                        "o3": _coerce_float(pol.get("o3")), "no2": _coerce_float(pol.get("no2")),
                        "so2": _coerce_float(pol.get("so2")), "co": _coerce_float(pol.get("co")),
                        "aqi_us": _coerce_float(row.get("aqi")),
                        "main_us": row.get("main_pollutant") or row.get("main_us") or None,
                        "source": PROVIDER_CODE,
                        "raw": {"provider": PROVIDER_CODE, "aqi_range": rng, "health_index": rng.get("health_index"),
                                "color": rng.get("color"), "v": PARSER_VERSION,
                                "prov": {**pref.prov(), "run": run_id, "pv": PARSER_VERSION,
                                         "aqi": {"source": "provider_reported", "scale": "unknown", "basis": "unknown"}}},
                    }
                    if r["aqi_us"] is not None:
                        r["aqi_us"] = int(round(r["aqi_us"]))
                    apply_units(r, PROVIDER_CODE)
                    v = validate_reading(r, now=now)
                    if not v.ok:
                        rejected[v.rejected] = rejected.get(v.rejected, 0) + 1
                        continue
                    if v.quarantined:
                        v.row["raw"]["prov"]["q"] = v.quarantined
                    rows.append(v.row)
                c.rows_fetched += len(rows)
                if rows:
                    wr = await dbs.reconcile_and_upsert_readings(db, rows, ReconcilePolicy(source=PROVIDER_CODE, run_id=run_id))
                    c.rows_written += wr.rows_written
                    c.rows_unchanged += wr.rows_unchanged
                    mx = max(r["ts_utc"] for r in rows)
                    latest_ts = mx if latest_ts is None or mx > latest_ts else latest_ts
                await db.commit()   # one commit per station: a later failure never loses this station's rows
                c.completed += 1
            except Exception as exc:
                await db.rollback()
                c.failed += 1
                recorder.add_failure(EntityFailure("station", key, type(exc).__name__, str(exc)[:500],
                                                   details={"district": district}))
                logger.warning("Punjab station %s failed: %s: %s", key, type(exc).__name__, exc)
            await sleep(float(s.PUNJAB_EPA_PACING_S))

        outcome.latest_observation_ts = latest_ts
        outcome.details["extraction"] = {"rejected": rejected, "archive_failures": archiver.failures}
    except Exception as exc:
        logger.exception("Punjab ingest run %s crashed", run_id)
        outcome.fail(type(exc).__name__, str(exc))
    finally:
        outcome.finish()
        await recorder.finish(outcome)
        await leases.release(lease)
    logger.info("Punjab ingest run %s %s: %s", run_id, outcome.status.value, outcome.counts)
    return outcome


async def _upsert_station(db: AsyncSession, *, provider_id: int, country_id: int, station_id: str,
                          source_station_id: str, name: str, lat: float, lon: float, tz: str = DEFAULT_TZ) -> None:
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO stations (station_id, country_id, name, lat, lon, provider_id, source_station_id, timezone, active)
        VALUES (:station_id, :country_id, :name, :lat, :lon, :provider_id, :source_station_id, :tz, true)
        ON CONFLICT (provider_id, source_station_id) DO UPDATE
        SET name = EXCLUDED.name, lat = EXCLUDED.lat, lon = EXCLUDED.lon, active = true, updated_at = NOW()
    """), dict(station_id=station_id, country_id=country_id, name=name, lat=lat, lon=lon,
               provider_id=provider_id, source_station_id=source_station_id, tz=tz))
