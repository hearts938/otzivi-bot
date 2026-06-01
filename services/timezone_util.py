from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo


def publish_at_midnight(day: date, tz_name: str) -> datetime:
    """00:00 указанного дня в заданной TZ → naive UTC для хранения в БД."""
    tz = ZoneInfo(tz_name)
    local = datetime.combine(day, time(0, 0), tzinfo=tz)
    return local.astimezone(timezone.utc).replace(tzinfo=None)
