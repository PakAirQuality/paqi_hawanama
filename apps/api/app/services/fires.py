"""Satellite fire detections (NASA FIRMS VIIRS) for the analyst desk.

What this module fixes relative to the first implementation:

* detections are keyed by their **acquisition day in Pakistan time** (acq_date + acq_time
  are UTC in FIRMS output; the night overpass around 20:00 UTC is already the next
  Pakistan calendar day), so a request for a Pakistan date returns that day's fires;
* two satellites (NOAA-20 and NOAA-21; Suomi NPP optional until its products stop on
  1 November 2026) through the FIRMS *area* API, west,south,east,north bbox;
* the last two days are refreshed on every run (a partial early-morning file is never
  frozen), zero-detection days are written as header-only files, and every day carries a
  ``.meta.json`` sidecar with the requested/observation period, per-source status and
  fetch time;
* readers get an explicit ``status`` (ok / empty / partial / stale / unavailable) instead
  of a silent fallback to an older day.

Files: ``hindcast/firms/firms_{YYYYMMDD}.csv`` (+ ``.meta.json``) in the forecasts bucket.
Older files written by the previous ingester are keyed by the UTC acquisition date and have
no sidecar; they are reported with ``day_basis='acq_utc'``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

PK_TZ = ZoneInfo("Asia/Karachi")
FIRMS_API_BASE = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
# South Asia bounding box (west,south,east,north): Pakistan plus neighbours for context
FIRMS_BBOX = "60,23,78,37"
SNPP_END = date(2026, 11, 1)  # NOAA ends Suomi NPP product delivery 2026-11-01 13:00 UTC
DEFAULT_SOURCES = ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
FIELDNAMES = ["latitude", "longitude", "frp", "confidence", "acq_date", "acq_time", "acq_datetime_utc", "satellite"]
LAYER_NAME = "Satellite fire detections"


def sources_for(day: date) -> List[str]:
    srcs = list(DEFAULT_SOURCES)
    if day < SNPP_END:
        srcs.append("VIIRS_SNPP_NRT")
    return srcs


def blob_paths(day: date) -> tuple[str, str]:
    ds = day.strftime("%Y%m%d")
    return f"hindcast/firms/firms_{ds}.csv", f"hindcast/firms/firms_{ds}.meta.json"


# ---------------------------------------------------------------- parsing

def acquisition_utc(acq_date: str, acq_time: str) -> Optional[datetime]:
    """FIRMS gives acq_date 'YYYY-MM-DD' and acq_time 'HHMM' (or 'HMM'), both UTC."""
    try:
        d = datetime.strptime(acq_date, "%Y-%m-%d")
        t = str(acq_time or "0").strip().zfill(4)
        return d.replace(hour=int(t[:2]), minute=int(t[2:]), tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_firms_csv(csv_text: str, satellite_hint: str = "") -> List[Dict[str, Any]]:
    """Rows from a FIRMS CSV (raw NASA or our simplified file), with acquisition times resolved."""
    rows: List[Dict[str, Any]] = []
    if not csv_text or "latitude" not in csv_text.split("\n", 1)[0]:
        return rows
    reader = csv.DictReader(io.StringIO(csv_text))
    for r in reader:
        try:
            lat = float(r["latitude"])
            lon = float(r["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        try:
            frp = round(float(r.get("frp") or 0), 1)
        except (ValueError, TypeError):
            frp = 0.0
        acq_date = (r.get("acq_date") or "").strip()
        acq_time = (r.get("acq_time") or "").strip()
        when = None
        if r.get("acq_datetime_utc"):
            try:
                when = datetime.fromisoformat(r["acq_datetime_utc"].replace("Z", "+00:00"))
            except ValueError:
                when = None
        if when is None:
            when = acquisition_utc(acq_date, acq_time) if acq_time else None
        rows.append({
            "latitude": lat,
            "longitude": lon,
            "frp": frp,
            "confidence": (r.get("confidence") or "").strip(),
            "acq_date": acq_date,
            "acq_time": acq_time,
            "acq_datetime_utc": when.isoformat().replace("+00:00", "Z") if when else "",
            "satellite": (r.get("satellite") or satellite_hint or "").strip(),
        })
    return rows


def pk_day_of(row: Dict[str, Any]) -> Optional[str]:
    """Pakistan calendar day of a detection; falls back to acq_date when no time is known."""
    if row.get("acq_datetime_utc"):
        try:
            return datetime.fromisoformat(row["acq_datetime_utc"].replace("Z", "+00:00")).astimezone(PK_TZ).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return row.get("acq_date") or None


def rows_to_csv(rows: List[Dict[str, Any]]) -> str:
    out = io.StringIO()
    w = csv.DictWriter(out, fieldnames=FIELDNAMES, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


# ---------------------------------------------------------------- ingestion

@dataclass
class SourceResult:
    source: str
    status: str                # ok | error
    rows: int = 0
    error: Optional[str] = None


@dataclass
class IngestOutcome:
    days: List[str] = field(default_factory=list)
    per_day: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sources: List[SourceResult] = field(default_factory=list)


async def fetch_source(http, key: str, source: str, days: int, start: date) -> SourceResult | tuple[SourceResult, str]:
    """One FIRMS area request. Returns (result, csv_text)."""
    url = f"{FIRMS_API_BASE}/{key}/{source}/{FIRMS_BBOX}/{days}/{start.strftime('%Y-%m-%d')}"
    try:
        resp = await http.get(url)
    except Exception as exc:  # network
        return SourceResult(source, "error", error=type(exc).__name__), ""
    if resp.status_code != 200:
        return SourceResult(source, "error", error=f"HTTP {resp.status_code}"), ""
    text = resp.text or ""
    head = text.split("\n", 1)[0]
    if "latitude" not in head:
        # FIRMS answers 200 with a plain-text message for bad keys / quota
        return SourceResult(source, "error", error=head.strip()[:80] or "empty response"), ""
    return SourceResult(source, "ok"), text


async def ingest_window(
    *,
    http,
    key: str,
    bucket,
    gcs_client,
    now_utc: Optional[datetime] = None,
    window_days: int = 2,
    sources: Optional[List[str]] = None,
) -> IngestOutcome:
    """Fetch the last ``window_days`` UTC days (ending today) from every source, re-key by
    Pakistan acquisition day and (re)write every day file in the window plus its sidecar."""
    now_utc = now_utc or datetime.now(timezone.utc)
    today_utc = now_utc.date()
    start_utc = today_utc - timedelta(days=window_days - 1)
    srcs = sources or sources_for(today_utc)
    outcome = IngestOutcome()

    rows: List[Dict[str, Any]] = []
    for src in srcs:
        res, text = await fetch_source(http, key, src, window_days, start_utc)
        if res.status == "ok":
            parsed = parse_firms_csv(text, satellite_hint=src)
            res.rows = len(parsed)
            rows.extend(parsed)
        outcome.sources.append(res)

    any_ok = any(s.status == "ok" for s in outcome.sources)
    all_ok = all(s.status == "ok" for s in outcome.sources)
    fetched_at = now_utc.isoformat().replace("+00:00", "Z")

    # Pakistan days fully or partly covered by the UTC window. The first PKT day only has
    # its last 19 hours covered, so the window's first day is excluded from rewriting.
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        d = pk_day_of(r)
        if d:
            by_day.setdefault(d, []).append(r)
    first_full_pk_day = (datetime.combine(start_utc, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)).astimezone(PK_TZ).date()
    last_pk_day = now_utc.astimezone(PK_TZ).date()
    day = first_full_pk_day
    while day <= last_pk_day:
        ds = day.strftime("%Y-%m-%d")
        day_rows = by_day.get(ds, [])
        csv_path, meta_path = blob_paths(day)
        meta = {
            "day": ds,
            "day_basis": "acq_pkt",
            "tz": "Asia/Karachi",
            "requested_period": {"start": f"{ds}T00:00:00+05:00", "end": f"{ds}T23:59:59+05:00"},
            "observation_period": _observation_period(day_rows),
            "fetched_at": fetched_at,
            "fetch_window_utc": {"start": start_utc.isoformat(), "end": today_utc.isoformat()},
            "sources": [{"source": s.source, "status": s.status, "rows": s.rows, "error": s.error} for s in outcome.sources],
            "status": "ok" if all_ok else ("partial" if any_ok else "unavailable"),
            "count": len(day_rows),
            "bbox": FIRMS_BBOX,
        }
        if any_ok:
            # Only (re)write detections when at least one source answered; otherwise keep
            # whatever the previous run stored and record the failure in the sidecar.
            bucket.blob(csv_path).upload_from_string(rows_to_csv(day_rows), content_type="text/csv")
        bucket.blob(meta_path).upload_from_string(json.dumps(meta), content_type="application/json")
        outcome.days.append(ds)
        outcome.per_day[ds] = {"count": len(day_rows), "status": meta["status"], "written": any_ok}
        day += timedelta(days=1)
    return outcome


def _observation_period(rows: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    times = sorted(r["acq_datetime_utc"] for r in rows if r.get("acq_datetime_utc"))
    if not times:
        return None
    return {"start": times[0], "end": times[-1]}


# ---------------------------------------------------------------- reading

def build_feature_collection(
    requested_date: str,
    read_text: Callable[[str], Optional[str]],
    *,
    max_lookback_days: int = 2,
) -> Dict[str, Any]:
    """GeoJSON for a Pakistan day with an explicit status; never a silent fallback.

    status: ok (detections for that day) · empty (file present, no detections) ·
    partial (a satellite source failed on the latest fetch) · stale (only an older day
    exists; `date` names it) · unavailable (nothing within the lookback)."""
    try:
        req = datetime.strptime(requested_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("date must be YYYY-MM-DD")

    used_day: Optional[date] = None
    raw: Optional[str] = None
    meta: Optional[Dict[str, Any]] = None
    for offset in range(max_lookback_days + 1):
        d = req - timedelta(days=offset)
        csv_path, meta_path = blob_paths(d)
        text = read_text(csv_path)
        if text is None:
            continue
        used_day = d
        raw = text
        mtext = read_text(meta_path)
        if mtext:
            try:
                meta = json.loads(mtext)
            except ValueError:
                meta = None
        break

    base: Dict[str, Any] = {
        "type": "FeatureCollection",
        "layer": LAYER_NAME,
        "requested_date": requested_date,
        "tz": "Asia/Karachi",
        "bbox": FIRMS_BBOX,
        "sources": meta.get("sources") if meta else None,
        "last_successful_fetch": meta.get("fetched_at") if meta else None,
        "day_basis": meta.get("day_basis") if meta else "acq_utc",
        "observation_period": meta.get("observation_period") if meta else None,
        "note": "VIIRS thermal anomalies at satellite-pixel locations; FRP is radiative power in MW. Neither count nor FRP measures a contribution to PM2.5.",
    }
    if used_day is None:
        return {**base, "date": requested_date, "status": "unavailable", "count": 0, "features": []}

    rows = parse_firms_csv(raw or "")
    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["longitude"], r["latitude"]]},
            "properties": {
                "frp": r["frp"],
                "confidence": r["confidence"],
                "satellite": r["satellite"],
                "acq_date": r["acq_date"] or used_day.strftime("%Y-%m-%d"),
                "acq_time": r["acq_time"],
                "acq_datetime_utc": r["acq_datetime_utc"],
            },
        }
        for r in rows
    ]
    if used_day != req:
        status = "stale"
    elif meta and meta.get("status") == "partial":
        status = "partial"
    elif meta and meta.get("status") == "unavailable":
        status = "unavailable"
    elif not features:
        status = "empty"
    else:
        status = "ok"
    if base["observation_period"] is None and features:
        base["observation_period"] = _observation_period(rows)
    return {**base, "date": used_day.strftime("%Y-%m-%d"), "status": status, "count": len(features), "features": features}
