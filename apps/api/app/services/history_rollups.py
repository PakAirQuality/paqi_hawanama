"""
Rollups computation service for history endpoints
"""

import logging
import statistics
from datetime import datetime
from typing import List, Optional, Dict, Any

from app.models.history import HistoryRow, Rollups, WindowStats, PollutantStats, AQIStats, HistoryQuery

logger = logging.getLogger(__name__)


class HistoryRollupsService:
    """Service for computing statistical rollups over historical data"""
    
    def compute_rollups(
        self,
        rows: List[HistoryRow],
        query: HistoryQuery
    ) -> Optional[Rollups]:
        """
        Compute statistical rollups for the given rows
        
        Args:
            rows: List of historical data rows
            query: History query parameters
            
        Returns:
            Rollups object or None if no data
        """
        if not rows:
            return None
        
        try:
            # Compute window statistics
            window_stats = self._compute_window_stats(rows, query)
            
            # Compute pollutant statistics
            pollutant_stats = {}
            for pollutant in ["pm25", "pm10", "o3", "no2", "so2", "co"]:
                if pollutant in query.pollutants:
                    stats = self._compute_pollutant_stats(rows, pollutant)
                    pollutant_stats[pollutant] = stats
                else:
                    pollutant_stats[pollutant] = None
            
            # Compute AQI statistics
            aqi_us_stats = self._compute_aqi_stats(rows, "us")
            aqi_cn_stats = self._compute_aqi_stats(rows, "cn")
            
            return Rollups(
                window=window_stats,
                pm25=pollutant_stats["pm25"],
                pm10=pollutant_stats["pm10"],
                o3=pollutant_stats["o3"],
                no2=pollutant_stats["no2"],
                so2=pollutant_stats["so2"],
                co=pollutant_stats["co"],
                aqi_us=aqi_us_stats,
                aqi_cn=aqi_cn_stats
            )
            
        except Exception as e:
            logger.error(f"Failed to compute rollups: {e}")
            return None
    
    def _compute_window_stats(
        self,
        rows: List[HistoryRow],
        query: HistoryQuery
    ) -> WindowStats:
        """
        Compute window statistics
        
        Args:
            rows: List of historical data rows
            query: History query parameters
            
        Returns:
            WindowStats object
        """
        # Count hours with any data (non-null rows)
        count_hours = len([r for r in rows if self._row_has_data(r)])
        
        # Calculate missing hours
        total_hours = int((query.to_time - query.from_time).total_seconds() / 3600) + 1
        missing_hours = total_hours - count_hours
        
        return WindowStats(
            from_=query.from_time,
            to=query.to_time,
            count_hours=count_hours,
            missing_hours=max(0, missing_hours)  # Ensure non-negative
        )
    
    def _compute_pollutant_stats(
        self,
        rows: List[HistoryRow],
        pollutant: str
    ) -> Optional[PollutantStats]:
        """
        Compute statistics for a specific pollutant
        
        Args:
            rows: List of historical data rows
            pollutant: Pollutant name
            
        Returns:
            PollutantStats or None if no data
        """
        try:
            # Extract non-null values
            values = []
            for row in rows:
                pollutant_data = row.pollutants.get(pollutant)
                if pollutant_data is not None and pollutant_data.conc is not None:
                    values.append(pollutant_data.conc)
            
            if not values:
                return None
            
            # Compute statistics
            mean_val = statistics.mean(values)
            median_val = statistics.median(values)
            max_val = max(values)
            
            # Compute 90th percentile
            p90_val = self._compute_percentile(values, 90)
            
            return PollutantStats(
                mean=round(mean_val, 2),
                median=round(median_val, 2),
                p90=round(p90_val, 2),
                max=round(max_val, 2)
            )
            
        except Exception as e:
            logger.error(f"Failed to compute stats for {pollutant}: {e}")
            return None
    
    def _compute_aqi_stats(
        self,
        rows: List[HistoryRow],
        aqi_scale: str
    ) -> Optional[AQIStats]:
        """
        Compute statistics for AQI scale
        
        Args:
            rows: List of historical data rows
            aqi_scale: AQI scale ("us" or "cn")
            
        Returns:
            AQIStats or None if no data
        """
        try:
            # Extract non-null AQI values
            values = []
            for row in rows:
                aqi_value = row.aqi.get(aqi_scale)
                if aqi_value is not None:
                    values.append(aqi_value)
            
            if not values:
                return None
            
            # Compute statistics
            mean_val = statistics.mean(values)
            max_val = max(values)
            
            return AQIStats(
                mean=round(mean_val),
                max=max_val
            )
            
        except Exception as e:
            logger.error(f"Failed to compute AQI stats for {aqi_scale}: {e}")
            return None
    
    def _compute_percentile(self, values: List[float], percentile: float) -> float:
        """
        Compute percentile value
        
        Args:
            values: List of values
            percentile: Percentile (0-100)
            
        Returns:
            Percentile value
        """
        if not values:
            return 0.0
        
        # Sort values
        sorted_values = sorted(values)
        
        # Calculate index
        n = len(sorted_values)
        k = (percentile / 100) * (n - 1)
        
        # Linear interpolation
        lower = int(k)
        upper = min(lower + 1, n - 1)
        
        if lower == upper:
            return sorted_values[lower]
        
        # Interpolate
        weight = k - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    
    def _row_has_data(self, row: HistoryRow) -> bool:
        """
        Check if a row has any meaningful data
        
        Args:
            row: History row
            
        Returns:
            True if row has data
        """
        # Check if any pollutant has data
        if any(p is not None for p in row.pollutants.values()):
            return True
        
        # Check if AQI has data
        if any(v is not None for v in row.aqi.values()):
            return True
        
        # Check if weather has data
        if any(v is not None for v in row.weather.values()):
            return True
        
        return False


# Global service instance
_history_rollups_service: Optional[HistoryRollupsService] = None


def get_history_rollups_service() -> HistoryRollupsService:
    """Get or create global history rollups service instance"""
    global _history_rollups_service
    if _history_rollups_service is None:
        _history_rollups_service = HistoryRollupsService()
    return _history_rollups_service