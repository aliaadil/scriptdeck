from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _table():
    from scriptdeck.db.models import schedules as _schedules
    return _schedules


def _scripts():
    from scriptdeck.db.models import scripts as _scripts
    return _scripts


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
        select(t, s.c.language, s.c.name, s.c.source_path)
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
