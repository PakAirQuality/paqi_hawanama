"""Punjab EPA data ingestion service"""

import json
import os
import time
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

def station_id_for_punjab(source_station_id: str) -> str:
    # Generate a shorter station ID using hash since db field is limited
    import hashlib
    hash_obj = hashlib.sha256(f"punjab:{source_station_id}".encode())
    return f"pb_{hash_obj.hexdigest()[:12]}"

def get_settings():
    epa_key = os.environ.get("PUNJAB_EPA_API_KEY", "")
    if not epa_key:
        logger.warning("PUNJAB_EPA_API_KEY not set — Punjab EPA ingestion will fail")
    return dict(
        api_base="https://aqipunjab.com/api",
        api_key=epa_key,
        tz="Asia/Karachi",
        country_id_pk=1,  # Pakistan country ID (adjust if needed)
        log_level="INFO",
    )

def http_get(url: str, headers: Dict[str, str], params: Dict[str, Any] | None = None, timeout=30):
    resp = requests.get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()

def fetch_stations(api_base: str, api_key: str) -> List[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-API-Key": api_key,
        "X-Platform": "web",
        "Origin": "https://aqipunjab.com",
        "Referer": "https://aqipunjab.com/"
    }
    logger.info("Fetching Punjab EPA stations")
    
    data = http_get(f"{api_base}/stations", headers=headers)
    
    if data.get("success") and data.get("data"):
        stations = data["data"][0]
        logger.info("Fetched %d stations", len(stations))
        return stations
    logger.warning("Unexpected stations payload: %s", data)
    return []

def fetch_station_24h(api_base: str, api_key: str, station_code: str, district: str) -> Optional[Dict[str, Any]]:
    headers = {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-API-Key": api_key,
        "X-Platform": "web",
        "Origin": "https://aqipunjab.com",
        "Referer": "https://aqipunjab.com/"
    }
    params = {"station": station_code, "district": district}
    data = http_get(f"{api_base}/historical/24hours", headers=headers, params=params)
    
    if data.get("success"):
        return data.get("data")
    return None

async def ensure_punjab_provider(db: AsyncSession) -> int:
    result = await db.execute(text("SELECT id FROM providers WHERE code='punjab'"))
    pid = result.scalar()
    if pid is None:
        result = await db.execute(text("""
            INSERT INTO providers (code, display_name, active)
            VALUES ('punjab','Punjab EPA', true)
            RETURNING id
        """))
        pid = result.scalar_one()
        await db.commit()
    return int(pid)

async def upsert_station(db: AsyncSession, *, provider_id: int, country_id: int,
                   source_station_id: str, name: str, lat: float, lon: float, tz: str) -> str:
    station_id = station_id_for_punjab(source_station_id)
    await db.execute(text("""
        INSERT INTO stations (
          station_id, country_id, name, lat, lon,
          provider_id, source_station_id, timezone, active
        )
        VALUES (
          :station_id, :country_id, :name, :lat, :lon,
          :provider_id, :source_station_id, :tz, true
        )
        ON CONFLICT (provider_id, source_station_id) DO UPDATE
        SET name=EXCLUDED.name, lat=EXCLUDED.lat, lon=EXCLUDED.lon, active=true, station_id=EXCLUDED.station_id
    """), dict(
        station_id=station_id, country_id=country_id, name=name,
        lat=lat, lon=lon, provider_id=provider_id,
        source_station_id=source_station_id, tz=tz,
    ))
    await db.commit()
    return station_id

