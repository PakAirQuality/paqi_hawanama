"""
Data normalization service for current conditions
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal, Union, List
import zoneinfo

from app.models.current import CurrentOut, Scope, ScalarWithUnit

logger = logging.getLogger(__name__)


def normalize_current(
    payload: Dict[str, Any], 
    aqi_mode: Literal["us", "cn", "both"], 
    tz_str: str, 
    scope: Dict[str, str]
) -> CurrentOut:
    """
    Normalize AirVisual current data payload to canonical CurrentOut format
    
    Args:
        payload: Raw AirVisual API response data
        aqi_mode: Which AQI scales to include ("us", "cn", "both")  
        tz_str: IANA timezone string for local timestamp conversion
        scope: Geographic scope with country, state, city keys
        
    Returns:
        Normalized CurrentOut object
    """
    # Extract main data sections
    current = payload.get("current", {})
    pollution = current.get("pollution", {})
    weather = current.get("weather", {})
    units = payload.get("units", {})
    
    # Parse timestamp from pollution data
    ts_utc = _parse_timestamp(pollution.get("ts"))
    ts_local = _convert_to_local_time(ts_utc, tz_str)
    
    # Normalize AQI data based on mode
    aqi_data = _normalize_aqi_data(pollution, aqi_mode)
    
    # Normalize weather data
    weather_data = _normalize_weather_data(weather)
    
    # Normalize pollutants data
    pollutants_data = _normalize_pollutants_data(pollution, units)
    
    # Get QC state if present
    qc_state = payload.get("qc_state")
    
    # Standard units mapping
    standard_units = {
        "pm25": "µg/m³",
        "pm10": "µg/m³", 
        "o3": "ppb",
        "no2": "ppb",
        "so2": "ppb",
        "co": "ppm"
    }
    
    # Create scope object
    scope_obj = Scope(
        country=scope["country"],
        state=scope["state"],
        city=scope["city"]
    )
    
    return CurrentOut(
        scope=scope_obj,
        source="airvisual",
        ts_utc=ts_utc,
        ts_local=ts_local,
        aqi=aqi_data,
        weather=weather_data,
        pollutants=pollutants_data,
        qc_state=qc_state,
        units=standard_units
    )


def _parse_timestamp(timestamp_str: Optional[str]) -> datetime:
    """
    Parse AirVisual timestamp string to UTC datetime
    
    Args:
        timestamp_str: ISO timestamp string from AirVisual API
        
    Returns:
        UTC datetime object
    """
    if not timestamp_str:
        return datetime.now(timezone.utc)
    
    try:
        # AirVisual timestamps are in ISO format with 'Z' suffix
        if timestamp_str.endswith('Z'):
            ts_utc = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
        else:
            ts_utc = datetime.fromisoformat(timestamp_str)
            if ts_utc.tzinfo is None:
                ts_utc = ts_utc.replace(tzinfo=timezone.utc)
        
        return ts_utc
        
    except (ValueError, TypeError) as e:
        logger.warning(f"Could not parse timestamp '{timestamp_str}': {e}")
        return datetime.now(timezone.utc)


def _convert_to_local_time(ts_utc: datetime, tz_str: str) -> datetime:
    """
    Convert UTC timestamp to local time using timezone string
    
    Args:
        ts_utc: UTC datetime object
        tz_str: IANA timezone string
        
    Returns:
        Localized datetime object, falls back to UTC if timezone invalid
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
        logger.warning(f"Invalid timezone '{tz_str}', falling back to UTC: {e}")
        return ts_utc.replace(tzinfo=timezone.utc) if ts_utc.tzinfo is None else ts_utc


def _normalize_aqi_data(pollution: Dict[str, Any], aqi_mode: Literal["us", "cn", "both"]) -> Dict[str, Union[int, str, None]]:
    """
    Normalize AQI data based on requested mode
    
    Args:
        pollution: Pollution data from AirVisual API
        aqi_mode: Which AQI scales to include
        
    Returns:
        Normalized AQI data dictionary
    """
    aqi_data = {}
    
    if aqi_mode in ["us", "both"]:
        aqi_data["us"] = pollution.get("aqius")
        # Map AirVisual main pollutant codes to our names
        main_us = pollution.get("mainus")
        aqi_data["main_us"] = _map_pollutant_code(main_us)
    
    if aqi_mode in ["cn", "both"]:
        aqi_data["cn"] = pollution.get("aqicn")
        # Map AirVisual main pollutant codes to our names
        main_cn = pollution.get("maincn") 
        aqi_data["main_cn"] = _map_pollutant_code(main_cn)
    
    # Set missing keys to None for consistency
    if aqi_mode == "us":
        aqi_data["cn"] = None
        aqi_data["main_cn"] = None
    elif aqi_mode == "cn":
        aqi_data["us"] = None
        aqi_data["main_us"] = None
    
    return aqi_data


