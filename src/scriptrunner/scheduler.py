"""Scheduler tick helpers for ScriptRunner.

The runner itself is not yet built (v0.2 Kanban card); this module provides the
pure-data pieces around it: retry policy enforcement and the firing of the
alerting webhook when a retry cycle exhausts.

Concrete flow:

1. The runner (or a test) reports a run finishing by calling
   ``record_run_result(...)`` with the final ``status``, ``exit_code``, etc.
2. For status in ``failure``/``error`` and a schedule with ``retry_max > 0``,
   a new run row is created with the same ``retry_group_id`` and an incremented
   ``retry_attempt``. The caller is responsible for actually executing it.
3. If retries are exhausted, the alerting webhook fires (best-effort).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from . import repository
from .alerting import build_alert_payload, post_alert
from .db import utc_now


@dataclass(frozen=True)
class RetryDecision:
    """The result of evaluating a finished run's retry state."""

    should_retry: bool
    next_attempt: int
    exhausted: bool  # True when webhook should fire (final failure)
    retry_group_id: str


def _group_id_for_run(run: dict[str, Any]) -> str:
    """Return the retry group id for a run, generating one if missing."""
    group_id = run.get("retry_group_id")
    if group_id:
        return str(group_id)
    return repository.new_retry_group_id()


def evaluate_retry(
    connection: sqlite3.Connection,
    run: dict[str, Any],
    schedule: dict[str, Any],
) -> RetryDecision:
    """Decide whether a finished run should be retried.

    Generates and persists a ``retry_group_id`` on the run if it doesn't already
    have one, so retries of the same cycle all share the id.
    """
    status = run["status"]
    if status not in repository.RETRYABLE_STATUSES:
        return RetryDecision(False, 0, False, run.get("retry_group_id") or _group_id_for_run(run))

    retry_max = int(schedule.get("retry_max") or 0)
    group_id = _group_id_for_run(run)

    # If the run row does not yet have a retry_group_id, write one so the
    # retry that follows inherits the same id.
    if not run.get("retry_group_id"):
        connection.execute(
            "UPDATE runs SET retry_group_id = ? WHERE id = ?",
            (group_id, run["id"]),
        )
        connection.commit()

    # How many times have we already retried? The original run is attempt 0;
    # each retry we create is the next attempt.
    already_retried = repository.count_runs_in_group(connection, group_id) - 1
    if already_retried < 0:
        already_retried = 0

    if already_retried < retry_max:
        return RetryDecision(
            should_retry=True,
            next_attempt=already_retried + 1,
            exhausted=False,
            retry_group_id=group_id,
        )

    return RetryDecision(
        should_retry=False,
        next_attempt=already_retried,
        exhausted=True,
        retry_group_id=group_id,
    )


def schedule_retry(
    connection: sqlite3.Connection,
    *,
    run: dict[str, Any],
    schedule: dict[str, Any],
    decision: RetryDecision,
    started_at: str | None = None,
) -> dict[str, Any]:
    """Insert a retry run row sharing the same ``retry_group_id``.

    The actual execution of the retry is the runner's job; this function only
    records the new run row so the schedule state stays consistent.
    """
    return repository.create_run(
        connection,
        script_id=run["script_id"],
        schedule_id=run["schedule_id"],
        started_at=started_at,
        status="error",  # retried runs are created in the "error" placeholder state
        retry_attempt=decision.next_attempt,
        retry_group_id=decision.retry_group_id,
    )


def fire_alert_if_exhausted(
    connection: sqlite3.Connection,
    *,
    run: dict[str, Any],
    schedule: dict[str, Any],
    decision: RetryDecision,
) -> bool:
    """POST to the schedule's alerting webhook if the retry cycle is exhausted.

    Returns True when the webhook fired (and was accepted), False otherwise.
    A ``False`` return covers both "no webhook configured" and "delivery
    failed"; either way the run row is untouched.
    """
    if not decision.exhausted:
        return False
    url = schedule.get("alert_webhook_url")
    if not url:
        return False

    payload = build_alert_payload(
        schedule_id=int(schedule["id"]),
        script_id=int(run["script_id"]),
        run_id=int(run["id"]),
        status=str(run["status"]),
        exit_code=run.get("exit_code"),
        log_path=run.get("log_path"),
        retry_attempt=int(run.get("retry_attempt") or 0),
    )
    return post_alert(str(url), payload)


def record_run_result(
    connection: sqlite3.Connection,
    *,
    run: dict[str, Any],
    schedule: dict[str, Any],
    ended_at: str | None = None,
) -> tuple[RetryDecision, dict[str, Any] | None, bool]:
    """Top-level entry point used by the runner (and tests).

    Returns ``(decision, retry_run_or_None, webhook_fired)``.
    """
    # Finalize the run row with ended_at if it isn't already set.
    if not run.get("ended_at"):
        connection.execute(
            "UPDATE runs SET ended_at = ? WHERE id = ?",
            (ended_at or utc_now(), run["id"]),
        )
        connection.commit()
        run = repository.get_run(connection, run["id"]) or run  # type: ignore[assignment]

    decision = evaluate_retry(connection, run, schedule)

    retry_run: dict[str, Any] | None = None
    if decision.should_retry:
        retry_run = schedule_retry(connection, run=run, schedule=schedule, decision=decision)

    webhook_fired = fire_alert_if_exhausted(
        connection, run=run, schedule=schedule, decision=decision
    )
    return decision, retry_run, webhook_fired
