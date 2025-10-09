"""
Pydantic models for Nearest API endpoints
"""

import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, Literal
from pydantic import BaseModel, Field


class CurrentOut(BaseModel):
    """Normalized current air quality and weather data"""
    ts_utc: datetime = Field(..., description="UTC timestamp of the data")
    ts_local: datetime = Field(..., description="Local timestamp of the data") 
    aqi: Dict[str, Any] = Field(..., description="AQI information for different scales")
    weather: Dict[str, Any] = Field(..., description="Weather information")
    pollutants: Dict[str, Any] = Field(..., description="Pollutant concentrations")
    qc_state: Optional[str] = Field(None, description="Quality control state")
    units: Dict[str, str] = Field(..., description="Units for different measurements")

    class Config:
        json_schema_extra = {
            "example": {
                "ts_utc": "2025-09-24T14:00:00Z",
                "ts_local": "2025-09-24T19:00:00+05:00",
                "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                "weather": {
                    "temp_c": 28, 
                    "humidity": 54, 
                    "pressure_hpa": 1011, 
                    "wind_speed_ms": 1.67, 
                    "wind_dir_deg": 135, 
                    "icon": "01n", 
                    "heatIndex_c": 29
                },
                "pollutants": {
                    "pm25": {"conc": 32.6, "unit": "µg/m³"}, 
                    "pm10": None, 
                    "o3": None, 
                    "no2": None, 
                    "so2": None, 
                    "co": None
                },
                "qc_state": "OK",
                "units": {
                    "pm25": "µg/m³",
                    "pm10": "µg/m³", 
                    "o3": "ppb",
                    "no2": "ppb",
                    "so2": "ppb",
                    "co": "ppm"
                }
            }
        }


class NearestBase(BaseModel):
    """Base model for nearest entities"""
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate") 
    country: str = Field(..., description="Country name")
    state: Optional[str] = Field(None, description="State or province name")
    city: str = Field(..., description="City name")


class NearestStationEntity(NearestBase):
    """Station entity information for nearest station response"""
    name: str = Field(..., description="Station name")
    station_id: str = Field(..., description="Unique station identifier (16-char SHA1 hash)")

    class Config:
        json_schema_extra = {
            "example": {
                "lat": 31.521,
                "lon": 74.355,
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore",
                "name": "Lahore US Consulate",
                "station_id": "9f1a0c2b8d6e3a41"
            }
        }


class NearestCityEntity(NearestBase):
    """City entity information for nearest city response"""
    
    class Config:
        json_schema_extra = {
            "example": {
                "lat": 31.517,
                "lon": 74.360,
                "country": "Pakistan", 
                "state": "Punjab",
                "city": "Lahore"
            }
        }


class NearestStationOut(BaseModel):
    """Response model for nearest station endpoint"""
    source: Literal["airvisual"] = Field(default="airvisual", description="Data source")
    distance_km: float = Field(..., description="Distance from query point in kilometers")
    entity: NearestStationEntity = Field(..., description="Station information")
    current: CurrentOut = Field(..., description="Current air quality data")

    class Config:
        json_schema_extra = {
            "example": {
                "source": "airvisual",
                "distance_km": 2.10,
                "entity": {
                    "lat": 31.521,
                    "lon": 74.355,
                    "country": "Pakistan",
                    "state": "Punjab", 
                    "city": "Lahore",
                    "name": "Lahore US Consulate",
                    "station_id": "9f1a0c2b8d6e3a41"
                },
                "current": {
                    "ts_utc": "2025-09-24T14:00:00Z",
                    "ts_local": "2025-09-24T19:00:00+05:00",
                    "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                    "weather": {"temp_c": 28, "humidity": 54},
                    "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                    "qc_state": "OK",
                    "units": {"pm25": "µg/m³"}
                }
            }
        }


class NearestCityOut(BaseModel):
    """Response model for nearest city endpoint"""
    source: Literal["airvisual"] = Field(default="airvisual", description="Data source")
    distance_km: float = Field(..., description="Distance from query point in kilometers")
    entity: NearestCityEntity = Field(..., description="City information")
    current: CurrentOut = Field(..., description="Current air quality data")

    class Config:
        json_schema_extra = {
            "example": {
                "source": "airvisual", 
                "distance_km": 4.32,
                "entity": {
                    "lat": 31.517,
                    "lon": 74.360,
                    "country": "Pakistan",
                    "state": "Punjab",
                    "city": "Lahore"
                },
                "current": {
                    "ts_utc": "2025-09-24T14:00:00Z",
                    "ts_local": "2025-09-24T19:00:00+05:00",
                    "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                    "weather": {"temp_c": 28, "humidity": 54},
                    "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                    "qc_state": "OK",
                    "units": {"pm25": "µg/m³"}
                }
            }
        }


def make_station_id(country: str, state: str, city: str, name: str, lat: float, lon: float) -> str:
    """
    Generate a stable, deterministic station ID using SHA1 hash
    
    Args:
        country: Country name
        state: State/province name (can be None)
        city: City name
        name: Station name
        lat: Latitude (will be formatted to 6 decimal places)
        lon: Longitude (will be formatted to 6 decimal places)
        
    Returns:
        16-character SHA1 hash prefix as station ID
    """
    # Handle None state
    state_str = state or ""
    
    # Format coordinates to 6 decimal places for consistency
    lat_str = f"{lat:.6f}"
    lon_str = f"{lon:.6f}"
    
    # Create deterministic string for hashing
    hash_input = f"{country}|{state_str}|{city}|{name}|{lat_str}|{lon_str}"
    
    # Generate SHA1 hash and return first 16 characters
    hash_obj = hashlib.sha1(hash_input.encode('utf-8'))
    return hash_obj.hexdigest()[:16]