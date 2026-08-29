"""
Pydantic models for Directory API endpoints
"""

from pydantic import BaseModel, Field
from typing import List
import hashlib


class CountryOut(BaseModel):
    """Response model for country listing"""
    country: str = Field(..., description="Country name")


class StateOut(BaseModel):
    """Response model for state/province listing"""
    state: str = Field(..., description="State or province name")


class CityOut(BaseModel):
    """Response model for city listing"""
    city: str = Field(..., description="City name")


class StationOut(BaseModel):
    """Response model for station listing"""
    station_id: str = Field(..., description="Unique station identifier (16-char SHA1 hash)")
    name: str = Field(..., description="Station name")
    country: str = Field(..., description="Country name")
    state: str = Field(..., description="State or province name") 
    city: str = Field(..., description="City name")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "9f1a0c2b8d6e3a41",
                "name": "Lahore US Consulate",
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore",
                "lat": 31.5204,
                "lon": 74.3587
            }
        }


def make_station_id(country: str, state: str, city: str, name: str, lat: float, lon: float) -> str:
    """
    Generate a stable, deterministic station ID using SHA1 hash
    
    Args:
        country: Country name
        state: State/province name  
        city: City name
        name: Station name
        lat: Latitude (will be formatted to 6 decimal places)
        lon: Longitude (will be formatted to 6 decimal places)
        
    Returns:
        16-character SHA1 hash prefix as station ID
    """
    # Format coordinates to 6 decimal places for consistency
    lat_str = f"{lat:.6f}"
    lon_str = f"{lon:.6f}"
    
    # Create deterministic string for hashing
    hash_input = f"{country}|{state}|{city}|{name}|{lat_str}|{lon_str}"
    
    # Generate SHA1 hash and return first 16 characters
    hash_obj = hashlib.sha1(hash_input.encode('utf-8'))
    return hash_obj.hexdigest()[:16]