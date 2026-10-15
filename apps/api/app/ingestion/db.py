"""
Database service for ingestion: geo hierarchy and station upserts, readings writes.

Shares the application's async engine (app.core.database) instead of building a
second one; the previous worker copy also created an unused sync engine.
"""

from typing import Dict, List, Any, Optional
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.database import engine as async_engine
from app.ingestion.identity import (append_identity_history, as_dict, ensure_identity, merge_discovery_metadata,
                                    now_iso)
from app.ingestion.reconcile import ReconcilePolicy, ReconcileResult, reconcile_and_upsert_readings

logger = logging.getLogger(__name__)

# expire_on_commit=False matches the previous worker session factory, which the
# ingestion tasks rely on when reading results after commit.
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


# cleanup_payload_json (no current callers) only trims legacy raw blobs above this
# size and never touches rows that carry provenance.
RAW_TRIM_THRESHOLD = 4000


class DatabaseService:
    def __init__(self):
        self.async_engine = async_engine

    async def get_async_session(self):
        """Get asynchronous database session"""
        return AsyncSessionLocal()
    
    def generate_station_id(self, country: str, state: str, city: str, name: str, lat: float, lon: float) -> str:
        """Generate stable station_id using SHA1 hash"""
        import hashlib
        canonical = f"{country}|{state}|{city}|{name}|{lat:.6f}|{lon:.6f}"
        return hashlib.sha1(canonical.encode('utf-8')).hexdigest()[:16]

    async def upsert_country(self, session: AsyncSession, country_data: Dict[str, Any]) -> int:
        """Insert or update country data"""
        from sqlalchemy import text
        
        query = text("""
            INSERT INTO countries (name, iso2, iso3, active, last_seen_at)
            VALUES (:name, :iso2, :iso3, :active, NOW())
            ON CONFLICT (name) 
            DO UPDATE SET 
                last_seen_at = NOW(),
                active = EXCLUDED.active
            RETURNING id
        """)
        
        result = await session.execute(query, {
            'name': country_data['name'],
            'iso2': country_data.get('iso2'),
            'iso3': country_data.get('iso3'),
            'active': True
        })
        return result.scalar()

    async def upsert_state(self, session: AsyncSession, state_data: Dict[str, Any]) -> int:
        """Insert or update state data"""
        from sqlalchemy import text
        
        query = text("""
            INSERT INTO states (country_id, name, code, active, last_seen_at)
            VALUES (:country_id, :name, :code, :active, NOW())
            ON CONFLICT (country_id, name) 
            DO UPDATE SET 
                last_seen_at = NOW(),
                active = EXCLUDED.active,
                code = EXCLUDED.code
            RETURNING id
        """)
        
        result = await session.execute(query, {
            'country_id': state_data['country_id'],
            'name': state_data['name'],
            'code': state_data.get('code'),
            'active': True
        })
        return result.scalar()

    async def upsert_city(self, session: AsyncSession, city_data: Dict[str, Any]) -> int:
        """Insert or update city data"""
        from sqlalchemy import text
        
        query = text("""
            INSERT INTO cities (country_id, state_id, name, timezone, active, last_seen_at)
            VALUES (:country_id, :state_id, :name, :timezone, :active, NOW())
            ON CONFLICT (country_id, state_id, name) 
            DO UPDATE SET 
                last_seen_at = NOW(),
                active = EXCLUDED.active,
                timezone = EXCLUDED.timezone
            RETURNING id
        """)
        
        result = await session.execute(query, {
            'country_id': city_data['country_id'],
            'state_id': city_data.get('state_id'),
            'name': city_data['name'],
            'timezone': city_data.get('timezone'),
            'active': True
        })
        return result.scalar()

    async def get_or_create_provider(self, session: AsyncSession, provider_code: str, display_name: Optional[str] = None) -> int:
        """SELECT-first: INSERT ... ON CONFLICT would burn providers_id_seq (SMALLSERIAL) on every call.
        display_name is only used when the row is created; existing names are never rewritten."""
        from sqlalchemy import text
        pid = (await session.execute(text("SELECT id FROM providers WHERE code = :code"), {"code": provider_code})).scalar()
        if pid is None:
            pid = (await session.execute(
                text("INSERT INTO providers (code, display_name) VALUES (:code, :display_name) RETURNING id"),
                {"code": provider_code, "display_name": display_name or provider_code.title()},
            )).scalar_one()
        return int(pid)

    async def resolve_country_id(self, session: AsyncSession, name: str, iso2: Optional[str] = None) -> int:
        """id of an existing country by name (or iso2), creating it if absent."""
        from sqlalchemy import text
        cid = (await session.execute(text("SELECT id FROM countries WHERE name = :n"), {"n": name})).scalar()
        if cid is None and iso2:
            cid = (await session.execute(text("SELECT id FROM countries WHERE iso2 = :i"), {"i": iso2})).scalar()
        if cid is None:
            cid = await self.upsert_country(session, {"name": name, "iso2": iso2})
        return int(cid)

    async def upsert_station(self, session: AsyncSession, station_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Insert or update a station without ever splitting a device's history.

        station_id is still sha1(country|state|city|name|lat|lon)[:16] for new
        rows, but an existing row is found by (provider_id, source_station_id)
        first: a coordinate correction keeps the legacy station_id and is
        recorded in metadata_json.identity.history instead of creating a second
        row. A computed id that already belongs to a different native id is an
        identity_conflict and is skipped (reported, never merged). Curated
        metadata keys survive; discovery only writes its own keys and native ids.
        """
        from sqlalchemy import text

        provider_code = station_data.get("provider_code", "airvisual")
        provider_id = await self.get_or_create_provider(session, provider_code)
        source_station_id = station_data.get("source_station_id")
        computed_id = self.generate_station_id(
            station_data["country"], station_data["state"], station_data["city"],
            station_data["name"], station_data["lat"], station_data["lon"],
        )
        ts = now_iso()
        incoming_meta = dict(station_data.get("metadata_json") or {})
        if source_station_id:
            incoming_meta = ensure_identity(incoming_meta, provider_code, source_station_id, since=ts,
                                            evidence=f"{provider_code}:discovery")

        by_native = None
        if source_station_id:
            by_native = (await session.execute(text("""
                SELECT station_id, name, lat, lon, metadata_json FROM stations
                WHERE provider_id = :pid AND source_station_id = :sid
            """), {"pid": provider_id, "sid": source_station_id})).fetchone()

        # --- 1. same native id, different computed id: a move/rename. Keep the legacy id. ---
        if by_native is not None and by_native.station_id.strip() != computed_id:
            legacy_id = by_native.station_id.strip()
            merged = merge_discovery_metadata(as_dict(by_native.metadata_json), incoming_meta)
            merged = append_identity_history(merged, {
                "at": ts, "run_id": station_data.get("run_id"), "event": "rename_or_move", "provider": provider_code,
                "from": {"name": by_native.name, "lat": by_native.lat, "lon": by_native.lon},
                "to": {"name": station_data["name"], "lat": station_data["lat"], "lon": station_data["lon"]},
                "computed_station_id": computed_id,
            })
            await session.execute(text("""
                UPDATE stations
                   SET name = :name, lat = :lat, lon = :lon, metadata_json = CAST(:metadata_json AS jsonb),
                       active = :active, updated_at = NOW(), last_seen_at = :last_seen_at
                 WHERE station_id = :station_id
            """), {"name": station_data["name"], "lat": station_data["lat"], "lon": station_data["lon"],
                   "metadata_json": json.dumps(merged), "active": station_data.get("active", True),
                   "last_seen_at": station_data.get("last_seen_at"), "station_id": legacy_id})
            logger.warning("Station %s (%s) moved/renamed: computed id %s, keeping legacy id %s",
                           station_data["name"], source_station_id, computed_id, legacy_id)
            return {"station_id": legacy_id, "created": False, "updated": True,
                    "identity_event": "rename_or_move", "computed_station_id": computed_id}

        # --- 2. computed id already used by a different native id: do not merge, report. ---
        by_id = (await session.execute(text("""
            SELECT station_id, provider_id, source_station_id, metadata_json FROM stations WHERE station_id = :sid
        """), {"sid": computed_id})).fetchone()
        if by_id is not None and source_station_id and by_id.source_station_id and \
                (by_id.source_station_id != source_station_id or int(by_id.provider_id) != provider_id):
            logger.error("Identity conflict: computed station_id %s for %s/%s already belongs to %s/%s; skipping",
                         computed_id, provider_code, source_station_id, by_id.provider_id, by_id.source_station_id)
            return {"station_id": None, "created": False, "updated": False, "identity_event": "identity_conflict",
                    "conflicting_station_id": computed_id, "conflicting_source_station_id": by_id.source_station_id}

        # --- 3. normal path: merge metadata in Python so curated keys survive, then upsert. ---
        merged = merge_discovery_metadata(as_dict(by_id.metadata_json) if by_id is not None else None, incoming_meta)
        await session.execute(text("""
            INSERT INTO stations (
                station_id, country_id, state_id, city_id, name, lat, lon,
                provider_id, source_station_id, metadata_json, active, updated_at, last_seen_at
            )
            VALUES (
                :station_id, :country_id, :state_id, :city_id, :name, :lat, :lon,
                :provider_id, :source_station_id, CAST(:metadata_json AS jsonb), :active, NOW(), :last_seen_at
            )
            ON CONFLICT (station_id) DO UPDATE SET
                name = EXCLUDED.name,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW(),
                active = EXCLUDED.active,
                last_seen_at = EXCLUDED.last_seen_at
        """), {
            "station_id": computed_id, "country_id": station_data["country_id"],
            "state_id": station_data.get("state_id"), "city_id": station_data.get("city_id"),
            "name": station_data["name"], "lat": station_data["lat"], "lon": station_data["lon"],
            "provider_id": provider_id, "source_station_id": source_station_id,
            "metadata_json": json.dumps(merged), "active": station_data.get("active", True),
            "last_seen_at": station_data.get("last_seen_at"),
        })

        # --- 4. rename candidates (same provider, city and coordinates, different name): report only. ---
        cands = (await session.execute(text("""
            SELECT station_id, name, source_station_id FROM stations
             WHERE provider_id = :pid AND station_id <> :sid
               AND COALESCE(city_id, -1) = COALESCE(:city_id, -1)
               AND abs(lat - :lat) < 0.000001 AND abs(lon - :lon) < 0.000001
             LIMIT 5
        """), {"pid": provider_id, "sid": computed_id, "city_id": station_data.get("city_id"),
               "lat": station_data["lat"], "lon": station_data["lon"]})).fetchall()
        result = {"station_id": computed_id, "created": by_id is None, "updated": by_id is not None}
        if cands:
            result["identity_event"] = "rename_candidate"
            result["rename_candidates"] = [{"station_id": c.station_id.strip(), "name": c.name,
                                            "source_station_id": c.source_station_id} for c in cands]
        return result

    async def reconcile_and_upsert_readings(self, session: AsyncSession, rows: List[Dict[str, Any]],
                                            policy: ReconcilePolicy) -> ReconcileResult:
        """
        Field-aware write: fills NULLs, revises changed values, never NULLs a stored
        value, exact replays are no-ops. See app.ingestion.reconcile. Caller commits.
        """
        return await reconcile_and_upsert_readings(session, rows, policy)

    async def get_stations_by_provider(self, session: AsyncSession, provider_code: str, country_name: str = 'Pakistan') -> List[Dict[str, Any]]:
        """Get all stations for a specific provider, filtered by country"""
        from sqlalchemy import text
        
        query = text("""
            SELECT s.station_id, s.name, s.lat, s.lon, s.metadata_json, s.source_station_id,
                   c.name as country, st.name as state, ci.name as city
            FROM stations s
            LEFT JOIN countries c ON s.country_id = c.id
            LEFT JOIN states st ON s.state_id = st.id
            LEFT JOIN cities ci ON s.city_id = ci.id
            JOIN providers p ON s.provider_id = p.id
            WHERE p.code = :provider_code 
              AND s.active = TRUE 
              AND c.name = :country_name
            ORDER BY s.station_id
        """)
        
        result = await session.execute(query, {
            'provider_code': provider_code,
            'country_name': country_name
        })
        return [dict(row._mapping) for row in result.fetchall()]
    
    async def get_latest_reading(self, session: AsyncSession, station_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest reading for a station"""
        from sqlalchemy import text
        
        query = text("""
            SELECT ts_utc, pm25, pm10, aqi_us, aqi_cn, temp_c, humidity, qc_state
            FROM readings
            WHERE scope_type = 'station' AND scope_key = :station_id
            ORDER BY ts_utc DESC
            LIMIT 1
        """)
        
        result = await session.execute(query, {'station_id': station_id})
        row = result.fetchone()
        return dict(row._mapping) if row else None
    
    async def cleanup_payload_json(self, session: AsyncSession, batch_size: int = 1000) -> int:
        """Clean up oversized payload_json fields to reduce storage waste"""
        from sqlalchemy import text
        
        # Get count of records with large raw JSON
        # Rows that carry provenance (raw ? 'prov') are never rewritten here.
        count_query = text("""
            SELECT COUNT(*) as large_payloads
            FROM readings 
            WHERE LENGTH(raw::text) > :threshold
              AND NOT (raw ? 'prov')
        """)        
        
        result = await session.execute(count_query, {"threshold": RAW_TRIM_THRESHOLD})
        total_large = result.scalar()
        
        if total_large == 0:
            logger.info("No oversized payload_json fields found")
            return 0
        
        logger.info(f"Found {total_large} readings with oversized raw JSON, cleaning up...")
        
        # Update raw JSON to contain only essential metadata
        cleanup_query = text("""
            UPDATE readings 
            SET raw = jsonb_build_object(
                'city', 
                CASE 
                    WHEN raw ? 'city' THEN raw->>'city'
                    ELSE NULL 
                END,
                'state',
                CASE 
                    WHEN raw ? 'state' THEN raw->>'state'
                    ELSE NULL 
                END,
                'country',
                CASE 
                    WHEN raw ? 'country' THEN raw->>'country'
                    ELSE 'Pakistan'
                END,
                'timestamp', ts_utc::text,
                'api_version', 'v2',
                'cleaned_up', NOW()::text
            )
            WHERE LENGTH(raw::text) > :threshold
              AND NOT (raw ? 'prov')
        """)
        
        await session.execute(cleanup_query, {"threshold": RAW_TRIM_THRESHOLD})
        await session.commit()
        
        logger.info(f"Successfully cleaned up {total_large} oversized raw JSON records")
        return total_large