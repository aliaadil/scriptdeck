from __future__ import annotations

import importlib.resources
import logging
import re
import sqlite3
from pathlib import Path

from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)

VERSION_RE = re.compile(r"^(\d{3})_.*\.sql$")


def _migration_files() -> list[tuple[int, str]]:
    files: list[tuple[int, str]] = []
    pkg = importlib.resources.files("kindling.migrations")
    for entry in pkg.iterdir():
        name = entry.name
        m = VERSION_RE.match(name)
        if m:
            files.append((int(m.group(1)), str(entry)))
    files.sort()
    return files


def _read_sql(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def run_migrations_sync(db_path: str) -> None:
    """Apply pending migrations synchronously via sqlite3.

    Used by `create_app` to eagerly bootstrap the schema without needing an
    event loop, so tests using ASGITransport (no lifespan) see the schema.
    Idempotent.
    """
    db_file = Path(db_path)
    # sqlite3.connect will not create the parent directory; bare-Python
    # boots (no Docker compose volume mount prepping ./data) would fail
    # with `unable to open database file`. Idempotent.
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    try:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        current = row[0] if row and row[0] is not None else 0
        for version, path in _migration_files():
            if version <= current:
                continue
            log.info("applying migration %03d from %s", version, path)
            conn.executescript(_read_sql(path))
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
        conn.commit()
    finally:
        conn.close()


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply pending migrations in order, tracked in schema_version table."""
    # Mirror run_migrations_sync: ensure the parent directory exists. aiosqlite
    # won't create it and aiosqlite connect also fails on missing dirs.
    parsed = make_url(engine.url.render_as_string(hide_password=False))
    if parsed.drivername.startswith("sqlite") and parsed.database:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        result = await conn.exec_driver_sql("SELECT MAX(version) FROM schema_version")
        row = result.first()
        current = row[0] if row and row[0] is not None else 0

    for version, path in _migration_files():
        if version <= current:
            continue
        log.info("applying migration %03d from %s", version, path)
        sql = _read_sql(path)
        async with engine.begin() as conn:
            # aiosqlite rejects multi-statement strings via exec_driver_sql;
            # use the underlying connection's executescript() instead.
            raw = await conn.get_raw_connection()
            await raw.driver_connection.executescript(sql)
            await conn.exec_driver_sql(
                "INSERT INTO schema_version (version) VALUES (:v)",
                {"v": version},
            )
