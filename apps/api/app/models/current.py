"""
Pydantic models for Current conditions endpoints
"""

from datetime import datetime
from typing import Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field


class Scope(BaseModel):
    """Geographic scope for current conditions"""
    country: str = Field(..., description="Country name")
    state: str = Field(..., description="State or province name")
    city: str = Field(..., description="City name")

    class Config:
        json_schema_extra = {
            "example": {
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore"
            }
        }


class ScalarWithUnit(BaseModel):
    """Pollutant concentration with unit"""
    conc: float = Field(..., description="Concentration value")
    unit: str = Field(..., description="Unit of measurement")

    class Config:
        json_schema_extra = {
            "example": {
                "conc": 32.6,
                "unit": "µg/m³"
            }
        }


class CurrentOut(BaseModel):
    """Current air quality and weather conditions response"""
    scope: Scope = Field(..., description="Geographic scope")
    source: Literal["airvisual"] = Field(default="airvisual", description="Data source")
    ts_utc: datetime = Field(..., description="UTC timestamp of the data")
    ts_local: datetime = Field(..., description="Local timestamp of the data")
    aqi: Dict[str, Union[int, str, None]] = Field(..., description="AQI information")
    weather: Dict[str, Union[float, int, str, None]] = Field(..., description="Weather conditions")
    pollutants: Dict[str, Optional[ScalarWithUnit]] = Field(..., description="Pollutant concentrations")
    qc_state: Optional[str] = Field(None, description="Quality control state")
    units: Dict[str, str] = Field(..., description="Standard units for measurements")

    class Config:
        json_schema_extra = {
            "example": {
                "scope": {
                    "country": "Pakistan",
                    "state": "Punjab", 
                    "city": "Lahore"
                },
                "source": "airvisual",
                "ts_utc": "2025-09-24T14:00:00Z",
                "ts_local": "2025-09-24T19:00:00+05:00",
                "aqi": {
                    "us": 95,
                    "cn": 70,
                    "main_us": "pm25",
                    "main_cn": "pm25"
                },
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


class StationMeta(BaseModel):
    """Station metadata for resolving station_id to IQAir parameters"""
    country: str = Field(..., description="Country name")
    state: str = Field(..., description="State or province name")
    city: str = Field(..., description="City name")
    name: str = Field(..., description="Station name")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    source_station_id: Optional[str] = Field(None, description="Source-specific station ID")

    class Config:
        json_schema_extra = {
            "example": {
                "country": "Pakistan",
                "state": "Punjab",
                "city": "Lahore",
                "name": "Lahore US Consulate",
                "lat": 31.5204,
                "lon": 74.3587,
                "source_station_id": None
            }
        }


class StationCurrent(BaseModel):
    """Station current data in simplified format"""
    station_id: str = Field(..., description="Station identifier")
    station_name: str = Field(..., description="Station name")
    pm25_concentration: Optional[float] = Field(None, description="PM2.5 concentration in µg/m³")
    aqi: Optional[int] = Field(None, description="Air Quality Index (US EPA)")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "9f1a0c2b8d6e3a41",
                "station_name": "Lahore US Consulate",
                "pm25_concentration": 32.6,
                "aqi": 95
            }
        }


class CityStationsResponse(BaseModel):
    """Response for city stations with current data"""
    city: str = Field(..., description="City name")
    stations: list[StationCurrent] = Field(..., description="List of stations with current data")
    
    class Config:
        json_schema_extra = {
            "example": {
                "city": "Lahore",
                "stations": [
                    {
                        "station_id": "9f1a0c2b8d6e3a41",
                        "station_name": "Lahore US Consulate", 
                        "pm25_concentration": 32.6,
                        "aqi": 95
                    }
                ]
            }
        }


class HighestPM25Station(BaseModel):
    """Station data for highest PM2.5 concentration ranking"""
    station_id: str = Field(..., description="Station identifier")
    station_name: str = Field(..., description="Station name")
    pm25_concentration: float = Field(..., description="PM2.5 concentration in µg/m³")
    aqi: Optional[int] = Field(None, description="Air Quality Index (US EPA)")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "c2af7d6fe582309c",
                "station_name": "Badian Rd LHE",
                "pm25_concentration": 265.0,
                "aqi": 315
            }
        }


class CityTop10PM25Response(BaseModel):
    """Response for top 10 highest PM2.5 stations in a city"""
    city: str = Field(..., description="City name")
    top_stations: list[HighestPM25Station] = Field(..., description="Top 10 stations with highest PM2.5", max_items=10)
    total_stations: int = Field(..., description="Total number of active stations with data in the city")
    
    class Config:
        json_schema_extra = {
            "example": {
                "city": "Lahore",
                "top_stations": [
                    {
                        "station_id": "c2af7d6fe582309c",
                        "station_name": "Badian Rd LHE",
                        "pm25_concentration": 265.0
                    },
                    {
                        "station_id": "57adc452bd10dbdc",
                        "station_name": "Barki, Lahore",
                        "pm25_concentration": 208.2
                    }
                ],
                "total_stations": 47
            }
        }


class CityAverageResponse(BaseModel):
    """Response for city average air quality data"""
    city: str = Field(..., description="City name")
    avg_pm25_concentration: Optional[float] = Field(None, description="Average PM2.5 concentration in µg/m³")
    aqi: Optional[int] = Field(None, description="Air Quality Index calculated from average PM2.5 (US EPA)")
    category: str = Field(..., description="AQI category (e.g., Good, Moderate, Unhealthy)")
    health_message: str = Field(..., description="Public health message with emoji based on AQI level")
    total_stations: int = Field(..., description="Total number of active stations used in calculation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "city": "Lahore",
                "avg_pm25_concentration": 89.4,
                "aqi": 162,
                "category": "Unhealthy",
                "health_message": "🔴 #Unhealthy",
                "total_stations": 47
            }
        }