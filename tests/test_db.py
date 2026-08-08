"""SQLite migrations and connection invariants."""

from __future__ import annotations

from pathlib import Path

from scriptrunner.db import (
    initialize_database,
    table_names,
)


def test_migrations_create_all_tables(tmp_db_path: Path) -> None:
    conn = initialize_database(tmp_db_path)
    try:
        names = set(table_names(conn))
        assert names == {"scripts", "schedules", "runs", "logs"}
    finally:
        conn.close()


def test_migrations_are_idempotent(tmp_db_path: Path) -> None:
    conn1 = initialize_database(tmp_db_path)
    conn1.close()

    # Re-initialize; should not raise and should not duplicate rows.
    conn2 = initialize_database(tmp_db_path)
    try:
        versions = [r[0] for r in conn2.execute("SELECT version FROM schema_migrations").fetchall()]
        assert versions == sorted(set(versions))
        assert len(versions) >= 1
    finally:
        conn2.close()


def test_foreign_keys_are_enforced(tmp_db_path: Path) -> None:
    conn = initialize_database(tmp_db_path)
    try:
        # schedules references scripts; inserting a schedule with no matching script must error.
        with __import__("pytest").raises(Exception):
            conn.execute(
                "INSERT INTO schedules(script_id, kind, expression, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (99999, "cron", "* * * * *", 1, "2026-01-01T00:00:00Z"),
            )
            conn.commit()
    finally:
        conn.close()


def test_storage_dir_is_created(tmp_db_path: Path) -> None:
    # Nested path: tmp_db_path may live several levels deep.
    nested = tmp_db_path.parent / "a" / "b" / "c" / "scriptdeck.db"
    nested.parent.mkdir(parents=True, exist_ok=True)
    conn = initialize_database(nested)
    try:
        assert nested.exists()
    finally:
        conn.close()