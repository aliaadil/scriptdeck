"""Tests that list_due never returns webhook rows.

Webhook triggers have next_run_at = NULL and are only enqueued via HTTP,
so the scheduler tick should never see them.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from kindling.config import Settings
from kindling.db.engine import make_engine
from kindling.db.migrations import run_migrations
from kindling.db.models import schedules, scripts, users
from kindling.services.schedule_service import list_due


@pytest.mark.asyncio
async def test_list_due_excludes_webhook_rows(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    # Seed: one user, one script, one due cron row, one due (in name only)
    # webhook row whose next_run_at is NULL, and one interval row.
    async with engine.begin() as conn:
        await conn.execute(insert(users).values(
            id=1, email="a@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await conn.execute(insert(scripts).values(
            id=10, name="t", language="python",
            source_path="s/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            user_id=1, entrypoint="main.py",
        ))
        await conn.execute(insert(schedules).values(
            script_id=10, kind="cron", expression="* * * * *",
            enabled=1, next_run_at="2026-01-01T00:00:00+00:00",
        ))
        await conn.execute(insert(schedules).values(
            script_id=10, kind="interval", expression="5m",
            enabled=1, next_run_at="2026-01-01T00:00:00+00:00",
        ))
        await conn.execute(insert(schedules).values(
            script_id=10, kind="webhook", expression=None,
            enabled=1, next_run_at=None,
        ))
    # Now ask list_due for everything due as of 2027-01-01 — both cron and
    # interval rows are due; the webhook row has NULL next_run_at and must
    # NOT appear.
    async with engine.connect() as conn:
        from kindling.db.engine import session_factory
        Session = session_factory(engine)
        async with Session() as session:
            due = await list_due(session, datetime(2027, 1, 1, tzinfo=UTC))
    kinds = sorted(r["kind"] for r in due)
    assert kinds == ["cron", "interval"]
    # And explicit assertion that webhook is excluded
    assert all(r["kind"] != "webhook" for r in due)


@pytest.mark.asyncio
async def test_list_due_excludes_disabled_rows(tmp_db):
    """Disabled cron/interval rows must also be excluded."""
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    async with engine.begin() as conn:
        await conn.execute(insert(users).values(
            id=1, email="a@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await conn.execute(insert(scripts).values(
            id=10, name="t", language="python",
            source_path="s/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
            user_id=1, entrypoint="main.py",
        ))
        await conn.execute(insert(schedules).values(
            script_id=10, kind="cron", expression="* * * * *",
            enabled=0, next_run_at="2026-01-01T00:00:00+00:00",
        ))
    async with engine.connect() as conn:
        from kindling.db.engine import session_factory
        Session = session_factory(engine)
        async with Session() as session:
            due = await list_due(session, datetime(2027, 1, 1, tzinfo=UTC))
    assert due == []
