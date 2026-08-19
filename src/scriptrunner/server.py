"""Minimal JSON HTTP service for ScriptRunner.

v0.8 — generalised the schedule model into triggers. Each script can have
multiple schedule triggers and any number of webhook triggers. Webhooks
expose a public POST endpoint at ``/webhooks/<token>`` (no Basic auth) that
fires the script on a successful token match.
"""

from __future__ import annotations

import json
import sqlite3
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import isolation, runner
from .config import Settings
from .db import initialize_database
from .log_stream import (
    TAIL_POLL_INTERVAL_SECONDS,
    encode_sse,
    encode_sse_heartbeat,
    read_new_lines,
)
from .repository import (
    TERMINAL_RUN_STATUSES,
    create_run,
    create_schedule_trigger,
    create_script,
    create_webhook_trigger,
    delete_trigger,
    get_log,
    get_run,
    get_script,
    get_trigger,
    get_trigger_by_webhook_token,
    list_recent_runs_with_script,
    list_runs,
    list_scripts,
    list_triggers,
    list_triggers_for_script,
    trigger_params,
    update_trigger,
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

    # ``protocol_version`` is bumped to HTTP/1.1 so chunked transfer encoding
    # is supported — required for the SSE endpoint, which never sets a
    # Content-Length and streams events for the lifetime of the run.
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the local tool quiet by default; callers can inspect HTTP status.
        return

    def _send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _send_no_content(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

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

    def _send_html(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)

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

    def _trigger_payload(self, row: dict[str, Any]) -> dict[str, Any]:
        """Normalise a trigger row for the wire. Only the relevant fields for
        the trigger's ``kind`` are surfaced; the other kind's fields are left
        out of the response to keep the API predictable.
        """
        out: dict[str, Any] = {
            "id": row["id"],
            "script_id": row["script_id"],
            "kind": row["kind"],
            "params": trigger_params(row),
            "created_at": row["created_at"],
        }
        if row["kind"] == "schedule":
            out["schedule_kind"] = row.get("schedule_kind")
            out["expression"] = row.get("expression")
            out["next_run_at"] = row.get("next_run_at")
            out["enabled"] = bool(row.get("enabled"))
            out["retry_max"] = int(row.get("retry_max") or 0)
            out["retry_backoff_seconds"] = int(row.get("retry_backoff_seconds") or 0)
            out["alert_webhook_url"] = row.get("alert_webhook_url")
        elif row["kind"] == "webhook":
            token = row.get("webhook_token")
            out["webhook_token"] = token
            # The full URL is surfaced so the operator can copy/paste it.
            if token:
                host = self.headers.get("Host") or f"{self.server.server_address[0]}:{self.server.server_address[1]}"
                out["webhook_url"] = f"http://{host}/webhooks/{token}"
        return out

    # ------------------------------------------------------------------ SSE
    def _stream_log_for_run(self, run: dict[str, Any]) -> None:
        """Tail ``<storage>/logs/<run_id>.log`` and push lines as SSE events.

        Writes the SSE response headers up front, then loops until the run's
        status reaches a terminal value or the client disconnects. Each full
        line that appears in the file becomes one ``data: <line>`` event. A
        final ``event: end`` is emitted before the connection is closed.
        """
        run_id = int(run["id"])
        log_path = self.server.settings.storage_dir / "logs" / f"{run_id}.log"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        # ``X-Accel-Buffering: no`` tells nginx (and compatible proxies) not to
        # buffer the response — otherwise events queue up and the user sees
        # nothing until the buffer fills.
        self.send_header("X-Accel-Buffering", "no")
        # Disable Python's Nagle buffering on the underlying socket so writes
        # flush to the client immediately. ``wfile`` is a BufferedWriter on
        # top of the socket; the underlying socket exposes ``setsockopt``.
        try:
            sock = self.connection
            sock.setsockopt(1, 6, 1)  # IPPROTO_TCP, TCP_NODELAY
            sock.setsockopt(1, 7, 1)  # IPPROTO_TCP, TCP_CORK off
        except OSError:
            pass
        self.end_headers()

        offset = 0
        # Replay any pre-existing content (e.g. fast clients connecting after
        # the runner has already emitted some output) before entering the loop.
        lines, offset = read_new_lines(log_path, offset)
        for line in lines:
            self._safe_write(encode_sse(line))

        last_heartbeat = time.monotonic()
        while True:
            # Check the run's terminal state via a fresh connection — sharing
            # ``self.server.connection`` across SSE threads would serialize all
            # streams behind a single writer.
            status = self._run_status(run_id)
            if status in TERMINAL_RUN_STATUSES:
                self._safe_write(encode_sse(f"status={status}", event="end"))
                return
            lines, offset = read_new_lines(log_path, offset)
            for line in lines:
                self._safe_write(encode_sse(line))
                last_heartbeat = time.monotonic()
            now = time.monotonic()
            if now - last_heartbeat >= 15:
                # Heartbeat keeps idle proxies (and EventSource's default
                # 45-second reconnect timer) from killing the connection.
                self._safe_write(encode_sse_heartbeat())
                last_heartbeat = now
            try:
                time.sleep(TAIL_POLL_INTERVAL_SECONDS)
            except OSError:
                return

    def _safe_write(self, payload: bytes) -> bool:
        """Write ``payload`` to ``wfile``; return False if the client is gone."""
        try:
            self.wfile.write(payload)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            return False

    def _run_status(self, run_id: int) -> str | None:
        """Read the current run status from a fresh DB connection."""
        try:
            conn = sqlite3.connect(
                str(self.server.settings.db_path),
                check_same_thread=False,
                timeout=2.0,
            )
            try:
                row = conn.execute(
                    "SELECT status FROM runs WHERE id = ?", (run_id,)
                ).fetchone()
                return row[0] if row else None
            finally:
                conn.close()
        except sqlite3.Error:
            return None

    # ------------------------------------------------------------------ views
    def _render_logs_index(self) -> None:
        rows = list_recent_runs_with_script(self.server.connection, limit=50)
        body = render_logs_index(rows)
        self._send_html(HTTPStatus.OK, body)

    def _render_logs_viewer(self, run: dict[str, Any]) -> None:
        body = render_logs_viewer(run, self.server.settings.storage_dir)
        self._send_html(HTTPStatus.OK, body)

    def _render_script_view(self, script: dict[str, Any]) -> None:
        triggers = list_triggers_for_script(self.server.connection, int(script["id"]))
        body = render_script_view(script, triggers)
        self._send_html(HTTPStatus.OK, body)

    # ------------------------------------------------------------------ routes
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self._require_auth():
            return
        try:
            if path == "/health":
                self._send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path == "/logs":
                self._render_logs_index()
                return
            if path.startswith("/logs/"):
                run = get_run(self.server.connection, int(path.rsplit("/", 1)[1]))
                if not run:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
                else:
                    self._render_logs_viewer(run)
                return
            if path.startswith("/scripts/") and not path.startswith("/api/scripts/"):
                # /scripts/<id> — HTML view of a script + its triggers
                script = get_script(self.server.connection, int(path.rsplit("/", 1)[1]))
                if not script:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "script not found"})
                else:
                    self._render_script_view(script)
                return
            if path == "/api/scripts":
                self._send_json(
                    HTTPStatus.OK,
                    [self._script_payload(s) for s in list_scripts(self.server.connection)],
                )
                return
            if path.startswith("/api/scripts/"):
                item = get_script(self.server.connection, int(path.rsplit("/", 1)[1]))
                self._send_json(
                    HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                    self._script_payload(item) or {"error": "script not found"},
                )
                return
            if path == "/api/triggers":
                self._send_json(
                    HTTPStatus.OK,
                    [self._trigger_payload(t) for t in list_triggers(self.server.connection)],
                )
                return
            if path.startswith("/api/triggers/"):
                item = get_trigger(self.server.connection, int(path.rsplit("/", 1)[1]))
                if not item:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "trigger not found"})
                else:
                    self._send_json(HTTPStatus.OK, self._trigger_payload(item))
                return
            if path.startswith("/api/scripts/") and path.endswith("/triggers"):
                sid = int(path.split("/")[3])
                script = get_script(self.server.connection, sid)
                if not script:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "script not found"})
                else:
                    self._send_json(
                        HTTPStatus.OK,
                        [
                            self._trigger_payload(t)
                            for t in list_triggers_for_script(self.server.connection, sid)
                        ],
                    )
                return
            if path == "/api/runs":
                self._send_json(HTTPStatus.OK, list_runs(self.server.connection))
                return
            if path.startswith("/api/logs/"):
                tail = path.rsplit("/", 1)[1]
                if tail == "stream":
                    # /api/logs/<run_id>/stream — match the prefix
                    # before the trailing component to get the run_id.
                    run_id_str = path.rsplit("/", 2)[-2]
                    run = get_run(self.server.connection, int(run_id_str))
                    if not run:
                        self._send_json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
                    else:
                        self._stream_log_for_run(run)
                else:
                    item = get_log(self.server.connection, int(tail))
                    self._send_json(
                        HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                        item or {"error": "log not found"},
                    )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid resource id"})
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "database error"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"

        # Public webhook endpoint — no Basic auth, token in URL path is the
        # only credential. This branch must come first so ``_require_auth``
        # isn't called.
        if path.startswith("/webhooks/"):
            token = path.rsplit("/", 1)[1]
            self._handle_webhook_hit(token)
            return

        if not self._require_auth():
            return
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
            if path.startswith("/api/scripts/") and path.endswith("/triggers/schedule"):
                sid = int(path.split("/")[3])
                item = self._create_schedule_trigger(sid, body)
                self._send_json(HTTPStatus.CREATED, item)
                return
            if path.startswith("/api/scripts/") and path.endswith("/triggers/webhook"):
                sid = int(path.split("/")[3])
                item = create_webhook_trigger(
                    self.server.connection,
                    script_id=sid,
                    params=_parse_params(body.get("params")),
                )
                self._send_json(HTTPStatus.CREATED, self._trigger_payload(item))
                return
            if path == "/api/triggers":
                # Generic create: caller specifies ``kind`` and the relevant fields.
                item = self._create_trigger(body)
                self._send_json(HTTPStatus.CREATED, item)
                return
            if path.startswith("/api/triggers/") and path.endswith("/run"):
                tid = int(path.split("/")[3])
                item = self._run_trigger_now(tid)
                self._send_json(HTTPStatus.CREATED, item)
                return
            if path == "/api/runs":
                item = create_run(
                    self.server.connection,
                    int(body["script_id"]),
                    int(body["trigger_id"]) if body.get("trigger_id") is not None else None,
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

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self._require_auth():
            return
        try:
            body = self._body()
            if path.startswith("/api/triggers/"):
                tid = int(path.rsplit("/", 1)[1])
                item = update_trigger(
                    self.server.connection,
                    tid,
                    enabled=body.get("enabled"),
                    next_run_at=body.get("next_run_at"),
                    expression=body.get("expression"),
                    retry_max=body.get("retry_max"),
                    retry_backoff_seconds=body.get("retry_backoff_seconds"),
                    alert_webhook_url=body["alert_webhook_url"]
                    if "alert_webhook_url" in body
                    else ...,
                    params=_parse_params(body["params"]) if "params" in body else None,
                )
                if not item:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "trigger not found"})
                else:
                    self._send_json(HTTPStatus.OK, self._trigger_payload(item))
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": f"invalid request: {exc}"})
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "database error"})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self._require_auth():
            return
        try:
            if path.startswith("/api/triggers/"):
                tid = int(path.rsplit("/", 1)[1])
                deleted = delete_trigger(self.server.connection, tid)
                if deleted:
                    self._send_no_content(HTTPStatus.NO_CONTENT)
                else:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "trigger not found"})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid resource id"})
        except sqlite3.Error:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "database error"})

    # --- helpers ----------------------------------------------------------

    def _handle_webhook_hit(self, token: str) -> None:
        """Public POST /webhooks/<token>: validate token, enqueue the script."""
        if not token:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        trigger = get_trigger_by_webhook_token(self.server.connection, token)
        if trigger is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "invalid webhook token"})
            return
        try:
            result = runner.run_script(
                connection=self.server.connection,
                storage_dir=self.server.settings.storage_dir,
                script_id=int(trigger["script_id"]),
                trigger_id=int(trigger["id"]),
            )
        except (ValueError, FileNotFoundError) as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            return
        self._send_json(
            HTTPStatus.ACCEPTED,
            {"run_id": result.run["id"], "status": result.run["status"]},
        )

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

    def _create_schedule_trigger(self, script_id: int, body: dict[str, Any]) -> dict[str, Any]:
        if get_script(self.server.connection, script_id) is None:
            raise ValueError("script not found")
        trigger = create_schedule_trigger(
            self.server.connection,
            script_id=script_id,
            kind=str(body["schedule_kind"]),
            expression=str(body["expression"]),
            next_run_at=body.get("next_run_at"),
            enabled=bool(body.get("enabled", True)),
            retry_max=int(body.get("retry_max", 0)),
            retry_backoff_seconds=int(body.get("retry_backoff_seconds", 60)),
            alert_webhook_url=body.get("alert_webhook_url"),
            params=_parse_params(body.get("params")),
        )
        return self._trigger_payload(trigger)

    def _create_trigger(self, body: dict[str, Any]) -> dict[str, Any]:
        kind = body.get("kind")
        if kind == "schedule":
            return self._create_schedule_trigger(int(body["script_id"]), body)
        if kind == "webhook":
            if get_script(self.server.connection, int(body["script_id"])) is None:
                raise ValueError("script not found")
            trigger = create_webhook_trigger(
                self.server.connection,
                script_id=int(body["script_id"]),
                params=_parse_params(body.get("params")),
            )
            return self._trigger_payload(trigger)
        raise ValueError("kind must be 'schedule' or 'webhook'")

    def _trigger_run(self, script_id: int, body: dict[str, Any]) -> dict[str, Any]:
        trigger_id = body.get("trigger_id")
        result = runner.run_script(
            connection=self.server.connection,
            storage_dir=self.server.settings.storage_dir,
            script_id=script_id,
            trigger_id=int(trigger_id) if trigger_id is not None else None,
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

    def _run_trigger_now(self, trigger_id: int) -> dict[str, Any]:
        trigger = get_trigger(self.server.connection, trigger_id)
        if trigger is None:
            raise ValueError("trigger not found")
        result = runner.run_script(
            connection=self.server.connection,
            storage_dir=self.server.settings.storage_dir,
            script_id=int(trigger["script_id"]),
            trigger_id=trigger_id,
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


def _parse_params(value: Any) -> dict[str, str] | None:
    """Accept either ``None``, ``{}``, or a flat dict of stringy values."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("params must be a JSON object")
    out: dict[str, str] = {}
    for key, raw in value.items():
        if not isinstance(key, str):
            raise ValueError("params keys must be strings")
        if not isinstance(raw, (str, int, float, bool)):
            raise ValueError(
                f"params[{key!r}] must be a scalar (string/number/bool)"
            )
        out[key] = str(raw)
    return out


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


# --------------------------------------------------------------------- HTML
# Tiny HTML helpers kept here (not Jinja) so the page works without any extra
# dependency. The renderer is intentionally minimal — no templates, no
# caching layer, just a handful of functions for the pages. HTML escape lives
# in ``_h`` so untrusted run metadata can't inject markup.


def _h(value: Any) -> str:
    """HTML-escape a value into a string."""
    s = "" if value is None else str(value)
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_logs_index(rows: list[dict[str, Any]]) -> str:
    """Render the ``/logs`` index page as a self-contained HTML document."""
    rows_html = []
    if not rows:
        rows_html.append('<tr><td colspan="5" class="empty">No runs yet.</td></tr>')
    else:
        for run in rows:
            rows_html.append(_render_index_row(run))
    rows_joined = "\n".join(rows_html)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ScriptDeck · Logs</title>
<style>
 body {{ font: 14px/1.4 -apple-system, system-ui, sans-serif; margin: 2rem; color: #1d1d1f; }}
 h1 {{ margin: 0 0 1rem; font-size: 1.25rem; }}
 table {{ width: 100%; border-collapse: collapse; }}
 th, td {{ text-align: left; padding: 0.5rem 0.75rem; border-bottom: 1px solid #e5e5e7; }}
 th {{ font-weight: 600; color: #6e6e73; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
 tr:hover {{ background: #f5f5f7; cursor: pointer; }}
 .empty {{ text-align: center; color: #6e6e73; padding: 2rem; }}
 .badge {{ display: inline-block; padding: 0.1rem 0.5rem; border-radius: 999px; \
            font-size: 0.75rem; font-weight: 600; text-transform: uppercase; }}
 .badge-success {{ background: #d1f4d8; color: #1c6b32; }}
 .badge-failure {{ background: #fcd7d4; color: #a3151d; }}
 .badge-error {{ background: #fce4cf; color: #8a4b00; }}
 .badge-cancelled {{ background: #e0e0e5; color: #3c3c43; }}
 .badge-running {{ background: #d1e7ff; color: #1a4480; }}
</style>
</head>
<body>
<h1>Recent runs</h1>
<table>
 <thead><tr><th>ID</th><th>Script</th><th>Status</th><th>Duration</th><th>Started</th></tr></thead>
 <tbody>
{rows_joined}
 </tbody>
</table>
<script>
document.querySelectorAll('tbody tr[data-href]').forEach(function (tr) {{
  tr.addEventListener('click', function () {{ window.location = tr.dataset.href; }});
}});
</script>
</body>
</html>"""


def _render_index_row(run: dict[str, Any]) -> str:
    status = run.get("status") or "running"
    started = run.get("started_at") or ""
    duration = _compute_duration(run)
    return (
        f'<tr data-href="/logs/{run["id"]}">'
        f"<td>{_h(run['id'])}</td>"
        f"<td>{_h(run.get('script_name') or '(deleted)')}</td>"
        f'<td><span class="badge badge-{_h(status)}">{_h(status)}</span></td>'
        f"<td>{_h(duration)}</td>"
        f"<td>{_h(started)}</td>"
        f"</tr>"
    )


def _compute_duration(run: dict[str, Any]) -> str:
    """Best-effort duration string. Empty while the run is in-flight."""
    started = run.get("started_at")
    ended = run.get("ended_at")
    if not started or not ended:
        return ""
    try:
        from datetime import datetime

        s = datetime.fromisoformat(started.replace("Z", "+00:00"))
        e = datetime.fromisoformat(ended.replace("Z", "+00:00"))
        delta = (e - s).total_seconds()
    except ValueError:
        return ""
    if delta < 1:
        return f"{int(delta * 1000)}ms"
    if delta < 60:
        return f"{delta:.1f}s"
    minutes, seconds = divmod(delta, 60)
    return f"{int(minutes)}m {int(seconds)}s"


def render_logs_viewer(run: dict[str, Any], storage_dir: Any) -> str:
    """Render the ``/logs/<run_id>`` viewer page with an embedded SSE client.

    The inline ``<script>`` block wires a vanilla ``EventSource`` to the SSE
    endpoint and updates the on-page status badge when the stream ends.
    """
    run_id = _h(run["id"])
    script_name = _h(run.get("script_name") or "(deleted)")
    started = _h(run.get("started_at") or "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ScriptDeck · Run #{run_id}</title>
<style>
 body {{ font: 14px/1.4 -apple-system, system-ui, sans-serif; margin: 0; color: #1d1d1f; background: #1d1d1f; }}
 header {{ padding: 0.75rem 1rem; background: #2c2c2e; color: #f5f5f7; display: flex; \
            gap: 1rem; align-items: baseline; }}
 header h1 {{ margin: 0; font-size: 0.95rem; font-weight: 600; }}
 header .meta {{ font-size: 0.8rem; color: #98989d; }}
 #status {{ padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.75rem; \
           font-weight: 600; text-transform: uppercase; background: #48484a; color: #f5f5f7; }}
 #status.live {{ background: #d1e7ff; color: #1a4480; }}
 #status.done {{ background: #d1f4d8; color: #1c6b32; }}
 #status.error {{ background: #fcd7d4; color: #a3151d; }}
 pre {{ margin: 0; padding: 1rem; font: 12.5px/1.5 ui-monospace, Menlo, Consolas, monospace; \
       color: #f5f5f7; white-space: pre-wrap; word-break: break-word; min-height: calc(100vh - 50px); }}
</style>
</head>
<body>
<header>
 <h1>Run #{run_id} — {script_name}</h1>
 <span class="meta">started {started}</span>
 <span id="status" class="live">live</span>
</header>
<pre id="log"></pre>
<script>
(function () {{
  var log = document.getElementById('log');
  var statusEl = document.getElementById('status');
  var es = new EventSource('/api/logs/{run_id}/stream');
  es.onmessage = function (e) {{
    log.textContent += e.data + '\\n';
  }};
  es.addEventListener('end', function (e) {{
    var s = (e.data || '').replace(/^status=/, '') || 'done';
    statusEl.textContent = s;
    statusEl.classList.remove('live');
    statusEl.classList.add(s === 'success' ? 'done' : (s === 'failure' || s === 'error') ? 'error' : 'done');
    es.close();
  }});
  es.onerror = function () {{
    statusEl.textContent = 'disconnected';
    statusEl.classList.remove('live');
  }};
}})();
</script>
</body>
</html>"""


def render_script_view(script: dict[str, Any], triggers: list[dict[str, Any]]) -> str:
    """Render the ``/scripts/<id>`` page: script metadata + all its triggers.

    Each trigger row shows its kind + a copy-able identifier (the cron
    expression for schedules, the URL for webhooks) and the standard CRUD
    affordances (add schedule, add webhook, run-now, edit, delete).
    """
    script_id = int(script["id"])
    script_name = _h(script.get("name") or "")
    language = _h(script.get("language") or "")
    rows = [_render_trigger_row(t) for t in triggers]
    if not rows:
        rows.append(
            '<tr><td colspan="5" class="empty">No triggers yet.</td></tr>'
        )
    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ScriptDeck · {script_name}</title>
<style>
 body {{ font: 14px/1.4 -apple-system, system-ui, sans-serif; margin: 2rem; color: #1d1d1f; max-width: 960px; }}
 h1 {{ margin: 0 0 0.25rem; font-size: 1.4rem; }}
 .meta {{ color: #6e6e73; font-size: 0.85rem; margin-bottom: 1.5rem; }}
 h2 {{ margin: 1.5rem 0 0.75rem; font-size: 1.05rem; }}
 table {{ width: 100%; border-collapse: collapse; }}
 th, td {{ text-align: left; padding: 0.6rem 0.75rem; border-bottom: 1px solid #e5e5e7; vertical-align: top; }}
 th {{ font-weight: 600; color: #6e6e73; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
 .empty {{ text-align: center; color: #6e6e73; padding: 2rem; }}
 .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 999px; \
            font-size: 0.72rem; font-weight: 600; text-transform: uppercase; }}
 .badge-schedule {{ background: #d1e7ff; color: #1a4480; }}
 .badge-webhook {{ background: #e5d1ff; color: #4b1a80; }}
 code {{ font: 12.5px/1.4 ui-monospace, Menlo, Consolas, monospace; \
        background: #f5f5f7; padding: 0.15rem 0.4rem; border-radius: 4px; }}
 .actions {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
 button {{ font: inherit; padding: 0.3rem 0.7rem; border-radius: 4px; border: 1px solid #d2d2d7; \
            background: #fff; cursor: pointer; }}
 button.primary {{ background: #1a4480; color: #fff; border-color: #1a4480; }}
 button.danger {{ color: #a3151d; border-color: #fcd7d4; }}
 form.add {{ display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: flex-end; \
             margin-top: 0.5rem; padding: 0.75rem; border: 1px solid #e5e5e7; border-radius: 6px; }}
 form.add label {{ display: flex; flex-direction: column; font-size: 0.78rem; color: #6e6e73; }}
 form.add input, form.add select {{ font: inherit; padding: 0.3rem 0.5rem; border: 1px solid #d2d2d7; \
                                     border-radius: 4px; }}
</style>
</head>
<body>
<h1>{script_name}</h1>
<div class="meta">script #{script_id} · {language}</div>

<h2>Triggers</h2>
<table>
 <thead><tr><th>ID</th><th>Kind</th><th>Detail</th><th>Params</th><th>Actions</th></tr></thead>
 <tbody>
{rows_html}
 </tbody>
</table>

<h2>Add schedule trigger</h2>
<form class="add" data-kind="schedule">
 <label>Kind
  <select name="schedule_kind">
   <option value="cron">cron</option>
   <option value="interval">interval</option>
  </select>
 </label>
 <label>Expression <input name="expression" placeholder="*/5 * * * *" required></label>
 <label>Enabled
  <select name="enabled">
   <option value="1">yes</option>
   <option value="0">no</option>
  </select>
 </label>
 <label>Retry max <input name="retry_max" type="number" min="0" value="0"></label>
 <label><button type="submit" class="primary">Add schedule</button></label>
</form>

<h2>Add webhook trigger</h2>
<form class="add" data-kind="webhook">
 <label>Params (JSON object, optional)
  <input name="params" placeholder='{{"env":"prod"}}'>
 </label>
 <label><button type="submit" class="primary">Add webhook</button></label>
</form>

<script>
(function () {{
  function submitForm(form, path) {{
    var body = {{}};
    Array.prototype.forEach.call(form.elements, function (el) {{
      if (!el.name) return;
      var v = el.value;
      if (el.type === 'number') {{
        v = v === '' ? null : Number(v);
      }}
      body[el.name] = v;
    }});
    if (form.dataset.kind === 'webhook' && body.params) {{
      try {{ body.params = JSON.parse(body.params); }}
      catch (err) {{
        alert('params must be valid JSON: ' + err.message);
        return;
      }}
    }}
    fetch(path, {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(body)
    }}).then(function (r) {{
      if (r.ok) {{
        location.reload();
      }} else {{
        return r.json().then(function (e) {{
          alert('Error: ' + (e.error || r.status));
        }});
      }}
    }});
  }}
  Array.prototype.forEach.call(document.querySelectorAll('form.add'), function (form) {{
    form.addEventListener('submit', function (e) {{
      e.preventDefault();
      var path = form.dataset.kind === 'webhook'
        ? '/api/scripts/{script_id}/triggers/webhook'
        : '/api/scripts/{script_id}/triggers/schedule';
      submitForm(form, path);
    }});
  }});
  document.body.addEventListener('click', function (e) {{
    var btn = e.target.closest('button[data-action]');
    if (!btn) return;
    var id = btn.dataset.id;
    if (btn.dataset.action === 'delete') {{
      if (!confirm('Delete trigger ' + id + '?')) return;
      fetch('/api/triggers/' + id, {{ method: 'DELETE' }}).then(function (r) {{
        if (r.ok) {{ location.reload(); }} else {{ alert('Delete failed'); }}
      }});
    }} else if (btn.dataset.action === 'run') {{
      fetch('/api/triggers/' + id + '/run', {{ method: 'POST' }}).then(function (r) {{
        r.json().then(function (b) {{
          alert('Run ' + (b.run ? b.run.id : '?') + ' (' + (b.run ? b.run.status : '?') + ')');
        }});
      }});
    }}
  }});
  Array.prototype.forEach.call(document.querySelectorAll('code[data-copy]'), function (el) {{
    el.style.cursor = 'pointer';
    el.title = 'click to copy';
    el.addEventListener('click', function () {{
      navigator.clipboard && navigator.clipboard.writeText(el.dataset.copy);
    }});
  }});
}})();
</script>
</body>
</html>"""


def _render_trigger_row(trigger: dict[str, Any]) -> str:
    tid = int(trigger["id"])
    kind = trigger.get("kind") or "schedule"
    params = trigger_params(trigger)
    params_html = (
        "<code>" + _h(json.dumps(params, sort_keys=True)) + "</code>"
        if params
        else '<span style="color:#98989d">—</span>'
    )
    if kind == "schedule":
        detail = (
            f"<code>{_h(trigger.get('expression') or '')}</code> "
            f"({_h(trigger.get('schedule_kind') or '')}) "
            + ("enabled" if trigger.get("enabled") else "<strong>disabled</strong>")
        )
        if trigger.get("alert_webhook_url"):
            detail += (
                f'<div style="font-size:0.8rem;color:#6e6e73;margin-top:0.25rem">'
                f'alert: {_h(trigger["alert_webhook_url"])}</div>'
            )
    else:
        url = trigger.get("webhook_url") or ""
        token = trigger.get("webhook_token") or ""
        detail = (
            f'<code data-copy="{_h(url)}">{_h(url)}</code>'
            if url
            else f'<code data-copy="{_h(token)}">{_h(token[:12])}…</code>'
        )
    return (
        f"<tr>"
        f"<td>{_h(tid)}</td>"
        f'<td><span class="badge badge-{_h(kind)}">{_h(kind)}</span></td>'
        f"<td>{detail}</td>"
        f"<td>{params_html}</td>"
        f'<td><div class="actions">'
        f'<button data-action="run" data-id="{_h(tid)}">Run now</button>'
        f'<button data-action="delete" data-id="{_h(tid)}" class="danger">Delete</button>'
        f"</div></td>"
        f"</tr>"
    )
