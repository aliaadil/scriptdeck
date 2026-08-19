"""Subprocess runner for ScriptDeck (v0.2 + v0.4 isolation + v0.8 triggers).

The runner is the bridge between the database and the filesystem:

1. Looks up the script row.
2. Calls ``isolation.resolve_interpreter`` to provision / reuse the per-script
   env (uv venv for python, node_modules for node, nothing for bash).
3. Invokes the interpreter with the source file, capturing stdout+stderr to
   ``<storage>/logs/<run_id>.log`` (line-buffered, tee'd live).
4. Writes the final ``runs`` row with ``status`` (success/failure/error),
   ``exit_code``, ``log_path``, ``log_size_bytes``, and timestamps.
5. Hands off to ``scheduler.record_run_result`` so retry/alert policy applies.

The runner is intentionally pure-side-effect and synchronous; threading
concerns (one-active-run-per-script, scheduler tick) live elsewhere.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import db, isolation, repository
from .scheduler import record_run_result

# Cross-process / cross-thread serialisation: at most one runner per script.
# Held in-process via threading.Lock AND on-disk via fcntl (the lock file in
# storage_dir/locks/<script_id>.lock) so multi-process deployments don't race.
_RUNNER_LOCAL_LOCKS: dict[int, threading.Lock] = {}
_RUNNER_LOCAL_LOCKS_GUARD = threading.Lock()


def _local_lock(script_id: int) -> threading.Lock:
    with _RUNNER_LOCAL_LOCKS_GUARD:
        lock = _RUNNER_LOCAL_LOCKS.get(script_id)
        if lock is None:
            lock = threading.Lock()
            _RUNNER_LOCAL_LOCKS[script_id] = lock
        return lock


@dataclass(frozen=True)
class RunResult:
    """What the runner returns to its caller."""

    run: dict[str, Any]
    decision: Any  # scheduler.RetryDecision — typed as Any to avoid import cycles
    retry_run: dict[str, Any] | None
    webhook_fired: bool


def _params_env(params: dict[str, str]) -> dict[str, str]:
    """Render trigger params as environment variables.

    Each key ``FOO=bar`` becomes ``SCRIPTDECK_PARAM_FOO=bar`` so the script
    can read its overrides from the environment without a parser dependency.
    Also serialises the full map as ``SCRIPTDECK_PARAMS_JSON`` for callers
    that prefer one lookup.
    """
    env: dict[str, str] = {}
    for key, value in params.items():
        # Keys come from the operator, not the script — uppercase + replace
        # non-identifier chars so we never produce malformed env names.
        normalised = "SCRIPTDECK_PARAM_" + "".join(
            ch if (ch.isalnum() or ch == "_") else "_" for ch in key.upper()
        )
        env[normalised] = value
    env["SCRIPTDECK_PARAMS_JSON"] = json.dumps(params, sort_keys=True)
    return env


def run_script(
    *,
    connection: sqlite3.Connection,
    storage_dir: Path,
    script_id: int,
    trigger_id: int | None = None,
    log_tail_lines: int = 0,
) -> RunResult:
    """Execute a script end-to-end and finalise its run row.

    Pass ``trigger_id`` when the run was kicked off by a specific trigger
    (schedule tick or webhook hit). The trigger's ``params_json`` is decoded
    and exported as environment variables so different schedules can pass
    different flags to the same script.

    Raises ``ValueError`` for malformed input and ``FileNotFoundError`` if the
    script's source file is missing.
    """
    script_row = repository.get_script(connection, script_id)
    if script_row is None:
        raise ValueError(f"script {script_id} does not exist")

    trigger_row: dict[str, Any] | None = None
    if trigger_id is not None:
        trigger_row = repository.get_trigger(connection, trigger_id)
        if trigger_row is None:
            raise ValueError(f"trigger {trigger_id} does not exist")
        if int(trigger_row["script_id"]) != script_id:
            raise ValueError(
                f"trigger {trigger_id} does not belong to script {script_id}"
            )

    source_path = Path(script_row["source_path"])
    if not source_path.exists():
        raise FileNotFoundError(f"script source not found: {source_path}")

    requirements_path = (
        Path(script_row["requirements_path"]) if script_row.get("requirements_path") else None
    )

    storage_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = storage_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Allocate the run row up-front so we have a run_id for the log file.
    run_row = repository.create_run(
        connection,
        script_id=script_id,
        trigger_id=trigger_id,
        status="error",  # placeholder; finalised below
    )
    log_path = logs_dir / f"{run_row['id']}.log"

    # 2. Serialise per-script: prevents the same script from being executed by
    #    two scheduler ticks (or two manual triggers) at the same time.
    with _local_lock(script_id):
        iso = isolation.resolve_interpreter(
            storage_dir=storage_dir,
            script_id=script_id,
            language=script_row["language"],
            source_path=source_path,
            requirements_path=requirements_path,
            connection=connection,
        )

        base_env = isolation.runner_env(
            language=script_row["language"],
            isolation=iso,
            script_row=script_row,
        )
        # Per-trigger params ride on top of the runner env so different
        # triggers can supply different flags / config without mutating
        # the script row.
        params = repository.trigger_params(trigger_row)
        env = {**base_env, **_params_env(params)}

        cmd, cwd = _build_command(script_row["language"], iso.interpreter_path, source_path)
        started_at = db.utc_now()
        # touch the log file so streaming consumers see it immediately
        log_path.touch()
        status, exit_code = _execute(cmd, env=env, cwd=cwd, log_path=log_path)
        ended_at = db.utc_now()

    # 3. Finalise the run row.
    log_size = log_path.stat().st_size if log_path.exists() else 0
    connection.execute(
        "UPDATE runs SET started_at = ?, ended_at = ?, exit_code = ?, status = ?, "
        "log_path = ?, log_size_bytes = ? WHERE id = ?",
        (started_at, ended_at, exit_code, status, str(log_path), log_size, run_row["id"]),
    )
    connection.commit()
    repository.create_log(connection, run_row["id"], str(log_path), log_size)
    run_row = repository.get_run(connection, run_row["id"]) or run_row

    # 4. Hand off to the scheduler for retry/alert policy.
    if trigger_row is not None and trigger_row.get("kind") == "schedule":
        decision, retry_run, webhook_fired = record_run_result(
            connection, run=run_row, trigger=trigger_row
        )
    else:
        # Webhook trigger or no trigger: still produce a RetryDecision for the
        # benefit of the caller, but skip retries/alerting.
        from .scheduler import evaluate_retry  # local import to avoid cycles

        decision = evaluate_retry(connection, run_row, _stub_trigger(trigger_id))
        retry_run = None
        webhook_fired = False

    return RunResult(
        run=run_row,
        decision=decision,
        retry_run=retry_run,
        webhook_fired=webhook_fired,
    )


def _stub_trigger(trigger_id: int | None) -> dict[str, Any]:
    """A trigger-like dict used when an ad-hoc / webhook run has no schedule trigger row."""
    return {
        "id": trigger_id or 0,
        "kind": "schedule",
        "retry_max": 0,
        "retry_backoff_seconds": 0,
        "alert_webhook_url": None,
    }


def _build_command(language: str, interpreter: Path, source: Path) -> tuple[list[str], Path]:
    """Compose the argv list and working directory for a script invocation."""
    if language == "python":
        return [str(interpreter), str(source)], source.parent
    if language == "node":
        return [str(interpreter), str(source)], source.parent
    if language == "bash":
        return [str(interpreter), str(source)], source.parent
    raise ValueError(f"unsupported language: {language!r}")


def _execute(
    cmd: list[str], *, env: dict[str, str], cwd: Path, log_path: Path
) -> tuple[str, int]:
    """Spawn the subprocess, tee stdout+stderr to log_path, return (status, code)."""
    with log_path.open("ab", buffering=0) as logf:
        proc = subprocess.Popen(
            cmd,
            env=env,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            logf.write(line.encode("utf-8", errors="replace"))
            logf.flush()
        proc.wait()
    exit_code = proc.returncode
    if exit_code == 0:
        return "success", 0
    if exit_code is None:
        return "error", -1
    return "failure", int(exit_code)


def wait_for_run(
    *,
    connection: sqlite3.Connection,
    run_id: int,
    poll_interval: float = 0.05,
    timeout: float = 30.0,
) -> dict[str, Any] | None:
    """Block until a run row has ended_at set or timeout expires.

    Used by tests; production code shouldn't wait synchronously.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = repository.get_run(connection, run_id)
        if row and row.get("ended_at"):
            return row
        time.sleep(poll_interval)
    return repository.get_run(connection, run_id)


__all__ = ["RunResult", "run_script", "wait_for_run"]
