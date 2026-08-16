from __future__ import annotations

import sqlite3
from pathlib import Path

from scriptdeck.cli_commands.migrate_users import migrate_users_run


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    storage = tmp_path / "storage"
    db = tmp_path / "t.db"
    (storage / "scripts" / "1").mkdir(parents=True)
    (storage / "scripts" / "1" / "hello.py").write_text("print(1)")
    (storage / "envs" / "1").mkdir(parents=True)
    (storage / "venvs" / "1").mkdir(parents=True)
    (storage / "node_modules" / "1").mkdir(parents=True)
    (storage / "logs").mkdir(parents=True)
    (storage / "logs" / "1.log").write_text("log")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT);
        INSERT INTO users VALUES (42, 'admin');
        CREATE TABLE scripts (id INTEGER PRIMARY KEY, user_id INTEGER);
        INSERT INTO scripts VALUES (1, 42);
    """)
    conn.commit()
    return storage, db


def test_migrate_users_dry_run_does_not_move(tmp_path):
    storage, db = _bootstrap(tmp_path)
    rc = migrate_users_run(str(storage), str(db), dry_run=True)
    assert rc == 0
    assert (storage / "scripts" / "1").exists()
    assert not (storage / "users" / "42").exists()


def test_migrate_users_moves_files(tmp_path):
    storage, db = _bootstrap(tmp_path)
    rc = migrate_users_run(str(storage), str(db), dry_run=False)
    assert rc == 0
    assert (storage / "users" / "42" / "scripts" / "1" / "hello.py").exists()
    assert (storage / "users" / "42" / "envs" / "1").exists()
    assert (storage / "users" / "42" / "venvs" / "1").exists()
    assert (storage / "users" / "42" / "node_modules" / "1").exists()
    assert (storage / "users" / "42" / "logs" / "1.log").exists()
    assert not (storage / "scripts" / "1").exists()


def test_migrate_users_is_idempotent(tmp_path):
    storage, db = _bootstrap(tmp_path)
    migrate_users_run(str(storage), str(db), dry_run=False)
    rc = migrate_users_run(str(storage), str(db), dry_run=False)
    assert rc == 0
    assert (storage / "users" / "42" / "scripts" / "1" / "hello.py").exists()