"""Small persistence API over the ScriptRunner SQLite schema.

v0.8 — the trigger model replaces the legacy single-schedule relationship.
A script may now have 0..N triggers; each trigger is either a ``schedule``
(with cron / interval + retry + alerting) or a ``webhook`` (with a unique
URL + secret token). ``runs.schedule_id`` is now ``runs.trigger_id``.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from typing import Any

from .db import utc_now

TRIGGER_KINDS = {"schedule", "webhook"}
SCHEDULE_KINDS = {"cron", "interval"}
RUN_STATUSES = {"running", "success", "failure", "error", "cancelled"}
# Statuses that mean a run has finished — the live log stream should close.
TERMINAL_RUN_STATUSES = {"success", "failure", "error", "cancelled"}
# Statuses that count as fail for retry policy and alerting.
RETRYABLE_STATUSES = {"failure", "error"}

# Webhook tokens are 32 bytes of entropy, hex-encoded — 64 chars. That is
# large enough to be unguessable in practice while still copy-paste friendly.
_WEBHOOK_TOKEN_BYTES = 32
# Sentinel for ``update_trigger`` callers who want to leave a column alone
# without resorting to ``None`` (which is a real value for
# ``alert_webhook_url`` and ``params``).
_UNSET: Any = object()


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _required(value: Any, field: str) -> Any:
    if value is None or value == "":
        raise ValueError(f"{field} is required")
    return value


def _decode_params(raw: str | None) -> dict[str, str]:
    """Return the trigger's params as a plain string dict.

    A NULL or empty string both mean "no overrides" — the runner uses ``{}``
    in that case. Bad JSON raises ``ValueError`` so callers see it during
    creation / editing rather than at run time.
    """
    if raw is None or raw == "":
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("params_json must decode to a JSON object")
    out: dict[str, str] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            raise ValueError("params_json keys must be strings")
        if not isinstance(value, (str, int, float, bool)):
            raise ValueError(
                f"params_json[{key!r}] must be a scalar (string/number/bool)"
            )
        out[key] = str(value)
    return out


def _encode_params(params: dict[str, str] | None) -> str | None:
    """Serialise ``params`` for storage. ``None`` and ``{}`` both become NULL."""
    if not params:
        return None
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def create_script(
    connection: sqlite3.Connection,
    name: str,
    language: str,
    source_path: str,
    env_path: str | None = None,
    requirements_path: str | None = None,
    interpreter_path: str | None = None,
) -> dict[str, Any]:
    _required(name, "name")
    _required(language, "language")
    _required(source_path, "source_path")
    cursor = connection.execute(
        "INSERT INTO scripts(name, language, source_path, env_path, created_at, "
        "requirements_path, interpreter_path) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            name,
            language,
            source_path,
            env_path,
            utc_now(),
            requirements_path,
            interpreter_path,
        ),
    )
    connection.commit()
    return get_script(connection, cursor.lastrowid)  # type: ignore[arg-type]


def get_script(connection: sqlite3.Connection, script_id: int) -> dict[str, Any] | None:
    return _dict(connection.execute("SELECT * FROM scripts WHERE id = ?", (script_id,)).fetchone())


def update_script_interpreter(
    connection: sqlite3.Connection, script_id: int, interpreter_path: str
) -> None:
    """Cache the resolved interpreter on the script row (v0.4)."""
    connection.execute(
        "UPDATE scripts SET interpreter_path = ? WHERE id = ?",
        (interpreter_path, script_id),
    )
    connection.commit()


def list_scripts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return [_dict(row) for row in connection.execute("SELECT * FROM scripts ORDER BY id")]


# ---------------------------------------------------------------- triggers


def _generate_webhook_token(connection: sqlite3.Connection) -> str:
    """Return a unique 64-char hex token.

    Re-rolls on the (vanishingly unlikely) chance the random token collides
    with an existing one. The unique index on ``webhook_token`` is the
    source of truth.
    """
    for _ in range(8):
        token = secrets.token_hex(_WEBHOOK_TOKEN_BYTES)
        existing = connection.execute(
            "SELECT 1 FROM triggers WHERE webhook_token = ?", (token,)
        ).fetchone()
        if existing is None:
            return token
    raise RuntimeError("could not generate a unique webhook token")


def create_schedule_trigger(
    connection: sqlite3.Connection,
    script_id: int,
    kind: str,
    expression: str,
    next_run_at: str | None = None,
    enabled: bool = True,
    retry_max: int = 0,
    retry_backoff_seconds: int = 60,
    alert_webhook_url: str | None = None,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a ``kind='schedule'`` trigger (the generalisation of the old
    ``create_schedule``). All schedule-specific fields are validated here.
    """
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
    # Validate params upfront so bad JSON / wrong types surface here, not at run time.
    encoded_params = _encode_params(params)
    if encoded_params is not None:
        _decode_params(encoded_params)  # round-trip check
    cursor = connection.execute(
        "INSERT INTO triggers(script_id, kind, schedule_kind, expression, "
        "next_run_at, enabled, created_at, retry_max, retry_backoff_seconds, "
        "alert_webhook_url, params_json) "
        "VALUES (?, 'schedule', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            encoded_params,
        ),
    )
    connection.commit()
    return get_trigger(connection, cursor.lastrowid)  # type: ignore[arg-type]


