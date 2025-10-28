"""
Pydantic models for History endpoints
"""

from datetime import datetime
from typing import Dict, Any, Optional, List, Union, Literal
from pydantic import BaseModel, Field

from app.models.current import Scope, ScalarWithUnit


class HistoryRow(BaseModel):
    """Single historical data point"""
    ts_utc: datetime = Field(..., description="UTC timestamp")
    ts_local: datetime = Field(..., description="Local timestamp")
    aqi: Dict[str, Union[int, str, None]] = Field(..., description="AQI information")
    pollutants: Dict[str, Optional[ScalarWithUnit]] = Field(..., description="Pollutant concentrations")
    weather: Dict[str, Union[float, int, str, None]] = Field(..., description="Weather conditions")
    qc_state: Optional[str] = Field(None, description="Quality control state")

    class Config:
        json_schema_extra = {
            "example": {
                "ts_utc": "2025-09-24T14:00:00Z",
                "ts_local": "2025-09-24T19:00:00+05:00",
                "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                "pollutants": {
                    "pm25": {"conc": 32.6, "unit": "µg/m³"},
                    "pm10": None,
                    "o3": None,
                    "no2": None,
                    "so2": None,
                    "co": None
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
                "qc_state": "OK"
            }
        }


class WindowStats(BaseModel):
    """Statistics for a time window"""
    from_: datetime = Field(..., alias="from", description="Window start time")
    to: datetime = Field(..., description="Window end time")
    count_hours: int = Field(..., description="Number of hours with data")
    missing_hours: int = Field(..., description="Number of missing hours in window")

    class Config:
        allow_population_by_field_name = True
        json_schema_extra = {
            "example": {
                "from": "2025-09-24T10:00:00Z",
                "to": "2025-09-26T10:00:00Z",
                "count_hours": 47,
                "missing_hours": 1
            }
        }


class PollutantStats(BaseModel):
    """Statistical summary for a pollutant"""
    mean: Optional[float] = Field(None, description="Mean value")
    median: Optional[float] = Field(None, description="Median value")
    p90: Optional[float] = Field(None, description="90th percentile value")
    max: Optional[float] = Field(None, description="Maximum value")

    class Config:
        json_schema_extra = {
            "example": {
                "mean": 41.2,
                "median": 38.5,
                "p90": 76.0,
                "max": 112.0
            }
        }


class AQIStats(BaseModel):
    """Statistical summary for AQI"""
    mean: Optional[int] = Field(None, description="Mean AQI value")
    max: Optional[int] = Field(None, description="Maximum AQI value")

    class Config:
        json_schema_extra = {
            "example": {
                "mean": 92,
                "max": 167
            }
        }


class Rollups(BaseModel):
    """Statistical rollups for the time period"""
    window: WindowStats = Field(..., description="Time window statistics")
    pm25: Optional[PollutantStats] = Field(None, description="PM2.5 statistics")
    pm10: Optional[PollutantStats] = Field(None, description="PM10 statistics")
    o3: Optional[PollutantStats] = Field(None, description="O3 statistics")
    no2: Optional[PollutantStats] = Field(None, description="NO2 statistics")
    so2: Optional[PollutantStats] = Field(None, description="SO2 statistics")
    co: Optional[PollutantStats] = Field(None, description="CO statistics")
    aqi_us: Optional[AQIStats] = Field(None, description="US AQI statistics")
    aqi_cn: Optional[AQIStats] = Field(None, description="China AQI statistics")

    class Config:
        json_schema_extra = {
            "example": {
                "window": {
                    "from": "2025-09-24T10:00:00Z",
                    "to": "2025-09-26T10:00:00Z",
                    "count_hours": 47,
                    "missing_hours": 1
                },
                "pm25": {"mean": 41.2, "median": 38.5, "p90": 76.0, "max": 112.0},
                "pm10": None,
                "aqi_us": {"mean": 92, "max": 167},
                "aqi_cn": {"mean": 71, "max": 130}
            }
        }