async def upsert_reading(db: AsyncSession, *, station_id: str, ts_utc: datetime,
                   pm25: Any, pm10: Any, o3: Any, no2: Any, so2: Any, co: Any,
                   aqi_us: Any, main_us: Any, raw: Dict[str, Any]):
    await db.execute(text("""
        INSERT INTO readings (
          scope_type, scope_key, ts_utc,
          pm25, pm10, o3, no2, so2, co,
          aqi_us, main_us, raw, source, ingested_at
        )
        VALUES (
          'station', :scope_key, :ts_utc,
          :pm25, :pm10, :o3, :no2, :so2, :co,
          :aqi_us, :main_us, CAST(:raw AS jsonb), 'punjab', now()
        )
        ON CONFLICT (scope_type, scope_key, ts_utc) DO UPDATE
        SET pm25=EXCLUDED.pm25, pm10=EXCLUDED.pm10, o3=EXCLUDED.o3,
            no2=EXCLUDED.no2, so2=EXCLUDED.so2, co=EXCLUDED.co,
            aqi_us=EXCLUDED.aqi_us, main_us=EXCLUDED.main_us,
            raw = COALESCE(readings.raw,'{}'::jsonb) || EXCLUDED.raw,
            source='punjab'
    """), dict(
        scope_key=station_id, ts_utc=ts_utc,
        pm25=pm25, pm10=pm10, o3=o3, no2=no2, so2=so2, co=co,
        aqi_us=aqi_us, main_us=main_us, raw=json.dumps(raw),
    ))
    await db.commit()

async def collect_once(db: AsyncSession) -> Dict[str, Any]:
    """One-shot ingestion for all Punjab stations; returns a JSON summary."""
    s = get_settings()
    logging.getLogger().setLevel(s["log_level"])
    
    provider_id = await ensure_punjab_provider(db)

    stations = fetch_stations(s["api_base"], s["api_key"])
    t0 = time.time()
    ok, fail, stored = 0, 0, 0
    errors: List[str] = []
    details: List[Dict[str, Any]] = []

    for i, st in enumerate(stations, start=1):
        code = st.get("station_code")
        district = st.get("district")
        if not code or not district:
            fail += 1
            errors.append(f"bad station meta #{i}: {st}")
            continue

        data = fetch_station_24h(s["api_base"], s["api_key"], code, district)
        if not data:
            fail += 1
            errors.append(f"no data {code}")
            continue

        # Use coordinates from stations list since station_metadata in 24h endpoint might be null
        lat = float(st.get("lat"))
        lon = float(st.get("lon"))
        name = st.get("station_name") or code
        if lat is None or lon is None:
            fail += 1
            errors.append(f"missing coords {code}")
            continue

        station_id = await upsert_station(
            db,
            provider_id=provider_id,
            country_id=s["country_id_pk"],
            source_station_id=code,
            name=name, lat=float(lat), lon=float(lon), tz=s["tz"]
        )

        hourly = data.get("hourly_data") or {}
        for _, row in hourly.items():
            # timestamps may be '...Z' or '+00:00'
            ts_str = row.get("datetime") or row.get("timestamp")
            if not ts_str:
                continue
            ts_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            pol = row.get("pollutants") or {}
            range_info = (row.get("aqi_range") or {})
            # NOTE: we are trusting Punjab's AQI & main pollutant as provided here.
            # If you want to compute US AQI yourself, call your usaqi module instead.
            await upsert_reading(
                db,
                station_id=station_id, ts_utc=ts_utc,
                pm25=pol.get("pm25"), pm10=pol.get("pm10"),
                o3=pol.get("o3"), no2=pol.get("no2"),
                so2=pol.get("so2"), co=pol.get("co"),
                aqi_us=row.get("aqi"),
                main_us=(row.get("main_pollutant") or row.get("main_us") or None),
                raw={
                    "provider": "punjab",
                    "aqi_range": range_info,
                    "health_index": range_info.get("health_index"),
                    "color": range_info.get("color"),
                    "v": "punjab_hourly_v1"
                }
            )
            stored += 1
        ok += 1
        time.sleep(0.25)  # gentle pacing

        details.append({"station_code": code, "stored": len(hourly)})

    dur = int(time.time() - t0)
    summary = {"ok": ok, "fail": fail, "stored": stored, "secs": dur, "details": details, "errors": errors}
    logger.info("Punjab ingest summary: %s", summary)
    return summary