def _map_pollutant_code(code: Optional[str]) -> Optional[str]:
    """
    Map AirVisual pollutant codes to our standard names
    
    Args:
        code: AirVisual pollutant code (p1, p2, o3, etc.)
        
    Returns:
        Mapped pollutant name or original code
    """
    if not code:
        return None
    
    mapping = {
        "p1": "pm10",
        "p2": "pm25", 
        "o3": "o3",
        "n2": "no2",
        "s2": "so2",
        "co": "co"
    }
    
    return mapping.get(code, code)


def _normalize_weather_data(weather: Dict[str, Any]) -> Dict[str, Union[float, int, str, None]]:
    """
    Normalize weather data from AirVisual format
    
    Args:
        weather: Weather data from AirVisual API
        
    Returns:
        Normalized weather data dictionary
    """
    weather_data = {}
    
    # Temperature in Celsius
    if "tp" in weather:
        weather_data["temp_c"] = weather["tp"]
    
    # Humidity percentage
    if "hu" in weather:
        weather_data["humidity"] = weather["hu"]
    
    # Pressure in hPa
    if "pr" in weather:
        weather_data["pressure_hpa"] = weather["pr"]
    
    # Wind speed in m/s
    if "ws" in weather:
        weather_data["wind_speed_ms"] = weather["ws"]
    
    # Wind direction in degrees
    if "wd" in weather:
        weather_data["wind_dir_deg"] = weather["wd"]
    
    # Weather icon code
    if "ic" in weather:
        weather_data["icon"] = weather["ic"]
    
    # Heat index - check both possible names
    heat_index = weather.get("heatIndex") or weather.get("heat_index")
    if heat_index is not None:
        weather_data["heatIndex_c"] = heat_index
    elif "tp" in weather and "hu" in weather:
        # Calculate heat index if temperature and humidity available
        weather_data["heatIndex_c"] = _calculate_heat_index(weather["tp"], weather["hu"])
    
    return weather_data


def _normalize_pollutants_data(pollution: Dict[str, Any], units: Dict[str, Any]) -> Dict[str, Optional[ScalarWithUnit]]:
    """
    Normalize pollutants data from AirVisual format
    
    Args:
        pollution: Pollution data from AirVisual API
        units: Units data from AirVisual API
        
    Returns:
        Normalized pollutants dictionary
    """
    pollutants_data = {}
    
    # Define pollutant mappings: our_name -> (airvisual_key, default_unit)
    pollutant_mappings = {
        "pm25": ("p2", "µg/m³"),
        "pm10": ("p1", "µg/m³"), 
        "o3": ("o3", "ppb"),
        "no2": ("n2", "ppb"),
        "so2": ("s2", "ppb"),
        "co": ("co", "ppm")
    }
    
    for our_name, (av_key, default_unit) in pollutant_mappings.items():
        pollutant_data = pollution.get(av_key)
        
        if pollutant_data and isinstance(pollutant_data, dict) and "conc" in pollutant_data:
            conc = pollutant_data["conc"]
            if conc is not None:
                # Get unit from data, units section, or default
                unit = (pollutant_data.get("unit") or 
                       units.get(av_key, {}).get("unit") if isinstance(units.get(av_key), dict) else None or
                       default_unit)
                
                pollutants_data[our_name] = ScalarWithUnit(conc=conc, unit=unit)
            else:
                pollutants_data[our_name] = None
        else:
            pollutants_data[our_name] = None
    
    return pollutants_data


def _calculate_heat_index(temp_celsius: float, humidity: float) -> Optional[float]:
    """
    Calculate heat index in Celsius using the National Weather Service formula
    
    Args:
        temp_celsius: Temperature in Celsius
        humidity: Relative humidity percentage
        
    Returns:
        Heat index in Celsius, or None if calculation not applicable
    """
    try:
        # Convert Celsius to Fahrenheit for the calculation
        temp_f = (temp_celsius * 9/5) + 32
        
        # Use simplified formula for temperatures < 80°F
        if temp_f < 80:
            return temp_celsius  # Return original temperature
            
        # Full heat index formula (in Fahrenheit)
        hi_f = (-42.379 + 
                2.04901523 * temp_f + 
                10.14333127 * humidity - 
                0.22475541 * temp_f * humidity - 
                0.00683783 * temp_f**2 - 
                0.05481717 * humidity**2 + 
                0.00122874 * temp_f**2 * humidity + 
                0.00085282 * temp_f * humidity**2 - 
                0.00000199 * temp_f**2 * humidity**2)
        
        # Convert back to Celsius
        heat_index_celsius = (hi_f - 32) * 5/9
        
        return round(heat_index_celsius, 1)
        
    except (ValueError, TypeError, ZeroDivisionError):
        logger.warning(f"Failed to calculate heat index for temp={temp_celsius}, humidity={humidity}")
        return None


