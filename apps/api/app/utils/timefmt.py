"""RFC 3339 formatting with a Z suffix. `isoformat() + "Z"` on a timezone-aware value produced '…+00:00Z'."""

from datetime import datetime, timezone
from typing import Optional


def iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
