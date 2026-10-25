"""timeutil.py - hospital-local time helpers. DB stores naive UTC; appointment date/time are hospital-local."""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings

log = logging.getLogger("helix.time")
try:
    TZ = ZoneInfo(settings.HOSPITAL_TIMEZONE)
except ZoneInfoNotFoundError:                            # pragma: no cover
    log.warning("Unknown HOSPITAL_TIMEZONE %r - falling back to UTC", settings.HOSPITAL_TIMEZONE)
    TZ = ZoneInfo("UTC")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def now_local() -> datetime:
    return datetime.now(TZ)


def today_local() -> date:
    return now_local().date()


def local_to_utc_naive(d: date, t: time) -> datetime:
    return datetime.combine(d, t).replace(tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)


def utc_naive_to_local(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ)


def hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")[:2]
    return time(int(h), int(m))


def day_slots() -> list[time]:
    """Appointment slots for one day, e.g. 09:00, 09:30 ... 16:30."""
    start, end = parse_hhmm(settings.DAY_START), parse_hhmm(settings.DAY_END)
    cur = datetime.combine(date.today(), start)
    stop = datetime.combine(date.today(), end)
    out = []
    while cur < stop:
        out.append(cur.time())
        cur += timedelta(minutes=settings.SLOT_MINUTES)
    return out
