"""Builders for ICIMOD payloads shaped exactly like the live responses (probed 2026-11-03)."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

BASE = "https://icimod.test/api/v1"
DISTRICTS = ["Lahore", "Kasur"]
DAY = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)


def label(hour: int, *, day: datetime = DAY) -> str:
    """The feed labels each hour at :30 with an explicit +00:00 offset."""
    return (day + timedelta(hours=hour, minutes=30)).isoformat()


def station(sid: int, name: str, *, district: str = "Lahore", lat: float = 31.56, lon: float = 74.33,
            state: str = "Punjab") -> Dict[str, Any]:
    return {"id": sid, "station_name": name, "district_name": district, "city": district, "state": state,
            "latitude": lat, "longitude": lon}


def stations_payload(*rows: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(rows) if rows else [station(26, "Egerton Road"), station(70, "Gulberg III, Lahore", lat=31.507, lon=74.338),
                                    station(6, "Barki Road", lat=31.536, lon=74.435)]


def feature(name: str, hourly: Optional[Dict[str, Any]], *, lat: float = 31.56, lon: float = 74.33) -> Dict[str, Any]:
    hourly = hourly or {}
    latest = hourly[max(hourly)] if hourly else None
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "country": "Pakistan", "value": latest, "hourly_data": hourly}}


def hourly(start_hour: int, n: int, *, base: float = 100.0, step: float = 1.0) -> Dict[str, float]:
    return {label(start_hour + i): round(base + i * step, 3) for i in range(n)}


def collection(*features: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "FeatureCollection", "features": list(features)}
