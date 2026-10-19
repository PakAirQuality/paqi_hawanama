"""
Station/city manifest helpers: GCS sync and the union-manifest writer used by discovery.
"""
import os, json, logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Tuple, Optional

from dataclasses import dataclass

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManifestRef:
    """Where a manifest came from, for the run record."""
    path: Path
    source: str                      # 'gcs' (downloaded now) | 'local' (cached/unsynced copy) | 'derived' | 'db'
    generation: Optional[str] = None  # GCS object generation, when known
    etag: Optional[str] = None
    synced_at: Optional[str] = None


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".meta.json")


def _read_sidecar(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(_sidecar(path).read_text())
    except Exception:
        return {}


def _write_sidecar(path: Path, generation: Optional[str], etag: Optional[str]) -> str:
    synced_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        _sidecar(path).write_text(json.dumps({"generation": generation, "etag": etag, "synced_at": synced_at}))
    except Exception as e:  # the sidecar is an optimisation; never fail a run over it
        logger.warning("Could not write manifest sidecar for %s: %s", path, e)
    return synced_at


def sync_latest_from_gcs(path_root: Path, gcs_prefix: str, fmt_preference: str = "parquet") -> Optional[ManifestRef]:
    """
    Make the local latest.(parquet|jsonl) match the GCS object, downloading only
    when the object generation differs from the sidecar recorded at the last
    sync. Falls back to whatever local copy exists when GCS is unavailable.
    Cloud Run instances do not share a disk, so a stale local manifest on one
    instance used to win over a newer one in the bucket.
    """
    names = ["latest.parquet", "latest.jsonl"] if fmt_preference == "parquet" else ["latest.jsonl", "latest.parquet"]
    candidates = [path_root / n for n in names]

    bucket_name = _bucket_name()
    client = _gcs_client() if bucket_name else None
    bucket = None
    if client is not None:
        try:
            bucket = client.bucket(bucket_name)
        except Exception as e:
            logger.error("GCS unavailable for manifest sync (bucket %s): %s", bucket_name, e)
    if bucket is not None:
        for p in candidates:
            blob_path = f"{gcs_prefix}/{p.name}"
            try:
                blob = bucket.blob(blob_path)
                if not blob.exists():
                    continue
                blob.reload()
                gen = str(blob.generation) if blob.generation is not None else None
                etag = getattr(blob, "etag", None)
                meta = _read_sidecar(p)
                if p.exists() and gen is not None and meta.get("generation") == gen:
                    logger.info("Manifest unchanged in GCS (generation %s): using local %s", gen, p)
                    return ManifestRef(p, "local", gen, etag, meta.get("synced_at"))
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(p.name + ".download.tmp")
                blob.download_to_filename(str(tmp))
                os.replace(tmp, p)
                synced_at = _write_sidecar(p, gen, etag)
                logger.info("Downloaded manifest gs://%s/%s (generation %s) → %s", bucket_name, blob_path, gen, p)
                return ManifestRef(p, "gcs", gen, etag, synced_at)
            except Exception as e:
                logger.error("GCS manifest sync failed for gs://%s/%s: %s", bucket_name, blob_path, e)
                continue
    elif bucket_name:
        logger.warning("sync_latest_from_gcs: google-cloud-storage not available; using local manifests only")

    for p in candidates:
        if p.exists():
            meta = _read_sidecar(p)
            return ManifestRef(p, "local", meta.get("generation"), meta.get("etag"), meta.get("synced_at"))
    return None

# Optional pandas (parquet). Falls back to JSONL.
try:
    import pandas as pd  # type: ignore
    _HAVE_PANDAS = True
except Exception:
    pd = None
    _HAVE_PANDAS = False

# --------------- GCS manifest sync helpers ---------------

def _bucket_name() -> str:
    """Read the bucket at call time so tests and settings overrides take effect."""
    return (settings.MANIFEST_GCS_BUCKET or "").strip()

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
    bucket_name = _bucket_name()
    if not bucket_name:
        return False
    if not local_path.exists():
        logger.warning("upload_manifest_to_gcs: local file does not exist: %s", local_path)
        return False
    client = _gcs_client()
    if client is None:
        logger.warning("upload_manifest_to_gcs: google-cloud-storage not available")
        return False
    try:
        bucket = client.bucket(bucket_name)
        blob_path = f"{gcs_prefix}/{local_path.name}"
        blob = bucket.blob(blob_path)
        blob.cache_control = "no-cache"
        blob.upload_from_filename(str(local_path), content_type="application/octet-stream")
        gen = str(blob.generation) if getattr(blob, "generation", None) is not None else None
        _write_sidecar(local_path, gen, getattr(blob, "etag", None))
        logger.info("Uploaded manifest to gs://%s/%s (generation %s)", bucket_name, blob_path, gen)
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
    bucket_name = _bucket_name()
    if not bucket_name:
        return False
    client = _gcs_client()
    if client is None:
        logger.warning("download_manifest_from_gcs: google-cloud-storage not available")
        return False
    try:
        bucket = client.bucket(bucket_name)
        blob_path = f"{gcs_prefix}/{local_path.name}"
        blob = bucket.blob(blob_path)
        if not blob.exists():
            logger.info("GCS manifest not found: gs://%s/%s", bucket_name, blob_path)
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(local_path))
        logger.info("Downloaded manifest from gs://%s/%s → %s", bucket_name, blob_path, local_path)
        return True
    except Exception as e:
        logger.error("Failed to download manifest from GCS: %s", e)
        return False

def ensure_latest_from_gcs(path_root: Path, fmt: str, gcs_prefix: str) -> Optional[Path]:
    """
    Return the local path of the latest manifest, synced from GCS when the
    bucket holds a newer generation (previously local-first, which let a stale
    copy on one instance win). Tries parquet first if fmt=="parquet".
    """
    ref = sync_latest_from_gcs(path_root, gcs_prefix, fmt)
    return ref.path if ref else None

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
