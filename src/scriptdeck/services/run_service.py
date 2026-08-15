from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _table():
    from scriptdeck.db.models import runs as _runs
    return _runs


async def create_run(
    session: AsyncSession, *, script_id: int, schedule_id: int | None, status: str = "running"
) -> tuple[int, str]:
    """Insert a new run row and return (run_id, started_at)."""
    t = _table()
    stmt = (
        insert(t)
        .values(script_id=script_id, schedule_id=schedule_id, status=status)
        .returning(t.c.id, t.c.started_at)
    )
    row = (await session.execute(stmt)).one()
    return int(row[0]), row[1]


async def has_active_run(session: AsyncSession, script_id: int) -> bool:
    t = _table()
    stmt = select(t.c.id).where(t.c.script_id == script_id, t.c.status == "running")
    return (await session.execute(stmt)).first() is not None


async def finalize_run(
    session: AsyncSession, *, run_id: int, exit_code: int, status: str
) -> None:
    t = _table()
    now = datetime.now(timezone.utc).isoformat()
    await session.execute(
        update(t)
        .where(t.c.id == run_id)
        .values(ended_at=now, exit_code=exit_code, status=status)
    )