class HistoryOut(BaseModel):
    """History response for city or station"""
    scope: Scope = Field(..., description="Geographic scope")
    source: Literal["airvisual"] = Field(default="airvisual", description="Data source")
    granularity: Literal["hour"] = Field(default="hour", description="Time granularity")
    units: Dict[str, str] = Field(..., description="Units for measurements")
    rows: List[HistoryRow] = Field(..., description="Historical data points")
    rollups: Optional[Rollups] = Field(None, description="Statistical rollups")

    class Config:
        json_schema_extra = {
            "example": {
                "scope": {
                    "country": "Pakistan",
                    "state": "Punjab",
                    "city": "Lahore"
                },
                "source": "airvisual",
                "granularity": "hour",
                "units": {
                    "pm25": "µg/m³",
                    "pm10": "µg/m³",
                    "o3": "ppb",
                    "no2": "ppb",
                    "so2": "ppb",
                    "co": "ppm"
                },
                "rows": [
                    {
                        "ts_utc": "2025-09-24T14:00:00Z",
                        "ts_local": "2025-09-24T19:00:00+05:00",
                        "aqi": {"us": 95, "cn": 70, "main_us": "pm25", "main_cn": "pm25"},
                        "pollutants": {"pm25": {"conc": 32.6, "unit": "µg/m³"}},
                        "weather": {"temp_c": 28, "humidity": 54},
                        "qc_state": "OK"
                    }
                ],
                "rollups": {
                    "window": {
                        "from": "2025-09-24T10:00:00Z",
                        "to": "2025-09-26T10:00:00Z",
                        "count_hours": 47,
                        "missing_hours": 1
                    },
                    "pm25": {"mean": 41.2, "median": 38.5, "p90": 76.0, "max": 112.0},
                    "aqi_us": {"mean": 92, "max": 167}
                }
            }
        }


class HistoryQuery(BaseModel):
    """Parameters for history queries"""
    from_time: datetime = Field(..., description="Start time (UTC)")
    to_time: datetime = Field(..., description="End time (UTC)")
    pollutants: List[str] = Field(..., description="Requested pollutants")
    granularity: Literal["hour"] = Field(default="hour", description="Time granularity")
    aqi_mode: Literal["us", "cn", "both"] = Field(default="both", description="AQI scales to include")
    tz: str = Field(default="Asia/Karachi", description="Timezone for local timestamps")
    fill: bool = Field(default=False, description="Fill missing hours with nulls")
    include_rollups: bool = Field(default=False, description="Include statistical rollups")

    class Config:
        json_schema_extra = {
            "example": {
                "from_time": "2025-09-24T10:00:00Z",
                "to_time": "2025-09-26T10:00:00Z",
                "pollutants": ["pm25", "pm10"],
                "granularity": "hour",
                "aqi_mode": "both",
                "tz": "Asia/Karachi",
                "fill": False,
                "include_rollups": False
            }
        }


class CityAverageHistoryPoint(BaseModel):
    """Single historical data point for city average"""
    timestamp_utc: datetime = Field(..., description="UTC timestamp")
    timestamp_local: datetime = Field(..., description="Local timestamp")
    avg_pm25_concentration: Optional[float] = Field(None, description="Average PM2.5 concentration across all city stations")
    aqi: Optional[int] = Field(None, description="Air Quality Index calculated from average PM2.5")
    category: str = Field(..., description="AQI category (e.g., Good, Moderate, Unhealthy)")
    stations_count: int = Field(..., description="Number of stations with data for this hour")

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp_utc": "2025-10-27T14:00:00Z",
                "timestamp_local": "2025-10-27T19:00:00+05:00",
                "avg_pm25_concentration": 89.4,
                "aqi": 162,
                "category": "Unhealthy",
                "stations_count": 47
            }
        }


class CityAverageHistoryResponse(BaseModel):
    """Response for city average historical air quality data"""
    city: str = Field(..., description="City name")
    country: str = Field(..., description="Country name")
    state: str = Field(..., description="State/Province name")
    from_time: datetime = Field(..., description="Start time of data period (UTC)")
    to_time: datetime = Field(..., description="End time of data period (UTC)")
    timezone: str = Field(default="Asia/Karachi", description="Timezone for local timestamps")
    data_points: List[CityAverageHistoryPoint] = Field(..., description="Historical average data points")
    summary: Dict[str, Union[float, int, str]] = Field(..., description="Summary statistics for the period")

    class Config:
        json_schema_extra = {
            "example": {
                "city": "Lahore",
                "country": "Pakistan", 
                "state": "Punjab",
                "from_time": "2025-10-26T14:00:00Z",
                "to_time": "2025-10-27T14:00:00Z",
                "timezone": "Asia/Karachi",
                "data_points": [
                    {
                        "timestamp_utc": "2025-10-26T14:00:00Z",
                        "timestamp_local": "2025-10-26T19:00:00+05:00",
                        "avg_pm25_concentration": 89.4,
                        "aqi": 162,
                        "category": "Unhealthy",
                        "stations_count": 47
                    },
                    {
                        "timestamp_utc": "2025-10-26T15:00:00Z",
                        "timestamp_local": "2025-10-26T20:00:00+05:00",
                        "avg_pm25_concentration": 92.1,
                        "aqi": 167,
                        "category": "Unhealthy",
                        "stations_count": 45
                    }
                ],
                "summary": {
                    "hours_with_data": 24,
                    "avg_pm25_mean": 89.4,
                    "avg_pm25_max": 142.3,
                    "avg_pm25_min": 45.2,
                    "aqi_mean": 162,
                    "aqi_max": 205,
                    "total_data_points": 24
                }
            }
        }