from __future__ import annotations

from datetime import UTC, datetime


def isoformat(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")