"""Repository CRUD invariants."""

from __future__ import annotations

import pytest

from scriptrunner.db import initialize_database
from scriptrunner.repository import (
    RUN_STATUSES,
    SCHEDULE_KINDS,
    TERMINAL_RUN_STATUSES,
    TRIGGER_KINDS,
    create_log,
    create_run,
    create_schedule_trigger,
    create_script,
    create_webhook_trigger,
    get_log,
    get_run,
    get_script,
    get_trigger,
    get_trigger_by_webhook_token,
    list_runs,
    list_scripts,
    list_triggers,
    list_triggers_for_script,
    trigger_params,
)


@pytest.fixture
def conn(tmp_db_path):
    c = initialize_database(tmp_db_path)
    yield c
    c.close()


def test_create_script_returns_full_row(conn) -> None:
    row = create_script(conn, name="hello", language="python", source_path="/srv/x.py")
    assert row["name"] == "hello"
    assert row["language"] == "python"
    assert row["env_path"] is None
    assert row["id"] >= 1
    assert row["created_at"]


def test_create_script_requires_fields(conn) -> None:
    with pytest.raises(ValueError):
        create_script(conn, name="", language="python", source_path="/x")
    with pytest.raises(ValueError):
        create_script(conn, name="x", language="", source_path="/x")
    with pytest.raises(ValueError):
        create_script(conn, name="x", language="python", source_path="")


def test_list_and_get_scripts(conn) -> None:
    a = create_script(conn, name="a", language="python", source_path="/a.py")
    create_script(conn, name="b", language="bash", source_path="/b.sh")
    listed = list_scripts(conn)
    assert [s["name"] for s in listed] == ["a", "b"]
    assert get_script(conn, a["id"])["name"] == "a"
    assert get_script(conn, 99999) is None


