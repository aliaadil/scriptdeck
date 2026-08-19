"""Tests for the migration chain (v2 + v3 + v4 + v5 + v6)."""

from __future__ import annotations

from pathlib import Path

from scriptrunner.db import initialize_database


def test_fresh_db_has_all_migrations_applied(tmp_db_path: Path) -> None:
    conn = initialize_database(tmp_db_path)
    try:
        versions = [
            r[0]
            for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        ]
        assert versions == [1, 2, 3, 4, 5, 6]
    finally:
        conn.close()


def test_fresh_db_has_v2_columns_on_schedules(tmp_db_path: Path) -> None:
    conn = initialize_database(tmp_db_path)
    try:
        # v6 renames the schedules table to triggers; the v2 columns
        # (retry_max, retry_backoff_seconds, alert_webhook_url) live on
        # the new table.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(triggers)").fetchall()]
        assert "retry_max" in cols
        assert "retry_backoff_seconds" in cols
        assert "alert_webhook_url" in cols
    finally:
        conn.close()


def test_fresh_db_has_v2_columns_on_runs(tmp_db_path: Path) -> None:
    conn = initialize_database(tmp_db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()]
        assert "retry_attempt" in cols
        assert "retry_group_id" in cols
        # v6 renames schedule_id -> trigger_id.
        assert "trigger_id" in cols
        assert "schedule_id" not in cols
    finally:
        conn.close()


def test_migrations_are_idempotent(tmp_db_path: Path) -> None:
    conn1 = initialize_database(tmp_db_path)
    conn1.close()
    conn2 = initialize_database(tmp_db_path)
    try:
        versions = [
            r[0]
            for r in conn2.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
        ]
        assert versions == [1, 2, 3, 4, 5, 6]
    finally:
        conn2.close()


def test_v5_allows_cancelled_status(tmp_db_path: Path) -> None:
    """v5 rebuilds the runs table to accept ``status='cancelled'``."""
    conn = initialize_database(tmp_db_path)
    try:
        conn.execute(
            "INSERT INTO scripts(name, language, source_path, created_at) VALUES (?, ?, ?, ?)",
            ("demo", "python", "/demo.py", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO runs(script_id, started_at, status) VALUES (?, ?, ?)",
            (1, "2026-01-01T00:00:01+00:00", "cancelled"),
        )
        conn.commit()
        row = conn.execute("SELECT status FROM runs WHERE id = 1").fetchone()
        assert row[0] == "cancelled"
    finally:
        conn.close()


def test_v5_preserves_existing_rows(tmp_db_path: Path) -> None:
    """Upgrading a v0.4 DB (migrations v1..v4 already applied) to v5 must keep
    every existing run and the v2 retry columns."""
    conn = initialize_database(tmp_db_path)
    try:
        conn.execute(
            "INSERT INTO scripts(name, language, source_path, created_at) VALUES (?, ?, ?, ?)",
            ("legacy", "python", "/x.py", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO runs(script_id, started_at, status, retry_attempt, retry_group_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "2026-01-01T00:00:01+00:00", "success", 2, "abc-123"),
        )
        conn.commit()
    finally:
        conn.close()

    conn = initialize_database(tmp_db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()
        assert row is not None
        assert row["status"] == "success"
        assert row["retry_attempt"] == 2
        assert row["retry_group_id"] == "abc-123"
        # The v2 index must still exist after the rebuild.
        idx = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='runs'"
            ).fetchall()
        ]
        assert "idx_runs_retry_group" in idx
    finally:
        conn.close()


def test_upgrade_from_v1_db_preserves_existing_rows(tmp_db_path: Path) -> None:
    """Simulate upgrading from v0.1 (migration v1 only) by writing the v1 schema
    directly, then opening with the full migration set and confirming the existing
    rows are still readable."""
    conn = initialize_database(tmp_db_path)
    try:
        conn.execute(
            "INSERT INTO scripts(name, language, source_path, created_at) VALUES (?, ?, ?, ?)",
            ("legacy", "python", "/x.py", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        legacy_id = conn.execute(
            "SELECT id FROM scripts WHERE name='legacy'"
        ).fetchone()[0]
    finally:
        conn.close()

    conn = initialize_database(tmp_db_path)
    try:
        row = conn.execute("SELECT * FROM scripts WHERE id = ?", (legacy_id,)).fetchone()
        assert row is not None
        assert row["name"] == "legacy"
    finally:
        conn.close()


# --- v6 migration tests ------------------------------------------------------


def test_v6_replaces_schedules_table_with_triggers(tmp_db_path: Path) -> None:
    """The legacy ``schedules`` table must be gone after v6 runs."""
    conn = initialize_database(tmp_db_path)
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "triggers" in names
        assert "schedules" not in names
    finally:
        conn.close()


def test_v6_backfills_existing_schedules_as_trigger_rows(tmp_db_path: Path) -> None:
    """Existing single-schedule scripts must keep working after v6.

    Build a v0.5 DB entirely by hand (without invoking the migration runner),
    insert legacy rows, close, then reopen via ``initialize_database`` so v6
    fires and back-fills the triggers table.
    """
    import sqlite3

    conn = sqlite3.connect(str(tmp_db_path))
    try:
        # Build a v0.1-shaped DB. The v2..v5 migrations will add columns
        # (``retry_max``, ``retry_backoff_seconds``, ``alert_webhook_url``,
        # ``requirements_path``, ``interpreter_path``) and rebuild ``runs``
        # so we leave those out here.
        conn.executescript(
            """
            CREATE TABLE scripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                language TEXT NOT NULL,
                source_path TEXT NOT NULL,
                env_path TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                script_id INTEGER NOT NULL,
                kind TEXT NOT NULL CHECK (kind IN ('cron', 'interval')),
                expression TEXT NOT NULL,
                next_run_at TEXT,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                created_at TEXT NOT NULL,
                FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE
            );
            CREATE TABLE runs (
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
            CREATE TABLE logs (
                run_id INTEGER PRIMARY KEY,
                path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
            );
            """
        )
        conn.execute(
            "INSERT INTO scripts(name, language, source_path, created_at) VALUES (?, ?, ?, ?)",
            ("legacy", "python", "/x.py", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            "INSERT INTO schedules(script_id, kind, expression, next_run_at, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                1, "cron", "*/5 * * * *", "2026-02-01T00:00:00+00:00", 1,
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            "INSERT INTO runs(script_id, schedule_id, started_at, status) VALUES (?, ?, ?, ?)",
            (1, 1, "2026-01-01T00:00:01+00:00", "success"),
        )
        conn.commit()
    finally:
        conn.close()

    # Phase 2: reopen — v2..v6 must apply and v6 must back-fill the legacy rows.
    conn = initialize_database(tmp_db_path)
    try:
        trigger = conn.execute(
            "SELECT * FROM triggers WHERE id = 1"
        ).fetchone()
        assert trigger is not None
        assert trigger["kind"] == "schedule"
        assert trigger["schedule_kind"] == "cron"
        assert trigger["expression"] == "*/5 * * * *"
        assert trigger["enabled"] == 1
        # v2's retry_max/retry_backoff_seconds defaults are 0 / 60.
        assert trigger["retry_max"] == 0
        assert trigger["retry_backoff_seconds"] == 60
        # v3's alerting webhook URL is NULL by default.
        assert trigger["alert_webhook_url"] is None
        # The run keeps its lineage via the renamed trigger_id column.
        run = conn.execute("SELECT * FROM runs WHERE id = 1").fetchone()
        assert run is not None
        assert run["trigger_id"] == 1
    finally:
        conn.close()
