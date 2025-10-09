"""
Parameter validation and parsing utilities for history endpoints
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Literal, Optional, Tuple
from app.models.history import HistoryQuery

logger = logging.getLogger(__name__)

# Valid pollutants
VALID_POLLUTANTS = {"pm25", "pm10", "o3", "no2", "so2", "co"}

# Default pollutants if none specified
DEFAULT_POLLUTANTS = ["pm25", "pm10", "o3", "no2", "so2", "co"]

# Maximum time span allowed (180 days)
MAX_SPAN_DAYS = 180


def parse_iso_timestamp(timestamp_str: str) -> datetime:
    """
    Parse ISO 8601 timestamp string to UTC datetime
    
    Args:
        timestamp_str: ISO timestamp string (should end with 'Z' for UTC)
        
    Returns:
        UTC datetime object
        
    Raises:
        ValueError: If timestamp format is invalid
    """
    try:
        if timestamp_str.endswith('Z'):
            # Remove 'Z' and add UTC timezone
            ts = datetime.fromisoformat(timestamp_str[:-1]).replace(tzinfo=timezone.utc)
        else:
            # Try to parse with timezone info
            ts = datetime.fromisoformat(timestamp_str)
            if ts.tzinfo is None:
                raise ValueError("Timestamp must be in UTC (end with 'Z') or include timezone info")
            # Convert to UTC
            ts = ts.astimezone(timezone.utc)
        
        return ts
        
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid timestamp format '{timestamp_str}': {e}")


def validate_time_range(from_time: datetime, to_time: datetime) -> None:
    """
    Validate time range constraints
    
    Args:
        from_time: Start time (UTC)
        to_time: End time (UTC)
        
    Raises:
        ValueError: If time range is invalid
    """
    if from_time > to_time:
        raise ValueError("'from' time must be before or equal to 'to' time")
    
    span = to_time - from_time
    if span.days > MAX_SPAN_DAYS:
        raise ValueError(f"Time span cannot exceed {MAX_SPAN_DAYS} days")


def validate_granularity(granularity: str) -> str:
    """
    Validate granularity parameter
    
    Args:
        granularity: Time granularity
        
    Returns:
        Validated granularity
        
    Raises:
        ValueError: If granularity is invalid
    """
    if granularity not in ["hour"]:
        raise ValueError(f"Invalid granularity '{granularity}'. Only 'hour' is supported.")
    
    return granularity


def validate_aqi_mode(aqi_mode: str) -> str:
    """
    Validate AQI mode parameter
    
    Args:
        aqi_mode: AQI mode
        
    Returns:
        Validated AQI mode
        
    Raises:
        ValueError: If AQI mode is invalid
    """
    if aqi_mode not in ["us", "cn", "both"]:
        raise ValueError(f"Invalid aqi mode '{aqi_mode}'. Must be 'us', 'cn', or 'both'.")
    
    return aqi_mode


def validate_pollutants(pollutants_str: Optional[str]) -> List[str]:
    """
    Validate and parse pollutants parameter
    
    Args:
        pollutants_str: Comma-separated pollutants string
        
    Returns:
        List of validated pollutants
        
    Raises:
        ValueError: If any pollutant is invalid
    """
    if not pollutants_str:
        return DEFAULT_POLLUTANTS
    
    # Split and clean
    pollutants = [p.strip().lower() for p in pollutants_str.split(',') if p.strip()]
    
    if not pollutants:
        return DEFAULT_POLLUTANTS
    
    # Validate each pollutant
    invalid_pollutants = set(pollutants) - VALID_POLLUTANTS
    if invalid_pollutants:
        raise ValueError(f"Invalid pollutants: {', '.join(invalid_pollutants)}. "
                        f"Valid pollutants are: {', '.join(sorted(VALID_POLLUTANTS))}")
    
    # Remove duplicates and maintain order
    seen = set()
    unique_pollutants = []
    for p in pollutants:
        if p not in seen:
            seen.add(p)
            unique_pollutants.append(p)
    
    return unique_pollutants


def get_default_time_range() -> Tuple[datetime, datetime]:
    """
    Get default time range (last 48 hours)
    
    Returns:
        Tuple of (from_time, to_time) in UTC
    """
    now = datetime.now(timezone.utc)
    # Round down to hour boundary
    to_time = now.replace(minute=0, second=0, microsecond=0)
    from_time = to_time - timedelta(hours=48)
    
    return from_time, to_time


def round_to_hour(dt: datetime) -> datetime:
    """
    Round datetime down to the hour boundary
    
    Args:
        dt: Datetime to round
        
    Returns:
        Datetime rounded down to hour
    """
    return dt.replace(minute=0, second=0, microsecond=0)


def parse_history_params(
    from_str: Optional[str] = None,
    to_str: Optional[str] = None,
    pollutants_str: Optional[str] = None,
    granularity: str = "hour",
    aqi: str = "both",
    tz: str = "Asia/Karachi",
    fill: bool = False,
    include_rollups: bool = False
) -> HistoryQuery:
    """
    Parse and validate all history endpoint parameters
    
    Args:
        from_str: ISO timestamp string for start time
        to_str: ISO timestamp string for end time
        pollutants_str: Comma-separated pollutants
        granularity: Time granularity
        aqi: AQI mode
        tz: Timezone string
        fill: Whether to fill missing hours
        include_rollups: Whether to include rollups
        
    Returns:
        Validated HistoryQuery object
        
    Raises:
        ValueError: If any parameter is invalid
    """
    # Parse time range
    if from_str is None or to_str is None:
        from_time, to_time = get_default_time_range()
        if from_str is not None:
            from_time = parse_iso_timestamp(from_str)
        if to_str is not None:
            to_time = parse_iso_timestamp(to_str)
    else:
        from_time = parse_iso_timestamp(from_str)
        to_time = parse_iso_timestamp(to_str)
    
    # Round times to hour boundaries for granularity=hour
    from_time = round_to_hour(from_time)
    to_time = round_to_hour(to_time)
    
    # Validate time range
    validate_time_range(from_time, to_time)
    
    # Validate other parameters
    validated_granularity = validate_granularity(granularity)
    validated_aqi_mode = validate_aqi_mode(aqi)
    validated_pollutants = validate_pollutants(pollutants_str)
    
    return HistoryQuery(
        from_time=from_time,
        to_time=to_time,
        pollutants=validated_pollutants,
        granularity=validated_granularity,
        aqi_mode=validated_aqi_mode,
        tz=tz,
        fill=fill,
        include_rollups=include_rollups
    )


def generate_hourly_timeline(from_time: datetime, to_time: datetime) -> List[datetime]:
    """
    Generate a list of hourly timestamps from from_time to to_time (inclusive)
    
    Args:
        from_time: Start time (should be rounded to hour)
        to_time: End time (should be rounded to hour)
        
    Returns:
        List of hourly timestamps
    """
    timeline = []
    current_time = from_time
    
    while current_time <= to_time:
        timeline.append(current_time)
        current_time += timedelta(hours=1)
    
    return timeline


def is_within_last_48h(timestamp: datetime) -> bool:
    """
    Check if a timestamp is within the last 48 hours
    
    Args:
        timestamp: Timestamp to check (UTC)
        
    Returns:
        True if within last 48 hours
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)
    return timestamp >= cutoff