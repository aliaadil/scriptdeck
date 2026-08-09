"""HTTP Basic authentication contract for ScriptDeck."""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from threading import Thread

import bcrypt
import pytest

from scriptrunner.auth import BasicAuth, parse_basic_auth
from scriptrunner.config import Settings
from scriptrunner.server import ScriptRunnerServer


def _credentials(username: str, password: str) -> str:
    encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {encoded}"


def _request(base: str, path: str, authorization: str | None = None) -> tuple[int, dict, dict[str, str]]:
    headers = {"Authorization": authorization} if authorization else {}
    request = urllib.request.Request(base + path, headers=headers)
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read()), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()), dict(error.headers)


@pytest.fixture
def auth_server(tmp_db_path, storage_dir):
    password_hash = bcrypt.hashpw(b"correct horse", bcrypt.gensalt(rounds=4)).decode()
    settings = Settings(
        db_path=tmp_db_path,
        storage_dir=storage_dir,
        host="127.0.0.1",
        port=0,
        basic_auth=parse_basic_auth(f"alice:{password_hash}"),
    )
    server = ScriptRunnerServer(settings)
    host, port = server.server_address
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}", password_hash
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_no_env_var_means_no_auth_required(tmp_db_path, storage_dir) -> None:
    server = ScriptRunnerServer(Settings(db_path=tmp_db_path, storage_dir=storage_dir, host="127.0.0.1", port=0))
    host, port = server.server_address
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body, _ = _request(f"http://{host}:{port}", "/health")
        assert status == 200
        assert body == {"status": "ok"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_config_reads_basic_auth_from_environment(monkeypatch) -> None:
    password_hash = bcrypt.hashpw(b"password", bcrypt.gensalt(rounds=4)).decode()
    monkeypatch.setenv("SCRIPTDECK_BASIC_AUTH", f"alice:{password_hash}")

    settings = Settings.from_env()

    assert settings.basic_auth is not None
    assert settings.basic_auth.username == "alice"
    assert settings.basic_auth.password_hash == password_hash


def test_auth_server_accepts_correct_credentials(auth_server) -> None:
    base, _ = auth_server
    status, body, _ = _request(base, "/health", _credentials("alice", "correct horse"))
    assert status == 200
    assert body == {"status": "ok"}


def test_auth_server_rejects_missing_and_wrong_credentials(auth_server) -> None:
    base, _ = auth_server
    status, body, headers = _request(base, "/health")
    assert status == 401
    assert body == {"error": "authentication required"}
    assert headers["WWW-Authenticate"] == 'Basic realm="scriptdeck"'

    status, _, headers = _request(base, "/api/scripts", _credentials("alice", "wrong"))
    assert status == 401
    assert headers["WWW-Authenticate"] == 'Basic realm="scriptdeck"'


def test_auth_protects_api_root_and_logs_routes(auth_server) -> None:
    base, _ = auth_server
    for path in ("/", "/logs", "/api/scripts"):
        status, _, headers = _request(base, path)
        assert status == 401
        assert headers["WWW-Authenticate"] == 'Basic realm="scriptdeck"'


def test_password_hash_comparison_does_not_short_circuit_on_username() -> None:
    password_hash = bcrypt.hashpw(b"password", bcrypt.gensalt(rounds=4)).decode()
    auth = BasicAuth("alice", password_hash)

    samples: list[tuple[str, float]] = []
    for username, password in (("alice", "wrong"), ("mallory", "password")):
        started = time.perf_counter()
        for _ in range(4):
            assert auth.check(_credentials(username, password)) is False
        samples.append((username, time.perf_counter() - started))

    # Both paths perform bcrypt work; this deliberately uses a broad bound to
    # avoid making a CI timing test pretend that a scheduler is a metronome.
    assert max(timing for _, timing in samples) < min(timing for _, timing in samples) * 4