def test_create_schedule_trigger_validates_kind(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    assert SCHEDULE_KINDS == {"cron", "interval"}
    assert TRIGGER_KINDS == {"schedule", "webhook"}
    with pytest.raises(ValueError):
        create_schedule_trigger(conn, script["id"], "weekly", "* * * * *")


def test_create_schedule_trigger_requires_existing_script(conn) -> None:
    with pytest.raises(ValueError):
        create_schedule_trigger(conn, 99999, "cron", "* * * * *")


def test_create_run_validates_status(conn) -> None:
    assert RUN_STATUSES == {"running", "success", "failure", "error", "cancelled"}
    assert TERMINAL_RUN_STATUSES == {"success", "failure", "error", "cancelled"}
    assert "running" not in TERMINAL_RUN_STATUSES
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    with pytest.raises(ValueError):
        create_run(conn, script["id"], status="crashed")
    # Cancelled is a valid status added in v0.5 for cancellation flows.
    cancelled = create_run(conn, script["id"], status="cancelled")
    assert cancelled["status"] == "cancelled"
    # Running is the in-flight placeholder the SSE stream relies on.
    running = create_run(conn, script["id"], status="running")
    assert running["status"] == "running"


def test_create_run_requires_existing_script(conn) -> None:
    with pytest.raises(ValueError):
        create_run(conn, 99999, status="success")


def test_create_run_negative_log_size(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    with pytest.raises(ValueError):
        create_run(conn, script["id"], status="success", log_size_bytes=-1)


def test_run_and_log_lifecycle(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    schedule = create_schedule_trigger(conn, script["id"], "interval", "5m")
    run = create_run(conn, script["id"], schedule["id"], status="success", log_size_bytes=128)
    assert run["status"] == "success"
    assert run["trigger_id"] == schedule["id"]

    log = create_log(conn, run["id"], path="/srv/logs/x.log", size_bytes=128)
    assert log["run_id"] == run["id"]
    assert log["size_bytes"] == 128
    assert get_log(conn, run["id"])["path"] == "/srv/logs/x.log"
    assert get_run(conn, run["id"])["status"] == "success"

    # list_runs orders by id ASC
    listed = list_runs(conn)
    assert [r["id"] for r in listed] == [run["id"]]


def test_create_log_requires_existing_run(conn) -> None:
    with pytest.raises(ValueError):
        create_log(conn, 99999, path="/x", size_bytes=0)


def test_list_triggers_orders_by_id(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    a = create_schedule_trigger(conn, script["id"], "cron", "*/5 * * * *")
    b = create_schedule_trigger(conn, script["id"], "interval", "1h")
    listed = list_triggers(conn)
    assert [s["id"] for s in listed] == [a["id"], b["id"]]


# ---- v0.8: trigger + webhook coverage ----------------------------------


def test_multiple_schedules_per_script(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    a = create_schedule_trigger(conn, script["id"], "cron", "*/5 * * * *")
    b = create_schedule_trigger(conn, script["id"], "interval", "1h", retry_max=2)
    c = create_schedule_trigger(
        conn, script["id"], "interval", "10m",
        params={"env": "staging", "verbose": "1"},
    )
    assert a["script_id"] == b["script_id"] == c["script_id"] == script["id"]
    listed = list_triggers_for_script(conn, script["id"])
    assert [t["id"] for t in listed] == [a["id"], b["id"], c["id"]]
    # trigger_params() decodes the JSON blob back to a plain dict for callers.
    assert trigger_params(listed[2]) == {"env": "staging", "verbose": "1"}


def test_create_webhook_trigger_generates_unique_token(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    a = create_webhook_trigger(conn, script["id"])
    b = create_webhook_trigger(conn, script["id"])
    assert a["kind"] == "webhook"
    assert b["kind"] == "webhook"
    assert a["webhook_token"] and b["webhook_token"]
    assert a["webhook_token"] != b["webhook_token"]
    assert len(a["webhook_token"]) == 64
    # Each token round-trips through the lookup by token.
    assert get_trigger_by_webhook_token(conn, a["webhook_token"])["id"] == a["id"]
    assert get_trigger_by_webhook_token(conn, b["webhook_token"])["id"] == b["id"]
    # Unknown tokens return None.
    assert get_trigger_by_webhook_token(conn, "deadbeef" * 8) is None


def test_create_webhook_trigger_requires_existing_script(conn) -> None:
    with pytest.raises(ValueError):
        create_webhook_trigger(conn, 99999)


def test_create_webhook_trigger_with_params(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    t = create_webhook_trigger(conn, script["id"], params={"region": "us-east-1"})
    # ``create_webhook_trigger`` returns the raw row; decode params via the helper.
    assert trigger_params(t) == {"region": "us-east-1"}
    assert trigger_params(get_trigger(conn, t["id"])) == {"region": "us-east-1"}


def test_schedule_trigger_params_round_trip(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    t = create_schedule_trigger(
        conn, script["id"], "cron", "*/10 * * * *",
        params={"--dry-run": "true", "env": "prod"},
    )
    # create_schedule_trigger also returns the raw row, not a normalised payload.
    assert trigger_params(t) == {"--dry-run": "true", "env": "prod"}
    assert trigger_params(get_trigger(conn, t["id"])) == {"--dry-run": "true", "env": "prod"}


def test_schedule_trigger_params_rejects_non_object_json(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    # Non-scalar values inside params must raise at creation time.
    with pytest.raises(ValueError):
        create_schedule_trigger(
            conn, script["id"], "cron", "* * * * *",
            params={"nested": {"x": 1}},  # type: ignore[dict-item]
        )


def test_run_with_trigger_id_link(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    schedule = create_schedule_trigger(conn, script["id"], "interval", "5m")
    webhook = create_webhook_trigger(conn, script["id"])
    r1 = create_run(conn, script["id"], schedule["id"], status="success")
    r2 = create_run(conn, script["id"], webhook["id"], status="success")
    assert r1["trigger_id"] == schedule["id"]
    assert r2["trigger_id"] == webhook["id"]
