"""Minimal JSON HTTP service for ScriptRunner."""

from __future__ import annotations

import json
import sqlite3
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

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
    create_schedule,
    create_script,
    get_log,
    get_run,
    get_script,
    list_recent_runs_with_script,
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

    # ------------------------------------------------------------------ routes
    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path == "/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        try:
            if path == "/logs":
                self._render_logs_index()
            elif path.startswith("/logs/"):
                run = get_run(self.server.connection, int(path.rsplit("/", 1)[1]))
                if not run:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "run not found"})
                else:
                    self._render_logs_viewer(run)
            elif path == "/api/scripts":
                self._send_json(HTTPStatus.OK, list_scripts(self.server.connection))
            elif path.startswith("/api/scripts/"):
                item = get_script(self.server.connection, int(path.rsplit("/", 1)[1]))
                self._send_json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND, item or {"error": "script not found"})
            elif path == "/api/schedules":
                self._send_json(HTTPStatus.OK, list_schedules(self.server.connection))
            elif path == "/api/runs":
                self._send_json(HTTPStatus.OK, list_runs(self.server.connection))
            elif path.startswith("/api/logs/"):
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


# --------------------------------------------------------------------- HTML
# Tiny HTML helpers kept here (not Jinja) so the page works without any extra
# dependency. The renderer is intentionally minimal — no templates, no
# caching layer, just two functions for the two pages. HTML escape lives in
# ``_h`` so untrusted run metadata can't inject markup.


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
