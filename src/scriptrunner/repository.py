"""Small persistence API over the ScriptRunner SQLite schema."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any

from .db import utc_now

SCHEDULE_KINDS = {"cron", "interval"}
RUN_STATUSES = {"success", "failure", "error"}
# Statuses that count as fail for retry policy and alerting.
RETRYABLE_STATUSES = {"failure", "error"}


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
    retry_max: int = 0,
    retry_backoff_seconds: int = 60,
    alert_webhook_url: str | None = None,
) -> dict[str, Any]:
    if kind not in SCHEDULE_KINDS:
        raise ValueError("kind must be cron or interval")
    _required(expression, "expression")
    if retry_max < 0:
        raise ValueError("retry_max must not be negative")
    if retry_backoff_seconds < 0:
        raise ValueError("retry_backoff_seconds must not be negative")
    if get_script(connection, script_id) is None:
        raise ValueError("script_id does not exist")
    if alert_webhook_url is not None and not str(alert_webhook_url).strip():
        raise ValueError("alert_webhook_url must not be empty when provided")
    cursor = connection.execute(
        "INSERT INTO schedules(script_id, kind, expression, next_run_at, enabled, created_at, "
        "retry_max, retry_backoff_seconds, alert_webhook_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            script_id,
            kind,
            expression,
            next_run_at,
            int(enabled),
            utc_now(),
            retry_max,
            retry_backoff_seconds,
            alert_webhook_url,
        ),
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
    retry_attempt: int = 0,
    retry_group_id: str | None = None,
) -> dict[str, Any]:
    if status not in RUN_STATUSES:
        raise ValueError("status must be success, failure, or error")
    if retry_attempt < 0:
        raise ValueError("retry_attempt must not be negative")
    if get_script(connection, script_id) is None:
        raise ValueError("script_id does not exist")
    if schedule_id is not None and get_schedule(connection, schedule_id) is None:
        raise ValueError("schedule_id does not exist")
    if log_size_bytes < 0:
        raise ValueError("log_size_bytes must not be negative")
    cursor = connection.execute(
        "INSERT INTO runs(script_id, schedule_id, started_at, ended_at, exit_code, status, "
        "log_path, log_size_bytes, retry_attempt, retry_group_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            script_id,
            schedule_id,
            started_at or utc_now(),
            ended_at,
            exit_code,
            status,
            log_path,
            log_size_bytes,
            retry_attempt,
            retry_group_id,
        ),
    )
    connection.commit()
    return get_run(connection, cursor.lastrowid)  # type: ignore[arg-type]


def get_run(connection: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    return _dict(connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())


def list_runs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_dict(row) for row in connection.execute("SELECT * FROM runs ORDER BY id")]


def list_runs_for_schedule(
    connection: sqlite3.Connection, schedule_id: int
) -> list[dict[str, Any]]:
    return [
        _dict(row)
        for row in connection.execute(
            "SELECT * FROM runs WHERE schedule_id = ? ORDER BY id", (schedule_id,)
        )
    ]


def list_orphaned_runs(
    connection: sqlite3.Connection, older_than_iso: str
) -> list[dict[str, Any]]:
    """Return runs whose `started_at` is older than `older_than_iso` and which never completed."""
    return [
        _dict(row)
        for row in connection.execute(
            "SELECT * FROM runs WHERE ended_at IS NULL AND started_at < ? ORDER BY started_at",
            (older_than_iso,),
        )
    ]


def latest_run_for_group(
    connection: sqlite3.Connection, retry_group_id: str
) -> dict[str, Any] | None:
    return _dict(
        connection.execute(
            "SELECT * FROM runs WHERE retry_group_id = ? ORDER BY id DESC LIMIT 1",
            (retry_group_id,),
        ).fetchone()
    )


def count_runs_in_group(connection: sqlite3.Connection, retry_group_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS n FROM runs WHERE retry_group_id = ?", (retry_group_id,)
    ).fetchone()
    return int(row[0]) if row else 0


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


def new_retry_group_id() -> str:
    """Return a fresh identifier that ties a run + its retries together."""
    return uuid.uuid4().hex
