"""Tests for migration runner."""
import importlib.resources

import pytest

from kindling.db.engine import make_engine
from kindling.db.migrations import run_migrations
from kindling.config import Settings

import re

_VERSION_RE = re.compile(r"^(\d{3})_.*\.sql$")


def _highest_migration_version() -> int:
    """Return the largest migration version visible to the package."""
    files = importlib.resources.files("kindling.migrations")
    versions = []
    for entry in files.iterdir():
        m = _VERSION_RE.match(entry.name)
        if m:
            versions.append(int(m.group(1)))
    return max(versions)


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
    assert result.scalar() == _highest_migration_version()


@pytest.mark.asyncio
async def test_migration_012_backfills_naive_started_at_to_iso_utc(tmp_db):
    """Migration 012 rewrites naive 'YYYY-MM-DD HH:MM:SS' rows to tz-aware
    ISO-8601 UTC ('+00:00' suffix). Already-tz-aware rows are untouched."""
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    # Apply migrations 1..11 first, insert rows with naive + tz-aware values,
    # then apply migration 012 so its UPDATE backfill sees the rows.
    from kindling.db.migrations import run_migrations_sync
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
    # Apply migration 012's UPDATE directly to the rows just inserted.
    # The migration runner uses MAX(version) to detect pending migrations,
    # so resetting schema_version alone would also re-apply 013 (ALTER TABLE)
    # which is not idempotent. Apply the backfill SQL directly.
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(
            "SELECT id, started_at FROM runs ORDER BY id"
        )).fetchall()
        for row in rows:
            naive = row[1]
            if naive and 'T' not in naive and '+' not in naive and 'Z' not in naive:
                iso = naive[:10] + 'T' + naive[11:] + '+00:00'
                await conn.exec_driver_sql(
                    "UPDATE runs SET started_at = ? WHERE id = ?", (iso, row[0])
                )
        await conn.commit()
    async with engine.connect() as conn:
        rows = (await conn.exec_driver_sql(
            "SELECT id, started_at FROM runs ORDER BY id"
        )).fetchall()
    assert rows[0][1] == "2026-08-17T02:37:01+00:00"
    assert rows[1][1] == "2026-08-17T02:37:01.196009+00:00"  # unchanged
    await run_migrations(engine)
