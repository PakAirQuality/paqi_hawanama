"""
Station registry service for resolving station_id to metadata
"""

import logging
from typing import Optional, Dict, Any
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import SessionLocal
from app.models.station import Station, Provider, City
from app.models.current import StationMeta
from app.schemas.directory import make_station_id

logger = logging.getLogger(__name__)

# In-memory cache for station metadata
_station_cache: Dict[str, StationMeta] = {}


class StationRegistry:
    """Service for resolving station IDs to metadata"""
    
    def __init__(self):
        self.cache = _station_cache
    
    async def resolve_station_id(self, station_id: str) -> Optional[StationMeta]:
        """
        Resolve a station_id to StationMeta
        
        Args:
            station_id: 16-character SHA1 hash of station
            
        Returns:
            StationMeta if found, None otherwise
        """
        # Check cache first
        if station_id in self.cache:
            logger.debug(f"Found station {station_id} in cache")
            return self.cache[station_id]
        
        # Query database
        async with SessionLocal() as session:
            try:
                station_meta = await self._query_station_from_db(session, station_id)
                
                if station_meta:
                    # Cache the result
                    self.cache[station_id] = station_meta
                    logger.info(f"Resolved and cached station {station_id}: {station_meta.name}")
                    return station_meta
                else:
                    logger.warning(f"Station {station_id} not found in database")
                    return None
                    
            except Exception as e:
                logger.error(f"Error resolving station {station_id}: {e}")
                return None
    
    async def _query_station_from_db(self, session: AsyncSession, station_id: str) -> Optional[StationMeta]:
        """
        Query station from database and construct StationMeta
        
        Args:
            session: Database session
            station_id: Station ID to look for
            
        Returns:
            StationMeta if found, None otherwise
        """
        try:
            # First, try to find stations and calculate their IDs to match
            # This is less efficient but handles the case where we don't store the calculated ID
            query = select(Station).options(
                selectinload(Station.provider),
                selectinload(Station.city),
                selectinload(Station.state),
                selectinload(Station.country)
            ).where(Station.provider.has(Provider.code == 'airvisual'))
            
            result = await session.execute(query)
            stations = result.scalars().all()
            
            for station in stations:
                # Use lat/lon from station record directly
                lat, lon = station.lat, station.lon
                
                # Extract location info from meta_json or derive from relationships
                meta_json = station.metadata_json or {}
                
                # Get location info
                country = meta_json.get('iqair_country', station.country.name if station.country else 'Unknown')
                state = meta_json.get('iqair_state', station.state.name if station.state else 'Unknown')
                city = meta_json.get('iqair_city', station.city.name if station.city else 'Unknown')
                
                # Calculate the station ID for this station
                calculated_id = make_station_id(country, state, city, station.name, lat, lon)
                
                if calculated_id == station_id:
                    # Found matching station
                    return StationMeta(
                        country=country,
                        state=state, 
                        city=city,
                        name=station.name,
                        lat=lat,
                        lon=lon,
                        source_station_id=station.source_station_id
                    )
            
            # If not found in database, try a fallback approach with known station patterns
            return await self._resolve_via_fallback(station_id)
            
        except Exception as e:
            logger.error(f"Database query error for station {station_id}: {e}")
            return None
    
    async def _resolve_via_fallback(self, station_id: str) -> Optional[StationMeta]:
        """
        Fallback resolution for common station patterns
        
        Args:
            station_id: Station ID to resolve
            
        Returns:
            StationMeta if pattern matches, None otherwise
        """
        # Common station patterns we might know about
        # This is a fallback for when the database doesn't have complete station info
        known_patterns = {
            # These would be populated from known stations
            # For now, return None as we need actual database data
        }
        
        if station_id in known_patterns:
            pattern = known_patterns[station_id]
            return StationMeta(**pattern)
        
        return None
    
    def clear_cache(self) -> None:
        """Clear the in-memory station cache"""
        self.cache.clear()
        logger.info("Station registry cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "cached_stations": len(self.cache),
            "station_ids": list(self.cache.keys())
        }


# Global registry instance
_station_registry: Optional[StationRegistry] = None


def get_station_registry() -> StationRegistry:
    """Get or create global station registry instance"""
    global _station_registry
    if _station_registry is None:
        _station_registry = StationRegistry()
    return _station_registry


async def resolve_station_id(station_id: str) -> Optional[StationMeta]:
    """
    Convenience function to resolve station_id to StationMeta
    
    Args:
        station_id: 16-character SHA1 hash of station
        
    Returns:
        StationMeta if found, None if not found
    """
    registry = get_station_registry()
    return await registry.resolve_station_id(station_id)