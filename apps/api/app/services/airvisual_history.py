"""
Main AirVisual history service that orchestrates all components
"""

import logging
from typing import List, Optional

from app.models.current import Scope
from app.models.history import HistoryOut, HistoryQuery
from app.services.station_registry import resolve_station_id
from app.services.history_db import get_history_db_service
from app.services.history_upstream import get_history_upstream_service
from app.services.history_merge import get_history_merge_service
from app.services.history_rollups import get_history_rollups_service

logger = logging.getLogger(__name__)


class AirVisualHistoryService:
    """Main service for AirVisual history endpoints"""
    
    def __init__(self):
        self.db_service = get_history_db_service()
        self.upstream_service = get_history_upstream_service()
        self.merge_service = get_history_merge_service()
        self.rollups_service = get_history_rollups_service()
    
    async def get_city_history(
        self,
        country: str,
        state: str,
        city: str,
        query: HistoryQuery
    ) -> HistoryOut:
        """
        Get historical data for a city
        
        Args:
            country: Country name
            state: State/province name
            city: City name
            query: History query parameters
            
        Returns:
            HistoryOut response
        """
        try:
            # Fetch from database
            db_readings = await self.db_service.get_city_readings(country, state, city, query)
            logger.info(f"Retrieved {len(db_readings)} readings from database for {city}")
            
            # Fetch from upstream if coverage needed and available
            upstream_readings = []
            if self.upstream_service.has_upstream_coverage(query):
                try:
                    upstream_readings = await self.upstream_service.get_city_history_last48h(
                        country, state, city
                    )
                    logger.info(f"Retrieved {len(upstream_readings)} readings from upstream for {city}")
                except Exception as e:
                    logger.warning(f"Failed to fetch upstream data for {city}: {e}")
            
            # Merge and normalize
            normalized_rows = self.merge_service.merge_and_normalize_readings(
                db_readings, upstream_readings, query
            )
            
            # Compute rollups if requested
            rollups = None
            if query.include_rollups:
                rollups = self.rollups_service.compute_rollups(normalized_rows, query)
            
            # Create scope
            scope = Scope(country=country, state=state, city=city)
            
            # Standard units
            units = {
                "pm25": "µg/m³",
                "pm10": "µg/m³",
                "o3": "ppb",
                "no2": "ppb",
                "so2": "ppb",
                "co": "ppm"
            }
            
            return HistoryOut(
                scope=scope,
                source="airvisual",
                granularity=query.granularity,
                units=units,
                rows=normalized_rows,
                rollups=rollups
            )
            
        except Exception as e:
            logger.error(f"Error getting city history for {city}, {state}, {country}: {e}")
            raise RuntimeError(f"Failed to retrieve city history: {e}")
    
    async def get_station_history(
        self,
        station_id: str,
        query: HistoryQuery
    ) -> HistoryOut:
        """
        Get historical data for a station
        
        Args:
            station_id: 16-character station ID
            query: History query parameters
            
        Returns:
            HistoryOut response
            
        Raises:
            RuntimeError: If station not found or data retrieval fails
        """
        try:
            # Resolve station metadata
            station_meta = await resolve_station_id(station_id)
            if not station_meta:
                raise RuntimeError("station_not_found")
            
            # Fetch from database
            db_readings = await self.db_service.get_station_readings(station_meta, query)
            logger.info(f"Retrieved {len(db_readings)} readings from database for station {station_meta.name}")
            
            # Fetch from upstream if coverage needed and available
            upstream_readings = []
            has_plan_access = True  # Assume access unless proven otherwise
            
            if self.upstream_service.has_upstream_coverage(query):
                try:
                    upstream_readings = await self.upstream_service.get_station_history_last48h(station_meta)
                    logger.info(f"Retrieved {len(upstream_readings)} readings from upstream for station {station_meta.name}")
                except Exception as e:
                    if "plan upgrade" in str(e).lower() or "not available" in str(e).lower():
                        has_plan_access = False
                        logger.info(f"Station history not available on plan for {station_meta.name}")
                    else:
                        logger.warning(f"Failed to fetch upstream data for station {station_meta.name}: {e}")
            
            # If no data from either source, check if it's a plan limitation
            if not db_readings and not upstream_readings and not has_plan_access:
                # Don't raise 501 here, just return empty with note in headers
                # The router will add the appropriate header
                pass
            
            # Merge and normalize
            normalized_rows = self.merge_service.merge_and_normalize_readings(
                db_readings, upstream_readings, query
            )
            
            # Compute rollups if requested
            rollups = None
            if query.include_rollups:
                rollups = self.rollups_service.compute_rollups(normalized_rows, query)
            
            # Create scope
            scope = Scope(
                country=station_meta.country,
                state=station_meta.state,
                city=station_meta.city
            )
            
            # Standard units
            units = {
                "pm25": "µg/m³",
                "pm10": "µg/m³",
                "o3": "ppb",
                "no2": "ppb",
                "so2": "ppb",
                "co": "ppm"
            }
            
            result = HistoryOut(
                scope=scope,
                source="airvisual",
                granularity=query.granularity,
                units=units,
                rows=normalized_rows,
                rollups=rollups
            )
            
            # Add metadata about plan limitations
            if not has_plan_access:
                # This will be used by the router to add headers
                result.upstream_note = "station_history_unavailable_on_plan"
            
            return result
            
        except RuntimeError as e:
            if "station_not_found" in str(e):
                raise
            logger.error(f"Error getting station history for {station_id}: {e}")
            raise RuntimeError(f"Failed to retrieve station history: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting station history for {station_id}: {e}")
            raise RuntimeError(f"Failed to retrieve station history: {e}")
    
    def check_timezone_fallback(self, result: HistoryOut, requested_tz: str) -> bool:
        """
        Check if timezone conversion fell back to UTC
        
        Args:
            result: History result
            requested_tz: Requested timezone
            
        Returns:
            True if fallback occurred
        """
        if not result.rows:
            return False
        
        first_row = result.rows[0]
        return self.merge_service.detect_timezone_fallback(
            first_row.ts_utc, first_row.ts_local, requested_tz
        )


# Global service instance
_history_service: Optional[AirVisualHistoryService] = None


def get_history_service() -> AirVisualHistoryService:
    """Get or create global history service instance"""
    global _history_service
    if _history_service is None:
        _history_service = AirVisualHistoryService()
    return _history_service