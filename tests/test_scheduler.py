"""Tests for retry policy + alerting webhook in the scheduler helper."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from scriptrunner.db import initialize_database
from scriptrunner.repository import (
    create_run,
    create_schedule_trigger,
    create_script,
    create_webhook_trigger,
    get_run,
    new_retry_group_id,
)
from scriptrunner.scheduler import (
    evaluate_retry,
    fire_alert_if_exhausted,
    record_run_result,
    schedule_retry,
)


@pytest.fixture
def conn(tmp_db_path):
    connection = initialize_database(tmp_db_path)
    yield connection
    connection.close()


@pytest.fixture
def script(conn):
    return create_script(conn, name="x", language="python", source_path="/x.py")


@pytest.fixture
def schedule(conn, script):
    return create_schedule_trigger(conn, script["id"], "interval", "5m")


def _run(conn, script, schedule, *, status: str, retry_attempt: int = 0, retry_group_id: str | None = None):
    return create_run(
        conn,
        script_id=script["id"],
        trigger_id=schedule["id"],
        status=status,
        retry_attempt=retry_attempt,
        retry_group_id=retry_group_id,
    )


# --- evaluate_retry -----------------------------------------------------------

def test_evaluate_retry_success_does_not_retry(conn, script, schedule) -> None:
    run = _run(conn, script, schedule, status="success")
    decision = evaluate_retry(conn, run, schedule)
    assert decision.should_retry is False
    assert decision.exhausted is False


def test_evaluate_retry_failure_with_retry_max_zero_marks_exhausted(conn, script) -> None:
    schedule = create_schedule_trigger(conn, script["id"], "interval", "5m", retry_max=0)
    run = _run(conn, script, schedule, status="failure")
    decision = evaluate_retry(conn, run, schedule)
    assert decision.should_retry is False
    assert decision.exhausted is True


def test_evaluate_retry_retries_until_exhausted(conn, script) -> None:
    schedule = create_schedule_trigger(conn, script["id"], "interval", "5m", retry_max=2)
    # First failure: should retry, attempt 1
    r1 = _run(conn, script, schedule, status="failure")
    decision = evaluate_retry(conn, r1, schedule)
    assert decision.should_retry is True
    assert decision.next_attempt == 1
    assert decision.exhausted is False

    group_id = decision.retry_group_id
    r2 = _run(conn, script, schedule, status="failure", retry_attempt=1, retry_group_id=group_id)
    decision2 = evaluate_retry(conn, r2, schedule)
    assert decision2.should_retry is True
    assert decision2.next_attempt == 2

    r3 = _run(conn, script, schedule, status="failure", retry_attempt=2, retry_group_id=group_id)
    decision3 = evaluate_retry(conn, r3, schedule)
    assert decision3.should_retry is False
    assert decision3.exhausted is True


def test_evaluate_retry_generates_group_id_for_run_without_one(conn, script, schedule) -> None:
    run = _run(conn, script, schedule, status="failure")
    assert run["retry_group_id"] is None
    decision = evaluate_retry(conn, run, schedule)
    assert decision.retry_group_id
    refreshed = get_run(conn, run["id"])
    assert refreshed["retry_group_id"] == decision.retry_group_id


def test_schedule_retry_inserts_run_with_same_group_id(conn, script) -> None:
    schedule = create_schedule_trigger(conn, script["id"], "interval", "5m", retry_max=3)
    run = _run(conn, script, schedule, status="failure")
    decision = evaluate_retry(conn, run, schedule)
    retry_run = schedule_retry(conn, run=run, trigger=schedule, decision=decision)
    assert retry_run["retry_attempt"] == 1
    assert retry_run["retry_group_id"] == decision.retry_group_id
    assert retry_run["status"] == "error"


# --- fire_alert_if_exhausted --------------------------------------------------

def _start_webhook(status_code: int = 200) -> tuple[ThreadingHTTPServer, str]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self.send_response(status_code)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args: Any) -> None:  # noqa: ARG002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def test_fire_alert_if_exhausted_returns_false_when_not_exhausted(conn, script) -> None:
    schedule = create_schedule_trigger(
        conn, script["id"], "interval", "5m",
        retry_max=3, alert_webhook_url="http://127.0.0.1:1/hook",
    )
    run = _run(conn, script, schedule, status="failure")
    decision = evaluate_retry(conn, run, schedule)
    assert decision.exhausted is False
    assert fire_alert_if_exhausted(conn, run=run, trigger=schedule, decision=decision) is False


def test_fire_alert_if_exhausted_returns_false_when_no_webhook(conn, script, schedule) -> None:
    run = _run(conn, script, schedule, status="failure")
    decision = evaluate_retry(conn, run, schedule)
    assert schedule["alert_webhook_url"] is None
    assert fire_alert_if_exhausted(conn, run=run, trigger=schedule, decision=decision) is False


def test_fire_alert_only_once_per_retry_cycle(conn, script) -> None:
    server, url = _start_webhook(200)
    try:
        schedule = create_schedule_trigger(
            conn, script["id"], "interval", "5m",
            retry_max=1, alert_webhook_url=url,
        )
        r1 = _run(conn, script, schedule, status="failure")
        d1 = evaluate_retry(conn, r1, schedule)
        retry_run = schedule_retry(conn, run=r1, trigger=schedule, decision=d1)
        assert fire_alert_if_exhausted(conn, run=r1, trigger=schedule, decision=d1) is False
        d2 = evaluate_retry(conn, retry_run, schedule)
        assert d2.exhausted is True
        assert fire_alert_if_exhausted(conn, run=retry_run, trigger=schedule, decision=d2) is True
    finally:
        server.shutdown()
        server.server_close()


def test_fire_alert_does_not_touch_run_row_on_webhook_5xx(conn, script) -> None:
    server, url = _start_webhook(500)
    try:
        schedule = create_schedule_trigger(
            conn, script["id"], "interval", "5m",
            retry_max=0, alert_webhook_url=url,
        )
        run = _run(conn, script, schedule, status="failure")
        decision = evaluate_retry(conn, run, schedule)
        assert decision.exhausted is True
        before_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert fire_alert_if_exhausted(conn, run=run, trigger=schedule, decision=decision) is False
        after_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert before_count == after_count
    finally:
        server.shutdown()
        server.server_close()


# --- record_run_result (top-level entry) -------------------------------------

def test_record_run_result_top_level(conn, script) -> None:
    schedule = create_schedule_trigger(conn, script["id"], "interval", "5m", retry_max=1)
    run = _run(conn, script, schedule, status="failure")
    decision, retry_run, _fired = record_run_result(conn, run=run, trigger=schedule)
    assert decision.should_retry is True
    assert retry_run is not None
    assert retry_run["retry_attempt"] == 1


def test_record_run_result_no_retry_on_success(conn, script, schedule) -> None:
    run = _run(conn, script, schedule, status="success")
    decision, retry_run, fired = record_run_result(conn, run=run, trigger=schedule)
    assert decision.should_retry is False
    assert retry_run is None
    assert fired is False


def test_retry_default_group_id_is_unique() -> None:
    a = new_retry_group_id()
    b = new_retry_group_id()
    assert a != b
    assert len(a) == 32


# --- v0.8: webhook triggers don't retry / alert ------------------------------


def test_webhook_trigger_skips_retry_and_alerting(conn, script) -> None:
    webhook = create_webhook_trigger(conn, script["id"])
    # A failed webhook-fired run should produce a RetryDecision with
    # ``should_retry=False`` and ``exhausted=False`` (webhooks never retry).
    run = create_run(conn, script_id=script["id"], trigger_id=webhook["id"], status="failure")
    decision = evaluate_retry(conn, run, webhook)
    assert decision.should_retry is False
    assert decision.exhausted is False

    # record_run_result on a webhook trigger must not fire any webhook and
    # must not create a retry run.
    decision, retry_run, fired = record_run_result(conn, run=run, trigger=webhook)
    assert decision.should_retry is False
    assert retry_run is None
    assert fired is False
