"""Satellite fire detections (NASA FIRMS VIIRS) for the analyst desk.

What this module fixes relative to the first implementation:

* detections are keyed by their **acquisition day in Pakistan time** (acq_date + acq_time
  are UTC in FIRMS output; the night overpass around 20:00 UTC is already the next
  Pakistan calendar day), so a request for a Pakistan date returns that day's fires;
* two satellites (NOAA-20 and NOAA-21; Suomi NPP optional until its products stop on
  1 November 2026) through the FIRMS *area* API, west,south,east,north bbox;
* the last days of the window are refreshed on every run (a partial early-morning file is never
  frozen), zero-detection days are written as header-only files, and every day carries a
  ``.meta.json`` sidecar with the requested/observation period, per-source status and
  fetch time;
* readers get an explicit ``status`` (ok / empty / partial / stale / unavailable) instead
  of a silent fallback to an older day.

Files: ``hindcast/firms/firms_{YYYYMMDD}.csv`` (+ ``.meta.json``) in the forecasts bucket.
Older files written by the previous ingester are keyed by the UTC acquisition date and have
no sidecar; they are reported with ``day_basis='acq_utc'``.

Operations runbook
------------------
* Schedule: Cloud Scheduler ``firms-fire-ingest`` (asia-south1) POSTs
  ``/api/v1/ops/analyst-desk/fires/ingest?window_days=3`` on hawanama-ingest every 3 h
  (``infra/scheduler.tf``). Each run is recorded in ``ops.ingest_runs`` as task
  ``ingest-fires`` and the HTTP status follows the run (200 success, 207 partial, 500
  failed), so Scheduler marks and retries real failures.
* Health: ``/api/v1/health/freshness`` reports source ``fires`` from the last run; it is
  degraded when the last run failed or the last success is older than
  ``FRESHNESS_MAX_AGE_MIN["fires"]`` (default 540 min = three missed runs) and the
  endpoint then answers 503, which the Cloud Monitoring uptime check turns into an email.
* Alerts (``infra/monitoring/``): "health freshness 503", "scheduler job failed" and
  "FIRMS ingest failed / invalid key". Each names the failing source or job.
* Key rotation (NASA FIRMS map key, one per e-mail, free at
  https://firms.modaps.eosdis.nasa.gov/api/map_key/): ``check_key`` is called at the start
  of every run and an invalid key fails the run with ``error_class='invalid_key'``.
  To replace it: add a new Secret Manager version of ``FIRMS_MAP_KEY`` (never paste the
  key into chat or code), run ``gcloud run services update hawanama-ingest --region
  asia-south1 --update-secrets=FIRMS_MAP_KEY=FIRMS_MAP_KEY:latest`` (and the same for
  ``hawanama``), then ``gcloud scheduler jobs run firms-fire-ingest``. Disable the old
  version afterwards. Budget: 5,000 requests per 10 min per key; a run uses one request
  per satellite.
* Satellites: NOAA-20 and NOAA-21 are the primary sources; Suomi NPP is requested only
  before ``SNPP_END`` (2026-11-01, when NOAA stops its product delivery). When another
  satellite is retired, change ``DEFAULT_SOURCES``/``sources_for`` and the test
  ``test_sources_drop_snpp_after_its_end_date``; a source that keeps returning errors makes
  every run ``partial`` and shows as such on the dashboard.
* Backfill: ``POST /fires/ingest?window_days=10&date=YYYY-MM-DD`` refetches a past window
  (the FIRMS area API serves at most 10 days per request).
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
FIRMS_KEY_STATUS_URL = "https://firms.modaps.eosdis.nasa.gov/mapserver/mapkey_status/"
FIRMS_MAX_WINDOW_DAYS = 10  # the area API serves at most 10 days per request
RETRY_DELAY_S = 5.0
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
    key: Optional[Dict[str, Any]] = None          # check_key() result
    rows_fetched: int = 0                          # rows parsed from every source
    rows_written: int = 0                          # rows in the day files rewritten
    latest_acq_utc: Optional[datetime] = None      # newest detection seen

    @property
    def status(self) -> str:
        """ok (every source answered) · partial · unavailable (no source answered / bad key)."""
        if self.key and self.key.get("status") == "invalid":
            return "unavailable"
        ok = [s for s in self.sources if s.status == "ok"]
        if not ok:
            return "unavailable"
        return "ok" if len(ok) == len(self.sources) else "partial"


async def check_key(http, key: str) -> Dict[str, Any]:
    """Ask FIRMS whether the map key is valid and how much of its budget is used.

    Returns {"status": "ok"|"invalid"|"error", "transaction_limit", "current_transactions",
    "transaction_interval", "error"}. The key itself is never included."""
    try:
        resp = await http.get(FIRMS_KEY_STATUS_URL, params={"MAP_KEY": key})
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__}
    text = (resp.text or "").strip()
    if resp.status_code != 200:
        return {"status": "error", "error": f"HTTP {resp.status_code}"}
    try:
        data = json.loads(text)
    except ValueError:
        data = None
    if isinstance(data, dict) and "transaction_limit" in data:
        return {
            "status": "ok",
            "transaction_limit": data.get("transaction_limit"),
            "current_transactions": data.get("current_transactions"),
            "transaction_interval": data.get("transaction_interval"),
        }
    # FIRMS answers 200 with a sentence for a bad key ("MAP_KEY is invalid or ...")
    return {"status": "invalid", "error": text[:120].replace(key, "<key>")}


async def _sleep(seconds: float) -> None:
    import asyncio
    await asyncio.sleep(seconds)


async def fetch_source(http, key: str, source: str, days: int, start: date) -> SourceResult | tuple[SourceResult, str]:
    """One FIRMS area request with a single retry for network errors, 429 and 5xx.
    Returns (result, csv_text)."""
    url = f"{FIRMS_API_BASE}/{key}/{source}/{FIRMS_BBOX}/{days}/{start.strftime('%Y-%m-%d')}"
    resp = None
    last_error: Optional[str] = None
    for attempt in range(2):
        try:
            resp = await http.get(url)
        except Exception as exc:  # network
            resp, last_error = None, type(exc).__name__
        else:
            if resp.status_code == 200:
                break
            last_error = f"HTTP {resp.status_code}"
            if resp.status_code != 429 and resp.status_code < 500:
                break
        if attempt == 0:
            await _sleep(RETRY_DELAY_S)
    if resp is None or resp.status_code != 200:
        return SourceResult(source, "error", error=last_error or "no response"), ""
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
    window_days = max(1, min(int(window_days), FIRMS_MAX_WINDOW_DAYS))
    today_utc = now_utc.date()
    start_utc = today_utc - timedelta(days=window_days - 1)
    srcs = sources or sources_for(today_utc)
    outcome = IngestOutcome()

    outcome.key = await check_key(http, key)
    if outcome.key.get("status") == "invalid":
        # Do not spend the (possibly rate-limited) area requests on a key FIRMS rejects.
        outcome.sources = [SourceResult(src, "error", error="invalid_key") for src in srcs]
        return outcome

    rows: List[Dict[str, Any]] = []
    for src in srcs:
        res, text = await fetch_source(http, key, src, window_days, start_utc)
        if res.status == "ok":
            parsed = parse_firms_csv(text, satellite_hint=src)
            res.rows = len(parsed)
            rows.extend(parsed)
        outcome.sources.append(res)
    outcome.rows_fetched = len(rows)
    for r in rows:
        if r.get("acq_datetime_utc"):
            try:
                t = datetime.fromisoformat(r["acq_datetime_utc"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if outcome.latest_acq_utc is None or t > outcome.latest_acq_utc:
                outcome.latest_acq_utc = t

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
            outcome.rows_written += len(day_rows)
        bucket.blob(meta_path).upload_from_string(json.dumps(meta), content_type="application/json")
        outcome.days.append(ds)
        outcome.per_day[ds] = {"count": len(day_rows), "status": meta["status"], "written": any_ok}
        day += timedelta(days=1)
    return outcome


def _age_hours(fetched_at: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    """Hours since the sidecar's fetched_at (None when unknown)."""
    if not fetched_at:
        return None
    try:
        t = datetime.fromisoformat(str(fetched_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return round(max(0.0, (now - t).total_seconds() / 3600), 1)


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
        "fetched_age_hours": _age_hours(meta.get("fetched_at")) if meta else None,
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
