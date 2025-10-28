"""
Data normalization utilities for air quality data
"""

import logging
import math
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Literal
import zoneinfo

from app.schemas.nearest import CurrentOut

logger = logging.getLogger(__name__)


def pm25_to_aqi(pm25: float, *, cap_at_500: bool = True) -> Optional[int]:
    """
    Convert PM2.5 (µg/m³) to US EPA AQI using 2024 breakpoints.
    - Truncates PM2.5 to 1 decimal.
    - Rounds AQI to nearest integer.
    - If cap_at_500=True, caps at 500; otherwise allows AQI > 500 per EPA.
    """
    if pm25 is None or math.isnan(pm25):
        return None
    if pm25 < 0:
        return 0

    # EPA truncation (not rounding) to 1 decimal place
    C = math.floor(pm25 * 10) / 10.0

    # 2024 PM2.5 breakpoints: (C_lo, C_hi, I_lo, I_hi)
    bps = [
        (0.0,   9.0,    0,   50),
        (9.1,  35.4,   51,  100),
        (35.5, 55.4,  101,  150),
        (55.5,125.4,  151,  200),
        (125.5,225.4, 201,  300),
        (225.5,325.4, 301,  500),  # top segment up to AQI 500
    ]

    for C_lo, C_hi, I_lo, I_hi in bps:
        if C_lo <= C <= C_hi:
            I = (I_hi - I_lo) / (C_hi - C_lo) * (C - C_lo) + I_lo
            I = int(round(I))
            return min(I, 500) if cap_at_500 else I

    # C > 325.4: extend the last segment (allows AQI > 500 if not capped)
    C_lo, C_hi, I_lo, I_hi = bps[-1]
    I = (I_hi - I_lo) / (C_hi - C_lo) * (C - C_lo) + I_lo
    I = int(round(I))
    return min(I, 500) if cap_at_500 else I


def get_aqi_label(aqi: Optional[int]) -> str:
    """
    Get AQI label with emoji and hashtags based on AQI value.
    
    Args:
        aqi: Air Quality Index value
        
    Returns:
        AQI label string with emoji and hashtags
    """
    if aqi is None or not isinstance(aqi, int) or aqi < 0:
        return "⚠️ AQI unavailable"
    
    if aqi > 800:
        return "Beyond Index #Airpocalypse 🤯🤯🤯"
    elif aqi > 500:
        return "Beyond Index"
    elif aqi > 300:
        return "#Hazardous 😱"
    elif aqi > 200:
        return "Very #Unhealthy 😰"
    elif aqi > 150:
        return "#Unhealthy"
    elif aqi > 100:
        return "Unhealthy for #SensitiveGroups"
    elif aqi > 50:
        return "#Moderate"
    else:
        return "#Good ❤️"


def get_aqi_category(aqi: Optional[int]) -> str:
    """
    Get AQI category name without emojis or hashtags.
    
    Args:
        aqi: Air Quality Index value
        
    Returns:
        AQI category string (e.g., "Good", "Moderate", "Unhealthy")
    """
    if aqi is None or not isinstance(aqi, int) or aqi < 0:
        return "Unknown"
    
    if aqi > 500:
        return "Beyond Index"
    elif aqi > 300:
        return "Hazardous"
    elif aqi > 200:
        return "Very Unhealthy"
    elif aqi > 150:
        return "Unhealthy"
    elif aqi > 100:
        return "Unhealthy for Sensitive Groups"
    elif aqi > 50:
        return "Moderate"
    else:
        return "Good"


