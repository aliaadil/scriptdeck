"""Scheduler tick: pending_retry pickup (Task 5). Task 7 adds executor retry.
Final-review fix: C1 — retry_group ULID chain identity."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, text

from kindling.config import Settings
from kindling.db.engine import make_engine, session_factory
from kindling.db.migrations import run_migrations
from kindling.scheduler.tick import _execute_and_finalize, _tick
from kindling.runner.executor import Script
from kindling.services.log_broker import LogBroker
from kindling.services.run_service import create_run


@pytest.mark.asyncio
async def test_pending_retry_runs_after_next_attempt_at(tmp_path):
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

    from kindling.db.models import runs, schedules, scripts, users
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=past,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python", source_path="scripts/1/main.py",
            user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="interval", expression="5m",
            next_run_at=future, retry_max=3, retry_backoff=60,
        ))
        # One run already in pending_retry, due now.
        await s.execute(insert(runs).values(
            script_id=1, schedule_id=10, status="pending_retry",
            started_at=past, next_attempt_at=past, attempt=1,
            retry_group="01TEST",
        ))
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    await _tick(
        settings=settings, session_factory=Sf, log_broker=broker,
        env_service=FakeEnv(), concurrency=sem,
        storage_dir=tmp_path / "s", app=None,
    )
    await asyncio.sleep(2)

    async with Sf() as s:
        rows = (await s.execute(text(
            "SELECT status FROM runs WHERE retry_group='01TEST'"
        ))).all()
    statuses = [r[0] for r in rows]
    assert "success" in statuses


@pytest.mark.asyncio
async def test_failure_with_retry_marks_pending_retry(tmp_path):
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

    from kindling.db.models import runs, schedules, scripts, users
    now = datetime.now(timezone.utc).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("import sys; sys.exit(1)\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=now,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="interval", expression="5m",
            next_run_at=now, retry_max=3, retry_backoff=60,
        ))
        await s.execute(insert(runs).values(
            script_id=1, schedule_id=10, status="running",
            started_at=now, attempt=0, retry_group="01ABC",
        ))
        run_id = (await s.execute(text("SELECT id FROM runs LIMIT 1"))).first()[0]
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    # Drive the executor directly to avoid touching the tick loop.
    script = Script(
        id=1, user_id=1, name="t", language="python",
        source_path=tmp_path / "s" / "scripts" / "1" / "main.py",
        requirements=[],
    )
    await _execute_and_finalize(
        run_id=run_id, script=script, env_service=FakeEnv(),
        log_broker=broker, concurrency=sem,
        storage_dir=tmp_path / "s", session_factory=Sf,
    )

    async with Sf() as s:
        row = (await s.execute(text(
            "SELECT status, attempt, next_attempt_at FROM runs WHERE id=:i"
        ), {"i": run_id})).first()
    assert row[0] == "pending_retry"
    assert row[1] == 1
    assert row[2] is not None


@pytest.mark.asyncio
async def test_failure_with_retry_exhausted_marks_failure(tmp_path):
    # Same setup but retry_max=0.
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

    from kindling.db.models import runs, schedules, scripts, users
    now = datetime.now(timezone.utc).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("import sys; sys.exit(1)\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=now,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="interval", expression="5m",
            next_run_at=now, retry_max=0, retry_backoff=0,
        ))
        await s.execute(insert(runs).values(
            script_id=1, schedule_id=10, status="running",
            started_at=now, attempt=0, retry_group="01DEF",
        ))
        run_id = (await s.execute(text("SELECT id FROM runs LIMIT 1"))).first()[0]
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    script = Script(
        id=1, user_id=1, name="t", language="python",
        source_path=tmp_path / "s" / "scripts" / "1" / "main.py",
        requirements=[],
    )
    await _execute_and_finalize(
        run_id=run_id, script=script, env_service=FakeEnv(),
        log_broker=broker, concurrency=sem,
        storage_dir=tmp_path / "s", session_factory=Sf,
    )

    async with Sf() as s:
        status = (await s.execute(text(
            "SELECT status FROM runs WHERE id=:i"
        ), {"i": run_id})).first()[0]
    assert status == "failure"


# ---- Final-review fix C1: retry_group ULID chain identity ----

@pytest.mark.asyncio
async def test_create_run_returns_nonempty_retry_group(tmp_path):
    """create_run returns a non-empty retry_group ULID; the DB row stores it.

    Chain identity so GET /api/kindling/runs?group=<retry_group> finds the run.
    """
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

    from kindling.db.models import runs, scripts, users
    now = datetime.now(timezone.utc).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=now,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.commit()

    async with Sf() as s:
        run_id, _started, retry_group = await create_run(
            s, script_id=1, schedule_id=None
        )
        await s.commit()

    assert retry_group is not None
    assert isinstance(retry_group, str)
    assert len(retry_group) > 0

    async with Sf() as s:
        row = (await s.execute(text(
            "SELECT retry_group FROM runs WHERE id=:i"
        ), {"i": run_id})).first()
    assert row[0] == retry_group


@pytest.mark.asyncio
async def test_create_run_explicit_retry_group_is_preserved(tmp_path):
    """When caller passes retry_group, the row gets that exact value."""
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

    from kindling.db.models import runs, scripts, users
    now = datetime.now(timezone.utc).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="owner@example.com", password_hash="x" * 32,
            role="admin", created_at=now,
        ))
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.commit()

    async with Sf() as s:
        run_id, _started, retry_group = await create_run(
            s, script_id=1, schedule_id=None, retry_group="CHAIN-123"
        )
        await s.commit()

    assert retry_group == "CHAIN-123"
    async with Sf() as s:
        row = (await s.execute(text(
            "SELECT retry_group FROM runs WHERE id=:i"
        ), {"i": run_id})).first()
    assert row[0] == "CHAIN-123"