# === City Ingestion Normalization Functions ===

def normalize_city_current(payload: Dict[str, Any], scope_key: str, aqi_mode: str = "both") -> Optional[Dict[str, Any]]:
    """
    Normalize IQAir city current data to ReadingRow format
    
    Args:
        payload: Raw IQAir API response
        scope_key: City scope key (e.g., "Pakistan|Punjab|Lahore")  
        aqi_mode: "us", "cn", or "both" for AQI values to include
    
    Returns:
        Normalized reading row or None if invalid data
    """
    try:
        import json
        
        current = payload.get("current", {})
        pollution = current.get("pollution", {})
        weather = current.get("weather", {})
        
        if not pollution:
            logger.debug(f"No pollution data in current reading for {scope_key}")
            return None
        
        # Parse timestamp and floor to hour for de-duplication
        timestamp_str = pollution.get("ts")
        if timestamp_str:
            try:
                if timestamp_str.endswith('Z'):
                    ts_utc = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
                else:
                    ts_utc = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
                
                # Floor to the top of the hour for de-duplication
                ts_utc = ts_utc.replace(minute=0, second=0, microsecond=0)
            except Exception as ts_error:
                logger.warning(f"Invalid timestamp '{timestamp_str}' for {scope_key}: {ts_error}")
                ts_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        else:
            ts_utc = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        
        # Extract pollutant data
        pm25_data = pollution.get("p2", {})
        pm10_data = pollution.get("p1", {})
        
        # Map pollutant codes
        main_us = pollution.get("mainus")
        main_cn = pollution.get("maincn")
        pollutant_mapping = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}
        
        # Build reading row
        reading_row = {
            "scope_type": "city",
            "scope_key": scope_key,
            "ts_utc": ts_utc,
            # AQI values based on mode
            "aqi_us": pollution.get("aqius") if aqi_mode in ["us", "both"] else None,
            "aqi_cn": pollution.get("aqicn") if aqi_mode in ["cn", "both"] else None,
            "main_us": pollutant_mapping.get(main_us, main_us) if main_us else None,
            "main_cn": pollutant_mapping.get(main_cn, main_cn) if main_cn else None,
            # Pollutant concentrations
            "pm25": pm25_data.get("conc") if pm25_data else None,
            "pm10": pm10_data.get("conc") if pm10_data else None,
            "o3": pollution.get("o3", {}).get("conc") if pollution.get("o3") else None,
            "no2": pollution.get("n2", {}).get("conc") if pollution.get("n2") else None,
            "so2": pollution.get("s2", {}).get("conc") if pollution.get("s2") else None,
            "co": pollution.get("co", {}).get("conc") if pollution.get("co") else None,
            # Standard units
            "units_pm25": "µg/m³",
            "units_pm10": "µg/m³",
            "units_o3": "ppb",
            "units_no2": "ppb", 
            "units_so2": "ppb",
            "units_co": "ppm",
            # Weather data
            "temp_c": weather.get("tp"),
            "humidity": weather.get("hu"),
            "pressure_hpa": weather.get("pr"),
            "wind_speed_ms": weather.get("ws"),
            "wind_dir_deg": weather.get("wd"),
            "weather_icon": weather.get("ic"),
            "heatindex_c": weather.get("heatIndex"),
            "pop_pct": weather.get("pop"),
            # QC and metadata
            "qc_state": "OK",  # Default to OK, QC validation runs separately
            "source": "airvisual",
            "raw": json.dumps({"current": current})
        }
        
        return reading_row
        
    except Exception as error:
        logger.error(f"Failed to normalize current data for {scope_key}: {error}")
        return None


