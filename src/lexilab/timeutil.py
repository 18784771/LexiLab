from __future__ import annotations

from datetime import datetime, timezone


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def local_time(value: str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    parsed = parse_utc(value)
    if parsed is None:
        return "-"
    return parsed.astimezone().strftime(fmt)
