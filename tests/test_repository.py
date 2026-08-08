"""Repository CRUD invariants."""

from __future__ import annotations

import pytest

from scriptrunner.db import initialize_database
from scriptrunner.repository import (
    RUN_STATUSES,
    SCHEDULE_KINDS,
    create_log,
    create_run,
    create_schedule,
    create_script,
    get_log,
    get_run,
    get_script,
    list_runs,
    list_schedules,
    list_scripts,
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


def test_create_schedule_validates_kind(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    assert SCHEDULE_KINDS == {"cron", "interval"}
    with pytest.raises(ValueError):
        create_schedule(conn, script["id"], "weekly", "* * * * *")


def test_create_schedule_requires_existing_script(conn) -> None:
    with pytest.raises(ValueError):
        create_schedule(conn, 99999, "cron", "* * * * *")


def test_create_run_validates_status(conn) -> None:
    assert RUN_STATUSES == {"success", "failure", "error"}
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    with pytest.raises(ValueError):
        create_run(conn, script["id"], status="crashed")


def test_create_run_requires_existing_script(conn) -> None:
    with pytest.raises(ValueError):
        create_run(conn, 99999, status="success")


def test_create_run_negative_log_size(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    with pytest.raises(ValueError):
        create_run(conn, script["id"], status="success", log_size_bytes=-1)


def test_run_and_log_lifecycle(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    schedule = create_schedule(conn, script["id"], "interval", "5m")
    run = create_run(conn, script["id"], schedule["id"], status="success", log_size_bytes=128)
    assert run["status"] == "success"
    assert run["schedule_id"] == schedule["id"]

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


def test_list_schedules_orders_by_id(conn) -> None:
    script = create_script(conn, name="x", language="python", source_path="/x.py")
    a = create_schedule(conn, script["id"], "cron", "*/5 * * * *")
    b = create_schedule(conn, script["id"], "interval", "1h")
    listed = list_schedules(conn)
    assert [s["id"] for s in listed] == [a["id"], b["id"]]