def normalize_city_history(payload: Dict[str, Any], scope_key: str) -> List[Dict[str, Any]]:
    """
    Normalize IQAir city historical data (≤48h) to ReadingRow format
    
    Args:
        payload: Raw IQAir API response  
        scope_key: City scope key
    
    Returns:
        List of normalized historical reading rows
    """
    try:
        from datetime import timedelta
        import json
        
        history = payload.get("history", {})
        if not history:
            logger.debug(f"No history data for {scope_key}")
            return []
        
        # IQAir history typically contains pollution and weather arrays
        pollution_history = history.get("pollution", [])
        weather_history = history.get("weather", [])
        
        if not pollution_history:
            logger.debug(f"No pollution history for {scope_key}")
            return []
        
        # Create lookup for weather data by timestamp
        weather_lookup = {}
        for weather_point in weather_history:
            ts = weather_point.get("ts")
            if ts:
                weather_lookup[ts] = weather_point
        
        reading_rows = []
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=48)
        
        for pollution_point in pollution_history:
            try:
                # Parse timestamp
                timestamp_str = pollution_point.get("ts")
                if not timestamp_str:
                    continue
                    
                if timestamp_str.endswith('Z'):
                    ts_utc = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
                else:
                    ts_utc = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
                
                # Only include last 48 hours and floor to hour
                if ts_utc < cutoff_time:
                    continue
                    
                ts_utc = ts_utc.replace(minute=0, second=0, microsecond=0)
                
                # Get corresponding weather data
                weather_point = weather_lookup.get(timestamp_str, {})
                
                # Extract pollutant data
                pm25_data = pollution_point.get("p2", {})
                pm10_data = pollution_point.get("p1", {})
                
                # Map pollutant codes
                main_us = pollution_point.get("mainus")
                main_cn = pollution_point.get("maincn")
                pollutant_mapping = {"p1": "pm10", "p2": "pm25", "o3": "o3", "n2": "no2", "s2": "so2", "co": "co"}
                
                reading_row = {
                    "scope_type": "city",
                    "scope_key": scope_key,
                    "ts_utc": ts_utc,
                    # AQI values
                    "aqi_us": pollution_point.get("aqius"),
                    "aqi_cn": pollution_point.get("aqicn"),
                    "main_us": pollutant_mapping.get(main_us, main_us) if main_us else None,
                    "main_cn": pollutant_mapping.get(main_cn, main_cn) if main_cn else None,
                    # Pollutant concentrations
                    "pm25": pm25_data.get("conc") if pm25_data else None,
                    "pm10": pm10_data.get("conc") if pm10_data else None,
                    "o3": pollution_point.get("o3", {}).get("conc") if pollution_point.get("o3") else None,
                    "no2": pollution_point.get("n2", {}).get("conc") if pollution_point.get("n2") else None,
                    "so2": pollution_point.get("s2", {}).get("conc") if pollution_point.get("s2") else None,
                    "co": pollution_point.get("co", {}).get("conc") if pollution_point.get("co") else None,
                    # Standard units
                    "units_pm25": "µg/m³",
                    "units_pm10": "µg/m³",
                    "units_o3": "ppb",
                    "units_no2": "ppb", 
                    "units_so2": "ppb",
                    "units_co": "ppm",
                    # Weather data
                    "temp_c": weather_point.get("tp"),
                    "humidity": weather_point.get("hu"),
                    "pressure_hpa": weather_point.get("pr"),
                    "wind_speed_ms": weather_point.get("ws"),
                    "wind_dir_deg": weather_point.get("wd"),
                    "weather_icon": weather_point.get("ic"),
                    "heatindex_c": weather_point.get("heatIndex"),
                    "pop_pct": weather_point.get("pop"),
                    # QC and metadata
                    "qc_state": "OK",
                    "source": "airvisual",
                    "raw": json.dumps({"pollution": pollution_point, "weather": weather_point})
                }
                
                reading_rows.append(reading_row)
                
            except Exception as point_error:
                logger.warning(f"Failed to parse history point for {scope_key}: {point_error}")
                continue
        
        logger.debug(f"Normalized {len(reading_rows)} historical points for {scope_key}")
        return reading_rows
        
    except Exception as error:
        logger.error(f"Failed to normalize history data for {scope_key}: {error}")
        return []