def create_webhook_trigger(
    connection: sqlite3.Connection,
    script_id: int,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a ``kind='webhook'`` trigger and auto-generate its secret token."""
    if get_script(connection, script_id) is None:
        raise ValueError("script_id does not exist")
    encoded_params = _encode_params(params)
    if encoded_params is not None:
        _decode_params(encoded_params)
    token = _generate_webhook_token(connection)
    cursor = connection.execute(
        "INSERT INTO triggers(script_id, kind, webhook_token, params_json, created_at) "
        "VALUES (?, 'webhook', ?, ?, ?)",
        (script_id, token, encoded_params, utc_now()),
    )
    connection.commit()
    return get_trigger(connection, cursor.lastrowid)  # type: ignore[arg-type]


def get_trigger(connection: sqlite3.Connection, trigger_id: int) -> dict[str, Any] | None:
    return _dict(
        connection.execute("SELECT * FROM triggers WHERE id = ?", (trigger_id,)).fetchone()
    )


def get_trigger_by_webhook_token(
    connection: sqlite3.Connection, token: str
) -> dict[str, Any] | None:
    return _dict(
        connection.execute(
            "SELECT * FROM triggers WHERE kind = 'webhook' AND webhook_token = ?",
            (token,),
        ).fetchone()
    )


def list_triggers(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute("SELECT * FROM triggers ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def list_triggers_for_script(
    connection: sqlite3.Connection, script_id: int
) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT * FROM triggers WHERE script_id = ? ORDER BY id", (script_id,)
    ).fetchall()
    return [dict(row) for row in rows]


def update_trigger(
    connection: sqlite3.Connection,
    trigger_id: int,
    *,
    enabled: bool | None = None,
    next_run_at: str | None = None,
    expression: str | None = None,
    retry_max: int | None = None,
    retry_backoff_seconds: int | None = None,
    alert_webhook_url: Any = _UNSET,
    params: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Patch a subset of fields on a trigger. Pass a value to update; pass
    the sentinel ``_UNSET`` to leave a column alone. ``None`` is a valid
    explicit value for ``alert_webhook_url`` and ``params`` (clearing them).

    Schedule-specific fields are silently ignored for webhook triggers.
    """
    if get_trigger(connection, trigger_id) is None:
        return None
    sets: list[str] = []
    args: list[Any] = []
    if enabled is not None:
        sets.append("enabled = ?")
        args.append(int(bool(enabled)))
    if next_run_at is not None:
        sets.append("next_run_at = ?")
        args.append(next_run_at)
    if expression is not None:
        sets.append("expression = ?")
        args.append(expression)
    if retry_max is not None:
        if retry_max < 0:
            raise ValueError("retry_max must not be negative")
        sets.append("retry_max = ?")
        args.append(retry_max)
    if retry_backoff_seconds is not None:
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must not be negative")
        sets.append("retry_backoff_seconds = ?")
        args.append(retry_backoff_seconds)
    # ``alert_webhook_url`` accepts the sentinel so callers can clear it.
    if alert_webhook_url is not _UNSET:
        sets.append("alert_webhook_url = ?")
        args.append(alert_webhook_url)
    if params is not None:
        encoded = _encode_params(params)
        if encoded is not None:
            _decode_params(encoded)
        sets.append("params_json = ?")
        args.append(encoded)
    if not sets:
        return get_trigger(connection, trigger_id)
    args.append(trigger_id)
    connection.execute(
        f"UPDATE triggers SET {', '.join(sets)} WHERE id = ?", tuple(args)
    )
    connection.commit()
    return get_trigger(connection, trigger_id)


def delete_trigger(connection: sqlite3.Connection, trigger_id: int) -> bool:
    cursor = connection.execute("DELETE FROM triggers WHERE id = ?", (trigger_id,))
    connection.commit()
    return cursor.rowcount > 0


def create_run(
    connection: sqlite3.Connection,
    script_id: int,
    trigger_id: int | None = None,
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
        raise ValueError(
            "status must be running, success, failure, error, or cancelled"
        )
    if retry_attempt < 0:
        raise ValueError("retry_attempt must not be negative")
    if get_script(connection, script_id) is None:
        raise ValueError("script_id does not exist")
    if trigger_id is not None and get_trigger(connection, trigger_id) is None:
        raise ValueError("trigger_id does not exist")
    if log_size_bytes < 0:
        raise ValueError("log_size_bytes must not be negative")
    cursor = connection.execute(
        "INSERT INTO runs(script_id, trigger_id, started_at, ended_at, exit_code, status, "
        "log_path, log_size_bytes, retry_attempt, retry_group_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            script_id,
            trigger_id,
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


def list_recent_runs_with_script(
    connection: sqlite3.Connection, limit: int = 50
) -> list[dict[str, Any]]:
    """Return the newest ``limit`` runs joined to their script name.

    Used by the ``/logs`` index page so each row can render the script label
    without a follow-up query per row.
    """
    rows = connection.execute(
        "SELECT runs.*, scripts.name AS script_name "
        "FROM runs LEFT JOIN scripts ON scripts.id = runs.script_id "
        "ORDER BY runs.id DESC LIMIT ?",
        (limit,),
    )
    return [_dict(row) for row in rows]


def list_runs_for_trigger(
    connection: sqlite3.Connection, trigger_id: int
) -> list[dict[str, Any]]:
    return [
        _dict(row)
        for row in connection.execute(
            "SELECT * FROM runs WHERE trigger_id = ? ORDER BY id", (trigger_id,)
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


def trigger_params(trigger: dict[str, Any] | None) -> dict[str, str]:
    """Return the params dict for a trigger, or ``{}`` for None / NULL params."""
    if not trigger:
        return {}
    return _decode_params(trigger.get("params_json"))
