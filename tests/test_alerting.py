"""Tests for the alerting webhook helper."""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from scriptrunner.alerting import (
    WebhookError,
    build_alert_payload,
    post_alert,
    validate_webhook_url,
)

_REQUESTED: list[dict[str, Any]] = []


class _CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        _REQUESTED.append({"path": self.path, "body": body})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args: Any) -> None:  # noqa: ARG002
        return


def _start_server(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


@pytest.fixture
def webhook_server():
    _REQUESTED.clear()
    server, base = _start_server(_CaptureHandler)
    yield base
    server.shutdown()
    server.server_close()


def test_validate_webhook_url_accepts_http_and_https() -> None:
    assert validate_webhook_url("http://example.com/hook") == "http://example.com/hook"
    assert validate_webhook_url("https://example.com/hook") == "https://example.com/hook"


@pytest.mark.parametrize("bad_url", ["", "   ", "ftp://example.com", "https://", "not-a-url"])
def test_validate_webhook_url_rejects_bad_urls(bad_url: str) -> None:
    with pytest.raises(WebhookError):
        validate_webhook_url(bad_url)


def test_build_alert_payload_shape() -> None:
    payload = build_alert_payload(
        schedule_id=1,
        script_id=2,
        run_id=3,
        status="failure",
        exit_code=1,
        log_path="/srv/logs/3.log",
        retry_attempt=2,
    )
    assert payload == {
        "schedule_id": 1,
        "script_id": 2,
        "run_id": 3,
        "status": "failure",
        "exit_code": 1,
        "log_path": "/srv/logs/3.log",
        "retry_attempt": 2,
    }


def test_post_alert_returns_true_on_2xx(webhook_server: str) -> None:
    payload = build_alert_payload(
        schedule_id=1, script_id=2, run_id=3, status="failure",
        exit_code=1, log_path=None, retry_attempt=0,
    )
    assert post_alert(webhook_server, payload, timeout=2.0) is True
    assert len(_REQUESTED) == 1
    assert _REQUESTED[0]["path"] == "/"
    decoded = json.loads(_REQUESTED[0]["body"])
    assert decoded["status"] == "failure"
    assert decoded["run_id"] == 3


def test_post_alert_returns_false_on_5xx() -> None:
    class FiveHundredHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"nope")

        def log_message(self, *args: Any) -> None:  # noqa: ARG002
            return

    server, url = _start_server(FiveHundredHandler)
    try:
        payload = build_alert_payload(
            schedule_id=1, script_id=2, run_id=3, status="error",
            exit_code=None, log_path=None, retry_attempt=0,
        )
        assert post_alert(url, payload, timeout=2.0) is False
    finally:
        server.shutdown()
        server.server_close()


def test_post_alert_returns_false_on_connection_error() -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    _, port = sock.getsockname()
    sock.close()
    payload = build_alert_payload(
        schedule_id=1, script_id=2, run_id=3, status="failure",
        exit_code=1, log_path=None, retry_attempt=0,
    )
    assert post_alert(f"http://127.0.0.1:{port}/", payload, timeout=1.0) is False


def test_post_alert_returns_false_on_invalid_url() -> None:
    payload = build_alert_payload(
        schedule_id=1, script_id=2, run_id=3, status="failure",
        exit_code=1, log_path=None, retry_attempt=0,
    )
    assert post_alert("ftp://nope/", payload, timeout=1.0) is False
    assert post_alert("", payload, timeout=1.0) is False
