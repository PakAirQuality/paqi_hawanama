"""
Envelope → archived payload → policy-normalized rows → validated rows.

Shared by the station and city tasks so both paths archive the provider
response, apply their TemporalPolicy, validate values and count what was
rejected or quarantined in exactly the same way.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.ingestion.raw_archive import RawPayloadArchiver
from app.ingestion.temporal import PARSER_VERSION, TEMPORAL_POLICIES, TemporalPolicy, extract_iqair_rows
from app.ingestion.validation import validate_reading


@dataclass
class ExtractStats:
    rejected: Counter = field(default_factory=Counter)       # reason -> rows never written
    notes: Counter = field(default_factory=Counter)          # extractor notes (e.g. no_current_pollution_ts)
    quarantined_fields: int = 0                              # values NULLed and kept in raw.prov.q
    archive_failures: int = 0

    def reset(self) -> None:
        self.rejected.clear()
        self.notes.clear()
        self.quarantined_fields = 0
        self.archive_failures = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"rejected": dict(self.rejected), "extract_notes": dict(self.notes),
                "quarantined_fields": self.quarantined_fields, "archive_failures": self.archive_failures}


def policy_for(scope_type: str) -> TemporalPolicy:
    return TEMPORAL_POLICIES["iqair_station_v1" if scope_type == "station" else "iqair_city_v1"]


async def normalize_envelope(env, parsed: Dict[str, Any], *, scope_type: str, scope_key: str, provider: str,
                             native_id: Any, stream: str, archiver: RawPayloadArchiver, session_factory,
                             run_id: Optional[str], backfill_hours: int, stats: ExtractStats,
                             now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    ref = await archiver.archive(
        provider=provider, stream=stream, native_id=native_id, payload=env.data,
        request_meta={"endpoint": env.endpoint, "params": env.params_redacted,
                      "elapsed_ms": env.elapsed_ms, "attempts": env.attempts},
        fetched_at=env.fetched_at, http_status=env.http_status, run_id=run_id, parser_version=PARSER_VERSION,
    )
    if ref.error:
        stats.archive_failures += 1
    await archiver.record(session_factory, ref)

    res = extract_iqair_rows(parsed, scope_type=scope_type, scope_key=scope_key, policy=policy_for(scope_type),
                             provider=provider, prov_base={**ref.prov(), "run": run_id})
    for n in res.notes:
        stats.notes[n] += 1

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=int(backfill_hours))
    out: List[Dict[str, Any]] = []
    for r in res.rows:
        v = validate_reading(r, now=now, cutoff=cutoff)
        if not v.ok:
            stats.rejected[v.rejected] += 1
            continue
        if v.quarantined:
            v.row["raw"]["prov"]["q"] = v.quarantined
            stats.quarantined_fields += len(v.quarantined)
        out.append(v.row)
    return out
