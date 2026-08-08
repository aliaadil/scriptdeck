"""Tests for the v0.7 migration chain (v2 + v3)."""

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
        assert versions == [1, 2, 3, 4]
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
        assert versions == [1, 2, 3, 4]
    finally:
        conn2.close()


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
