"""Tests for migration runner."""
import pytest

from scriptdeck.db.engine import make_engine
from scriptdeck.db.migrations import run_migrations
from scriptdeck.config import Settings


@pytest.mark.asyncio
async def test_run_migrations_creates_tables(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    async with engine.connect() as conn:
        tables = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row[0] for row in tables}
    assert {"scripts", "schedules", "runs", "logs", "users",
            "invites", "script_envs", "script_deps",
            "audit_log", "schema_version"} <= names


@pytest.mark.asyncio
async def test_run_migrations_idempotent(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    await run_migrations(engine)  # second call is a no-op
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT COUNT(*) FROM schema_version"
        )
        assert result.scalar() == 12


@pytest.mark.asyncio
async def test_migration_012_backfills_naive_started_at_to_iso_utc(tmp_db):
    """Migration 012 rewrites naive 'YYYY-MM-DD HH:MM:SS' rows to tz-aware
    ISO-8601 UTC ('+00:00' suffix). Already-tz-aware rows are untouched."""
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    # Apply migrations 1..11 first, insert rows with naive + tz-aware values,
    # then apply migration 012 so its UPDATE backfill sees the rows.
    from scriptdeck.db.migrations import run_migrations_sync
    run_migrations_sync(str(tmp_db))
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO users(id, email, password_hash, role, timezone) "
            "VALUES (1, 'a@b.c', 'x', 'admin', 'UTC')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO scripts(id, user_id, name, language, source_path) "
            "VALUES (1, 1, 's', 'python', 'x.py')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO runs(id, script_id, started_at, status, exit_code) "
            "VALUES (1, 1, '2026-08-17 02:37:01', 'success', 0)"
        )
        await conn.exec_driver_sql(
            "INSERT INTO runs(id, script_id, started_at, status, exit_code) "
            "VALUES (2, 1, '2026-08-17T02:37:01.196009+00:00', 'success', 0)"
        )
    # Reset schema_version to 11 so re-running migrations applies only 012.
    async with engine.begin() as conn:
        await conn.exec_driver_sql("DELETE FROM schema_version WHERE version = 12")
    await run_migrations(engine)
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(
            "SELECT id, started_at FROM runs ORDER BY id"
        )).fetchall()
    assert rows[0][1] == "2026-08-17T02:37:01+00:00"
    assert rows[1][1] == "2026-08-17T02:37:01.196009+00:00"  # unchanged
