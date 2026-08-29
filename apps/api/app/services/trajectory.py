"""
On-demand HYSPLIT back-trajectory service.

Triggers trajectory runs only for flagged cases (high PM, medium/high
transport or fire scores) and caches results in GCS. Designed as a fast
worker — HYSPLIT trajectory integration takes seconds when met files are
staged.

Trigger conditions (any one):
  - PM2.5 D+1 median > 75 µg/m³ AND transport score >= 40
  - Fire score >= 40
  - Analyst explicitly asks "is this transported?"
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Trigger thresholds
TRIGGER_PM25_MIN = 75.0
TRIGGER_TRANSPORT_SCORE_MIN = 40
TRIGGER_FIRE_SCORE_MIN = 40


def should_trigger_trajectory(driver_entry: dict) -> bool:
    """Decide whether a city warrants a back-trajectory run.

    Parameters
    ----------
    driver_entry : dict
        A single city entry from driver_summaries with drivers list.

    Returns
    -------
    bool — True if trajectory analysis would add value.
    """
    pm25 = driver_entry.get("pm25_d1_median") or 0
    drivers = {d["driver"]: d["score"] for d in driver_entry.get("drivers", [])}

    transport_score = drivers.get("transport", 0)
    fire_score = drivers.get("fire", 0)

    # High PM + meaningful transport signal
    if pm25 > TRIGGER_PM25_MIN and transport_score >= TRIGGER_TRANSPORT_SCORE_MIN:
        return True

    # Significant fire signal (may want trajectory to confirm upwind path)
    if fire_score >= TRIGGER_FIRE_SCORE_MIN:
        return True

    return False


def load_trajectory_from_gcs(
    city_name: str,
    date_str: str,
) -> dict | None:
    """Load cached trajectory summary from GCS.

    Trajectory results are stored as:
      forecasts/trajectories/traj_{city}_{YYYYMMDD}.json
    """
    from app.routers.analyst_desk import _gcs_read_json

    # Normalise city name for filename
    city_key = city_name.lower().replace(" ", "_").replace("'", "")
    ds = date_str.replace("-", "")
    blob_path = f"forecasts/trajectories/traj_{city_key}_{ds}.json"

    try:
        return _gcs_read_json(blob_path)
    except Exception:
        return None


def save_trajectory_to_gcs(
    summary: dict,
    city_name: str,
    date_str: str,
) -> None:
    """Save trajectory summary to GCS for caching."""
    try:
        from google.cloud import storage as gcs_storage
        from app.core.config import settings

        bucket_name = settings.OPS_FORECASTS_BUCKET or "paqi-forecasts-hawanama-data"
        city_key = city_name.lower().replace(" ", "_").replace("'", "")
        ds = date_str.replace("-", "")
        blob_path = f"forecasts/trajectories/traj_{city_key}_{ds}.json"

        client = gcs_storage.Client()
        blob = client.bucket(bucket_name).blob(blob_path)
        blob.upload_from_string(
            json.dumps(summary, indent=2),
            content_type="application/json",
        )
        logger.info(f"Trajectory saved to GCS: {blob_path}")
    except Exception as e:
        logger.warning(f"Trajectory GCS save failed: {e}")


def get_trajectory_for_city(
    city_name: str,
    date_str: str,
    driver_entry: dict | None = None,
    force: bool = False,
) -> dict | None:
    """Get trajectory summary for a city — from cache or on-demand run.

    Parameters
    ----------
    city_name : str
        City to analyse.
    date_str : str
        Forecast date (YYYY-MM-DD).
    driver_entry : dict, optional
        Driver attribution entry (used to decide whether to trigger).
    force : bool
        If True, skip trigger check and run trajectory regardless.

    Returns
    -------
    dict or None — trajectory summary, or None if not triggered/available.
    """
    # Check GCS cache first
    cached = load_trajectory_from_gcs(city_name, date_str)
    if cached and cached.get("status") == "ok":
        return cached

    # Check trigger conditions (unless forced)
    if not force and driver_entry:
        if not should_trigger_trajectory(driver_entry):
            return None

    # Attempt on-demand trajectory run
    # This requires HYSPLIT to be installed on the worker.
    # In production, this would call the HYSPLIT Cloud Run worker.
    # For now, return None if HYSPLIT is not available locally.
    try:
        from infrastructure.hysplit import run_back_trajectory, HYSPLIT_EXEC

        if not HYSPLIT_EXEC.exists():
            logger.debug("HYSPLIT not installed — trajectory unavailable")
            return None

        # Get city coordinates from driver entry or forecast data
        # (In production, this comes from the stations database)
        summary_data = driver_entry or {}
        # We need lat/lon — these would come from the forecast/stations data
        # For now, trajectory runs are only available when pre-computed
        logger.info(
            f"HYSPLIT trajectory would be triggered for {city_name} "
            f"but on-demand execution requires worker deployment"
        )
        return None

    except ImportError:
        # HYSPLIT infrastructure not available in API container
        return None


def enrich_drivers_with_trajectory(
    driver_attribution: list[dict],
    trajectory: dict | None,
) -> list[dict]:
    """Enrich driver scores with trajectory evidence.

    If a trajectory summary is available, adds trajectory-derived
    evidence to the transport and fire drivers.
    """
    if not trajectory or trajectory.get("status") != "ok":
        return driver_attribution

    enriched = []
    for drv in driver_attribution:
        drv_copy = dict(drv)
        evidence = list(drv_copy.get("evidence", []))
        sources = list(drv_copy.get("sources_used", []))

        if drv_copy["driver"] == "transport":
            corridor = trajectory.get("dominant_corridor", "unknown")
            consistent = trajectory.get("corridor_consistent", False)
            crossings = trajectory.get("pollution_crossings", [])

            evidence.append(
                f"72h back-trajectory: air mass from {corridor}"
                + (" (consistent across heights)" if consistent else " (variable with height)")
            )
            if crossings:
                cities = [c["city_name"] for c in crossings[:3]]
                evidence.append(f"Trajectory crossed polluted areas: {', '.join(cities)}")
            sources.append("hysplit_trajectory")

        elif drv_copy["driver"] == "fire":
            fire_ints = trajectory.get("fire_intersections", [])
            if fire_ints:
                n = len(fire_ints)
                ages = [abs(fi["age_hours"]) for fi in fire_ints]
                evidence.append(
                    f"Trajectory intersected {n} fire cluster(s) "
                    f"({min(ages):.0f}–{max(ages):.0f}h upwind)"
                )
                sources.append("hysplit_trajectory")

        drv_copy["evidence"] = evidence
        drv_copy["sources_used"] = list(dict.fromkeys(sources))  # dedupe preserving order
        enriched.append(drv_copy)

    return enriched
