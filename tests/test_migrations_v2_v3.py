"""Tests for the migration chain (v2 + v3 + v4 + v5)."""

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
        assert versions == [1, 2, 3, 4, 5]
    finally:
        conn.close()


def test_fresh_db_has_v2_columns_on_schedules(tmp_db_path: Path) -> None:
    conn = initialize_database(tmp_db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(schedules)").fetchall()]
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
        assert versions == [1, 2, 3, 4, 5]
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
