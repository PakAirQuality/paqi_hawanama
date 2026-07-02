"""
Internal Stations Analytics API Router - provides detailed station analytics
"""

from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Literal

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.schemas.internal_station import (
    StationOverviewResponse,
    StationInfo,
    DataAvailability,
    PollutantSummary,
    SensorDeployment,
    StationUptimeResponse,
    TimeWindow,
    CoverageStats,
    OfflinePeriod,
    FlatlinePeriod,
    DiurnalResponse,
    DiurnalWindow,
    DiurnalBucket,
    EpisodesResponse,
    EpisodeDay,
    Episode,
    EpisodeHour,
)
from app.core.database import get_database
from app.services.ingestion.bam_service import (
    FLOW_TARGET_LPM,
    FLOW_TOL_FRAC,
    HIGH_RH_PCT,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# WHO/Local thresholds (µg/m³)
WHO_24H_PM25 = 15.0
LOCAL_24H_PM25 = 35.0


async def fetch_station_info(db: AsyncSession, station_id: str) -> Optional[StationInfo]:
    """Fetch station identity and metadata information"""
    q = text("""
        SELECT
          s.station_id,
          s.name,
          s.lat, s.lon,
          s.provider_id,
          p.display_name AS provider,
          c.name AS country,
          st.name AS state,
          ci.name AS city,
          s.source_station_id,
          s.timezone,
          s.metadata_json
        FROM stations s
        LEFT JOIN providers p ON p.id = s.provider_id
        LEFT JOIN countries c ON c.id = s.country_id
        LEFT JOIN states    st ON st.id = s.state_id
        LEFT JOIN cities    ci ON ci.id = s.city_id
        WHERE s.station_id = :station_id
    """)
    
    try:
        res = await db.execute(q, {"station_id": station_id})
        row = res.mappings().first()
        if row is None:
            return None

        meta = row["metadata_json"] or {}
        return StationInfo(
            station_id=row["station_id"],
            name=row["name"],
            provider=row["provider"],
            provider_id=row["provider_id"],
            source_station_id=row["source_station_id"],
            country=row["country"],
            state=row["state"],
            city=row["city"],
            lat=row["lat"],
            lon=row["lon"],
            site_type=meta.get("site_type"),
            indoor_outdoor=meta.get("indoor_outdoor"),
            height_m=meta.get("height_m"),
            distance_to_road_m=meta.get("distance_to_road_m"),
            timezone=row["timezone"],
            metadata=meta,
        )
    except Exception as e:
        logger.error(f"Error fetching station info for {station_id}: {e}")
        raise


async def compute_data_availability(
    db: AsyncSession,
    station_id: str,
    start: datetime,
    end: datetime,
) -> DataAvailability:
    """Compute data availability and coverage statistics"""
    try:
        # First / last obs overall
        q1 = text("""
            SELECT
              MIN(ts_utc) AS first_obs,
              MAX(ts_utc) AS last_obs
            FROM readings
            WHERE scope_type = 'station'
              AND scope_key  = :station_id
        """)
        r1 = (await db.execute(q1, {"station_id": station_id})).mappings().first()
        first_obs = r1["first_obs"] if r1 else None
        last_obs = r1["last_obs"] if r1 else None

        # Coverage in window from `start` to `end` using sa_daily_station
        q2 = text("""
            SELECT
              COUNT(*) FILTER (WHERE hours_total > 0) AS total_days_with_any_data,
              COALESCE(SUM(hours_total), 0) AS hours_total,
              COALESCE(SUM(hours_total), 0) AS hours_with_data,
              COALESCE(SUM(hours_qc_ok), 0) AS hours_qc_ok
            FROM sa_daily_station
            WHERE station_id = :station_id
              AND day_utc >= :start
              AND day_utc <  :end
        """)
        r2 = (await db.execute(q2, {"station_id": station_id, "start": start, "end": end})).mappings().first()

        total_days_with_any_data = r2["total_days_with_any_data"] or 0
        hours_total = r2["hours_total"] or 0
        hours_with_data = r2["hours_with_data"] or 0
        hours_qc_ok = r2["hours_qc_ok"] or 0

        # Theoretical hours in window (rough: days * 24)
        num_days = max(1, (end.date() - start.date()).days)
        theoretical_hours = num_days * 24
        coverage_pct = 100.0 * (float(hours_with_data) / theoretical_hours) if theoretical_hours > 0 else 0.0

        return DataAvailability(
            first_obs=first_obs,
            last_obs=last_obs,
            total_days_with_any_data=total_days_with_any_data,
            coverage_last_365d_pct=coverage_pct,
            hours_total=theoretical_hours,
            hours_with_data=hours_with_data,
            hours_qc_ok=hours_qc_ok,
        )
    except Exception as e:
        logger.error(f"Error computing data availability for {station_id}: {e}")
        raise


async def compute_pollutant_summary(
    db: AsyncSession,
    station_id: str,
    window_end: datetime,
    pollutant: str = "pm25",
) -> PollutantSummary:
    """Compute pollutant statistics and threshold analysis"""
    try:
        # Last value
        q_last = text("""
            SELECT ts_utc, pm25
            FROM readings
            WHERE scope_type = 'station'
              AND scope_key  = :station_id
              AND pm25 IS NOT NULL
            ORDER BY ts_utc DESC
            LIMIT 1
        """)
        row_last = (await db.execute(q_last, {"station_id": station_id})).mappings().first()
        last_value = row_last["pm25"] if row_last else None
        last_value_ts = row_last["ts_utc"] if row_last else None

        # Rolling means: 24h from readings, 7d/30d from sa_daily_station
        q_24h = text("""
            SELECT avg(pm25) AS mean_24h
            FROM readings
            WHERE scope_type = 'station'
              AND scope_key  = :station_id
              AND ts_utc >= :start
              AND ts_utc <  :end
              AND pm25 IS NOT NULL
        """)
        start_24h = window_end - timedelta(hours=24)
        r_24h = (await db.execute(q_24h, {"station_id": station_id, "start": start_24h, "end": window_end})).mappings().first()
        mean_24h = r_24h["mean_24h"] if r_24h else None

        q_7_30 = text("""
            SELECT
              avg(pm25_mean) FILTER (WHERE day_utc >= :start_7d)  AS mean_7d,
              avg(pm25_mean) FILTER (WHERE day_utc >= :start_30d) AS mean_30d
            FROM sa_daily_station
            WHERE station_id = :station_id
              AND day_utc < :end_day
        """)
        end_day = window_end.date()
        r_7_30 = (await db.execute(
            q_7_30,
            {
                "station_id": station_id,
                "start_7d": end_day - timedelta(days=7),
                "start_30d": end_day - timedelta(days=30),
                "end_day": end_day,
            },
        )).mappings().first()
        mean_7d = r_7_30["mean_7d"] if r_7_30 else None
        mean_30d = r_7_30["mean_30d"] if r_7_30 else None

        # Days above thresholds (30d, 365d) using sa_daily_station
        q_thresh = text("""
            SELECT
              COUNT(*) FILTER (WHERE pm25_mean > :who)   AS who_30,
              COUNT(*) FILTER (WHERE pm25_mean > :local) AS local_30
            FROM sa_daily_station
            WHERE station_id = :station_id
              AND day_utc >= :start_30d
              AND day_utc <  :end_day
        """)
        r_30 = (await db.execute(
            q_thresh,
            {
                "station_id": station_id,
                "who": WHO_24H_PM25,
                "local": LOCAL_24H_PM25,
                "start_30d": end_day - timedelta(days=30),
                "end_day": end_day,
            },
        )).mappings().first()
        who_30 = r_30["who_30"] or 0
        local_30 = r_30["local_30"] or 0

        q_thresh_365 = text("""
            SELECT
              COUNT(*) FILTER (WHERE pm25_mean > :who)   AS who_365,
              COUNT(*) FILTER (WHERE pm25_mean > :local) AS local_365
            FROM sa_daily_station
            WHERE station_id = :station_id
              AND day_utc >= :start_365d
              AND day_utc <  :end_day
        """)
        r_365 = (await db.execute(
            q_thresh_365,
            {
                "station_id": station_id,
                "who": WHO_24H_PM25,
                "local": LOCAL_24H_PM25,
                "start_365d": end_day - timedelta(days=365),
                "end_day": end_day,
            },
        )).mappings().first()
        who_365 = r_365["who_365"] or 0
        local_365 = r_365["local_365"] or 0

        return PollutantSummary(
            pollutant=pollutant,
            last_value=last_value,
            last_value_ts=last_value_ts,
            rolling_means={
                "24h": mean_24h,
                "7d": mean_7d,
                "30d": mean_30d,
            },
            days_above_thresholds_last_30d={
                "WHO_24h": who_30,
                "local_24h": local_30,
            },
            days_above_thresholds_last_365d={
                "WHO_24h": who_365,
                "local_24h": local_365,
            },
        )
    except Exception as e:
        logger.error(f"Error computing pollutant summary for {station_id}: {e}")
        raise


async def fetch_sensor_history(db: AsyncSession, station_id: str) -> list[SensorDeployment]:
    """Fetch sensor deployment history (placeholder for now)"""
    # For now, return empty list - can be wired to station_versions later
    return []


@router.get("/{station_id}/overview", response_model=StationOverviewResponse)
async def get_station_overview(
    station_id: str,
    from_: Optional[datetime] = Query(None, alias="from", description="Start of analysis window"),
    to: Optional[datetime] = Query(None, description="End of analysis window"),
    pollutant: str = Query("pm25", description="Pollutant to analyze"),
    db: AsyncSession = Depends(get_database),
):
    """
    Get comprehensive station overview with analytics
    
    Returns detailed station information including:
    - Station identity and metadata
    - Data availability statistics
    - Pollutant trends and threshold analysis
    - Sensor deployment history
    
    **Parameters:**
    - **station_id**: Station identifier (16-character hash)
    - **from**: Start of analysis window (defaults to 365 days ago)
    - **to**: End of analysis window (defaults to now)
    - **pollutant**: Pollutant to analyze (defaults to pm25)
    """
    try:
        station = await fetch_station_info(db, station_id)
        if station is None:
            raise HTTPException(status_code=404, detail="Station not found")

        # Default window: last 365 days
        if to is None:
            to = datetime.now(timezone.utc)
        if from_ is None:
            from_ = to - timedelta(days=365)

        data_availability = await compute_data_availability(db, station_id, from_, to)
        pollutant_summary = await compute_pollutant_summary(db, station_id, to, pollutant)
        sensors = await fetch_sensor_history(db, station_id)

        return StationOverviewResponse(
            station=station,
            data_availability=data_availability,
            sensors=sensors,
            pollutant_summary=pollutant_summary,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station overview for {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


def detect_offline_periods(bucket_data: list, bucket_interval: str, min_offline_hours: float = 3.0) -> list[OfflinePeriod]:
    """Detect consecutive missing buckets as offline periods"""
    if not bucket_data:
        return []
    
    # Convert bucket interval to hours
    interval_hours = {
        "5m": 5/60,
        "1h": 1.0,
        "1d": 24.0
    }.get(bucket_interval, 1.0)
    
    min_buckets = max(1, int(min_offline_hours / interval_hours))
    offline_periods = []
    current_gap_start = None
    current_gap_buckets = 0
    
    for i, bucket in enumerate(bucket_data):
        is_missing = bucket["pm25_max"] is None
        
        if is_missing:
            if current_gap_start is None:
                current_gap_start = bucket["bucket"]
            current_gap_buckets += 1
        else:
            # End of gap
            if current_gap_start is not None and current_gap_buckets >= min_buckets:
                duration_hours = current_gap_buckets * interval_hours
                offline_periods.append(OfflinePeriod(
                    start=current_gap_start,
                    end=bucket["bucket"],
                    duration_hours=duration_hours,
                    reason="offline"
                ))
            current_gap_start = None
            current_gap_buckets = 0
    
    # Handle gap at end of data
    if current_gap_start is not None and current_gap_buckets >= min_buckets:
        duration_hours = current_gap_buckets * interval_hours
        # Estimate end time
        last_bucket = bucket_data[-1]["bucket"]
        estimated_end = last_bucket + timedelta(hours=interval_hours)
        offline_periods.append(OfflinePeriod(
            start=current_gap_start,
            end=estimated_end,
            duration_hours=duration_hours,
            reason="offline"
        ))
    
    return offline_periods


def detect_flatline_periods(bucket_data: list, bucket_interval: str, min_flatline_hours: float = 6.0, max_variation: float = 1.0) -> list[FlatlinePeriod]:
    """Detect periods where values remain constant (flatlined)"""
    if not bucket_data:
        return []
    
    # Convert bucket interval to hours
    interval_hours = {
        "5m": 5/60,
        "1h": 1.0,
        "1d": 24.0
    }.get(bucket_interval, 1.0)
    
    min_buckets = max(2, int(min_flatline_hours / interval_hours))
    flatline_periods = []
    current_flatline_start = None
    current_flatline_buckets = 0
    current_flatline_value = None
    
    for i, bucket in enumerate(bucket_data):
        pm25_max = bucket["pm25_max"]
        pm25_min = bucket["pm25_min"]
        
        # Skip missing data
        if pm25_max is None or pm25_min is None:
            # End current flatline if any
            if current_flatline_start is not None and current_flatline_buckets >= min_buckets:
                duration_hours = current_flatline_buckets * interval_hours
                flatline_periods.append(FlatlinePeriod(
                    start=current_flatline_start,
                    end=bucket["bucket"],
                    duration_hours=duration_hours,
                    value=current_flatline_value,
                    pollutant="pm25"
                ))
            current_flatline_start = None
            current_flatline_buckets = 0
            current_flatline_value = None
            continue
        
        # Check if this bucket has low variation (flatline)
        variation = abs(pm25_max - pm25_min)
        is_flatline = variation <= max_variation
        
        if is_flatline:
            bucket_value = (pm25_max + pm25_min) / 2
            
            if current_flatline_start is None:
                # Start new flatline
                current_flatline_start = bucket["bucket"]
                current_flatline_buckets = 1
                current_flatline_value = bucket_value
            elif abs(bucket_value - current_flatline_value) <= max_variation:
                # Continue existing flatline
                current_flatline_buckets += 1
            else:
                # Value changed, end current flatline if long enough
                if current_flatline_buckets >= min_buckets:
                    duration_hours = current_flatline_buckets * interval_hours
                    flatline_periods.append(FlatlinePeriod(
                        start=current_flatline_start,
                        end=bucket["bucket"],
                        duration_hours=duration_hours,
                        value=current_flatline_value,
                        pollutant="pm25"
                    ))
                # Start new flatline
                current_flatline_start = bucket["bucket"]
                current_flatline_buckets = 1
                current_flatline_value = bucket_value
        else:
            # End current flatline if any
            if current_flatline_start is not None and current_flatline_buckets >= min_buckets:
                duration_hours = current_flatline_buckets * interval_hours
                flatline_periods.append(FlatlinePeriod(
                    start=current_flatline_start,
                    end=bucket["bucket"],
                    duration_hours=duration_hours,
                    value=current_flatline_value,
                    pollutant="pm25"
                ))
            current_flatline_start = None
            current_flatline_buckets = 0
            current_flatline_value = None
    
    # Handle flatline at end of data
    if current_flatline_start is not None and current_flatline_buckets >= min_buckets:
        duration_hours = current_flatline_buckets * interval_hours
        last_bucket = bucket_data[-1]["bucket"]
        estimated_end = last_bucket + timedelta(hours=interval_hours)
        flatline_periods.append(FlatlinePeriod(
            start=current_flatline_start,
            end=estimated_end,
            duration_hours=duration_hours,
            value=current_flatline_value,
            pollutant="pm25"
        ))
    
    return flatline_periods


async def compute_station_uptime(
    db: AsyncSession,
    station_id: str,
    bucket: str,
    start: datetime,
    end: datetime,
) -> StationUptimeResponse:
    """Compute comprehensive station uptime analysis"""
    try:
        # Map bucket to TimescaleDB interval
        interval_map = {
            "5m": "5 minutes",
            "1h": "1 hour",
            "1d": "1 day"
        }
        
        if bucket not in interval_map:
            raise ValueError(f"Invalid bucket: {bucket}")
        
        pg_interval = interval_map[bucket]
        
        # Use time_bucket_gapfill to detect missing data
        # Note: Using f-string for interval since it's validated from enum
        q = text(f"""
            SELECT
              time_bucket_gapfill('{pg_interval}'::interval, ts_utc) AS bucket,
              max(pm25) AS pm25_max,
              min(pm25) AS pm25_min,
              count(*) AS reading_count
            FROM readings
            WHERE scope_type = 'station'
              AND scope_key = :station_id
              AND ts_utc >= :start
              AND ts_utc < :end
            GROUP BY bucket
            ORDER BY bucket
        """)
        
        result = await db.execute(q, {
            "station_id": station_id,
            "start": start,
            "end": end
        })
        
        bucket_data = [dict(row) for row in result.mappings()]
        
        # Calculate coverage statistics
        total_buckets = len(bucket_data)
        buckets_with_data = sum(1 for bucket in bucket_data if bucket["pm25_max"] is not None)
        missing_buckets = total_buckets - buckets_with_data
        coverage_pct = (float(buckets_with_data) / total_buckets * 100) if total_buckets > 0 else 0.0
        
        coverage = CoverageStats(
            expected_buckets=total_buckets,
            buckets_with_data=buckets_with_data,
            coverage_pct=coverage_pct,
            missing_buckets=missing_buckets
        )
        
        # Detect offline and flatline periods
        offline_periods = detect_offline_periods(bucket_data, bucket)
        flatline_periods = detect_flatline_periods(bucket_data, bucket)
        
        return StationUptimeResponse(
            station_id=station_id,
            bucket=bucket,
            window=TimeWindow(**{"from": start, "to": end}),
            coverage=coverage,
            offline_periods=offline_periods,
            flatline_periods=flatline_periods
        )
        
    except Exception as e:
        logger.error(f"Error computing uptime for station {station_id}: {e}")
        raise


@router.get("/{station_id}/uptime", response_model=StationUptimeResponse)
async def get_station_uptime(
    station_id: str,
    bucket: str = Query("1h", description="Time bucket size", regex="^(5m|1h|1d)$"),
    from_: Optional[datetime] = Query(None, alias="from", description="Start of analysis window"),
    to: Optional[datetime] = Query(None, description="End of analysis window"),
    db: AsyncSession = Depends(get_database),
):
    """
    Analyze station uptime and data quality
    
    Returns comprehensive uptime analysis including:
    - Data coverage statistics
    - Offline period detection 
    - Flatline/stuck sensor detection
    
    **Parameters:**
    - **station_id**: Station identifier (16-character hash)
    - **bucket**: Time bucket size (5m, 1h, 1d)
    - **from**: Start of analysis window (defaults to 365 days ago)
    - **to**: End of analysis window (defaults to now)
    
    **Use cases:**
    - "Is this station healthy?"
    - "How often is it offline?"
    - "Any stuck-at-zero behavior?"
    - "Is this time series safe for analysis?"
    """
    try:
        # Verify station exists
        station = await fetch_station_info(db, station_id)
        if station is None:
            raise HTTPException(status_code=404, detail="Station not found")

        # Default window: last 365 days
        if to is None:
            to = datetime.now(timezone.utc)
        if from_ is None:
            from_ = to - timedelta(days=365)

        return await compute_station_uptime(db, station_id, bucket, from_, to)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station uptime for {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def get_station_timezone(db: AsyncSession, station_id: str) -> str:
    """Get station timezone, default to Asia/Karachi for South Asia"""
    q = text("""
        SELECT timezone FROM stations 
        WHERE station_id = :station_id
    """)
    
    result = await db.execute(q, {"station_id": station_id})
    row = result.mappings().first()
    
    if row and row["timezone"]:
        return row["timezone"]
    else:
        # Default timezone for South Asia stations
        return "Asia/Karachi"


async def fetch_overall_diurnal(
    db: AsyncSession,
    station_id: str,
    tz: str,
    start: datetime,
    end: datetime,
) -> List[DiurnalBucket]:
    """Fetch overall diurnal pattern (24-hour average across all days)"""
    
    q = text("""
        SELECT
          EXTRACT(HOUR FROM (ts_utc AT TIME ZONE :tz))::int AS hour_local,
          avg(pm25) AS mean,
          percentile_cont(0.10) WITHIN GROUP (ORDER BY pm25) AS p10,
          percentile_cont(0.50) WITHIN GROUP (ORDER BY pm25) AS p50,
          percentile_cont(0.90) WITHIN GROUP (ORDER BY pm25) AS p90,
          count(*) AS count
        FROM readings
        WHERE scope_type = 'station'
          AND scope_key  = :station_id
          AND ts_utc >= :start
          AND ts_utc <  :end
          AND pm25 IS NOT NULL
          -- qc_state filter removed: column not populated yet
        GROUP BY hour_local
        ORDER BY hour_local;
    """)

    res = await db.execute(q, {
        "station_id": station_id,
        "tz": tz,
        "start": start,
        "end": end,
    })

    buckets = []
    for row in res.mappings():
        buckets.append(DiurnalBucket(
            hour_local=row["hour_local"],
            mean=row["mean"],
            p10=row["p10"],
            p50=row["p50"],
            p90=row["p90"],
            count=row["count"],
        ))

    return buckets


async def fetch_weekday_weekend_diurnal(
    db: AsyncSession,
    station_id: str,
    tz: str,
    start: datetime,
    end: datetime,
) -> Dict[str, List[DiurnalBucket]]:
    """
    Returns:
      {
        "weekday": [DiurnalBucket, ...],
        "weekend": [DiurnalBucket, ...]
      }
    """

    q = text("""
        SELECT
          EXTRACT(HOUR FROM (ts_utc AT TIME ZONE :tz))::int AS hour_local,
          (EXTRACT(ISODOW FROM (ts_utc AT TIME ZONE :tz)) IN (6,7)) AS is_weekend,
          avg(pm25) AS mean,
          percentile_cont(0.10) WITHIN GROUP (ORDER BY pm25) AS p10,
          percentile_cont(0.50) WITHIN GROUP (ORDER BY pm25) AS p50,
          percentile_cont(0.90) WITHIN GROUP (ORDER BY pm25) AS p90,
          count(*) AS count
        FROM readings
        WHERE scope_type = 'station'
          AND scope_key  = :station_id
          AND ts_utc >= :start
          AND ts_utc <  :end
          AND pm25 IS NOT NULL
          -- qc_state filter removed: column not populated yet
        GROUP BY is_weekend, hour_local
        ORDER BY is_weekend, hour_local;
    """)

    res = await db.execute(q, {
        "station_id": station_id,
        "tz": tz,
        "start": start,
        "end": end,
    })

    weekday: List[DiurnalBucket] = []
    weekend: List[DiurnalBucket] = []

    for row in res.mappings():
        bucket = DiurnalBucket(
            hour_local=row["hour_local"],
            mean=row["mean"],
            p10=row["p10"],
            p50=row["p50"],
            p90=row["p90"],
            count=row["count"],
        )
        if row["is_weekend"]:
            weekend.append(bucket)
        else:
            weekday.append(bucket)

    return {
        "weekday": weekday,
        "weekend": weekend,
    }


async def fetch_season_diurnal(
    db: AsyncSession,
    station_id: str,
    tz: str,
    start: datetime,
    end: datetime,
) -> Dict[str, List[DiurnalBucket]]:
    """
    Returns:
      {
        "winter":      [DiurnalBucket, ...],
        "pre_monsoon": [DiurnalBucket, ...],
        "monsoon":     [DiurnalBucket, ...],
        "post_monsoon":[DiurnalBucket, ...]
      }
    """

    q = text("""
        SELECT
          EXTRACT(HOUR FROM (ts_utc AT TIME ZONE :tz))::int AS hour_local,
          CASE
            WHEN EXTRACT(MONTH FROM (ts_utc AT TIME ZONE :tz)) IN (12,1,2)
              THEN 'winter'
            WHEN EXTRACT(MONTH FROM (ts_utc AT TIME ZONE :tz)) IN (3,4,5)
              THEN 'pre_monsoon'
            WHEN EXTRACT(MONTH FROM (ts_utc AT TIME ZONE :tz)) IN (6,7,8,9)
              THEN 'monsoon'
            ELSE 'post_monsoon'
          END AS season,
          avg(pm25) AS mean,
          percentile_cont(0.10) WITHIN GROUP (ORDER BY pm25) AS p10,
          percentile_cont(0.50) WITHIN GROUP (ORDER BY pm25) AS p50,
          percentile_cont(0.90) WITHIN GROUP (ORDER BY pm25) AS p90,
          count(*) AS count
        FROM readings
        WHERE scope_type = 'station'
          AND scope_key  = :station_id
          AND ts_utc >= :start
          AND ts_utc <  :end
          AND pm25 IS NOT NULL
          -- qc_state filter removed: column not populated yet
        GROUP BY season, hour_local
        ORDER BY season, hour_local;
    """)

    res = await db.execute(q, {
        "station_id": station_id,
        "tz": tz,
        "start": start,
        "end": end,
    })

    # Ensure all seasons exist, even if empty
    seasons: Dict[str, List[DiurnalBucket]] = {
        "winter": [],
        "pre_monsoon": [],
        "monsoon": [],
        "post_monsoon": [],
    }

    for row in res.mappings():
        season_key = row["season"]
        if season_key not in seasons:
            # Just in case, but it should be one of the four
            seasons[season_key] = []

        seasons[season_key].append(DiurnalBucket(
            hour_local=row["hour_local"],
            mean=row["mean"],
            p10=row["p10"],
            p50=row["p50"],
            p90=row["p90"],
            count=row["count"],
        ))

    return seasons


@router.get("/{station_id}/diurnal", response_model=DiurnalResponse)
async def get_station_diurnal(
    station_id: str,
    from_: Optional[datetime] = Query(None, alias="from", description="Start of analysis window"),
    to: Optional[datetime] = Query(None, description="End of analysis window"),
    pollutant: str = Query("pm25", description="Pollutant to analyze"),
    include_weekday_weekend: bool = Query(True, description="Include weekday vs weekend breakdown"),
    include_season: bool = Query(True, description="Include seasonal breakdown"),
    db: AsyncSession = Depends(get_database),
):
    """
    Analyze station diurnal (24-hour) patterns
    
    Returns detailed diurnal pattern analysis including:
    - Overall 24-hour average pattern
    - Weekday vs weekend differences  
    - Seasonal pattern variations
    - Statistical distribution (percentiles) for each hour
    
    **Parameters:**
    - **station_id**: Station identifier (16-character hash)
    - **from**: Start of analysis window (defaults to 365 days ago)
    - **to**: End of analysis window (defaults to now)
    - **pollutant**: Pollutant to analyze (currently only pm25 supported)
    - **include_weekday_weekend**: Include weekday vs weekend analysis
    - **include_season**: Include seasonal pattern analysis
    
    **Use cases:**
    - "What's the typical daily pattern?"
    - "Rush hour vs off-peak differences?"
    - "Weekend vs weekday pollution?"
    - "Seasonal behavior changes?"
    - "Station personality/signature identification"
    """
    try:
        if pollutant != "pm25":
            raise HTTPException(status_code=400, detail="Only pm25 supported for now")

        # Verify station exists
        station = await fetch_station_info(db, station_id)
        if station is None:
            raise HTTPException(status_code=404, detail="Station not found")

        # Default window: last 365 days
        if to is None:
            to = datetime.now(timezone.utc)
        if from_ is None:
            from_ = to - timedelta(days=365)

        tz = await get_station_timezone(db, station_id)

        overall = await fetch_overall_diurnal(db, station_id, tz, from_, to)

        by_weekday_weekend = None
        if include_weekday_weekend:
            by_weekday_weekend = await fetch_weekday_weekend_diurnal(db, station_id, tz, from_, to)

        by_season = None
        if include_season:
            by_season = await fetch_season_diurnal(db, station_id, tz, from_, to)

        return DiurnalResponse(
            station_id=station_id,
            pollutant=pollutant,
            timezone=tz,
            window=DiurnalWindow(**{"from": from_, "to": to}),
            overall=overall,
            by_weekday_weekend=by_weekday_weekend,
            by_season=by_season,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting station diurnal for {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


async def detect_day_level_episodes(
    db: AsyncSession,
    station_id: str,
    tz: str,
    start: datetime,
    end: datetime,
    threshold: float,
    limit: int = 10,
) -> List[EpisodeDay]:
    """Detect day-level episodes using sa_daily_station aggregates"""
    
    q = text("""
        SELECT
          day_utc,
          (day_utc AT TIME ZONE 'UTC' AT TIME ZONE :tz)::date AS day_local,
          pm25_mean,
          hours_total
        FROM sa_daily_station
        WHERE station_id = :station_id
          AND day_utc >= :start
          AND day_utc < :end
          AND pm25_mean > :threshold
          AND hours_total >= 12  -- Require at least 12 hours of data
        ORDER BY pm25_mean DESC
        LIMIT :limit
    """)

    result = await db.execute(q, {
        "station_id": station_id,
        "tz": tz,
        "start": start,
        "end": end,
        "threshold": threshold,
        "limit": limit,
    })

    episode_days = []
    for row in result.mappings():
        # Calculate severity score: normalized by threshold with max cap at 300
        severity_score = min(1.0, (row["pm25_mean"] - threshold) / (300 - threshold))
        
        # Estimate hours above threshold (simplified heuristic - assume ~80% of hours for severe days)
        hours_above = min(24, int(row["hours_total"] * 0.8))
        
        episode_days.append(EpisodeDay(
            date=row["day_local"].strftime("%Y-%m-%d"),
            mean_value=row["pm25_mean"],
            max_value=row["pm25_mean"] * 1.3,  # Estimate max as ~30% higher than mean
            hours_above_threshold=hours_above,
            severity_score=severity_score,
        ))

    return episode_days


async def detect_hour_level_episodes(
    db: AsyncSession,
    station_id: str,
    tz: str,
    start: datetime,
    end: datetime,
    threshold: float,
    limit: int = 10,
    min_duration_hours: int = 3,
) -> List[Episode]:
    """Detect hour-level episodes by finding consecutive hours above threshold"""
    
    # Get all hourly readings above threshold
    q = text("""
        SELECT
          ts_utc,
          ts_utc AT TIME ZONE :tz AS ts_local,
          pm25
        FROM readings
        WHERE scope_type = 'station'
          AND scope_key = :station_id
          AND ts_utc >= :start
          AND ts_utc < :end
          AND pm25 > :threshold
          -- qc_state filter removed: column not populated yet
        ORDER BY ts_utc
    """)

    result = await db.execute(q, {
        "station_id": station_id,
        "tz": tz,
        "start": start,
        "end": end,
        "threshold": threshold,
    })

    readings = list(result.mappings())
    if not readings:
        return []

    # Group consecutive hours into episodes
    episodes = []
    current_episode_readings = []
    
    for i, reading in enumerate(readings):
        # Start new episode or continue current one
        if not current_episode_readings:
            current_episode_readings = [reading]
        else:
            # Check if this reading is consecutive (within 2 hours of last reading)
            last_ts = current_episode_readings[-1]["ts_utc"]
            current_ts = reading["ts_utc"]
            time_gap = (current_ts - last_ts).total_seconds() / 3600
            
            if time_gap <= 2.0:  # Allow 1-hour gap
                current_episode_readings.append(reading)
            else:
                # End current episode if it meets minimum duration
                if len(current_episode_readings) >= min_duration_hours:
                    episodes.append(current_episode_readings)
                # Start new episode
                current_episode_readings = [reading]
    
    # Handle last episode
    if len(current_episode_readings) >= min_duration_hours:
        episodes.append(current_episode_readings)
    
    # Convert to Episode objects and sort by severity
    episode_objects = []
    for episode_readings in episodes:
        start_reading = episode_readings[0]
        end_reading = episode_readings[-1]
        
        # Calculate episode stats
        values = [r["pm25"] for r in episode_readings]
        peak_value = max(values)
        mean_value = sum(values) / len(values)
        peak_reading = max(episode_readings, key=lambda r: r["pm25"])
        
        # Calculate severity score
        severity_score = min(1.0, (mean_value - threshold) / (300 - threshold))
        
        # Create hour objects
        hours = []
        for reading in episode_readings:
            hour_severity = min(1.0, (reading["pm25"] - threshold) / (300 - threshold))
            hours.append(EpisodeHour(
                datetime_local=reading["ts_local"],
                value=reading["pm25"],
                threshold=threshold,
                severity_score=hour_severity,
            ))
        
        episode_objects.append(Episode(
            start_datetime_local=start_reading["ts_local"],
            end_datetime_local=end_reading["ts_local"],
            duration_hours=len(episode_readings),
            peak_value=peak_value,
            peak_datetime_local=peak_reading["ts_local"],
            mean_value=mean_value,
            severity_score=severity_score,
            hours=hours,
        ))
    
    # Sort by severity and limit
    episode_objects.sort(key=lambda e: e.severity_score, reverse=True)
    return episode_objects[:limit]


@router.get("/{station_id}/episodes", response_model=EpisodesResponse)
async def get_station_episodes(
    station_id: str,
    from_: Optional[datetime] = Query(None, alias="from", description="Start of analysis window"),
    to: Optional[datetime] = Query(None, description="End of analysis window"),
    pollutant: str = Query("pm25", description="Pollutant to analyze"),
    level: Literal["day", "hour"] = Query("hour", description="Detection level: day or hour"),
    limit: int = Query(10, description="Maximum number of episodes to return"),
    threshold: Optional[float] = Query(None, description="Custom threshold (defaults to WHO 24h guideline)"),
    db: AsyncSession = Depends(get_database),
):
    """
    Detect pollution episodes and anomalies
    
    Returns episodes of elevated pollution including:
    - Top episode days ranked by severity
    - Detailed hourly episodes with start/end times
    - Peak values and duration analysis
    - Severity scoring for prioritization
    
    **Detection Logic:**
    - **Day-level**: Uses daily aggregates from sa_daily_station
    - **Hour-level**: Groups consecutive hours above threshold into episodes
    - **Severity**: Normalized score based on exceedance above threshold
    
    **Parameters:**
    - **station_id**: Station identifier (16-character hash)
    - **from**: Start of analysis window (defaults to 30 days ago)
    - **to**: End of analysis window (defaults to now)
    - **pollutant**: Pollutant to analyze (currently only pm25 supported)
    - **level**: Detection granularity (day or hour)
    - **limit**: Maximum episodes to return (default: 10)
    - **threshold**: Custom threshold in µg/m³ (defaults to WHO 24h: 15µg/m³)
    
    **Use cases:**
    - "Show me the worst smoke/dust episodes this winter"
    - "When was the station last severely impacted?"
    - "Identify multi-day pollution events"
    - "Find hourly-resolution episode patterns"
    """
    try:
        if pollutant != "pm25":
            raise HTTPException(status_code=400, detail="Only pm25 supported for now")

        # Verify station exists
        station = await fetch_station_info(db, station_id)
        if station is None:
            raise HTTPException(status_code=404, detail="Station not found")

        # Default window: last 30 days
        if to is None:
            to = datetime.now(timezone.utc)
        if from_ is None:
            from_ = to - timedelta(days=30)

        # Default threshold: WHO 24h guideline
        if threshold is None:
            threshold = WHO_24H_PM25  # 15.0 µg/m³

        tz = await get_station_timezone(db, station_id)

        # Detect episodes based on level
        if level == "day":
            top_days = await detect_day_level_episodes(db, station_id, tz, from_, to, threshold, limit)
            episodes = []  # Day-level doesn't provide hourly episodes
        else:  # hour
            episodes = await detect_hour_level_episodes(db, station_id, tz, from_, to, threshold, limit)
            # For hour-level, also get day summaries for top days
            top_days = await detect_day_level_episodes(db, station_id, tz, from_, to, threshold, 5)

        # Calculate totals
        total_episodes = len(episodes)
        total_episode_hours = sum(e.duration_hours for e in episodes)

        return EpisodesResponse(
            station_id=station_id,
            pollutant=pollutant,
            level=level,
            threshold=threshold,
            window=TimeWindow(**{"from": from_, "to": to}),
            top_days=top_days,
            episodes=episodes,
            total_episodes=total_episodes,
            total_episode_hours=total_episode_hours,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error detecting episodes for station {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# =====================================================================================
# BAM QC/QA status — live device health + plausibility verdict for the /bam monitor page
# =====================================================================================

# Spatial cross-check: flag if BAM diverges strongly from nearby stations.
QC_NEIGHBOR_RADIUS_M = 40000
QC_SPATIAL_MIN_NEIGHBORS = 2
QC_SPATIAL_RATIO = 3.0        # BAM outside [median/3, median*3] ...
QC_SPATIAL_ABS_MIN = 20.0     # ... AND absolute gap > 20 µg/m³ → divergent
# Stuck-sensor: near-zero variance over a recent window.
QC_STUCK_WINDOW_MIN = 30
QC_STUCK_MIN_SAMPLES = 30
QC_STUCK_STD_EPS = 0.05


def _verdict_from_checks(checks: List[dict]) -> dict:
    statuses = [c["status"] for c in checks]
    fails = [c for c in checks if c["status"] == "fail"]
    warns = [c for c in checks if c["status"] == "warn"]
    if fails:
        level = "RED"
    elif warns:
        level = "YELLOW"
    else:
        level = "GREEN"
    if level == "GREEN":
        headline = "BAM is healthy — readings are plausible and reporting normally."
    else:
        problems = ", ".join(c["label"].lower() for c in (fails + warns))
        lead = "BAM has a problem" if fails else "BAM looks mostly OK, watch"
        headline = f"{lead}: {problems}."
    return {"level": level, "headline": headline,
            "issues": [c["key"] for c in (fails + warns)]}


@router.get("/{station_id}/qc-status")
async def get_station_qc_status(
    station_id: str,
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_database),
):
    """Live QC/QA verdict for a station (built for the BAM monitor page).

    Always returns the station's true state (it does NOT hide flagged data the way the
    public map does) so faults are visible. Computed on-demand via bucketed SQL — never
    pulls the raw 1/sec rows.
    """
    try:
        info = await fetch_station_info(db, station_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Station not found")

        # --- latest reading (current state) ---
        latest = (await db.execute(text("""
            SELECT ts_utc, pm25, aqi_us, temp_c, humidity, pressure_hpa,
                   wind_speed_ms, wind_dir_deg, qc_state, qc_flags,
                   (raw->>'flow')::float AS flow,
                   EXTRACT(EPOCH FROM (NOW() - ts_utc)) AS age_s
            FROM readings
            WHERE scope_type='station' AND scope_key=:sid
            ORDER BY ts_utc DESC
            LIMIT 1
        """), {"sid": station_id})).mappings().first()

        # --- window aggregates ---
        agg = (await db.execute(text("""
            SELECT
              COUNT(*) AS n,
              COUNT(*) FILTER (WHERE qc_state='INVALID') AS n_invalid,
              COUNT(*) FILTER (WHERE qc_state='SUSPECT') AS n_suspect,
              COUNT(*) FILTER (WHERE qc_state IS NULL OR qc_state='OK') AS n_ok,
              AVG(pm25)  FILTER (WHERE qc_state IS NULL OR qc_state='OK') AS pm25_avg,
              MAX(pm25)  FILTER (WHERE qc_state IS NULL OR qc_state='OK') AS pm25_max,
              COUNT(*) FILTER (WHERE humidity > :high_rh) AS n_high_rh,
              COUNT(*) FILTER (WHERE (raw->>'flow') IS NOT NULL) AS n_flow,
              COUNT(*) FILTER (WHERE (raw->>'flow') IS NOT NULL
                     AND abs((raw->>'flow')::float - :flow_t)/:flow_t <= :flow_tol) AS n_flow_ok,
              AVG((raw->>'flow')::float) AS flow_avg,
              STDDEV_POP((raw->>'flow')::float) AS flow_std,
              COUNT(DISTINCT date_trunc('minute', ts_utc)) AS minutes_with_data,
              MIN(ts_utc) AS first_ts, MAX(ts_utc) AS last_ts
            FROM readings
            WHERE scope_type='station' AND scope_key=:sid
              AND ts_utc > NOW() - (:hours * interval '1 hour')
        """), {"sid": station_id, "hours": hours, "high_rh": HIGH_RH_PCT,
               "flow_t": FLOW_TARGET_LPM, "flow_tol": FLOW_TOL_FRAC})).mappings().first()

        # --- recent continuity (last 60 min) — drives the Reporting verdict, so a brand-new
        # monitor with low 24h coverage isn't marked broken while it's actually reporting now ---
        recent = (await db.execute(text("""
            SELECT COUNT(DISTINCT date_trunc('minute', ts_utc)) AS minutes_with_data
            FROM readings
            WHERE scope_type='station' AND scope_key=:sid
              AND ts_utc > NOW() - interval '60 minutes'
        """), {"sid": station_id})).mappings().first()

        # --- stuck-sensor: variance over the recent window ---
        stuck_row = (await db.execute(text("""
            SELECT STDDEV_POP(pm25) AS sd, COUNT(*) AS n
            FROM readings
            WHERE scope_type='station' AND scope_key=:sid
              AND pm25 IS NOT NULL
              AND ts_utc > NOW() - (:mins * interval '1 minute')
        """), {"sid": station_id, "mins": QC_STUCK_WINDOW_MIN})).mappings().first()

        # --- spatial: BAM median vs nearby stations (last hour) ---
        spatial = (await db.execute(text("""
            WITH me AS (SELECT geom FROM stations WHERE station_id=:sid),
            neigh AS (
              SELECT DISTINCT ON (r.scope_key) r.scope_key, r.pm25
              FROM readings r
              JOIN stations s2 ON s2.station_id = r.scope_key
              JOIN providers p2 ON p2.id = s2.provider_id
              CROSS JOIN me
              WHERE r.scope_type='station'
                AND COALESCE(p2.code,'') != 'bam'
                AND s2.active = true
                AND r.pm25 IS NOT NULL
                AND (r.qc_state IS NULL OR r.qc_state NOT IN ('INVALID','SUSPECT'))
                AND r.ts_utc > NOW() - interval '6 hours'
                AND me.geom IS NOT NULL
                AND ST_DWithin(s2.geom, me.geom, :radius)
              ORDER BY r.scope_key, r.ts_utc DESC
            ),
            mine AS (
              SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY pm25) AS bam_median
              FROM readings
              WHERE scope_type='station' AND scope_key=:sid AND pm25 IS NOT NULL
                AND (qc_state IS NULL OR qc_state='OK')
                AND ts_utc > NOW() - interval '1 hour'
            )
            SELECT
              (SELECT COUNT(*) FROM neigh) AS n_neighbors,
              (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY pm25) FROM neigh) AS neighbor_median,
              (SELECT bam_median FROM mine) AS bam_median
        """), {"sid": station_id, "radius": QC_NEIGHBOR_RADIUS_M})).mappings().first()

        # --- hourly PM2.5 series for the trend (bucketed; avoids pulling 1/sec rows) ---
        series_rows = (await db.execute(text("""
            SELECT date_trunc('hour', ts_utc) AS hour_utc,
                   AVG(pm25) FILTER (WHERE qc_state IS NULL OR qc_state='OK') AS pm25,
                   COUNT(*) AS n
            FROM readings
            WHERE scope_type='station' AND scope_key=:sid
              AND ts_utc > NOW() - (:hours * interval '1 hour')
            GROUP BY 1 ORDER BY 1
        """), {"sid": station_id, "hours": hours})).mappings().all()
        series = [
            {"hour_utc": r["hour_utc"].isoformat(),
             "pm25": round(float(r["pm25"]), 1) if r["pm25"] is not None else None}
            for r in series_rows
        ]

        # ---------- assemble ----------
        n = int(agg["n"] or 0)
        age_s = float(latest["age_s"]) if latest and latest["age_s"] is not None else None
        if age_s is None:
            cur_status = "offline"
        elif age_s < 120:
            cur_status = "online"
        elif age_s < 900:
            cur_status = "delayed"
        else:
            cur_status = "offline"

        total_minutes = hours * 60
        coverage_pct = round(100.0 * (agg["minutes_with_data"] or 0) / total_minutes, 1) if total_minutes else 0.0
        invalid_rate = round(100.0 * (agg["n_invalid"] or 0) / n, 1) if n else 0.0
        suspect_rate = round(100.0 * (agg["n_suspect"] or 0) / n, 1) if n else 0.0
        high_rh_rate = round(100.0 * (agg["n_high_rh"] or 0) / n, 1) if n else 0.0
        flow_ok_rate = round(100.0 * (agg["n_flow_ok"] or 0) / agg["n_flow"], 1) if (agg["n_flow"] or 0) else None

        # recent (last-hour) coverage drives the reporting verdict
        recent_cov = round(100.0 * (recent["minutes_with_data"] or 0) / 60.0, 1) if recent else 0.0

        checks: List[dict] = []

        # Reporting / continuity — judged on "is it reporting NOW", not 24h history.
        if age_s is None or cur_status == "offline" or recent_cov < 50:
            st = "fail"
        elif cur_status == "delayed" or recent_cov < 90:
            st = "warn"
        else:
            st = "pass"
        checks.append({"key": "reporting", "label": "Reporting", "status": st,
                       "value": recent_cov,
                       "detail": (f"{recent_cov}% minute-coverage in last hour; last reading "
                                  f"{int(age_s)}s ago ({coverage_pct}% over {hours}h)"
                                  if age_s is not None else "no data received")})

        # Flow — INFORMATIONAL only (correct target/units unconfirmed; never fails the verdict).
        flow_avg = round(float(agg["flow_avg"]), 2) if agg["flow_avg"] is not None else None
        flow_std = round(float(agg["flow_std"]), 2) if agg["flow_std"] is not None else None
        if flow_avg is None:
            flow_detail = "no flow reported"
        else:
            flow_detail = f"avg {flow_avg} L/min" + (f" (σ={flow_std})" if flow_std is not None else "")
        checks.append({"key": "flow", "label": "Flow (info)", "status": "pass",
                       "value": flow_avg, "detail": flow_detail})

        # Stuck sensor
        sd = stuck_row["sd"] if stuck_row else None
        sn = int(stuck_row["n"]) if stuck_row and stuck_row["n"] is not None else 0
        stuck = sd is not None and sn >= QC_STUCK_MIN_SAMPLES and float(sd) < QC_STUCK_STD_EPS
        checks.append({"key": "stuck", "label": "Stuck sensor", "status": "fail" if stuck else "pass",
                       "value": float(sd) if sd is not None else None,
                       "detail": (f"PM2.5 variance ~0 over last {QC_STUCK_WINDOW_MIN}min ({sn} samples)"
                                  if stuck else f"PM2.5 varying normally (σ={float(sd):.2f})" if sd is not None
                                  else "not enough recent data")})

        # Invalid rate
        if invalid_rate > 20:
            st = "fail"
        elif invalid_rate > 5:
            st = "warn"
        else:
            st = "pass"
        checks.append({"key": "invalid_rate", "label": "Invalid readings", "status": st,
                       "value": invalid_rate, "detail": f"{invalid_rate}% of last {hours}h flagged INVALID"})

        # Spatial agreement
        n_neighbors = int(spatial["n_neighbors"] or 0) if spatial else 0
        neighbor_median = float(spatial["neighbor_median"]) if spatial and spatial["neighbor_median"] is not None else None
        bam_median = float(spatial["bam_median"]) if spatial and spatial["bam_median"] is not None else None
        spatial_status = "pass"; spatial_detail = "consistent with nearby stations"
        ratio = None
        if n_neighbors < QC_SPATIAL_MIN_NEIGHBORS or neighbor_median is None or bam_median is None:
            spatial_status = "warn"; spatial_detail = "no nearby stations to compare"
        else:
            ratio = round(bam_median / neighbor_median, 2) if neighbor_median else None
            diverged = (
                (bam_median > QC_SPATIAL_RATIO * neighbor_median or
                 bam_median < neighbor_median / QC_SPATIAL_RATIO)
                and abs(bam_median - neighbor_median) > QC_SPATIAL_ABS_MIN
            )
            if diverged:
                spatial_status = "fail"
                spatial_detail = (f"BAM ~{bam_median:.0f} vs nearby ~{neighbor_median:.0f} µg/m³ "
                                  f"({n_neighbors} stations)")
            else:
                spatial_detail = (f"BAM ~{bam_median:.0f} vs nearby ~{neighbor_median:.0f} µg/m³ "
                                  f"({n_neighbors} stations)")
        checks.append({"key": "spatial", "label": "Spatial agreement", "status": spatial_status,
                       "value": ratio, "detail": spatial_detail})

        # High humidity — informational only; never affects the verdict (common in Karachi).
        checks.append({"key": "high_rh", "label": "Humidity context", "status": "pass",
                       "value": high_rh_rate,
                       "detail": f"{high_rh_rate}% of readings above {int(HIGH_RH_PCT)}% RH"
                                 + (" — PM may over-read" if high_rh_rate > 50 else "")})

        latest_flags = list(latest["qc_flags"]) if latest and latest["qc_flags"] else []
        current = None
        if latest:
            current = {
                "ts_utc": latest["ts_utc"].isoformat() if latest["ts_utc"] else None,
                "age_seconds": int(age_s) if age_s is not None else None,
                "status": cur_status,
                "pm25": float(latest["pm25"]) if latest["pm25"] is not None else None,
                "aqi_us": int(latest["aqi_us"]) if latest["aqi_us"] is not None else None,
                "temp_c": float(latest["temp_c"]) if latest["temp_c"] is not None else None,
                "humidity": float(latest["humidity"]) if latest["humidity"] is not None else None,
                "pressure_hpa": float(latest["pressure_hpa"]) if latest["pressure_hpa"] is not None else None,
                "wind_speed_ms": float(latest["wind_speed_ms"]) if latest["wind_speed_ms"] is not None else None,
                "wind_dir_deg": int(latest["wind_dir_deg"]) if latest["wind_dir_deg"] is not None else None,
                "flow": float(latest["flow"]) if latest["flow"] is not None else None,
                "qc_state": latest["qc_state"],
                "qc_flags": latest_flags,
            }

        return {
            "station_id": station_id,
            "name": info.name,
            "provider": info.provider,
            "lat": info.lat,
            "lon": info.lon,
            "window_hours": hours,
            "current": current,
            "stats24h": {
                "n": n,
                "pm25_avg": round(float(agg["pm25_avg"]), 1) if agg["pm25_avg"] is not None else None,
                "pm25_max": round(float(agg["pm25_max"]), 1) if agg["pm25_max"] is not None else None,
                "coverage_pct": coverage_pct,
                "invalid_rate_pct": invalid_rate,
                "suspect_rate_pct": suspect_rate,
                "high_rh_rate_pct": high_rh_rate,
                "flow_ok_rate_pct": flow_ok_rate,
                "flow_avg": round(float(agg["flow_avg"]), 2) if agg["flow_avg"] is not None else None,
            },
            "neighbors": {"n": n_neighbors, "median": neighbor_median, "bam_median": bam_median},
            "series": series,
            "checks": checks,
            "verdict": _verdict_from_checks(checks),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing QC status for {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{station_id}/timeseries")
async def get_station_timeseries(
    station_id: str,
    minutes: int = Query(60, ge=1, le=1440),
    db: AsyncSession = Depends(get_database),
):
    """Raw per-reading time series for the BAM monitor page.

    Returns full ~1/sec resolution for short windows; auto-downsamples (time_bucket avg)
    when the window would exceed MAX_POINTS so the payload/chart stays sane. INVALID pm25
    (sentinels) is nulled so it doesn't distort the line; other channels pass through.
    """
    MAX_POINTS = 3000
    est_points = minutes * 60
    downsample = est_points > MAX_POINTS
    try:
        if downsample:
            import math as _math
            bucket_s = max(1, _math.ceil(est_points / MAX_POINTS))
            rows = (await db.execute(text("""
                SELECT time_bucket(make_interval(secs => :bs), ts_utc) AS ts,
                       AVG(pm25) FILTER (WHERE qc_state IS NULL OR qc_state <> 'INVALID') AS pm25,
                       AVG((raw->>'flow')::float) AS flow,
                       AVG(humidity) AS humidity,
                       AVG(temp_c) AS temp,
                       AVG(pressure_hpa) AS pressure,
                       AVG(wind_speed_ms) AS wind
                FROM readings
                WHERE scope_type='station' AND scope_key=:sid
                  AND ts_utc > NOW() - (:minutes * interval '1 minute')
                GROUP BY 1 ORDER BY 1
            """), {"sid": station_id, "minutes": minutes, "bs": bucket_s})).mappings().all()
        else:
            bucket_s = 1
            rows = (await db.execute(text("""
                SELECT ts_utc AS ts,
                       CASE WHEN qc_state = 'INVALID' THEN NULL ELSE pm25 END AS pm25,
                       (raw->>'flow')::float AS flow,
                       humidity, temp_c AS temp, pressure_hpa AS pressure,
                       wind_speed_ms AS wind
                FROM readings
                WHERE scope_type='station' AND scope_key=:sid
                  AND ts_utc > NOW() - (:minutes * interval '1 minute')
                ORDER BY ts_utc ASC
            """), {"sid": station_id, "minutes": minutes})).mappings().all()

        def num(v, nd=1):
            return round(float(v), nd) if v is not None else None

        points = [{
            "ts": r["ts"].isoformat(),
            "pm25": num(r["pm25"]),
            "flow": num(r["flow"], 2),
            "humidity": num(r["humidity"]),
            "temp": num(r["temp"]),
            "pressure": num(r["pressure"]),
            "wind": num(r["wind"], 2),
        } for r in rows]

        return {
            "station_id": station_id,
            "minutes": minutes,
            "downsampled": downsample,
            "bucket_seconds": bucket_s,
            "count": len(points),
            "points": points,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing timeseries for {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/{station_id}/live")
async def get_station_live(
    station_id: str,
    limit: int = Query(30, ge=1, le=200),
    db: AsyncSession = Depends(get_database),
):
    """Most-recent raw readings for the BAM monitor's live feed (newest first).

    Returns each reading with its full `raw` jsonb payload (what BAM actually sent),
    so the page can show the raw JSON ticking in near-real-time.
    """
    try:
        rows = (await db.execute(text("""
            SELECT ts_utc, pm25, aqi_us, temp_c, humidity, pressure_hpa,
                   wind_speed_ms, wind_dir_deg, qc_state, qc_flags, raw, ingested_at
            FROM readings
            WHERE scope_type='station' AND scope_key=:sid
            ORDER BY ts_utc DESC
            LIMIT :limit
        """), {"sid": station_id, "limit": limit})).mappings().all()

        readings = [{
            "ts_utc": r["ts_utc"].isoformat() if r["ts_utc"] else None,
            "pm25": float(r["pm25"]) if r["pm25"] is not None else None,
            "aqi_us": int(r["aqi_us"]) if r["aqi_us"] is not None else None,
            "temp_c": float(r["temp_c"]) if r["temp_c"] is not None else None,
            "humidity": float(r["humidity"]) if r["humidity"] is not None else None,
            "pressure_hpa": float(r["pressure_hpa"]) if r["pressure_hpa"] is not None else None,
            "wind_speed_ms": float(r["wind_speed_ms"]) if r["wind_speed_ms"] is not None else None,
            "wind_dir_deg": int(r["wind_dir_deg"]) if r["wind_dir_deg"] is not None else None,
            "qc_state": r["qc_state"],
            "qc_flags": list(r["qc_flags"]) if r["qc_flags"] else [],
            "raw": r["raw"],
            "ingested_at": r["ingested_at"].isoformat() if r["ingested_at"] else None,
        } for r in rows]

        return {"station_id": station_id, "count": len(readings), "readings": readings}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching live readings for {station_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
