#!/usr/bin/env python3
"""
Evaluate model bias over the last 60 days.

Compares backbone and enhanced (support_aware) model predictions
against observed station PM2.5 values.
"""

import asyncio
import os
import statistics
import sys
from pathlib import Path

import aiohttp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://hawanama-152782825429.asia-south1.run.app"
ENV_FILE = Path(__file__).parent / ".env.local"

# ~30 well-distributed sample points across Pakistan
# Covering major population centres and geographic regions
SAMPLE_POINTS = [
    # Punjab
    (31.5204, 74.3587),   # Lahore
    (31.4187, 73.0791),   # Faisalabad
    (30.1575, 71.5249),   # Multan
    (32.1617, 74.1883),   # Gujranwala
    (30.6682, 73.1114),   # Sahiwal
    (33.5970, 73.0479),   # Rawalpindi / Islamabad
    (32.2946, 72.3566),   # Sargodha
    (29.3956, 71.6836),   # Bahawalpur
    (28.4212, 70.2989),   # Rahim Yar Khan
    # Sindh
    (24.8607, 67.0011),   # Karachi
    (25.3960, 68.3578),   # Hyderabad
    (27.5600, 68.2200),   # Larkana
    (26.2461, 68.3903),   # Nawabshah
    (27.7244, 68.8228),   # Sukkur
    # KPK
    (34.0151, 71.5249),   # Peshawar
    (34.7717, 72.3600),   # Swat (Mingora)
    (35.9208, 74.3080),   # Gilgit
    (33.9960, 71.9734),   # Mardan
    (34.2081, 72.0408),   # Swabi
    # Balochistan
    (30.1798, 66.9750),   # Quetta
    (25.8880, 66.6200),   # Gwadar
    (28.3800, 68.3500),   # Jacobabad (border area)
    (29.0300, 66.6300),   # Kalat
    (26.4500, 63.0000),   # Turbat
    # Azad Kashmir / Northern
    (34.3700, 73.4700),   # Muzaffarabad
    (33.7715, 72.7511),   # Abbottabad
    (35.3306, 75.5397),   # Skardu
    # Central / Southern Punjab extras
    (31.9700, 72.3300),   # Khushab
    (30.9600, 70.9400),   # DG Khan
    (32.9340, 73.7350),   # Jhelum
]

MAX_CONCURRENT = 10  # limit concurrent HTTP requests


