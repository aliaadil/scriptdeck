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
        assert result.scalar() == 8