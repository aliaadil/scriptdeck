"""Minimal JSON HTTP service for ScriptRunner."""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .db import initialize_database
from .repository import (
    create_run,
    create_schedule,
    create_script,
    get_log,
    get_script,
    list_runs,
    list_schedules,
    list_scripts,
)


class ScriptRunnerServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, settings: Settings):
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        connection = initialize_database(settings.db_path)
        self.settings = settings
        self.connection = connection
        super().__init__((settings.host, settings.port), RequestHandler)

    def server_close(self) -> None:
        self.connection.close()
        super().server_close()


class RequestHandler(BaseHTTPRequestHandler):
    server: ScriptRunnerServer

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the local tool quiet by default; callers can inspect HTTP status.
        return

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _require_auth(self) -> bool:
        configured = self.server.settings.basic_auth
        if configured is None or configured.check(self.headers.get("Authorization")):
            return True
        body = json.dumps({"error": "authentication required"}).encode("utf-8")
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="scriptdeck"')
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("request body must be JSON")
        parsed = json.loads(self.rfile.read(length))
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self._require_auth():
            return
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        try:
            if path == "/api/scripts":
                self._send_json(HTTPStatus.OK, list_scripts(self.server.connection))
            elif path.startswith("/api/scripts/"):
                item = get_script(self.server.connection, int(path.rsplit("/", 1)[1]))
                self._send_json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND, item or {"error": "script not found"})
            elif path == "/api/schedules":
                self._send_json(HTTPStatus.OK, list_schedules(self.server.connection))
            elif path == "/api/runs":
                self._send_json(HTTPStatus.OK, list_runs(self.server.connection))
            elif path.startswith("/api/logs/"):
                item = get_log(self.server.connection, int(path.rsplit("/", 1)[1]))
                self._send_json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND, item or {"error": "log not found"})
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid resource id"})
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "database error"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self._require_auth():
            return
        try:
            body = self._body()
            if path == "/api/scripts":
                item = create_script(
                    self.server.connection,
                    body.get("name"), body.get("language"), body.get("source_path"), body.get("env_path"),
                )
            elif path == "/api/schedules":
                item = create_schedule(
                    self.server.connection,
                    int(body["script_id"]), body.get("kind"), body.get("expression"),
                    body.get("next_run_at"), bool(body.get("enabled", True)),
                )
            elif path == "/api/runs":
                item = create_run(
                    self.server.connection,
                    int(body["script_id"]),
                    int(body["schedule_id"]) if body.get("schedule_id") is not None else None,
                    started_at=body.get("started_at"), ended_at=body.get("ended_at"),
                    exit_code=body.get("exit_code"), status=body.get("status", "error"),
                    log_path=body.get("log_path"), log_size_bytes=int(body.get("log_size_bytes", 0)),
                )
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            self._send_json(HTTPStatus.CREATED, item)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid request"})
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "database error"})


def serve(settings: Settings | None = None) -> None:
    settings = settings or Settings.from_env()
    server = ScriptRunnerServer(settings)
    print(f"ScriptRunner listening on http://{settings.host}:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
