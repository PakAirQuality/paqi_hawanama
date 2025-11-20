"""
Pydantic models for Internal Station Analytics API endpoints
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Literal
from datetime import datetime


class StationInfo(BaseModel):
    """Station identity and metadata information"""
    station_id: str = Field(..., description="Unique station identifier")
    name: str = Field(..., description="Station name")
    provider: Optional[str] = Field(None, description="Data provider name")
    provider_id: Optional[int] = Field(None, description="Provider ID")
    source_station_id: Optional[str] = Field(None, description="Original station ID from data source")
    country: Optional[str] = Field(None, description="Country name")
    state: Optional[str] = Field(None, description="State or province name")
    city: Optional[str] = Field(None, description="City name")
    lat: float = Field(..., description="Latitude coordinate")
    lon: float = Field(..., description="Longitude coordinate")
    site_type: Optional[str] = Field(None, description="Site classification (traffic, residential, etc.)")
    indoor_outdoor: Optional[str] = Field(None, description="Installation type (indoor/outdoor)")
    height_m: Optional[float] = Field(None, description="Height above ground in meters")
    distance_to_road_m: Optional[float] = Field(None, description="Distance to nearest major road in meters")
    timezone: Optional[str] = Field(None, description="Local timezone")
    metadata: Dict[str, object] = Field(default_factory=dict, description="Additional metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "01cb11a02fbad27d",
                "name": "Model Town B LHE",
                "provider": "IQAir",
                "provider_id": 1,
                "source_station_id": "6730",
                "country": "Pakistan",
                "state": "Punjab", 
                "city": "Lahore",
                "lat": 31.5204,
                "lon": 74.3587,
                "site_type": "urban",
                "indoor_outdoor": "outdoor",
                "height_m": 3.5,
                "distance_to_road_m": 50.0,
                "timezone": "Asia/Karachi",
                "metadata": {}
            }
        }


class DataAvailability(BaseModel):
    """Data availability and coverage statistics"""
    first_obs: Optional[datetime] = Field(None, description="Timestamp of first observation")
    last_obs: Optional[datetime] = Field(None, description="Timestamp of last observation")
    total_days_with_any_data: int = Field(..., description="Number of days with any data in the analysis window")
    coverage_last_365d_pct: float = Field(..., description="Data coverage percentage in the analysis window")
    hours_total: int = Field(..., description="Total theoretical hours in analysis window")
    hours_with_data: int = Field(..., description="Hours with actual data")
    hours_qc_ok: int = Field(..., description="Hours with quality-controlled data")

    class Config:
        json_schema_extra = {
            "example": {
                "first_obs": "2025-01-01T00:00:00Z",
                "last_obs": "2025-11-20T12:00:00Z",
                "total_days_with_any_data": 324,
                "coverage_last_365d_pct": 88.5,
                "hours_total": 8760,
                "hours_with_data": 7752,
                "hours_qc_ok": 7200
            }
        }


class PollutantSummary(BaseModel):
    """Pollutant statistics and threshold analysis"""
    pollutant: str = Field(..., description="Pollutant code (pm25, pm10, etc.)")
    last_value: Optional[float] = Field(None, description="Most recent measurement value")
    last_value_ts: Optional[datetime] = Field(None, description="Timestamp of most recent measurement")
    rolling_means: Dict[str, Optional[float]] = Field(..., description="Rolling averages for different time windows")
    days_above_thresholds_last_30d: Dict[str, int] = Field(..., description="Days exceeding thresholds in last 30 days")
    days_above_thresholds_last_365d: Dict[str, int] = Field(..., description="Days exceeding thresholds in last 365 days")

    class Config:
        json_schema_extra = {
            "example": {
                "pollutant": "pm25",
                "last_value": 45.2,
                "last_value_ts": "2025-11-20T12:00:00Z",
                "rolling_means": {
                    "24h": 42.1,
                    "7d": 38.5,
                    "30d": 41.2
                },
                "days_above_thresholds_last_30d": {
                    "WHO_24h": 15,
                    "local_24h": 8
                },
                "days_above_thresholds_last_365d": {
                    "WHO_24h": 180,
                    "local_24h": 95
                }
            }
        }


class SensorDeployment(BaseModel):
    """Sensor deployment/version history"""
    label: Optional[str] = Field(None, description="Sensor or deployment label")
    valid_from: Optional[datetime] = Field(None, description="Start of deployment period")
    valid_to: Optional[datetime] = Field(None, description="End of deployment period")

    class Config:
        json_schema_extra = {
            "example": {
                "label": "AirGradient Pro v1.0",
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_to": None
            }
        }


class StationOverviewResponse(BaseModel):
    """Complete station overview response"""
    station: StationInfo = Field(..., description="Station identity and metadata")
    data_availability: DataAvailability = Field(..., description="Data coverage statistics")
    sensors: List[SensorDeployment] = Field(..., description="Sensor deployment history")
    pollutant_summary: PollutantSummary = Field(..., description="Pollutant statistics and trends")

    class Config:
        json_schema_extra = {
            "example": {
                "station": {
                    "station_id": "01cb11a02fbad27d",
                    "name": "Model Town B LHE",
                    "provider": "IQAir",
                    "country": "Pakistan",
                    "state": "Punjab",
                    "city": "Lahore",
                    "lat": 31.5204,
                    "lon": 74.3587,
                    "site_type": "urban",
                    "metadata": {}
                },
                "data_availability": {
                    "total_days_with_any_data": 324,
                    "coverage_last_365d_pct": 88.5,
                    "hours_total": 8760,
                    "hours_with_data": 7752,
                    "hours_qc_ok": 7200
                },
                "sensors": [],
                "pollutant_summary": {
                    "pollutant": "pm25",
                    "last_value": 45.2,
                    "rolling_means": {"24h": 42.1, "7d": 38.5, "30d": 41.2},
                    "days_above_thresholds_last_30d": {"WHO_24h": 15, "local_24h": 8}
                }
            }
        }


class TimeWindow(BaseModel):
    """Time window specification"""
    from_: datetime = Field(..., alias="from", description="Start of analysis window")
    to: datetime = Field(..., description="End of analysis window")

    class Config:
        json_schema_extra = {
            "example": {
                "from": "2024-11-20T00:00:00Z",
                "to": "2025-11-20T00:00:00Z"
            }
        }


class CoverageStats(BaseModel):
    """Data coverage statistics for uptime analysis"""
    expected_buckets: int = Field(..., description="Total number of expected time buckets")
    buckets_with_data: int = Field(..., description="Number of buckets containing data")
    coverage_pct: float = Field(..., description="Percentage of buckets with data")
    missing_buckets: int = Field(..., description="Number of buckets without data")

    class Config:
        json_schema_extra = {
            "example": {
                "expected_buckets": 8760,
                "buckets_with_data": 7126,
                "coverage_pct": 81.3,
                "missing_buckets": 1634
            }
        }


class OfflinePeriod(BaseModel):
    """Period when station was offline/not reporting"""
    start: datetime = Field(..., description="Start of offline period")
    end: datetime = Field(..., description="End of offline period")
    duration_hours: float = Field(..., description="Duration of offline period in hours")
    reason: Optional[str] = Field(None, description="Classification of offline reason")

    class Config:
        json_schema_extra = {
            "example": {
                "start": "2025-01-10T03:00:00Z",
                "end": "2025-01-12T14:00:00Z",
                "duration_hours": 59.0,
                "reason": "offline"
            }
        }


class FlatlinePeriod(BaseModel):
    """Period when station reported unchanging (flatline) values"""
    start: datetime = Field(..., description="Start of flatline period")
    end: datetime = Field(..., description="End of flatline period")
    duration_hours: float = Field(..., description="Duration of flatline period in hours")
    value: float = Field(..., description="Constant value during flatline")
    pollutant: str = Field(..., description="Pollutant that was flatlined")

    class Config:
        json_schema_extra = {
            "example": {
                "start": "2025-02-01T00:00:00Z",
                "end": "2025-02-02T12:00:00Z",
                "duration_hours": 36.0,
                "value": 0.0,
                "pollutant": "pm25"
            }
        }


class StationUptimeResponse(BaseModel):
    """Station uptime and data quality analysis"""
    station_id: str = Field(..., description="Station identifier")
    bucket: Literal["5m", "1h", "1d"] = Field(..., description="Time bucket size used for analysis")
    window: TimeWindow = Field(..., description="Analysis time window")
    coverage: CoverageStats = Field(..., description="Data coverage statistics")
    offline_periods: List[OfflinePeriod] = Field(..., description="Detected offline periods")
    flatline_periods: List[FlatlinePeriod] = Field(..., description="Detected flatline periods")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "PKLAH0001",
                "bucket": "1h",
                "window": {
                    "from": "2024-11-20T00:00:00Z",
                    "to": "2025-11-20T00:00:00Z"
                },
                "coverage": {
                    "expected_buckets": 8760,
                    "buckets_with_data": 7126,
                    "coverage_pct": 81.3,
                    "missing_buckets": 1634
                },
                "offline_periods": [
                    {
                        "start": "2025-01-10T03:00:00Z",
                        "end": "2025-01-12T14:00:00Z",
                        "duration_hours": 59.0,
                        "reason": "offline"
                    }
                ],
                "flatline_periods": [
                    {
                        "start": "2025-02-01T00:00:00Z",
                        "end": "2025-02-02T12:00:00Z",
                        "duration_hours": 36.0,
                        "value": 0.0,
                        "pollutant": "pm25"
                    }
                ]
            }
        }


class DiurnalBucket(BaseModel):
    """Single hour bucket in diurnal pattern analysis"""
    hour_local: int = Field(..., description="Hour of day in local time (0-23)")
    mean: float = Field(..., description="Mean pollutant concentration")
    p10: float = Field(..., description="10th percentile")
    p50: float = Field(..., description="Median (50th percentile)")
    p90: float = Field(..., description="90th percentile")
    count: int = Field(..., description="Number of observations")

    class Config:
        json_schema_extra = {
            "example": {
                "hour_local": 14,
                "mean": 42.5,
                "p10": 28.1,
                "p50": 41.2,
                "p90": 58.9,
                "count": 315
            }
        }


class DiurnalWindow(BaseModel):
    """Time window for diurnal analysis"""
    from_: datetime = Field(..., alias="from", description="Start of analysis window")
    to: datetime = Field(..., description="End of analysis window")

    class Config:
        json_schema_extra = {
            "example": {
                "from": "2024-11-20T00:00:00Z",
                "to": "2025-11-20T00:00:00Z"
            }
        }


class DiurnalResponse(BaseModel):
    """Complete diurnal pattern analysis"""
    station_id: str = Field(..., description="Station identifier")
    pollutant: str = Field(..., description="Pollutant analyzed")
    timezone: str = Field(..., description="Timezone used for local time calculations")
    window: DiurnalWindow = Field(..., description="Analysis time window")
    overall: List[DiurnalBucket] = Field(..., description="Overall diurnal pattern")
    by_weekday_weekend: Optional[Dict[str, List[DiurnalBucket]]] = Field(None, description="Weekday vs weekend patterns")
    by_season: Optional[Dict[str, List[DiurnalBucket]]] = Field(None, description="Seasonal diurnal patterns")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "PKLAH0001",
                "pollutant": "pm25",
                "timezone": "Asia/Karachi",
                "window": {
                    "from": "2024-11-20T00:00:00Z",
                    "to": "2025-11-20T00:00:00Z"
                },
                "overall": [
                    {
                        "hour_local": 0,
                        "mean": 35.2,
                        "p10": 22.1,
                        "p50": 33.5,
                        "p90": 51.2,
                        "count": 285
                    }
                ],
                "by_weekday_weekend": {
                    "weekday": [],
                    "weekend": []
                },
                "by_season": {
                    "winter": [],
                    "pre_monsoon": [],
                    "monsoon": [],
                    "post_monsoon": []
                }
            }
        }


class EpisodeDay(BaseModel):
    """Day-level episode summary"""
    date: str = Field(..., description="Date in local timezone (YYYY-MM-DD)")
    mean_value: float = Field(..., description="Mean pollutant concentration for the day")
    max_value: float = Field(..., description="Maximum pollutant concentration for the day")
    hours_above_threshold: int = Field(..., description="Number of hours above episode threshold")
    severity_score: float = Field(..., description="Episode severity score (0-1)")

    class Config:
        json_schema_extra = {
            "example": {
                "date": "2025-01-15",
                "mean_value": 85.2,
                "max_value": 142.8,
                "hours_above_threshold": 18,
                "severity_score": 0.75
            }
        }


class EpisodeHour(BaseModel):
    """Hour-level episode detail"""
    datetime_local: datetime = Field(..., description="Hour timestamp in local timezone")
    value: float = Field(..., description="Pollutant concentration")
    threshold: float = Field(..., description="Threshold used for detection")
    severity_score: float = Field(..., description="Hourly severity score")

    class Config:
        json_schema_extra = {
            "example": {
                "datetime_local": "2025-01-15T14:00:00+05:00",
                "value": 142.8,
                "threshold": 75.0,
                "severity_score": 0.91
            }
        }


class Episode(BaseModel):
    """Complete episode with day summary and hourly details"""
    start_datetime_local: datetime = Field(..., description="Episode start in local time")
    end_datetime_local: datetime = Field(..., description="Episode end in local time")
    duration_hours: int = Field(..., description="Duration of episode in hours")
    peak_value: float = Field(..., description="Peak pollutant value during episode")
    peak_datetime_local: datetime = Field(..., description="Time of peak value in local time")
    mean_value: float = Field(..., description="Mean value during episode")
    severity_score: float = Field(..., description="Overall episode severity (0-1)")
    hours: List[EpisodeHour] = Field(..., description="Hourly readings during episode")

    class Config:
        json_schema_extra = {
            "example": {
                "start_datetime_local": "2025-01-15T12:00:00+05:00",
                "end_datetime_local": "2025-01-15T20:00:00+05:00",
                "duration_hours": 8,
                "peak_value": 142.8,
                "peak_datetime_local": "2025-01-15T14:00:00+05:00",
                "mean_value": 95.4,
                "severity_score": 0.82,
                "hours": [
                    {
                        "datetime_local": "2025-01-15T14:00:00+05:00",
                        "value": 142.8,
                        "threshold": 75.0,
                        "severity_score": 0.91
                    }
                ]
            }
        }


class EpisodesResponse(BaseModel):
    """Episodes/anomaly detection response"""
    station_id: str = Field(..., description="Station identifier")
    pollutant: str = Field(..., description="Pollutant analyzed")
    level: Literal["day", "hour"] = Field(..., description="Detection level used")
    threshold: float = Field(..., description="Threshold used for detection")
    window: TimeWindow = Field(..., description="Analysis time window")
    top_days: List[EpisodeDay] = Field(..., description="Most severe episode days")
    episodes: List[Episode] = Field(..., description="Detailed episode information")
    total_episodes: int = Field(..., description="Total number of episodes found")
    total_episode_hours: int = Field(..., description="Total hours in episodes")

    class Config:
        json_schema_extra = {
            "example": {
                "station_id": "01cb11a02fbad27d",
                "pollutant": "pm25",
                "level": "hour",
                "threshold": 75.0,
                "window": {
                    "from": "2025-01-01T00:00:00Z",
                    "to": "2025-01-20T00:00:00Z"
                },
                "top_days": [
                    {
                        "date": "2025-01-15",
                        "mean_value": 85.2,
                        "max_value": 142.8,
                        "hours_above_threshold": 18,
                        "severity_score": 0.75
                    }
                ],
                "episodes": [
                    {
                        "start_datetime_local": "2025-01-15T12:00:00+05:00",
                        "end_datetime_local": "2025-01-15T20:00:00+05:00",
                        "duration_hours": 8,
                        "peak_value": 142.8,
                        "peak_datetime_local": "2025-01-15T14:00:00+05:00",
                        "mean_value": 95.4,
                        "severity_score": 0.82,
                        "hours": []
                    }
                ],
                "total_episodes": 3,
                "total_episode_hours": 24
            }
        }