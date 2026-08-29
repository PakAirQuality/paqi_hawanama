from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime, JSON, ForeignKey, Text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.dialects.postgresql import insert
from geoalchemy2 import Geometry
# Dual-path imports for API container compatibility
try:
    from app.config.settings import get_settings
    settings = get_settings()
except ImportError:  # running in pure worker repo layout
    from config.settings import settings
from typing import Dict, List, Any, Optional
import asyncio
import json
import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

logger = logging.getLogger(__name__)

# Create engines
sync_engine = create_engine(settings.SYNC_DATABASE_URL)
async_engine = create_async_engine(settings.DATABASE_URL)

# Session makers
SyncSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class DatabaseService:
    def __init__(self):
        self.sync_engine = sync_engine
        self.async_engine = async_engine
    
    def get_sync_session(self):
        """Get synchronous database session"""
        return SyncSessionLocal()
    
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

    async def upsert_station(self, session: AsyncSession, station_data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update station data with versioning"""
        from sqlalchemy import text
        
        # Generate stable station_id
        station_id = self.generate_station_id(
            station_data['country'], 
            station_data['state'], 
            station_data['city'],
            station_data['name'], 
            station_data['lat'], 
            station_data['lon']
        )
        
        # Check if station exists and if location/name changed
        check_query = text("""
            SELECT station_id, name, lat, lon FROM stations 
            WHERE station_id = :station_id
        """)
        
        existing = await session.execute(check_query, {'station_id': station_id})
        existing_station = existing.fetchone()
        
        if existing_station:
            # Check if name or coordinates changed
            name_changed = existing_station.name != station_data['name']
            coords_changed = (
                abs(existing_station.lat - station_data['lat']) > 0.000001 or 
                abs(existing_station.lon - station_data['lon']) > 0.000001
            )
            
            if name_changed or coords_changed:
                # Add version history
                version_query = text("""
                    INSERT INTO station_versions (station_id, valid_from, name, lat, lon, metadata_json)
                    VALUES (:station_id, NOW(), :old_name, :old_lat, :old_lon, :old_metadata)
                """)
                
                await session.execute(version_query, {
                    'station_id': station_id,
                    'old_name': existing_station.name,
                    'old_lat': existing_station.lat,
                    'old_lon': existing_station.lon,
                    'old_metadata': json.dumps({'changed_reason': 'coordinates_or_name_update'})
                })
        
        # Determine if this will be a create or update
        was_existing = existing_station is not None
        
        # Get or create provider (providers table has required display_name column)
        provider_query = text("""
            INSERT INTO providers (code, display_name) 
            VALUES (:code, :display_name)
            ON CONFLICT (code) DO UPDATE SET
                display_name = EXCLUDED.display_name
            RETURNING id
        """)
        
        provider_code = station_data.get('provider_code', 'airvisual')
        provider_result = await session.execute(provider_query, {
            'code': provider_code,
            'display_name': provider_code.title()
        })
        
        # Get provider ID
        provider_id_query = text("""
            SELECT id FROM providers WHERE code = :code
        """)
        provider_result = await session.execute(provider_id_query, {
            'code': station_data.get('provider_code', 'airvisual')
        })
        provider_id = provider_result.scalar()
        
        upsert_query = text("""
            INSERT INTO stations (
                station_id, country_id, state_id, city_id, name, lat, lon,
                provider_id, source_station_id, metadata_json, active, updated_at, last_seen_at
            )
            VALUES (
                :station_id, :country_id, :state_id, :city_id, :name, :lat, :lon,
                :provider_id, :source_station_id, :metadata_json, :active, NOW(), :last_seen_at
            )
            ON CONFLICT (station_id) 
            DO UPDATE SET 
                name = EXCLUDED.name,
                lat = EXCLUDED.lat,
                lon = EXCLUDED.lon,
                metadata_json = EXCLUDED.metadata_json,
                updated_at = NOW(),
                active = EXCLUDED.active,
                last_seen_at = EXCLUDED.last_seen_at
        """)
        
        await session.execute(upsert_query, {
            'station_id': station_id,
            'country_id': station_data['country_id'],
            'state_id': station_data.get('state_id'),
            'city_id': station_data.get('city_id'),
            'name': station_data['name'],
            'lat': station_data['lat'],
            'lon': station_data['lon'],
            'provider_id': provider_id,
            'source_station_id': station_data.get('source_station_id'),
            'metadata_json': json.dumps(station_data.get('metadata_json', {})),
            'active': station_data.get('active', True),
            'last_seen_at': station_data.get('last_seen_at')
        })
        
        return {
            'station_id': station_id,
            'created': not was_existing,
            'updated': was_existing
        }
    
    async def upsert_reading(self, session: AsyncSession, reading_data: Dict[str, Any]) -> None:
        """Insert or update reading data in new TimescaleDB schema"""
        from sqlalchemy import text
        
        query = text("""
            INSERT INTO readings (
                scope_type, scope_key, ts_utc,
                aqi_us, aqi_cn, main_us, main_cn,
                pm25, pm10, o3, no2, so2, co,
                units_pm25, units_pm10, units_o3, units_no2, units_so2, units_co,
                temp_c, humidity, pressure_hpa, wind_speed_ms, wind_dir_deg,
                weather_icon, heatindex_c, pop_pct,
                qc_state, source, raw
            )
            VALUES (
                :scope_type, :scope_key, :ts_utc,
                :aqi_us, :aqi_cn, :main_us, :main_cn,
                :pm25, :pm10, :o3, :no2, :so2, :co,
                :units_pm25, :units_pm10, :units_o3, :units_no2, :units_so2, :units_co,
                :temp_c, :humidity, :pressure_hpa, :wind_speed_ms, :wind_dir_deg,
                :weather_icon, :heatindex_c, :pop_pct,
                :qc_state, :source, :raw
            )
            ON CONFLICT (scope_type, scope_key, ts_utc) 
            DO UPDATE SET 
                aqi_us = EXCLUDED.aqi_us,
                aqi_cn = EXCLUDED.aqi_cn,
                main_us = EXCLUDED.main_us,
                main_cn = EXCLUDED.main_cn,
                pm25 = EXCLUDED.pm25,
                pm10 = EXCLUDED.pm10,
                o3 = EXCLUDED.o3,
                no2 = EXCLUDED.no2,
                so2 = EXCLUDED.so2,
                co = EXCLUDED.co,
                units_pm25 = EXCLUDED.units_pm25,
                units_pm10 = EXCLUDED.units_pm10,
                units_o3 = EXCLUDED.units_o3,
                units_no2 = EXCLUDED.units_no2,
                units_so2 = EXCLUDED.units_so2,
                units_co = EXCLUDED.units_co,
                temp_c = EXCLUDED.temp_c,
                humidity = EXCLUDED.humidity,
                pressure_hpa = EXCLUDED.pressure_hpa,
                wind_speed_ms = EXCLUDED.wind_speed_ms,
                wind_dir_deg = EXCLUDED.wind_dir_deg,
                weather_icon = EXCLUDED.weather_icon,
                heatindex_c = EXCLUDED.heatindex_c,
                pop_pct = EXCLUDED.pop_pct,
                qc_state = EXCLUDED.qc_state,
                raw = EXCLUDED.raw
        """)
        
        await session.execute(query, reading_data)

    async def upsert_readings_bulk(self, session: AsyncSession, readings_data: List[Dict[str, Any]]) -> int:
        """Bulk insert/update readings data for better performance"""
        from sqlalchemy import text
        
        if not readings_data:
            return 0
        
        query = text("""
            INSERT INTO readings (
                scope_type, scope_key, ts_utc,
                aqi_us, aqi_cn, main_us, main_cn,
                pm25, pm10, o3, no2, so2, co,
                units_pm25, units_pm10, units_o3, units_no2, units_so2, units_co,
                temp_c, humidity, pressure_hpa, wind_speed_ms, wind_dir_deg,
                weather_icon, heatindex_c, pop_pct,
                qc_state, source
            )
            VALUES (
                :scope_type, :scope_key, :ts_utc,
                :aqi_us, :aqi_cn, :main_us, :main_cn,
                :pm25, :pm10, :o3, :no2, :so2, :co,
                :units_pm25, :units_pm10, :units_o3, :units_no2, :units_so2, :units_co,
                :temp_c, :humidity, :pressure_hpa, :wind_speed_ms, :wind_dir_deg,
                :weather_icon, :heatindex_c, :pop_pct,
                :qc_state, :source
            )
            ON CONFLICT (scope_type, scope_key, ts_utc) 
            DO UPDATE SET 
                aqi_us = EXCLUDED.aqi_us,
                aqi_cn = EXCLUDED.aqi_cn,
                main_us = EXCLUDED.main_us,
                main_cn = EXCLUDED.main_cn,
                pm25 = EXCLUDED.pm25,
                pm10 = EXCLUDED.pm10,
                o3 = EXCLUDED.o3,
                no2 = EXCLUDED.no2,
                so2 = EXCLUDED.so2,
                co = EXCLUDED.co,
                units_pm25 = EXCLUDED.units_pm25,
                units_pm10 = EXCLUDED.units_pm10,
                units_o3 = EXCLUDED.units_o3,
                units_no2 = EXCLUDED.units_no2,
                units_so2 = EXCLUDED.units_so2,
                units_co = EXCLUDED.units_co,
                temp_c = EXCLUDED.temp_c,
                humidity = EXCLUDED.humidity,
                pressure_hpa = EXCLUDED.pressure_hpa,
                wind_speed_ms = EXCLUDED.wind_speed_ms,
                wind_dir_deg = EXCLUDED.wind_dir_deg,
                weather_icon = EXCLUDED.weather_icon,
                heatindex_c = EXCLUDED.heatindex_c,
                pop_pct = EXCLUDED.pop_pct,
                qc_state = EXCLUDED.qc_state
        """)
        
        # For PostgreSQL async, we need to execute individually or use bulk_insert_mappings
        count = 0
        for reading in readings_data:
            await session.execute(query, reading)
            count += 1
        return count
    
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
        count_query = text("""
            SELECT COUNT(*) as large_payloads
            FROM readings 
            WHERE LENGTH(raw::text) > 1000
        """)        
        
        result = await session.execute(count_query)
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
            WHERE LENGTH(raw::text) > 1000
        """)
        
        await session.execute(cleanup_query)
        await session.commit()
        
        logger.info(f"Successfully cleaned up {total_large} oversized raw JSON records")
        return total_large