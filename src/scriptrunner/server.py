"""Minimal JSON HTTP service for ScriptRunner."""

from __future__ import annotations

import json
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import isolation, runner
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

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("request body must be JSON")
        parsed = json.loads(self.rfile.read(length))
        if not isinstance(parsed, dict):
            raise ValueError("request body must be a JSON object")
        return parsed

    def _script_payload(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        """Normalise a script row for the wire (string-ify paths)."""
        if row is None:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "language": row["language"],
            "source_path": row["source_path"],
            "env_path": row.get("env_path"),
            "requirements_path": row.get("requirements_path"),
            "interpreter_path": row.get("interpreter_path"),
            "created_at": row["created_at"],
        }

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        try:
            if path == "/api/scripts":
                self._send_json(
                    HTTPStatus.OK,
                    [self._script_payload(s) for s in list_scripts(self.server.connection)],
                )
            elif path.startswith("/api/scripts/"):
                item = get_script(self.server.connection, int(path.rsplit("/", 1)[1]))
                self._send_json(
                    HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                    self._script_payload(item) or {"error": "script not found"},
                )
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
        try:
            body = self._body()
            if path == "/api/scripts":
                item = self._create_script(body)
                self._send_json(HTTPStatus.CREATED, item)
                return
            if path.startswith("/api/scripts/") and path.endswith("/run"):
                sid = int(path.split("/")[3])
                item = self._trigger_run(sid, body)
                self._send_json(HTTPStatus.CREATED, item)
                return
            if path == "/api/schedules":
                item = create_schedule(
                    self.server.connection,
                    int(body["script_id"]),
                    str(body["kind"]),
                    str(body["expression"]),
                    body.get("next_run_at"),
                    bool(body.get("enabled", True)),
                )
                self._send_json(HTTPStatus.CREATED, item)
                return
            if path == "/api/runs":
                item = create_run(
                    self.server.connection,
                    int(body["script_id"]),
                    int(body["schedule_id"]) if body.get("schedule_id") is not None else None,
                    started_at=body.get("started_at"),
                    ended_at=body.get("ended_at"),
                    exit_code=body.get("exit_code"),
                    status=body.get("status", "error"),
                    log_path=body.get("log_path"),
                    log_size_bytes=int(body.get("log_size_bytes", 0)),
                )
                self._send_json(HTTPStatus.CREATED, item)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"invalid request: {exc}"})
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "database error"})

    # --- helpers ----------------------------------------------------------

    def _create_script(self, body: dict[str, Any]) -> dict[str, Any]:
        """Accept either pre-uploaded paths (legacy) or inline source (v0.4).

        Body keys (v0.4): ``name``, ``language``, ``source``, ``requirements``.
        Body keys (legacy): ``name``, ``language``, ``source_path``, ``env_path``.
        """
        name = body.get("name") or ""
        language = body.get("language") or ""
        if language not in isolation.SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {sorted(isolation.SUPPORTED_LANGUAGES)}")

        storage_dir = self.server.settings.storage_dir

        if "source" in body:
            # v0.4 path: write the uploaded source + optional requirements
            # to disk before allocating a script row, so we can use the row's
            # id to name the per-script directory.
            placeholder_id_row = create_script(
                self.server.connection,
                name=name + "-tmp",  # placeholder, deleted below
                language=language,
                source_path=str(storage_dir / "pending"),
            )
            script_id = int(placeholder_id_row["id"])
            source_path, req_path = isolation.upload_script_files(
                storage_dir=storage_dir,
                script_id=script_id,
                name=name,
                source=str(body.get("source") or ""),
                requirements=body.get("requirements"),
            )
            # Rewrite the placeholder row with the real paths + correct name.
            self.server.connection.execute(
                "UPDATE scripts SET name = ?, source_path = ?, requirements_path = ? "
                "WHERE id = ?",
                (name, str(source_path), str(req_path) if req_path else None, script_id),
            )
            self.server.connection.commit()
        else:
            # Legacy path: caller already wrote files somewhere.
            if not body.get("source_path"):
                raise ValueError("source_path is required when source is not provided")
            row = create_script(
                self.server.connection,
                name=name,
                language=language,
                source_path=str(body["source_path"]),
                env_path=body.get("env_path"),
            )
            script_id = int(row["id"])

        # Provision the env up-front so the API can surface interpreter_path on
        # the response. Failure here is a 500 — it's almost always "uv missing"
        # or "requirements syntax error", and the caller wants to know.
        script_row = get_script(self.server.connection, script_id)
        if script_row is None:
            raise ValueError("script row vanished")
        iso = isolation.resolve_interpreter(
            storage_dir=storage_dir,
            script_id=script_id,
            language=language,
            source_path=_as_path(script_row["source_path"]),
            requirements_path=(
                _as_path(script_row["requirements_path"])
                if script_row.get("requirements_path")
                else None
            ),
            connection=self.server.connection,
        )
        self.server.connection.execute(
            "UPDATE scripts SET interpreter_path = ? WHERE id = ?",
            (str(iso.interpreter_path), script_id),
        )
        self.server.connection.commit()
        row = get_script(self.server.connection, script_id)
        return self._script_payload(row) or {"error": "script row vanished"}

    def _trigger_run(self, script_id: int, body: dict[str, Any]) -> dict[str, Any]:
        schedule_id = body.get("schedule_id")
        result = runner.run_script(
            connection=self.server.connection,
            storage_dir=self.server.settings.storage_dir,
            script_id=script_id,
            schedule_id=int(schedule_id) if schedule_id is not None else None,
        )
        return {
            "run": result.run,
            "decision": {
                "should_retry": result.decision.should_retry,
                "exhausted": result.decision.exhausted,
                "next_attempt": result.decision.next_attempt,
                "retry_group_id": result.decision.retry_group_id,
            },
            "retry_run": result.retry_run,
            "webhook_fired": result.webhook_fired,
        }


def _as_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


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