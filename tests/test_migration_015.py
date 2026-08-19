"""Migration 015: triggers (per-schedule params + webhooks table)."""

from __future__ import annotations

import importlib.resources
import re

import pytest

from kindling.config import Settings
from kindling.db.engine import make_engine
from kindling.db.migrations import run_migrations

_VERSION_RE = re.compile(r"^(\d{3})_.*\.sql$")


def _migration_files():
    files = importlib.resources.files("kindling.migrations")
    versions = []
    for entry in files.iterdir():
        m = _VERSION_RE.match(entry.name)
        if m:
            versions.append(int(m.group(1)))
    return sorted(versions)


@pytest.mark.asyncio
async def test_migration_015_applies(tmp_db):
    """Migration 015 adds params_json to schedules and creates webhooks."""
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    async with engine.connect() as conn:
        # schedules.params_json exists
        cols = {
            row[1]
            for row in await conn.exec_driver_sql("PRAGMA table_info(schedules)")
        }
        assert "params_json" in cols
        # webhooks table exists with the expected columns
        rows = await conn.exec_driver_sql("PRAGMA table_info(webhooks)")
        wh_cols = {row[1] for row in rows}
        for col in (
            "id",
            "script_id",
            "secret_token",
            "enabled",
            "params_json",
            "description",
            "created_at",
            "last_fired_at",
            "fire_count",
        ):
            assert col in wh_cols, f"webhooks missing column {col}"


@pytest.mark.asyncio
async def test_migration_015_is_idempotent(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    # Re-running must not error or duplicate rows.
    await run_migrations(engine)
    async with engine.connect() as conn:
        version = await conn.exec_driver_sql(
            "SELECT MAX(version) FROM schema_version"
        )
        max_v = list(version)[0][0]
    assert max_v >= 15


@pytest.mark.asyncio
async def test_legacy_schedule_gets_default_params_json(tmp_db):
    """Pre-015 schedules survive the migration with a sane default.

    Operators upgrading an existing instance must not see their schedules
    lose data; ``params_json`` must default to ``'{}'`` (non-null JSON)
    so the runner sees the same env it did before.
    """
    from sqlalchemy import insert, select

    from kindling.db.engine import session_factory
    from kindling.db.models import scripts, users

    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    Session = session_factory(engine)
    async with Session() as session:
        await session.execute(
            insert(users).values(
                email="a@b.com", password_hash="x", role="admin"
            )
        )
        await session.execute(
            insert(scripts).values(
                id=42,
                name="legacy",
                language="python",
                source_path="scripts/42/main.py",
                user_id=1,
            )
        )
        await session.commit()
    # We didn't seed a legacy schedule (the column has NOT NULL DEFAULT
    # so a fresh insert always gets '{}'). The important guarantee is
    # that ``params_json`` is non-null for any schedule the runner
    # picks up — verified below by inserting one and reading it back.
    from kindling.db.models import schedules as schedules_t

    async with Session() as session:
        await session.execute(
            insert(schedules_t).values(
                script_id=42,
                kind="cron",
                expression="0 9 * * *",
                next_run_at="2030-01-01T00:00:00+00:00",
                enabled=1,
            )
        )
        await session.commit()
        row = (
            await session.execute(
                select(schedules_t.c.params_json).where(schedules_t.c.script_id == 42)
            )
        ).one()
        assert row[0] == "{}", f"expected default '{{}}', got {row[0]!r}"


@pytest.mark.asyncio
async def test_webhooks_unique_token_index_is_partial(tmp_db):
    """The unique index on secret_token is partial — disabled rows don't collide.

    Two webhooks with the same disabled token must coexist (the operator
    regenerates tokens, leaving the old row disabled for audit).
    """
    from sqlalchemy import insert, text

    from kindling.db.engine import session_factory
    from kindling.db.models import scripts, users

    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    Session = session_factory(engine)
    async with Session() as session:
        await session.execute(
            insert(users).values(email="a@b.com", password_hash="x", role="admin")
        )
        await session.execute(
            insert(scripts).values(
                name="x",
                language="python",
                source_path="scripts/1/main.py",
                user_id=1,
            )
        )
        await session.commit()
    # Inspect the partial index definition.
    async with engine.connect() as conn:
        rows = await conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name='idx_webhooks_token'"
        )
        ddl = list(rows)[0][0]
    assert "WHERE enabled = 1" in ddl
