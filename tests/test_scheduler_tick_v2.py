"""Scheduler tick v2: overlap policies (skip / queue / parallel)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, text

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations
from scriptdeck.scheduler.tick import _tick
from scriptdeck.services.log_broker import LogBroker


def _settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )


async def _setup_due_schedule(Sf, *, overlap_policy="skip", queue_max=10):
    from scriptdeck.db.models import schedules, scripts, users

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
    from scriptdeck.db.models import runs

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
