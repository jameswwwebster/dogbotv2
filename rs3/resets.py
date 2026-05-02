"""RS3 reset / D&D schedule computation.

All times are reasoned in UTC since Jagex resets are UTC-based.
The schedule is hard-coded — no API exists for these — and the
`next_occurrence(now)` helper is unit-tested for correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class Cadence(str, Enum):
    DAILY = "daily"            # at HH:MM UTC every day
    WEEKLY = "weekly"           # at HH:MM UTC on a fixed weekday (0=Mon..6=Sun)
    HOURLY = "hourly"           # at MM minutes past every hour


@dataclass(frozen=True)
class Reset:
    key: str
    name: str
    description: str
    cadence: Cadence
    hour: int = 0
    minute: int = 0
    weekday: int = 0  # 0..6, Monday=0; only used for WEEKLY


# ---------------------------------------------------------------------------
# Catalogue (extend freely — adding a row here surfaces it from /next).
# ---------------------------------------------------------------------------
RESETS: list[Reset] = [
    Reset(
        key="daily",
        name="Daily reset",
        description="TH keys, daily challenges, daily skilling resources, daily D&D rerolls.",
        cadence=Cadence.DAILY,
        hour=0, minute=0,
    ),
    Reset(
        key="weekly",
        name="Weekly reset",
        description="Penguin Hide & Seek, weekly D&Ds, Goebies supplies, Vis Wax limit, hard clue caches.",
        cadence=Cadence.WEEKLY,
        weekday=2,  # Wednesday
        hour=0, minute=0,
    ),
    Reset(
        key="vorago",
        name="Vorago / Telos lockout",
        description="Per-account boss reset (kill counters / weekly hard mode); shares the weekly cycle.",
        cadence=Cadence.WEEKLY,
        weekday=2,
        hour=0, minute=0,
    ),
    Reset(
        key="croesus",
        name="Croesus reset",
        description="Croesus weekly reset.",
        cadence=Cadence.WEEKLY,
        weekday=2,
        hour=0, minute=0,
    ),
    Reset(
        key="flash",
        name="Wilderness Flash Event",
        description="Hourly Wilderness Flash Event begins (xx:00 UTC; warning at xx:55).",
        cadence=Cadence.HOURLY,
        minute=0,
    ),
    Reset(
        key="merchant",
        name="Travelling Merchant rotation",
        description="Travelling Merchant stock rotation (daily, ties to the daily reset).",
        cadence=Cadence.DAILY,
        hour=0, minute=0,
    ),
]


def get(key: str) -> Reset | None:
    for r in RESETS:
        if r.key == key.lower():
            return r
    return None


def next_occurrence(reset: Reset, now: datetime) -> datetime:
    """Compute the next firing time of the given reset at or after `now`."""
    now = _ensure_utc(now)

    if reset.cadence is Cadence.HOURLY:
        candidate = now.replace(minute=reset.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(hours=1)
        return candidate

    if reset.cadence is Cadence.DAILY:
        candidate = now.replace(hour=reset.hour, minute=reset.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    if reset.cadence is Cadence.WEEKLY:
        candidate = now.replace(hour=reset.hour, minute=reset.minute, second=0, microsecond=0)
        days_ahead = (reset.weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    raise ValueError(f"Unhandled cadence {reset.cadence}")


def time_until(reset: Reset, now: datetime) -> timedelta:
    return next_occurrence(reset, now) - _ensure_utc(now)


def _ensure_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_timedelta(td: timedelta) -> str:
    """Render a timedelta as 'Xd Yh Zm' (or 'Xh Ym' / 'Xm Ys')."""
    total_seconds = int(td.total_seconds())
    if total_seconds < 0:
        total_seconds = 0
    days, rem = divmod(total_seconds, 86_400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"