def read_token() -> str:
    """Read the API token from the .env.local file."""
    if not ENV_FILE.exists():
        print(f"ERROR: {ENV_FILE} not found", file=sys.stderr)
        sys.exit(1)

    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("NEXT_PUBLIC_TASKS_API_SECRET="):
            return line.split("=", 1)[1]

    print("ERROR: NEXT_PUBLIC_TASKS_API_SECRET not found in .env.local", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

async def fetch_dates(session: aiohttp.ClientSession) -> list[str]:
    """Fetch available dates from the API."""
    url = f"{BASE_URL}/api/v1/ops/pipeline/tiles/dates?limit=60"
    async with session.get(url) as resp:
        resp.raise_for_status()
        data = await resp.json()
        # The endpoint may return {"dates": [...]} or a plain list
        if isinstance(data, dict) and "dates" in data:
            return data["dates"]
        if isinstance(data, list):
            return data
        raise ValueError(f"Unexpected dates response shape: {type(data)}")


async def fetch_backbone_mean(session: aiohttp.ClientSession, date: str) -> float | None:
    """Fetch backbone prediction mean for a given date."""
    url = f"{BASE_URL}/api/v1/ops/pipeline/predictions/{date}"
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            return data.get("stats", {}).get("mean")
    except Exception:
        return None


async def fetch_station_obs(session: aiohttp.ClientSession, date: str) -> float | None:
    """Fetch mean observed PM2.5 from stations for a given date."""
    url = f"{BASE_URL}/api/v1/ops/pipeline/stations/daily/{date}?country=Pakistan"
    try:
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            stations = data.get("stations", [])
            pm25_vals = [s["pm25"] for s in stations if s.get("pm25") is not None]
            if not pm25_vals:
                return None
            return statistics.mean(pm25_vals)
    except Exception:
        return None


async def fetch_point_value(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    date: str,
    lat: float,
    lon: float,
) -> float | None:
    """Query one point from the enhanced (support_aware) TIF layer."""
    url = (
        f"{BASE_URL}/api/v1/ops/pipeline/tiles/{date}/point"
        f"?lat={lat}&lon={lon}&model=support_aware"
    )
    async with sem:
        try:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                # Try common response shapes
                if isinstance(data, (int, float)):
                    return float(data)
                if isinstance(data, dict):
                    for key in ("value", "pm25", "pm2_5", "result"):
                        if key in data and data[key] is not None:
                            return float(data[key])
                return None
        except Exception:
            return None


async def fetch_enhanced_mean(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    date: str,
) -> float | None:
    """Sample ~30 points and return the mean enhanced-model PM2.5."""
    tasks = [
        fetch_point_value(session, sem, date, lat, lon)
        for lat, lon in SAMPLE_POINTS
    ]
    results = await asyncio.gather(*tasks)
    valid = [v for v in results if v is not None]
    if not valid:
        return None
    return statistics.mean(valid)


# ---------------------------------------------------------------------------
# Per-date orchestrator
# ---------------------------------------------------------------------------

async def process_date(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    date: str,
) -> dict | None:
    """Fetch all three metrics for one date concurrently."""
    obs_task = fetch_station_obs(session, date)
    backbone_task = fetch_backbone_mean(session, date)
    enhanced_task = fetch_enhanced_mean(session, sem, date)

    obs_mean, backbone_mean, enhanced_mean = await asyncio.gather(
        obs_task, backbone_task, enhanced_task
    )

    # Need at least observation to compute bias
    if obs_mean is None:
        return None

    row = {
        "date": date,
        "obs_mean": obs_mean,
        "backbone_mean": backbone_mean,
        "backbone_bias": (backbone_mean - obs_mean) if backbone_mean is not None else None,
        "enhanced_mean": enhanced_mean,
        "enhanced_bias": (enhanced_mean - obs_mean) if enhanced_mean is not None else None,
    }
    return row


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def fmt(val: float | None, width: int = 10) -> str:
    """Format a float or show 'N/A'."""
    if val is None:
        return "N/A".rjust(width)
    return f"{val:>{width}.2f}"


async def main() -> None:
    token = read_token()
    headers = {"Authorization": f"Bearer {token}"}
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        # Step 1: get dates
        print("Fetching available dates...")
        dates = await fetch_dates(session)
        print(f"  → {len(dates)} dates retrieved\n")

        # Step 2: process all dates (3 dates concurrently at a time to be polite)
        date_sem = asyncio.Semaphore(3)

        async def guarded(d: str):
            async with date_sem:
                return await process_date(session, sem, d)

        tasks = [guarded(d) for d in dates]
        results_raw = await asyncio.gather(*tasks)

    results = [r for r in results_raw if r is not None]
    results.sort(key=lambda r: r["date"])

    if not results:
        print("No valid data retrieved.")
        return

    # Print table
    header = (
        f"{'Date':<12} {'Obs Mean':>10} {'BB Mean':>10} {'BB Bias':>10} "
        f"{'Enh Mean':>10} {'Enh Bias':>10}"
    )
    print(header)
    print("-" * len(header))

    backbone_biases: list[float] = []
    enhanced_biases: list[float] = []

    for r in results:
        bb_bias = r["backbone_bias"]
        en_bias = r["enhanced_bias"]
        if bb_bias is not None:
            backbone_biases.append(bb_bias)
        if en_bias is not None:
            enhanced_biases.append(en_bias)

        print(
            f"{r['date']:<12} "
            f"{fmt(r['obs_mean'])} "
            f"{fmt(r['backbone_mean'])} "
            f"{fmt(bb_bias)} "
            f"{fmt(r['enhanced_mean'])} "
            f"{fmt(en_bias)}"
        )

    # Summary
    print()
    print("=" * len(header))
    print("SUMMARY")
    print("=" * len(header))
    print(f"  Days with data:       {len(results)}")

    if backbone_biases:
        print(f"  Backbone mean bias:   {statistics.mean(backbone_biases):+.2f}")
        print(f"  Backbone median bias: {statistics.median(backbone_biases):+.2f}")
        print(f"  Backbone MAE:         {statistics.mean(abs(b) for b in backbone_biases):.2f}")
    else:
        print("  Backbone: no data")

    if enhanced_biases:
        print(f"  Enhanced mean bias:   {statistics.mean(enhanced_biases):+.2f}")
        print(f"  Enhanced median bias: {statistics.median(enhanced_biases):+.2f}")
        print(f"  Enhanced MAE:         {statistics.mean(abs(b) for b in enhanced_biases):.2f}")
    else:
        print("  Enhanced: no data")


if __name__ == "__main__":
    asyncio.run(main())
