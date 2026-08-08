"""End-to-end HTTP contract for the stdlib server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from threading import Thread

import pytest

from scriptrunner.config import Settings
from scriptrunner.server import ScriptRunnerServer


@pytest.fixture
def server(tmp_db_path, storage_dir):
    settings = Settings(
        db_path=tmp_db_path,
        storage_dir=storage_dir,
        host="127.0.0.1",
        port=0,  # ephemeral
    )
    srv = ScriptRunnerServer(settings)
    host, port = srv.server_address
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}", srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=2)


def _request(method: str, base: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        base + path,
        method=method,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_health(server) -> None:
    base, _ = server
    status, body = _request("GET", base, "/health")
    assert status == 200
    assert body == {"status": "ok"}


def test_scripts_crud(server) -> None:
    base, _ = server

    # Initially empty
    status, body = _request("GET", base, "/api/scripts")
    assert status == 200
    assert body == []

    # Create
    status, body = _request("POST", base, "/api/scripts", {
        "name": "hello",
        "language": "python",
        "source_path": "/srv/hello.py",
    })
    assert status == 201
    assert body["name"] == "hello"

    # Read
    status, body = _request("GET", base, f"/api/scripts/{body['id']}")
    assert status == 200
    assert body["name"] == "hello"


def test_get_unknown_script_returns_404(server) -> None:
    base, _ = server
    status, body = _request("GET", base, "/api/scripts/9999")
    assert status == 404
    assert body["error"] == "script not found"


def test_invalid_json_returns_400(server) -> None:
    base, _ = server
    status, body = _request("POST", base, "/api/scripts", {"name": ""})
    assert status == 400
    assert "error" in body


def test_unknown_route_returns_404(server) -> None:
    base, _ = server
    status, body = _request("GET", base, "/api/nope")
    assert status == 404
    assert body["error"] == "not found"


def test_schedule_creation_and_listing(server) -> None:
    base, _ = server
    _, script = _request("POST", base, "/api/scripts", {
        "name": "sched-test",
        "language": "python",
        "source_path": "/srv/x.py",
    })
    status, body = _request("POST", base, "/api/schedules", {
        "script_id": script["id"],
        "kind": "interval",
        "expression": "5m",
    })
    assert status == 201
    assert body["enabled"] in (1, True)  # JSON normalizes 1->True, both OK

    status, body = _request("GET", base, "/api/schedules")
    assert status == 200
    assert len(body) == 1
    assert body[0]["expression"] == "5m"


def test_run_creation_and_logs(server) -> None:
    base, _ = server
    _, script = _request("POST", base, "/api/scripts", {
        "name": "runner-test",
        "language": "python",
        "source_path": "/srv/r.py",
    })
    status, body = _request("POST", base, "/api/runs", {
        "script_id": script["id"],
        "status": "success",
        "log_size_bytes": 256,
    })
    assert status == 201
    run_id = body["id"]

    # Log row is not yet populated — expected scaffold behavior, flagged in README.
    status, body = _request("GET", base, f"/api/logs/{run_id}")
    assert status == 404
    assert body["error"] == "log not found"