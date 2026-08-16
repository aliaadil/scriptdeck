"""Scheduler tick: pending_retry pickup (Task 5). Task 7 adds the other two tests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, text

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations
from scriptdeck.scheduler.tick import _tick
from scriptdeck.services.log_broker import LogBroker


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

    from scriptdeck.db.models import runs, schedules, scripts, users
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
