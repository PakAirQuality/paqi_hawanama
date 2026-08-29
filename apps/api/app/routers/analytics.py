"""Analytics REST endpoints — thin wrappers over the analytics service layer.

These endpoints serve the same data the copilot tools use, enabling
direct API access for debugging, dashboards, and external consumers.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_database
from app.core.security import verify_tasks_token
from app.services import analytics

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/analytics/hotspots/daily",
    summary="Air quality hotspots (observation-based)",
    description="Current PM2.5 hotspots from station observations, optionally enriched with forecast outlook.",
)
async def hotspots_daily(
    date: Optional[str] = Query(None, description="Date (YYYY-MM-DD). Defaults to today."),
    geography: str = Query("city", description="Group by: city, station, or province."),
    metric: str = Query("avg_pm25", description="Ranking metric: avg_pm25 or max_pm25."),
    top_k: int = Query(5, ge=1, le=50, description="Number of results."),
    country: Optional[str] = Query(None, description="Country name filter (e.g. Pakistan, India)."),
    db: AsyncSession = Depends(get_database),
    _auth=Depends(verify_tasks_token),
):
    return await analytics.get_hotspots_daily(db, date, geography, metric, top_k, country)


@router.get(
    "/analytics/cities/{city_name}/detail",
    summary="City air quality detail (observation-based)",
    description="Current readings, 24h trend, and optional forecast outlook for a city.",
)
async def city_detail(
    city_name: str,
    date: Optional[str] = Query(None, description="Date (YYYY-MM-DD). Defaults to today."),
    include: Optional[str] = Query(
        "stations,trend",
        description="Comma-separated sections: stations, trend, forecast.",
    ),
    db: AsyncSession = Depends(get_database),
    _auth=Depends(verify_tasks_token),
):
    include_list = [s.strip() for s in include.split(",")] if include else ["stations", "trend"]
    return await analytics.get_city_detail(db, city_name, date, include_list)


@router.get(
    "/analytics/stations/{station_id}/detail",
    summary="Station detail (observation-based)",
    description="Current reading and forecast horizons for a single station.",
)
async def station_detail(
    station_id: str,
    date: Optional[str] = Query(None, description="Date (YYYY-MM-DD). Defaults to today."),
    db: AsyncSession = Depends(get_database),
    _auth=Depends(verify_tasks_token),
):
    return await analytics.get_city_detail(db, sensor_id=station_id, date=date)


@router.get(
    "/analytics/compare",
    summary="Compare air quality between two dates (observation-based)",
    description="Compares observed PM2.5 across two dates with delta and biggest movers.",
)
async def compare_dates(
    date1: str = Query(..., description="First date (YYYY-MM-DD)."),
    date2: str = Query(..., description="Second date (YYYY-MM-DD)."),
    geography: str = Query("national", description="'national' or a city name."),
    country: Optional[str] = Query(None, description="Country name filter (e.g. Pakistan, India)."),
    db: AsyncSession = Depends(get_database),
    _auth=Depends(verify_tasks_token),
):
    return await analytics.get_compare_dates(db, date1, date2, geography, country)


@router.get(
    "/analytics/drivers",
    summary="Explain air quality drivers",
    description="Anomaly driver attribution from watchlists, enriched with current observations.",
)
async def explain_drivers(
    target: str = Query(..., description="City or station name to investigate."),
    date: Optional[str] = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
    db: AsyncSession = Depends(get_database),
    _auth=Depends(verify_tasks_token),
):
    return await analytics.get_explain_drivers(db, target, date)


@router.get(
    "/analytics/incidents",
    summary="Active incidents and alerts",
    description="Watchlist-based incidents enriched with current observations. Falls back to DB if no watchlist.",
)
async def incident_summary(
    date: Optional[str] = Query(None, description="Forecast date (YYYY-MM-DD). Defaults to latest."),
    severity: str = Query("all", description="Filter: all, critical, or warning."),
    country: Optional[str] = Query(None, description="Country name filter (e.g. Pakistan, India)."),
    db: AsyncSession = Depends(get_database),
    _auth=Depends(verify_tasks_token),
):
    return await analytics.get_incident_summary(db, date, severity, country)


@router.get(
    "/analytics/audit",
    summary="Forecast accuracy audit",
    description="Single-day or multi-day forecast accuracy metrics from drift reports.",
)
async def forecast_audit(
    date: Optional[str] = Query(None, description="End date (YYYY-MM-DD). Defaults to latest."),
    n_days: int = Query(1, ge=1, le=90, description="Number of days to audit."),
    _auth=Depends(verify_tasks_token),
):
    return await analytics.get_forecast_audit(date, n_days)
