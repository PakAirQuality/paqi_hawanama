"""Builders for OpenAQ v3 payloads shaped like the documented responses."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

BASE = "https://api.openaq.test/v3"
T0 = datetime(2026, 10, 15, 0, 0, tzinfo=timezone.utc)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sensor(sid: int, parameter: str = "pm25", units: str = "µg/m³") -> Dict[str, Any]:
    return {"id": sid, "name": f"{parameter} {units}", "parameter": {"id": 2, "name": parameter, "units": units, "displayName": "PM2.5"}}


def location(lid: int, *, name: str = None, lat: float = 31.5, lon: float = 74.3, provider: str = "AirGradient",
             owner: str = "Someone", sensors: Optional[List[Dict[str, Any]]] = None, is_mobile: bool = False,
             is_monitor: bool = False, licenses: Optional[list] = None) -> Dict[str, Any]:
    return {
        "id": lid, "name": name or f"Location {lid}", "locality": "Lahore", "timezone": "Asia/Karachi",
        "country": {"id": 150, "code": "PK", "name": "Pakistan"},
        "owner": {"id": 4, "name": owner}, "provider": {"id": 9, "name": provider},
        "isMobile": is_mobile, "isMonitor": is_monitor,
        "instruments": [{"id": 1, "name": "AirGradient Open Air"}],
        "sensors": sensors if sensors is not None else [sensor(lid * 10)],
        "coordinates": {"latitude": lat, "longitude": lon},
        "licenses": licenses if licenses is not None else [{"id": 33, "name": "CC BY 4.0", "attribution": {"name": owner, "url": None},
                                                             "dateFrom": "2024-01-01", "dateTo": None}],
        "bounds": [lon, lat, lon, lat], "distance": None,
        "datetimeFirst": {"utc": _z(T0 - timedelta(days=30)), "local": "x"},
        "datetimeLast": {"utc": _z(T0), "local": "x"},
    }


def page(results: List[Dict[str, Any]], *, page_no: int = 1, limit: int = 100, found: Any = None) -> Dict[str, Any]:
    return {"meta": {"name": "openaq-api", "website": "/", "page": page_no, "limit": limit,
                     "found": found if found is not None else len(results)}, "results": results}


def measurement(ts_end: datetime, value: float, *, interval: str = "01:00:00", units: str = "µg/m³",
                parameter: str = "pm25", has_flags: bool = False) -> Dict[str, Any]:
    start = ts_end - timedelta(hours=1)
    return {
        "value": value, "flagInfo": {"hasFlags": has_flags},
        "parameter": {"id": 2, "name": parameter, "units": units, "displayName": "PM2.5"},
        "period": {"label": "raw", "interval": interval,
                   "datetimeFrom": {"utc": _z(start), "local": "x"}, "datetimeTo": {"utc": _z(ts_end), "local": "x"}},
        "coordinates": None, "summary": None,
        "coverage": {"expectedCount": 1, "expectedInterval": interval, "observedCount": 1, "observedInterval": interval,
                     "percentComplete": 100, "percentCoverage": 100,
                     "datetimeFrom": {"utc": _z(start), "local": "x"}, "datetimeTo": {"utc": _z(ts_end), "local": "x"}},
    }


def hourly_series(start: datetime, hours: int, *, base: float = 10.0) -> List[Dict[str, Any]]:
    return [measurement(start + timedelta(hours=i + 1), base + i) for i in range(hours)]
