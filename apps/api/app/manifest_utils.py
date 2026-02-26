# apps/worker/manifest_utils.py
import os, json, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Optional pandas (parquet). Falls back to JSONL.
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    pd = None
    _HAVE_PANDAS = False

# --------------- GCS manifest sync helpers ---------------

_MANIFEST_GCS_BUCKET = os.getenv("MANIFEST_GCS_BUCKET", "").strip()

def _gcs_client():
    """Lazy-load google.cloud.storage; returns None if unavailable."""
    try:
        from google.cloud import storage  # type: ignore
        return storage.Client()
    except Exception:
        return None

def upload_manifest_to_gcs(local_path: Path, gcs_prefix: str) -> bool:
    """
    Upload a local manifest file to GCS.
    gcs_prefix example: "manifests/station_manifests"
    Uploads to: gs://<MANIFEST_GCS_BUCKET>/<gcs_prefix>/<filename>
    No-op if MANIFEST_GCS_BUCKET is unset or google-cloud-storage is missing.
    """
    if not _MANIFEST_GCS_BUCKET:
        return False
    if not local_path.exists():
        logger.warning("upload_manifest_to_gcs: local file does not exist: %s", local_path)
        return False
    client = _gcs_client()
    if client is None:
        logger.warning("upload_manifest_to_gcs: google-cloud-storage not available")
        return False
    try:
        bucket = client.bucket(_MANIFEST_GCS_BUCKET)
        blob_path = f"{gcs_prefix}/{local_path.name}"
        blob = bucket.blob(blob_path)
        blob.cache_control = "no-cache"
        blob.upload_from_filename(str(local_path), content_type="application/octet-stream")
        logger.info("Uploaded manifest to gs://%s/%s", _MANIFEST_GCS_BUCKET, blob_path)
        return True
    except Exception as e:
        logger.error("Failed to upload manifest to GCS: %s", e)
        return False

def download_manifest_from_gcs(local_path: Path, gcs_prefix: str) -> bool:
    """
    Download a manifest file from GCS to local_path.
    gcs_prefix example: "manifests/station_manifests"
    Downloads from: gs://<MANIFEST_GCS_BUCKET>/<gcs_prefix>/<filename>
    No-op if MANIFEST_GCS_BUCKET is unset or google-cloud-storage is missing.
    """
    if not _MANIFEST_GCS_BUCKET:
        return False
    client = _gcs_client()
    if client is None:
        logger.warning("download_manifest_from_gcs: google-cloud-storage not available")
        return False
    try:
        bucket = client.bucket(_MANIFEST_GCS_BUCKET)
        blob_path = f"{gcs_prefix}/{local_path.name}"
        blob = bucket.blob(blob_path)
        if not blob.exists():
            logger.info("GCS manifest not found: gs://%s/%s", _MANIFEST_GCS_BUCKET, blob_path)
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        logger.info("Downloaded manifest from gs://%s/%s → %s", _MANIFEST_GCS_BUCKET, blob_path, local_path)
        return True
    except Exception as e:
        logger.error("Failed to download manifest from GCS: %s", e)
        return False

def ensure_latest_from_gcs(path_root: Path, fmt: str, gcs_prefix: str) -> Optional[Path]:
    """
    If latest manifest doesn't exist locally, try downloading from GCS.
    Tries parquet first if fmt=="parquet", then jsonl.
    Returns the local Path if found/downloaded, else None.
    """
    candidates = []
    if fmt == "parquet":
        candidates = [path_root / "latest.parquet", path_root / "latest.jsonl"]
    else:
        candidates = [path_root / "latest.jsonl", path_root / "latest.parquet"]

    # Check local first
    for p in candidates:
        if p.exists():
            return p

    # Try GCS download
    for p in candidates:
        if download_manifest_from_gcs(p, gcs_prefix):
            return p

    return None

# ---------------------------------------------------------

ManifestRow = Dict[str, Any]

