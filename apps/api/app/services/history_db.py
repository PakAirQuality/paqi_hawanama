"""
Database service for historical air quality data
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import select, and_, or_, text, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.station import Station, Provider, City
from app.models.reading import Reading
from app.models.current import StationMeta
from app.models.history import HistoryQuery

logger = logging.getLogger(__name__)


class HistoryDatabaseService:
    """Service for querying historical data from database"""
    
    async def get_city_readings(
        self, 
        country: str, 
        state: str, 
        city: str, 
        query: HistoryQuery
    ) -> List[Dict[str, Any]]:
        """
        Get historical readings for a city from the database
        
        Args:
            country: Country name
            state: State/province name
            city: City name
            query: History query parameters
            
        Returns:
            List of reading dictionaries
        """
        async with SessionLocal() as session:
            try:
                # Find stations in the city
                stations_query = (
                    select(Station)
                    .options(selectinload(Station.source))
                    .where(
                        and_(
                            Station.source.has(MonitorSource.type == 'iqair'),
                            # Match city from meta_json or relationship
                            or_(
                                Station.meta_json.op('->>')('iqair_city') == city,
                                Station.city.has(City.name == city)
                            )
                        )
                    )
                )
                
                stations_result = await session.execute(stations_query)
                stations = stations_result.scalars().all()
                
                if not stations:
                    logger.warning(f"No stations found for {city}, {state}, {country}")
                    return []
                
                station_ids = [s.id for s in stations]
                
                # Query readings for all stations in the city
                readings = await self._query_readings_by_station_ids(
                    session, station_ids, query
                )
                
                # Add scope information
                for reading in readings:
                    reading['scope_country'] = country
                    reading['scope_state'] = state
                    reading['scope_city'] = city
                
                return readings
                
            except Exception as e:
                logger.error(f"Error querying city readings for {city}, {state}, {country}: {e}")
                return []
    
    async def get_station_readings(
        self, 
        station_meta: StationMeta, 
        query: HistoryQuery
    ) -> List[Dict[str, Any]]:
        """
        Get historical readings for a specific station from the database
        
        Args:
            station_meta: Station metadata
            query: History query parameters
            
        Returns:
            List of reading dictionaries
        """
        async with SessionLocal() as session:
            try:
                # Find the station by metadata
                station = await self._find_station_by_meta(session, station_meta)
                
                if not station:
                    logger.warning(f"Station not found in database: {station_meta.name}")
                    return []
                
                # Query readings for the station
                readings = await self._query_readings_by_station_ids(
                    session, [station.id], query
                )
                
                # Add scope information
                for reading in readings:
                    reading['scope_country'] = station_meta.country
                    reading['scope_state'] = station_meta.state
                    reading['scope_city'] = station_meta.city
                
                return readings
                
            except Exception as e:
                logger.error(f"Error querying station readings for {station_meta.name}: {e}")
                return []
    
    async def _find_station_by_meta(
        self, 
        session: AsyncSession, 
        station_meta: StationMeta
    ) -> Optional[Station]:
        """
        Find a station by metadata
        
        Args:
            session: Database session
            station_meta: Station metadata
            
        Returns:
            Station object if found, None otherwise
        """
        try:
            # Try to find by external_id first if available
            if station_meta.source_station_id:
                query = select(Station).where(
                    Station.external_id == station_meta.source_station_id
                )
                result = await session.execute(query)
                station = result.scalar_one_or_none()
                if station:
                    return station
            
            # Fallback: find by location and name similarity
            # Use PostGIS distance function to find nearby stations
            query = select(Station).where(
                and_(
                    Station.name.ilike(f'%{station_meta.name}%'),
                    func.ST_DWithin(
                        Station.geom,
                        func.ST_Point(station_meta.lon, station_meta.lat),
                        0.01  # ~1km tolerance
                    )
                )
            )
            result = await session.execute(query)
            return result.scalar_one_or_none()
            
        except Exception as e:
            logger.error(f"Error finding station by metadata: {e}")
            return None
    
    async def _query_readings_by_station_ids(
        self,
        session: AsyncSession,
        station_ids: List[int],
        query: HistoryQuery
    ) -> List[Dict[str, Any]]:
        """
        Query readings for given station IDs and time range
        
        Args:
            session: Database session
            station_ids: List of station IDs to query
            query: History query parameters
            
        Returns:
            List of reading dictionaries
        """
        try:
            # Build the query
            readings_query = (
                select(ReadingHour)
                .where(
                    and_(
                        ReadingHour.station_id.in_(station_ids),
                        ReadingHour.ts >= query.from_time,
                        ReadingHour.ts <= query.to_time
                    )
                )
                .order_by(ReadingHour.ts)
            )
            
            result = await session.execute(readings_query)
            db_readings = result.scalars().all()
            
            # Convert to dictionary format
            readings = []
            for reading in db_readings:
                reading_dict = {
                    'ts_utc': reading.ts,
                    'station_id': reading.station_id,
                    # Pollutants
                    'pm25': reading.pm25,
                    'pm10': reading.pm10,
                    'o3': reading.o3,
                    'no2': reading.no2,
                    'so2': reading.so2,
                    'co': reading.co,
                    'aqi_raw': reading.aqi_raw,
                    # Weather
                    'temp_c': reading.temp,
                    'humidity': reading.hum,
                    'pressure_hpa': reading.pressure,
                    'wind_speed_ms': reading.wind_speed,
                    'wind_dir_deg': reading.wind_direction,
                    'icon': reading.weather_icon,
                    'heatIndex_c': reading.heat_index,
                    # Metadata
                    'qc_state': reading.qc_state,
                    'origin': reading.origin,
                    'source': 'database'
                }
                readings.append(reading_dict)
            
            logger.info(f"Retrieved {len(readings)} readings from database for {len(station_ids)} stations")
            return readings
            
        except Exception as e:
            logger.error(f"Error querying readings from database: {e}")
            return []
    
    async def get_coverage_stats(
        self,
        station_ids: List[int],
        from_time: datetime,
        to_time: datetime
    ) -> Dict[str, Any]:
        """
        Get coverage statistics for stations in time range
        
        Args:
            station_ids: List of station IDs
            from_time: Start time
            to_time: End time
            
        Returns:
            Coverage statistics dictionary
        """
        async with SessionLocal() as session:
            try:
                # Count total readings
                count_query = select(func.count(ReadingHour.ts)).where(
                    and_(
                        ReadingHour.station_id.in_(station_ids),
                        ReadingHour.ts >= from_time,
                        ReadingHour.ts <= to_time
                    )
                )
                result = await session.execute(count_query)
                total_readings = result.scalar() or 0
                
                # Calculate expected readings (hours in range)
                total_hours = int((to_time - from_time).total_seconds() / 3600) + 1
                expected_readings = total_hours * len(station_ids)
                
                return {
                    'total_readings': total_readings,
                    'expected_readings': expected_readings,
                    'coverage_ratio': total_readings / expected_readings if expected_readings > 0 else 0,
                    'stations_count': len(station_ids)
                }
                
            except Exception as e:
                logger.error(f"Error getting coverage stats: {e}")
                return {
                    'total_readings': 0,
                    'expected_readings': 0,
                    'coverage_ratio': 0,
                    'stations_count': len(station_ids)
                }
    
    async def aggregate_city_readings(
        self,
        readings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Aggregate multiple station readings by timestamp for a city
        
        Args:
            readings: List of individual station readings
            
        Returns:
            List of aggregated readings by timestamp
        """
        if not readings:
            return []
        
        # Group by timestamp
        timestamp_groups = {}
        for reading in readings:
            ts = reading['ts_utc']
            if ts not in timestamp_groups:
                timestamp_groups[ts] = []
            timestamp_groups[ts].append(reading)
        
        # Aggregate each timestamp group
        aggregated = []
        for ts, group_readings in sorted(timestamp_groups.items()):
            # Take the first reading for scope and metadata
            base_reading = group_readings[0]
            
            aggregated_reading = {
                'ts_utc': ts,
                'scope_country': base_reading['scope_country'],
                'scope_state': base_reading['scope_state'],
                'scope_city': base_reading['scope_city'],
                'source': 'database',
                'qc_state': 'OK'  # Default for aggregated
            }
            
            # Aggregate pollutants (simple average for now)
            pollutants = ['pm25', 'pm10', 'o3', 'no2', 'so2', 'co', 'aqi_raw']
            for pollutant in pollutants:
                values = [r[pollutant] for r in group_readings if r[pollutant] is not None]
                aggregated_reading[pollutant] = sum(values) / len(values) if values else None
            
            # Aggregate weather (simple average)
            weather_fields = ['temp_c', 'humidity', 'pressure_hpa', 'wind_speed_ms', 
                             'wind_dir_deg', 'heatIndex_c']
            for field in weather_fields:
                values = [r[field] for r in group_readings if r[field] is not None]
                aggregated_reading[field] = sum(values) / len(values) if values else None
            
            # Take first non-null weather icon
            aggregated_reading['icon'] = next(
                (r['icon'] for r in group_readings if r['icon'] is not None), None
            )
            
            aggregated.append(aggregated_reading)
        
        return aggregated


# Global service instance
_history_db_service: Optional[HistoryDatabaseService] = None


def get_history_db_service() -> HistoryDatabaseService:
    """Get or create global history database service instance"""
    global _history_db_service
    if _history_db_service is None:
        _history_db_service = HistoryDatabaseService()
    return _history_db_service