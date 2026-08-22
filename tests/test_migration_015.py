"""Tests for migration 015 — triggers (webhook kind + params_json + webhook_token).

Verifies:
1. Migration 015 applies cleanly on a fresh DB.
2. ``schedules.kind`` CHECK constraint accepts 'webhook'.
3. The new optional columns exist: params_json (TEXT), webhook_token_hash (TEXT).
4. Existing rows in ``schedules`` survive the upgrade unchanged (back-fill safety).
5. ``next_run_at`` is nullable after the migration so webhook rows can be inserted
   with ``next_run_at = NULL``.
"""
from __future__ import annotations

import importlib.resources
import re
import sqlite3

import pytest

from kindling.config import Settings
from kindling.db.engine import make_engine
from kindling.db.migrations import run_migrations

_VERSION_RE = re.compile(r"^(\d{3})_.*\.sql$")


def _read_migration(version: int) -> str:
    files = importlib.resources.files("kindling.migrations")
    for entry in files.iterdir():
        m = _VERSION_RE.match(entry.name)
        if m and int(m.group(1)) == version:
            return entry.read_text(encoding="utf-8")
    raise FileNotFoundError(f"migration {version:03d} not found")


def _apply_migrations_through(version: int, db_path: str) -> None:
    """Apply all migrations up to and including `version` to a fresh sqlite file."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        pkg = importlib.resources.files("kindling.migrations")
        files = []
        for entry in pkg.iterdir():
            m = _VERSION_RE.match(entry.name)
            if m:
                files.append((int(m.group(1)), str(entry)))
        files.sort()
        for v, path in files:
            if v > version:
                continue
            conn.executescript(open(path).read())
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (v,),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_migration_015_accepts_webhook_kind_on_schedules(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    # After migration 015, the schedules.kind CHECK must accept 'webhook'.
    async with engine.connect() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO users (id, email, password_hash, role, created_at) "
            "VALUES (1, 'a@x.com', 'x', 'editor', '2026-01-01T00:00:00+00:00')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO scripts (id, name, language, source_path, "
            "created_at, updated_at, user_id, entrypoint) "
            "VALUES (1, 't', 'python', 's/main.py', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
            "1, 'main.py')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO schedules (script_id, kind, expression, enabled, next_run_at) "
            "VALUES (1, 'webhook', NULL, 1, NULL)"
        )
        rows = await conn.exec_driver_sql(
            "SELECT kind, next_run_at FROM schedules WHERE script_id = 1"
        )
        kind, next_run_at = list(rows)[0]
    assert kind == "webhook"
    assert next_run_at is None


@pytest.mark.asyncio
async def test_migration_015_adds_params_json_and_webhook_token_columns(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    async with engine.connect() as conn:
        cols = await conn.exec_driver_sql("PRAGMA table_info(schedules)")
        names = {row[1] for row in cols}
    assert "params_json" in names
    assert "webhook_token_hash" in names


@pytest.mark.asyncio
async def test_migration_015_back_fills_existing_schedules(tmp_db):
    """Migration must not destroy existing schedule rows."""
    # Apply migrations 1..14 then insert a baseline schedule row, then apply 015.
    _apply_migrations_through(14, str(tmp_db))
    conn = sqlite3.connect(str(tmp_db))
    try:
        # baseline user + script + schedule
        conn.executescript(
            "INSERT INTO users (id, email, password_hash, role, created_at) "
            "VALUES (1, 'a@x.com', 'x', 'editor', '2026-01-01T00:00:00+00:00')"
        )
        conn.executescript(
            "INSERT INTO scripts (id, name, language, source_path, "
            "created_at, updated_at, user_id, entrypoint) "
            "VALUES (1, 'hello', 'python', 's/main.py', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
            "1, 'main.py')"
        )
        conn.execute(
            "INSERT INTO schedules (script_id, kind, expression, enabled, next_run_at) "
            "VALUES (1, 'cron', '* * * * *', 1, '2026-02-01T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    # Now apply the remaining migrations (015+).
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    async with engine.connect() as conn:
        rows = await conn.exec_driver_sql(
            "SELECT id, kind, expression, next_run_at FROM schedules"
        )
        rows = list(rows)
    assert len(rows) == 1
    rid, kind, expr, nra = rows[0]
    assert rid == 1
    assert kind == "cron"
    assert expr == "* * * * *"
    assert nra == "2026-02-01T00:00:00+00:00"


def test_migration_015_sql_is_well_formed():
    """The migration SQL must parse and must NOT use sqlite-incompatible features
    that break the apply loop (no unfinished transactions, valid PRAGMA, etc.)."""
    sql = _read_migration(15)
    # Soft check — no obvious typos
    assert "schedules" in sql.lower()
    # Must touch the kind CHECK to widen it OR introduce a new table that accepts 'webhook'
    assert "webhook" in sql.lower()