def _key(row: ManifestRow) -> Tuple[str, str]:
    """
    Primary identity: (provider_code, provider_uid) if available,
    else fall back to (provider_code, source_station_id) — still stable vs name drift.
    """
    pc = row.get("provider_code") or "unknown"
    uid = (row.get("provider_uid")            # new, preferred
           or row.get("source_station_id")    # stable slug fallback
           or f"{row.get('country')}|{row.get('state')}|{row.get('city')}|{row.get('iqair_station_name')}".lower())
    return (pc, str(uid))

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def load_latest_manifest(path_root: Path, fmt: str) -> List[ManifestRow]:
    latest = (path_root / f"latest.parquet") if (fmt == "parquet") else (path_root / f"latest.jsonl")
    if not latest.exists():
        return []
    if fmt == "parquet" and _HAVE_PANDAS:
        df = pd.read_parquet(latest)
        return df.to_dict(orient="records")
    # JSONL
    rows: List[ManifestRow] = []
    with open(latest, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

def write_latest_and_run(path_root: Path, run_dir: Path, fmt: str, rows: List[ManifestRow],
                         gcs_prefix: str = "") -> None:
    # Ensure deterministic column order when possible
    if fmt == "parquet" and _HAVE_PANDAS:
        df = pd.DataFrame(rows)
        tmp_run = run_dir / "stations.parquet.tmp"
        run_p   = run_dir / "stations.parquet"
        df.to_parquet(tmp_run, index=False); os.replace(tmp_run, run_p)

        latest = path_root / "latest.parquet"
        tmp_latest = latest.with_suffix(".tmp")
        df.to_parquet(tmp_latest, index=False); os.replace(tmp_latest, latest)
    else:
        run_p = run_dir / "stations.jsonl"
        tmp_run = run_dir / "stations.jsonl.tmp"
        with open(tmp_run, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp_run, run_p)

        latest = path_root / "latest.jsonl"
        tmp_latest = latest.with_suffix(".tmp")
        with open(tmp_latest, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        os.replace(tmp_latest, latest)

    # Upload latest to GCS (no-op if bucket not configured)
    if gcs_prefix:
        upload_manifest_to_gcs(latest, gcs_prefix)

def finalize_union_manifest(
    path_root: Path,
    run_dir: Path,
    fmt: str,
    discovered_rows: List[ManifestRow],
    cities_successfully_fetched: Optional[set] = None,
    gcs_prefix: str = ""
) -> List[ManifestRow]:
    """
    Simplified contract:
      - Union newly discovered rows with previous latest
      - Track liveness (last_seen_at_utc, miss_count) but never remove stations
      - All stations remain active=True (liveness tracking is for polling frequency optimization)
      - Handle duplicates gracefully by preferring fresh data
    """
    cities_successfully_fetched = cities_successfully_fetched or set()

    ensure_latest_from_gcs(path_root, fmt, gcs_prefix)
    prev = load_latest_manifest(path_root, fmt)
    prev_by_key: Dict[Tuple[str,str], ManifestRow] = {_key(r): r for r in prev}

    now_iso = _now_iso()
    discovered_by_key: Dict[Tuple[str,str], ManifestRow] = {}
    seen_scope_keys: set = set()

    # Normalize and prepare discovered
    for r in discovered_rows:
        r = dict(r)  # copy
        r.setdefault("provider_uid", r.get("metadata_json", {}).get("iqair_uid"))
        r.setdefault("miss_count", 0)
        r.setdefault("first_seen_at_utc", now_iso)
        r["last_seen_at_utc"] = now_iso
        r["active"] = True  # All discovered stations are active
        discovered_by_key[_key(r)] = r
        if r.get("country") and r.get("state") and r.get("city"):
            seen_scope_keys.add(f"{r['country'].lower()}|{r['state'].lower()}|{r['city'].lower()}")

    union: Dict[Tuple[str,str], ManifestRow] = {}

    # First, add fresh discoveries (reset miss_count, preserve first_seen)
    for k, r in discovered_by_key.items():
        base = prev_by_key.get(k)
        if base:
            r["first_seen_at_utc"] = base.get("first_seen_at_utc", r["first_seen_at_utc"])
        r["miss_count"] = 0  # Reset because we found it this run
        union[k] = r

    # Then, carry forward previous rows not seen this run (increment miss_count for liveness tracking)
    for k, old in prev_by_key.items():
        if k in union:
            continue  # already handled
        old = dict(old)
        old.setdefault("miss_count", 0)
        old.setdefault("first_seen_at_utc", old.get("last_seen_at_utc") or now_iso)

        scope_key = (f"{(old.get('country') or '').lower()}|"
                     f"{(old.get('state') or '').lower()}|"
                     f"{(old.get('city') or '').lower()}")

        # Only increment miss_count if that scope was successfully fetched this run.
        if scope_key in seen_scope_keys:
            old["miss_count"] = int(old["miss_count"]) + 1
        # else: leave miss_count as is (do not punish for an API-wide city miss)

        # Keep all stations active - liveness tracking is for optimization, not exclusion
        old["active"] = True

        # Keep in union (never drop stations)
        union[k] = old

    # Write both run-scoped and latest pointers
    final_rows = list(union.values())
    write_latest_and_run(path_root, run_dir, fmt, final_rows, gcs_prefix=gcs_prefix)
    return final_rows