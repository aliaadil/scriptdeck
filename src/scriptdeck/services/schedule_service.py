from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ComputeError(ValueError):
    """Schedule computation failed (bad cron, no valid fire within bounded horizon)."""


def _table():
    from scriptdeck.db.models import schedules as _schedules
    return _schedules


def _scripts():
    from scriptdeck.db.models import scripts as _scripts
    return _scripts


_MAX_COMPUTE_HORIZON_DAYS = 7


def compute_next_run(
    *,
    cron_expr: str,
    tz_name: str,
    blackout_dates: list[str] | None,
    include_days: list[int] | None,
    after: datetime,
) -> datetime:
    """Return next firing after `after` (UTC-aware), respecting tz + filters.

    Args:
        cron_expr: 5-field cron string.
        tz_name: IANA timezone name (e.g. "America/New_York"); "UTC" allowed.
        blackout_dates: list of "YYYY-MM-DD" in schedule tz to skip; None = no skips.
        include_days: list of 0..6 (Mon=0) to override cron's day-of-week; None = use cron.
        after: naive-or-aware datetime in UTC; lower bound, exclusive.

    Returns: tz-aware datetime in UTC.
    Raises: ComputeError on bad cron, unknown tz, or no fire within 7 days.
    """
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ComputeError(f"unknown timezone: {tz_name}") from exc

    if after.tzinfo is None:
        after_utc = after.replace(tzinfo=UTC)
    else:
        after_utc = after.astimezone(UTC)

    after_local = after_utc.astimezone(tz)
    horizon_end_local = after_local + timedelta(days=_MAX_COMPUTE_HORIZON_DAYS)

    try:
        it = croniter(cron_expr, after_local)
    except (ValueError, KeyError, TypeError) as exc:
        raise ComputeError(f"bad cron expression: {cron_expr!r}") from exc

    while True:
        try:
            candidate_local = it.get_next(datetime)
        except (ValueError, StopIteration):
            raise ComputeError(f"no fire within {_MAX_COMPUTE_HORIZON_DAYS} days")
        if candidate_local > horizon_end_local:
            raise ComputeError(f"no fire within {_MAX_COMPUTE_HORIZON_DAYS} days")

        if include_days is not None and candidate_local.weekday() not in include_days:
            continue
        date_iso = candidate_local.date().isoformat()
        if blackout_dates and date_iso in blackout_dates:
            continue

        return candidate_local.astimezone(UTC)


# ---- Existing functions below (unchanged) ----
def advance_next_run(kind: str, expression: str, prev_next_run: str) -> str:
    if kind == "cron":
        it = croniter(expression, datetime.fromisoformat(prev_next_run))
        return it.get_next(datetime).isoformat()
    if kind == "interval":
        n = int(expression[:-1])
        unit = expression[-1]
        delta = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return (datetime.fromisoformat(prev_next_run) + timedelta(seconds=n * delta)).isoformat()
    raise ValueError(f"unknown kind: {kind}")


async def list_due(session: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    t = _table()
    s = _scripts()
    stmt = (
        select(
            t, s.c.language, s.c.name, s.c.source_path, s.c.user_id,
            t.c.overlap_policy, t.c.queue_max,
            t.c.timezone, t.c.blackout_dates, t.c.include_days,
        )
        .where(t.c.enabled == 1, t.c.next_run_at <= now.isoformat())
        .join(s, t.c.script_id == s.c.id)
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def advance(session: AsyncSession, schedule_id: int, new_next_run: str) -> None:
    t = _table()
    await session.execute(
        update(t).where(t.c.id == schedule_id).values(next_run_at=new_next_run)
    )
