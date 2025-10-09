"""
Geographic utility functions
"""

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on the earth 
    using the Haversine formula.
    
    Args:
        lat1: Latitude of first point in decimal degrees
        lon1: Longitude of first point in decimal degrees  
        lat2: Latitude of second point in decimal degrees
        lon2: Longitude of second point in decimal degrees
        
    Returns:
        Distance in kilometers (float)
    """
    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = (math.sin(dlat / 2) ** 2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2)
    
    c = 2 * math.asin(math.sqrt(a))
    
    # Radius of earth in kilometers
    earth_radius_km = 6371.0
    
    # Calculate the distance
    distance = earth_radius_km * c
    
    return round(distance, 2)


def validate_coordinates(lat: float, lon: float) -> None:
    """
    Validate latitude and longitude coordinates
    
    Args:
        lat: Latitude in decimal degrees
        lon: Longitude in decimal degrees
        
    Raises:
        ValueError: If coordinates are out of valid range
    """
    if not (-90 <= lat <= 90):
        raise ValueError(f"Latitude must be between -90 and 90 degrees, got {lat}")
    
    if not (-180 <= lon <= 180):
        raise ValueError(f"Longitude must be between -180 and 180 degrees, got {lon}")


def validate_radius(radius_km: float) -> float:
    """
    Validate and clamp radius to acceptable range
    
    Args:
        radius_km: Radius in kilometers
        
    Returns:
        Clamped radius value
        
    Raises:
        ValueError: If radius is not a valid number
    """
    if not isinstance(radius_km, (int, float)) or radius_km <= 0:
        raise ValueError(f"Radius must be a positive number, got {radius_km}")
    
    # Clamp to acceptable range (1-300 km)
    return max(1.0, min(300.0, float(radius_km)))