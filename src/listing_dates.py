from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_CREATION = "itemCreationDate"
_ORIGIN = "itemOriginDate"


def _parse_iso(raw: str) -> datetime:
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))


def parse_age_at(item: dict[str, Any]) -> datetime:
    """Timestamp for recency checks — prefers itemCreationDate (updates on relist)."""
    creation = item.get(_CREATION)
    if creation:
        return _parse_iso(creation)
    origin = item.get(_ORIGIN)
    if origin:
        return _parse_iso(origin)
    return datetime.now(timezone.utc)


def parse_listed_at(item: dict[str, Any]) -> datetime:
    """Latest known timestamp (for display / stale-date hints)."""
    parsed: list[datetime] = []
    for key in (_CREATION, _ORIGIN):
        raw = item.get(key)
        if raw:
            parsed.append(_parse_iso(raw))
    if parsed:
        return max(parsed)
    return datetime.now(timezone.utc)