def normalize_city_forecasts(payload: Dict[str, Any], scope_key: str) -> List[Dict[str, Any]]:
    """
    Normalize IQAir city forecast data to ForecastRow format
    Handles both hourly and daily forecasts if present
    
    Args:
        payload: Raw IQAir API response
        scope_key: City scope key
    
    Returns:
        List of normalized forecast rows
    """
    try:
        import json
        
        forecasts = payload.get("forecasts", {})
        if not forecasts:
            logger.debug(f"No forecast data for {scope_key}")
            return []
        
        forecast_rows = []
        
        # Process hourly forecasts
        hourly_forecasts = forecasts.get("hourly", [])
        for hourly_point in hourly_forecasts:
            try:
                # Parse timestamp
                timestamp_str = hourly_point.get("ts")
                if not timestamp_str:
                    continue
                    
                if timestamp_str.endswith('Z'):
                    ts_utc = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
                else:
                    ts_utc = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
                
                # Hour-align forecast timestamp
                ts_utc = ts_utc.replace(minute=0, second=0, microsecond=0)
                
                # Extract forecast data
                pollution = hourly_point.get("pollution", {})
                weather = hourly_point.get("weather", {})
                
                forecast_row = {
                    "scope_type": "city",
                    "scope_key": scope_key,
                    "ts_utc": ts_utc,
                    "forecast_type": "hourly",
                    "forecast_horizon_hours": _calculate_forecast_horizon(ts_utc),
                    # Pollution forecast
                    "aqi_us": pollution.get("aqius"),
                    "aqi_cn": pollution.get("aqicn"),
                    "pm25": pollution.get("p2", {}).get("conc") if pollution.get("p2") else None,
                    "pm10": pollution.get("p1", {}).get("conc") if pollution.get("p1") else None,
                    # Weather forecast
                    "temp_c": weather.get("tp"),
                    "humidity": weather.get("hu"),
                    "pressure_hpa": weather.get("pr"),
                    "wind_speed_ms": weather.get("ws"),
                    "wind_dir_deg": weather.get("wd"),
                    "weather_icon": weather.get("ic"),
                    "pop_pct": weather.get("pop"),
                    # Metadata
                    "source": "airvisual",
                    "raw": json.dumps(hourly_point),
                    "created_at": datetime.now(timezone.utc)
                }
                
                forecast_rows.append(forecast_row)
                
            except Exception as point_error:
                logger.warning(f"Failed to parse hourly forecast point for {scope_key}: {point_error}")
                continue
        
        # Process daily forecasts
        daily_forecasts = forecasts.get("daily", [])
        for daily_point in daily_forecasts:
            try:
                # Parse timestamp (usually start of day)
                timestamp_str = daily_point.get("ts")
                if not timestamp_str:
                    continue
                    
                if timestamp_str.endswith('Z'):
                    ts_utc = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
                else:
                    ts_utc = datetime.fromisoformat(timestamp_str).replace(tzinfo=timezone.utc)
                
                # Day-align forecast timestamp
                ts_utc = ts_utc.replace(hour=0, minute=0, second=0, microsecond=0)
                
                # Extract forecast data
                pollution = daily_point.get("pollution", {})
                weather = daily_point.get("weather", {})
                
                forecast_row = {
                    "scope_type": "city",
                    "scope_key": scope_key,
                    "ts_utc": ts_utc,
                    "forecast_type": "daily",
                    "forecast_horizon_hours": _calculate_forecast_horizon(ts_utc),
                    # Pollution forecast (daily might have min/max/avg)
                    "aqi_us": pollution.get("aqius") or pollution.get("aqius_avg"),
                    "aqi_cn": pollution.get("aqicn") or pollution.get("aqicn_avg"),
                    "pm25": (pollution.get("p2", {}).get("conc") or 
                            pollution.get("p2", {}).get("avg")) if pollution.get("p2") else None,
                    "pm10": (pollution.get("p1", {}).get("conc") or 
                            pollution.get("p1", {}).get("avg")) if pollution.get("p1") else None,
                    # Weather forecast
                    "temp_c": weather.get("tp") or weather.get("tp_avg"),
                    "temp_min_c": weather.get("tp_min"),
                    "temp_max_c": weather.get("tp_max"),
                    "humidity": weather.get("hu") or weather.get("hu_avg"),
                    "pressure_hpa": weather.get("pr") or weather.get("pr_avg"),
                    "wind_speed_ms": weather.get("ws") or weather.get("ws_avg"),
                    "wind_dir_deg": weather.get("wd") or weather.get("wd_avg"),
                    "weather_icon": weather.get("ic"),
                    "pop_pct": weather.get("pop"),
                    # Metadata
                    "source": "airvisual",
                    "raw": json.dumps(daily_point),
                    "created_at": datetime.now(timezone.utc)
                }
                
                forecast_rows.append(forecast_row)
                
            except Exception as point_error:
                logger.warning(f"Failed to parse daily forecast point for {scope_key}: {point_error}")
                continue
        
        logger.debug(f"Normalized {len(forecast_rows)} forecast points for {scope_key}")
        return forecast_rows
        
    except Exception as error:
        logger.error(f"Failed to normalize forecast data for {scope_key}: {error}")
        return []


def _calculate_forecast_horizon(forecast_time: datetime) -> int:
    """Calculate forecast horizon in hours from now"""
    now = datetime.now(timezone.utc)
    horizon = forecast_time - now
    return max(0, int(horizon.total_seconds() / 3600))  # Convert to hours, min 0