def to_local(ts_utc: datetime, tz_str: str) -> datetime:
    """
    Convert UTC timestamp to local time using timezone string
    
    Args:
        ts_utc: UTC datetime object
        tz_str: IANA timezone string (e.g., 'Asia/Karachi')
        
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


def normalize_airvisual_current_data(
    data: Dict[str, Any], 
    aqi_filter: Literal["us", "cn", "both"] = "both",
    tz_str: str = "Asia/Karachi"
) -> CurrentOut:
    """
    Normalize AirVisual API current data to our canonical format
    
    Args:
        data: Raw AirVisual API response data
        aqi_filter: Which AQI scales to include ("us", "cn", "both")
        tz_str: IANA timezone for local timestamp conversion
        
    Returns:
        Normalized CurrentOut object
    """
    # Extract basic structure
    current = data.get("current", {})
    pollution = current.get("pollution", {})
    weather = current.get("weather", {})
    
    # Parse timestamp
    timestamp_str = pollution.get("ts")
    if timestamp_str:
        try:
            # IQAir timestamps are in ISO format with 'Z' suffix
            ts_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except ValueError:
            logger.warning(f"Could not parse timestamp: {timestamp_str}")
            ts_utc = datetime.now(timezone.utc)
    else:
        ts_utc = datetime.now(timezone.utc)
    
    # Convert to local time
    ts_local = to_local(ts_utc, tz_str)
    
    # Normalize AQI data
    aqi_data = {}
    
    if aqi_filter in ["us", "both"]:
        aqi_data["us"] = pollution.get("aqius")
        aqi_data["main_us"] = pollution.get("mainus")
    
    if aqi_filter in ["cn", "both"]:
        aqi_data["cn"] = pollution.get("aqicn") 
        aqi_data["main_cn"] = pollution.get("maincn")
    
    # Extract pollutant data
    pm25_data = pollution.get("p2", {})
    pm10_data = pollution.get("p1", {})
    o3_data = pollution.get("o3", {})
    no2_data = pollution.get("n2", {})
    so2_data = pollution.get("s2", {})
    co_data = pollution.get("co", {})
    
    pollutants = {
        "pm25": {
            "conc": pm25_data.get("conc"),
            "unit": "µg/m³"
        } if pm25_data.get("conc") is not None else None,
        
        "pm10": {
            "conc": pm10_data.get("conc"),
            "unit": "µg/m³"
        } if pm10_data.get("conc") is not None else None,
        
        "o3": {
            "conc": o3_data.get("conc"),
            "unit": "ppb"
        } if o3_data.get("conc") is not None else None,
        
        "no2": {
            "conc": no2_data.get("conc"), 
            "unit": "ppb"
        } if no2_data.get("conc") is not None else None,
        
        "so2": {
            "conc": so2_data.get("conc"),
            "unit": "ppb"
        } if so2_data.get("conc") is not None else None,
        
        "co": {
            "conc": co_data.get("conc"),
            "unit": "ppm"
        } if co_data.get("conc") is not None else None,
    }
    
    # Calculate heat index if temperature and humidity are available
    heat_index = None
    temp_c = weather.get("tp")
    humidity = weather.get("hu")
    
    if temp_c is not None and humidity is not None:
        heat_index = calculate_heat_index(temp_c, humidity)
    
    # Normalize weather data
    weather_data = {
        "temp_c": temp_c,
        "humidity": humidity,
        "pressure_hpa": weather.get("pr"),
        "wind_speed_ms": weather.get("ws"),
        "wind_dir_deg": weather.get("wd"),
        "icon": weather.get("ic"),
        "heatIndex_c": heat_index
    }
    
    # Remove None values from weather
    weather_data = {k: v for k, v in weather_data.items() if v is not None}
    
    # Standard units
    units = {
        "pm25": "µg/m³",
        "pm10": "µg/m³",
        "o3": "ppb", 
        "no2": "ppb",
        "so2": "ppb",
        "co": "ppm"
    }
    
    return CurrentOut(
        ts_utc=ts_utc,
        ts_local=ts_local,
        aqi=aqi_data,
        weather=weather_data,
        pollutants=pollutants,
        qc_state="OK",  # Default QC state
        units=units
    )


def calculate_heat_index(temp_celsius: float, humidity: float) -> Optional[float]:
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


def extract_location_info(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract location information from AirVisual API response
    
    Args:
        data: Raw AirVisual API response data
        
    Returns:
        Dictionary with location information
    """
    location = data.get("location", {})
    coordinates = location.get("coordinates", [])
    
    return {
        "lat": coordinates[1] if len(coordinates) > 1 else None,
        "lon": coordinates[0] if len(coordinates) > 0 else None,
        "country": data.get("country"),
        "state": data.get("state"),
        "city": data.get("city")
    }