"""
Data merging and normalization service for history endpoints
"""

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Set, Literal, Optional
import zoneinfo

from app.models.current import ScalarWithUnit
from app.models.history import HistoryRow, HistoryQuery
from app.utils.history_params import generate_hourly_timeline

logger = logging.getLogger(__name__)


class HistoryMergeService:
    """Service for merging and normalizing historical data from multiple sources"""
    
    def merge_and_normalize_readings(
        self,
        db_readings: List[Dict[str, Any]],
        upstream_readings: List[Dict[str, Any]], 
        query: HistoryQuery
    ) -> List[HistoryRow]:
        """
        Merge database and upstream readings, normalize to HistoryRow format
        
        Args:
            db_readings: Readings from database
            upstream_readings: Readings from upstream API
            query: History query parameters
            
        Returns:
            List of normalized HistoryRow objects
        """
        # Merge readings by timestamp (DB wins on conflicts)
        merged_readings = self._merge_readings_by_timestamp(db_readings, upstream_readings)
        
        # Fill missing hours if requested
        if query.fill:
            merged_readings = self._fill_missing_hours(merged_readings, query)
        
        # Normalize to HistoryRow format
        normalized_rows = []
        for reading in merged_readings:
            try:
                row = self._normalize_reading_to_row(reading, query)
                normalized_rows.append(row)
            except Exception as e:
                logger.warning(f"Failed to normalize reading at {reading.get('ts_utc')}: {e}")
                continue
        
        # Sort by timestamp
        normalized_rows.sort(key=lambda x: x.ts_utc)
        
        logger.info(f"Merged and normalized {len(normalized_rows)} readings")
        return normalized_rows
    
    def _merge_readings_by_timestamp(
        self,
        db_readings: List[Dict[str, Any]],
        upstream_readings: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Merge readings by timestamp, DB wins on conflicts
        
        Args:
            db_readings: Readings from database
            upstream_readings: Readings from upstream
            
        Returns:
            List of merged readings
        """
        # Index readings by timestamp
        readings_by_ts = {}
        
        # Add upstream readings first
        for reading in upstream_readings:
            ts = reading['ts_utc']
            # Round to hour for merging
            ts_hour = ts.replace(minute=0, second=0, microsecond=0)
            readings_by_ts[ts_hour] = reading.copy()
        
        # Add DB readings (overwrites upstream on conflicts)
        for reading in db_readings:
            ts = reading['ts_utc']
            # Round to hour for merging
            ts_hour = ts.replace(minute=0, second=0, microsecond=0)
            readings_by_ts[ts_hour] = reading.copy()
            
        # Return sorted list
        merged = list(readings_by_ts.values())
        merged.sort(key=lambda x: x['ts_utc'])
        
        logger.debug(f"Merged {len(db_readings)} DB readings and {len(upstream_readings)} upstream readings into {len(merged)} unique timestamps")
        return merged
    
    def _fill_missing_hours(
        self,
        readings: List[Dict[str, Any]],
        query: HistoryQuery
    ) -> List[Dict[str, Any]]:
        """
        Fill missing hours with null readings
        
        Args:
            readings: Existing readings
            query: History query parameters
            
        Returns:
            List of readings with filled gaps
        """
        if not readings:
            # If no readings, create null readings for entire range
            timeline = generate_hourly_timeline(query.from_time, query.to_time)
            return [self._create_null_reading(ts) for ts in timeline]
        
        # Generate complete timeline
        timeline = generate_hourly_timeline(query.from_time, query.to_time)
        
        # Index existing readings by timestamp
        readings_by_ts = {
            r['ts_utc'].replace(minute=0, second=0, microsecond=0): r 
            for r in readings
        }
        
        # Fill timeline
        filled_readings = []
        for ts in timeline:
            if ts in readings_by_ts:
                filled_readings.append(readings_by_ts[ts])
            else:
                # Create null reading for missing hour
                null_reading = self._create_null_reading(ts)
                # Copy scope information from first available reading
                if readings:
                    first_reading = readings[0]
                    null_reading.update({
                        'scope_country': first_reading.get('scope_country'),
                        'scope_state': first_reading.get('scope_state'),
                        'scope_city': first_reading.get('scope_city')
                    })
                filled_readings.append(null_reading)
        
        logger.debug(f"Filled {len(filled_readings) - len(readings)} missing hours")
        return filled_readings
    
    def _create_null_reading(self, ts_utc: datetime) -> Dict[str, Any]:
        """
        Create a null reading for a missing timestamp
        
        Args:
            ts_utc: Timestamp for null reading
            
        Returns:
            Dictionary with null values
        """
        return {
            'ts_utc': ts_utc,
            'source': 'filled',
            'scope_country': None,
            'scope_state': None,
            'scope_city': None,
            
            # Null pollutants
            'pm25': None,
            'pm10': None,
            'o3': None,
            'no2': None,
            'so2': None,
            'co': None,
            'aqi_raw': None,
            
            # Null weather
            'temp_c': None,
            'humidity': None,
            'pressure_hpa': None,
            'wind_speed_ms': None,
            'wind_dir_deg': None,
            'icon': None,
            'heatIndex_c': None,
            
            'qc_state': None
        }
    
    def _normalize_reading_to_row(
        self,
        reading: Dict[str, Any],
        query: HistoryQuery
    ) -> HistoryRow:
        """
        Normalize a reading dictionary to HistoryRow format
        
        Args:
            reading: Raw reading dictionary
            query: History query parameters
            
        Returns:
            Normalized HistoryRow object
        """
        ts_utc = reading['ts_utc']
        ts_local = self._convert_to_local_time(ts_utc, query.tz)
        
        # Normalize AQI data
        aqi_data = self._normalize_aqi_data(reading, query.aqi_mode)
        
        # Normalize pollutants data
        pollutants_data = self._normalize_pollutants_data(reading, query.pollutants)
        
        # Normalize weather data
        weather_data = self._normalize_weather_data(reading)
        
        return HistoryRow(
            ts_utc=ts_utc,
            ts_local=ts_local,
            aqi=aqi_data,
            pollutants=pollutants_data,
            weather=weather_data,
            qc_state=reading.get('qc_state')
        )
    
    def _convert_to_local_time(self, ts_utc: datetime, tz_str: str) -> datetime:
        """
        Convert UTC timestamp to local time
        
        Args:
            ts_utc: UTC timestamp
            tz_str: Timezone string
            
        Returns:
            Local timestamp (falls back to UTC if invalid)
        """
        try:
            # Ensure UTC timezone is set
            if ts_utc.tzinfo is None:
                ts_utc = ts_utc.replace(tzinfo=timezone.utc)
            elif ts_utc.tzinfo != timezone.utc:
                ts_utc = ts_utc.astimezone(timezone.utc)
            
            # Convert to target timezone
            target_tz = zoneinfo.ZoneInfo(tz_str)
            return ts_utc.astimezone(target_tz)
            
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as e:
            logger.warning(f"Invalid timezone '{tz_str}', using UTC: {e}")
            return ts_utc.replace(tzinfo=timezone.utc) if ts_utc.tzinfo is None else ts_utc
    
    def _normalize_aqi_data(
        self,
        reading: Dict[str, Any], 
        aqi_mode: Literal["us", "cn", "both"]
    ) -> Dict[str, Any]:
        """
        Normalize AQI data based on mode
        
        Args:
            reading: Raw reading data
            aqi_mode: AQI mode from query
            
        Returns:
            Normalized AQI dictionary
        """
        aqi_data = {}
        
        # Extract raw AQI (assume US AQI from database/upstream)
        raw_aqi = reading.get('aqi_raw')
        
        if aqi_mode in ["us", "both"]:
            aqi_data["us"] = int(raw_aqi) if raw_aqi is not None else None
            # Determine main pollutant from highest concentration
            main_pollutant = self._determine_main_pollutant(reading)
            aqi_data["main_us"] = main_pollutant
        
        if aqi_mode in ["cn", "both"]:
            # Convert US AQI to CN AQI (simplified approximation)
            if raw_aqi is not None:
                # This is a simplified conversion - in practice you'd need proper conversion tables
                cn_aqi = int(raw_aqi * 0.73)  # Rough approximation
                aqi_data["cn"] = cn_aqi
            else:
                aqi_data["cn"] = None
            aqi_data["main_cn"] = self._determine_main_pollutant(reading)
        
        # Set missing keys to None for consistency
        if aqi_mode == "us":
            aqi_data["cn"] = None
            aqi_data["main_cn"] = None
        elif aqi_mode == "cn":
            aqi_data["us"] = None
            aqi_data["main_us"] = None
        
        return aqi_data
    
    def _determine_main_pollutant(self, reading: Dict[str, Any]) -> Optional[str]:
        """
        Determine main pollutant based on concentrations
        
        Args:
            reading: Raw reading data
            
        Returns:
            Main pollutant name or None
        """
        # Simple heuristic: if PM2.5 is present and > 35, it's likely the main pollutant
        pm25 = reading.get('pm25')
        if pm25 is not None and pm25 > 35:
            return "pm25"
        
        # Check PM10
        pm10 = reading.get('pm10')
        if pm10 is not None and pm10 > 50:
            return "pm10"
        
        # Default to pm25 if any pollutant data exists
        if any(reading.get(p) is not None for p in ['pm25', 'pm10', 'o3', 'no2', 'so2', 'co']):
            return "pm25"
        
        return None
    
    def _normalize_pollutants_data(
        self,
        reading: Dict[str, Any],
        requested_pollutants: List[str]
    ) -> Dict[str, Optional[ScalarWithUnit]]:
        """
        Normalize pollutants data
        
        Args:
            reading: Raw reading data
            requested_pollutants: List of requested pollutants
            
        Returns:
            Normalized pollutants dictionary
        """
        pollutants_data = {}
        
        # Standard units for pollutants
        units_map = {
            "pm25": "µg/m³",
            "pm10": "µg/m³",
            "o3": "ppb",
            "no2": "ppb",
            "so2": "ppb",
            "co": "ppm"
        }
        
        # Always include all standard pollutants, set to None if not in data
        for pollutant in ["pm25", "pm10", "o3", "no2", "so2", "co"]:
            conc = reading.get(pollutant)
            
            if conc is not None and pollutant in requested_pollutants:
                pollutants_data[pollutant] = ScalarWithUnit(
                    conc=float(conc),
                    unit=units_map[pollutant]
                )
            else:
                pollutants_data[pollutant] = None
        
        return pollutants_data
    
    def _normalize_weather_data(self, reading: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize weather data
        
        Args:
            reading: Raw reading data
            
        Returns:
            Normalized weather dictionary
        """
        weather_data = {}
        
        # Map weather fields
        weather_fields = {
            'temp_c': 'temp_c',
            'humidity': 'humidity',
            'pressure_hpa': 'pressure_hpa',
            'wind_speed_ms': 'wind_speed_ms',
            'wind_dir_deg': 'wind_dir_deg',
            'icon': 'icon',
            'heatIndex_c': 'heatIndex_c'
        }
        
        for field_name, reading_key in weather_fields.items():
            value = reading.get(reading_key)
            weather_data[field_name] = value
        
        # Remove None values to keep response clean
        weather_data = {k: v for k, v in weather_data.items() if v is not None}
        
        return weather_data
    
    def detect_timezone_fallback(self, ts_utc: datetime, ts_local: datetime, tz: str) -> bool:
        """
        Detect if timezone conversion fell back to UTC
        
        Args:
            ts_utc: UTC timestamp
            ts_local: Local timestamp  
            tz: Requested timezone
            
        Returns:
            True if fallback occurred
        """
        if tz in ["UTC", "Asia/Karachi"]:
            return False
        
        # If local time equals UTC time, likely a fallback occurred
        return (ts_local.replace(tzinfo=None) == ts_utc.replace(tzinfo=None) and
                ts_local.tzinfo is not None and 
                str(ts_local.tzinfo) == "UTC")


# Global service instance
_history_merge_service: Optional[HistoryMergeService] = None


def get_history_merge_service() -> HistoryMergeService:
    """Get or create global history merge service instance"""
    global _history_merge_service
    if _history_merge_service is None:
        _history_merge_service = HistoryMergeService()
    return _history_merge_service