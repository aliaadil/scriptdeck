from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _table():
    from kindling.db.models import runs as _runs
    return _runs


def _new_ulid() -> str:
    """Generate a 26-char Crockford ULID without an external dependency.

    Layout: 6-byte big-endian time (ms since epoch) + 10-byte random.
    Base32-encoded with the Crockford alphabet (excludes I, L, O, U for
    readability).
    """
    import secrets

    _CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    time_chars = ["0"] * 10
    for i in range(9, -1, -1):
        time_chars[i] = _CROCKFORD[ms % 32]
        ms //= 32
    rand = secrets.token_bytes(10)
    rand_int = int.from_bytes(rand, "big")
    rand_chars = ["0"] * 16
    for i in range(15, -1, -1):
        rand_chars[i] = _CROCKFORD[rand_int % 32]
        rand_int //= 32
    return "".join(time_chars + rand_chars)


async def create_run(
    session: AsyncSession,
    *,
    script_id: int,
    schedule_id: int | None,
    trigger_kind: str | None = None,
    status: str = "running",
    skip_reason: str | None = None,
    retry_group: str | None = None,
    params_json: str | None = None,
) -> tuple[int, str, str]:
    """Insert a new run row and return (run_id, started_at, retry_group).

    ``params_json`` is a serialized JSON object string written verbatim
    to ``runs.params_json``. ``None`` keeps the column NULL — caller's
    responsibility to json.dumps() before passing.
    """
    t = _table()
    rg = retry_group or _new_ulid()
    started_at = datetime.now(UTC).isoformat()
    stmt = (
        insert(t)
        .values(
            script_id=script_id,
            schedule_id=schedule_id,
            trigger_kind=trigger_kind,
            status=status,
            skip_reason=skip_reason,
            retry_group=rg,
            started_at=started_at,
            params_json=params_json,
        )
        .returning(t.c.id, t.c.started_at, t.c.retry_group)
    )
    row = (await session.execute(stmt)).one()
    return int(row[0]), row[1], row[2]


async def has_active_run(session: AsyncSession, script_id: int) -> bool:
    t = _table()
    stmt = select(t.c.id).where(t.c.script_id == script_id, t.c.status == "running")
    return (await session.execute(stmt)).first() is not None


async def own_script_ids(session: AsyncSession, user_id: int) -> list[int]:
    """Return the list of script_ids owned by ``user_id``.

    Used by the runs listing endpoint to restrict non-admin users to
    their own scripts' runs.
    """
    from kindling.db.models import scripts as _scripts
    stmt = select(_scripts.c.id).where(_scripts.c.user_id == user_id)
    return [int(i) for i in (await session.execute(stmt)).scalars().all()]


async def count_pending(session: AsyncSession, script_id: int) -> int:
    """Return the count of runs in 'pending' status for a script."""
    t = _table()
    stmt = select(t.c.id).where(t.c.script_id == script_id, t.c.status == "pending")
    return len((await session.execute(stmt)).all())


async def promote_oldest_pending(
    session: AsyncSession, script_id: int
) -> int | None:
    """Atomically flip the oldest pending run to running; return its id or None."""
    t = _table()
    row = (
        await session.execute(
            select(t.c.id)
            .where(t.c.script_id == script_id, t.c.status == "pending")
            .order_by(t.c.started_at)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    run_id = int(row[0])
    await session.execute(
        update(t).where(t.c.id == run_id).values(status="running")
    )
    return run_id


async def pick_due_retries(session: AsyncSession, now: datetime) -> list[dict]:
    """Return run rows with status='pending_retry' and next_attempt_at <= now.

    Joins scripts so the caller can dispatch using the script's name, language,
    and source_path without an extra round trip.
    """
    from kindling.db.models import scripts
    t = _table()
    stmt = (
        select(
            t,
            scripts.c.name,
            scripts.c.language,
            scripts.c.source_path,
            scripts.c.user_id,
            scripts.c.entrypoint,
        )
        .where(
            t.c.status == "pending_retry",
            t.c.next_attempt_at <= now.isoformat(),
        )
        .join(scripts, t.c.script_id == scripts.c.id)
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


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


async def mark_pending_retry(
    session: AsyncSession,
    *,
    run_id: int,
    attempt: int,
    schedule_retry_max: int,
    schedule_retry_backoff: int,
) -> bool:
    """If retries remain, set status=pending_retry + next_attempt_at and return True.
    Otherwise return False (caller should mark terminal failure)."""
    from datetime import UTC, timedelta
    from datetime import datetime as _dt
    t = _table()
    if attempt >= schedule_retry_max:
        return False
    delay = timedelta(seconds=schedule_retry_backoff * (2 ** attempt))
    next_at = (_dt.now(UTC) + delay).isoformat()
    await session.execute(
        update(t)
        .where(t.c.id == run_id)
        .values(
            status="pending_retry",
            attempt=attempt + 1,
            next_attempt_at=next_at,
        )
    )
    return True
