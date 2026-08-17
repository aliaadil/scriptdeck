"""Scheduler tick v2: overlap policies (skip / queue / parallel)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, text

from kindling.config import Settings
from kindling.db.engine import make_engine, session_factory
from kindling.db.migrations import run_migrations
from kindling.scheduler.tick import _tick
from kindling.services.log_broker import LogBroker


def _settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )


async def _setup_due_schedule(Sf, *, overlap_policy="skip", queue_max=10):
    from kindling.db.models import schedules, scripts, users

    now = datetime.now(timezone.utc).isoformat()
    async with Sf() as s:
        await s.execute(
            insert(users).values(
                id=1,
                email="owner@example.com",
                password_hash="x" * 32,
                role="admin",
                created_at=now,
            )
        )
        await s.execute(
            insert(scripts).values(
                id=1,
                name="t",
                language="python",
                source_path="scripts/1/main.py",
                user_id=1,
            )
        )
        await s.execute(
            insert(schedules).values(
                script_id=1,
                kind="interval",
                expression="5m",
                next_run_at=now,
                overlap_policy=overlap_policy,
                queue_max=queue_max,
            )
        )
        await s.commit()


async def _mark_running(Sf, script_id=1):
    from kindling.db.models import runs

    now = datetime.now(timezone.utc).isoformat()
    async with Sf() as s:
        await s.execute(
            insert(runs).values(
                script_id=script_id,
                status="running",
                started_at=now,
            )
        )
        await s.commit()


class _FakeEnv:
    def decrypt_lines(self, *a, **kw):
        return {}


@pytest.mark.asyncio
async def test_overlap_skip_creates_skipped_run(tmp_path):
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    await _setup_due_schedule(Sf, overlap_policy="skip")
    await _mark_running(Sf)

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    await _tick(
        settings=settings,
        session_factory=Sf,
        log_broker=broker,
        env_service=_FakeEnv(),
        concurrency=sem,
        storage_dir=tmp_path / "s",
        app=None,
    )

    async with Sf() as s:
        rows = (
            await s.execute(text("SELECT status, skip_reason FROM runs ORDER BY id"))
        ).all()
    statuses = [(r[0], r[1]) for r in rows]
    assert ("skipped", "overlap") in statuses


@pytest.mark.asyncio
async def test_overlap_queue_creates_pending_then_drops(tmp_path):
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    await _setup_due_schedule(Sf, overlap_policy="queue", queue_max=2)
    await _mark_running(Sf)

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    # Tick three times: cap=2, so the third tick must drop with
    # queue_dropped incremented. Re-arm next_run_at between ticks so
    # the schedule remains due (cursor advances during _tick).
    for _ in range(3):
        async with Sf() as s:
            now_rearm = datetime.now(timezone.utc).isoformat()
            await s.execute(
                text("UPDATE schedules SET next_run_at = :n WHERE id = 1"),
                {"n": now_rearm},
            )
            await s.commit()
        await _tick(
            settings=settings,
            session_factory=Sf,
            log_broker=broker,
            env_service=_FakeEnv(),
            concurrency=sem,
            storage_dir=tmp_path / "s",
            app=None,
        )

    async with Sf() as s:
        statuses = (await s.execute(text("SELECT status FROM runs"))).all()
        dropped = (
            await s.execute(
                text("SELECT queue_dropped FROM schedules WHERE id=1")
            )
        ).first()
    s_list = [r[0] for r in statuses]
    assert s_list.count("pending") == 2
    assert s_list.count("skipped") == 1
    assert dropped[0] == 1


# ---- Final-review fix M2: tz-aware cursor advance in _tick ----

@pytest.mark.asyncio
async def test_tick_advances_cursor_with_timezone(tmp_path):
    """A cron schedule with timezone=America/New_York gets a cursor that
    reflects NY time math (UTC-4 in August → 13:00 UTC for 09:00 local),
    not the bare croniter math that ignores the timezone column.
    """
    from zoneinfo import ZoneInfo

    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)

    from kindling.db.models import schedules, scripts, users

    # Pin next_run_at to a known UTC instant and pick a cron that, under
    # naive croniter math, would fire at 09:00 UTC; under NY time math it
    # must fire at 09:00 NY = 13:00 UTC (EDT, UTC-4).
    after_utc = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    next_run_at = after_utc.isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=next_run_at,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="cron", expression="0 9 * * *",
            next_run_at=next_run_at, timezone="America/New_York",
            overlap_policy="skip", queue_max=10,
        ))
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    await _tick(
        settings=settings, session_factory=Sf, log_broker=broker,
        env_service=_FakeEnv(), concurrency=sem,
        storage_dir=tmp_path / "s", app=None,
    )

    async with Sf() as s:
        row = (await s.execute(text(
            "SELECT next_run_at FROM schedules WHERE id=10"
        ))).first()
    new_next = datetime.fromisoformat(row[0])
    if new_next.tzinfo is None:
        new_next = new_next.replace(tzinfo=timezone.utc)
    # Expected: 09:00 NY on 2026-08-16 = 13:00 UTC (EDT, UTC-4).
    expected = datetime(2026, 8, 16, 13, 0, tzinfo=timezone.utc)
    # The new cursor must be after the original (cursor moved forward).
    assert new_next > after_utc
    # The new cursor must be exactly 13:00 UTC, not 09:00 UTC.
    assert new_next.hour == 13, (
        f"expected 13:00 UTC (NY local 09:00), got {new_next.isoformat()}"
    )
    assert new_next == expected


@pytest.mark.asyncio
async def test_tick_advances_cursor_without_timezone_uses_utc(tmp_path):
    """When timezone is NULL, the cursor uses UTC (the spec default)."""
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)

    from kindling.db.models import schedules, scripts, users

    after_utc = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
    next_run_at = after_utc.isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=next_run_at,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="cron", expression="0 9 * * *",
            next_run_at=next_run_at, timezone=None,
            overlap_policy="skip", queue_max=10,
        ))
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    await _tick(
        settings=settings, session_factory=Sf, log_broker=broker,
        env_service=_FakeEnv(), concurrency=sem,
        storage_dir=tmp_path / "s", app=None,
    )

    async with Sf() as s:
        row = (await s.execute(text(
            "SELECT next_run_at FROM schedules WHERE id=10"
        ))).first()
    new_next = datetime.fromisoformat(row[0])
    if new_next.tzinfo is None:
        new_next = new_next.replace(tzinfo=timezone.utc)
    # No timezone → UTC: 09:00 UTC.
    assert new_next == datetime(2026, 8, 16, 9, 0, tzinfo=timezone.utc)

