"""Small persistence API over the ScriptRunner SQLite schema."""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import utc_now

SCHEDULE_KINDS = {"cron", "interval"}
RUN_STATUSES = {"success", "failure", "error"}


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _required(value: Any, field: str) -> Any:
    if value is None or value == "":
        raise ValueError(f"{field} is required")
    return value


def create_script(
    connection: sqlite3.Connection,
    name: str,
    language: str,
    source_path: str,
    env_path: str | None = None,
) -> dict[str, Any]:
    _required(name, "name")
    _required(language, "language")
    _required(source_path, "source_path")
    cursor = connection.execute(
        "INSERT INTO scripts(name, language, source_path, env_path, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, language, source_path, env_path, utc_now()),
    )
    connection.commit()
    return get_script(connection, cursor.lastrowid)  # type: ignore[arg-type]


def get_script(connection: sqlite3.Connection, script_id: int) -> dict[str, Any] | None:
    return _dict(connection.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone())


def list_scripts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_dict(row) for row in connection.execute("SELECT * FROM scripts ORDER BY id")]


def create_schedule(
    connection: sqlite3.Connection,
    script_id: int,
    kind: str,
    expression: str,
    next_run_at: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    if kind not in SCHEDULE_KINDS:
        raise ValueError("kind must be cron or interval")
    _required(expression, "expression")
    if get_script(connection, script_id) is None:
        raise ValueError("script_id does not exist")
    cursor = connection.execute(
        "INSERT INTO schedules(script_id, kind, expression, next_run_at, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (script_id, kind, expression, next_run_at, int(enabled), utc_now()),
    )
    connection.commit()
    return get_schedule(connection, cursor.lastrowid)  # type: ignore[arg-type]


def get_schedule(connection: sqlite3.Connection, schedule_id: int) -> dict[str, Any] | None:
    return _dict(
        connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    )


def list_schedules(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_dict(row) for row in connection.execute("SELECT * FROM schedules ORDER BY id")]


def create_run(
    connection: sqlite3.Connection,
    script_id: int,
    schedule_id: int | None = None,
    *,
    started_at: str | None = None,
    ended_at: str | None = None,
    exit_code: int | None = None,
    status: str = "error",
    log_path: str | None = None,
    log_size_bytes: int = 0,
) -> dict[str, Any]:
    if status not in RUN_STATUSES:
        raise ValueError("status must be success, failure, or error")
    if get_script(connection, script_id) is None:
        raise ValueError("script_id does not exist")
    if schedule_id is not None and get_schedule(connection, schedule_id) is None:
        raise ValueError("schedule_id does not exist")
    if log_size_bytes < 0:
        raise ValueError("log_size_bytes must not be negative")
    cursor = connection.execute(
        "INSERT INTO runs(script_id, schedule_id, started_at, ended_at, exit_code, status, "
        "log_path, log_size_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            script_id,
            schedule_id,
            started_at or utc_now(),
            ended_at,
            exit_code,
            status,
            log_path,
            log_size_bytes,
        ),
    )
    connection.commit()
    return get_run(connection, cursor.lastrowid)  # type: ignore[arg-type]


def get_run(connection: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    return _dict(connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())


def list_runs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_dict(row) for row in connection.execute("SELECT * FROM runs ORDER BY id")]


def create_log(
    connection: sqlite3.Connection, run_id: int, path: str, size_bytes: int = 0
) -> dict[str, Any]:
    _required(path, "path")
    if size_bytes < 0:
        raise ValueError("size_bytes must not be negative")
    if get_run(connection, run_id) is None:
        raise ValueError("run_id does not exist")
    connection.execute(
        "INSERT INTO logs(run_id, path, size_bytes) VALUES (?, ?, ?)",
        (run_id, path, size_bytes),
    )
    connection.commit()
    return _dict(
        connection.execute("SELECT * FROM logs WHERE run_id = ?", (run_id,)).fetchone()
    )  # type: ignore[return-value]


def get_log(connection: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    return _dict(connection.execute("SELECT * FROM logs WHERE run_id = ?", (run_id,)).fetchone())
