"""SQLite connection and reproducible migrations for ScriptRunner."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

DBPath = str | Path

MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS scripts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        language TEXT NOT NULL,
        source_path TEXT NOT NULL,
        env_path TEXT,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS schedules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        script_id INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('cron', 'interval')),
        expression TEXT NOT NULL,
        next_run_at TEXT,
        enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
        created_at TEXT NOT NULL,
        FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        script_id INTEGER NOT NULL,
        schedule_id INTEGER,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        exit_code INTEGER,
        status TEXT NOT NULL CHECK (status IN ('success', 'failure', 'error')),
        log_path TEXT,
        log_size_bytes INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE,
        FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS logs (
        run_id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
    );
    """,
    2: """
    -- Retry policy on schedules + per-run tracking of which retry cycle a run belongs to.
    ALTER TABLE schedules ADD COLUMN retry_max INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE schedules ADD COLUMN retry_backoff_seconds INTEGER NOT NULL DEFAULT 60;
    ALTER TABLE runs ADD COLUMN retry_attempt INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE runs ADD COLUMN retry_group_id TEXT;
    CREATE INDEX IF NOT EXISTS idx_runs_retry_group ON runs(retry_group_id);
    """,
    3: """
    -- Alerting webhook URL on a schedule. NULL means no alert.
    ALTER TABLE schedules ADD COLUMN alert_webhook_url TEXT;
    """,
    4: """
    -- Per-script isolation (v0.4): surface the uploaded requirements file path
    -- alongside source_path so the runner can find it without rediscovering.
    ALTER TABLE scripts ADD COLUMN requirements_path TEXT;
    -- interpreter_path is a derived/cached value: it points at the resolved
    -- executable for the script (venv python, node binary, or bash itself).
    -- NULL until first run provisions it.
    ALTER TABLE scripts ADD COLUMN interpreter_path TEXT;
    """,
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect(db_path: DBPath) -> sqlite3.Connection:
    """Open a configured connection with row dictionaries and FK enforcement."""
    # The built-in HTTP server handles requests on worker threads while sharing
    # this one local connection. SQLite serializes writes; disabling the Python
    # thread-affinity guard lets the service use that connection safely.
    connection = sqlite3.connect(str(db_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(db_path: DBPath) -> sqlite3.Connection:
    """Apply all migrations and return an initialized connection."""
    path = Path(db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(db_path)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    applied = {
        row[0]
        for row in connection.execute("SELECT version FROM schema_migrations")
    }
    for version, sql in sorted(MIGRATIONS.items()):
        if version in applied:
            continue
        with connection:
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, utc_now()),
            )
    return connection


def table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations'"
    )
    return [row[0] for row in rows]
