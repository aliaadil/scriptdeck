from __future__ import annotations

from datetime import UTC, datetime

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


async def own_script_ids(session: AsyncSession, user_id: int) -> list[int]:
    """Return the list of script_ids owned by ``user_id``.

    Used by the runs listing endpoint to restrict non-admin users to
    their own scripts' runs.
    """
    from scriptdeck.db.models import scripts as _scripts
    stmt = select(_scripts.c.id).where(_scripts.c.user_id == user_id)
    return [int(i) for i in (await session.execute(stmt)).scalars().all()]


async def finalize_run(
    session: AsyncSession, *, run_id: int, exit_code: int, status: str
) -> None:
    t = _table()
    now = datetime.now(UTC).isoformat()
    await session.execute(
        update(t)
        .where(t.c.id == run_id)
        .values(ended_at=now, exit_code=exit_code, status=status)
    )
