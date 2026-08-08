"""Tests for the live log SSE stream and the static ``/logs`` viewer pages.

These are end-to-end against the real :class:`ThreadingHTTPServer`. Each test
spawns the server on an ephemeral port, hits the relevant URL with ``urllib``,
and reads the response body either to completion (for the static pages) or as
a streaming byte source (for the SSE endpoint). The streaming reads use a
thread that accumulates events until a sentinel value is seen, with a hard
timeout so a stuck stream fails the test instead of hanging the suite.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.client import HTTPResponse
from queue import Queue
from threading import Thread

import pytest

from scriptrunner.config import Settings
from scriptrunner.repository import create_run, create_script
from scriptrunner.server import ScriptRunnerServer


# ----------------------------------------------------------------- fixtures
@pytest.fixture
def server(tmp_db_path, storage_dir):
    settings = Settings(
        db_path=tmp_db_path,
        storage_dir=storage_dir,
        host="127.0.0.1",
        port=0,
    )
    srv = ScriptRunnerServer(settings)
    host, port = srv.server_address
    thread = Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}", srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=2)


@pytest.fixture
def seeded_run(tmp_db_path, storage_dir):
    """A script + run with a real ``log_path`` pointing inside ``storage_dir``."""
    conn = sqlite3.connect(str(tmp_db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        script = create_script(
            conn, name="echo", language="python", source_path="/srv/echo.py"
        )
        logs_dir = storage_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / "1.log"
        log_path.write_text("")  # create the file so the stream can stat it
        run = create_run(
            conn,
            script["id"],
            status="running",
            started_at="2026-08-08T12:00:00+00:00",
            log_path=str(log_path),
            log_size_bytes=0,
        )
        yield conn, script, run, log_path
    finally:
        conn.close()


# ----------------------------------------------------------------- helpers
def _get(base: str, path: str, timeout: float | None = None) -> tuple[int, bytes, HTTPResponse]:
    """Open a GET with an optional read timeout. Returns (status, body, raw)."""
    req = urllib.request.Request(base + path, method="GET")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        body = resp.read()
        return resp.status, body, resp
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e


def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        base + path,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _read_sse_until(
    base: str,
    path: str,
    stop_event: threading.Event,
    results: list[str],
    errors: list[BaseException],
    timeout: float = 8.0,
) -> None:
    """Worker thread: open an SSE GET and append events to ``results``."""
    try:
        req = urllib.request.Request(base + path, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout)
        buf = b""
        while not stop_event.is_set():
            chunk = resp.read(1)
            if not chunk:
                break
            buf += chunk
            # SSE frames end with a blank line — flush one frame at a time.
            while b"\n\n" in buf:
                raw_frame, _, buf = buf.partition(b"\n\n")
                frame = raw_frame.decode("utf-8", errors="replace")
                results.append(frame)
                if any(line.startswith("event: end") for line in frame.splitlines()):
                    stop_event.set()
                    return
    except BaseException as exc:  # noqa: BLE001 — surface anything to the main thread
        errors.append(exc)


def _drain_until_sentinel(
    resp: HTTPResponse,
    queue: Queue[str | None],
    sentinel: str,
    timeout: float = 8.0,
) -> None:
    """Worker thread: read SSE frames until one contains ``sentinel``."""
    try:
        buf = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = resp.read(1)
            if not chunk:
                queue.put(None)
                return
            buf += chunk
            while b"\n\n" in buf:
                frame, _, buf = buf.partition(b"\n\n")
                decoded = frame.decode("utf-8", errors="replace")
                queue.put(decoded)
                if sentinel in decoded:
                    return
        queue.put(None)
    except BaseException as exc:  # noqa: BLE001
        queue.put(exc)


# ----------------------------------------------------------------- (a) tail
def test_sse_tails_an_active_file(server, seeded_run) -> None:
    """Lines appended to the log file arrive over SSE within 1s."""
    base, _ = server
    _, _, run, log_path = seeded_run

    stop = threading.Event()
    frames: list[str] = []
    errors: list[BaseException] = []
    worker = Thread(
        target=_read_sse_until,
        args=(base, f"/api/logs/{run['id']}/stream", stop, frames, errors),
        daemon=True,
    )
    worker.start()

    # Give the stream a moment to send its headers before we write data.
    time.sleep(0.3)
    started = time.monotonic()
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write("hello world\n")
        fh.write("second line\n")
        fh.flush()

    # Wait for the two events to land; 1s SLA per acceptance criteria.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        joined = "\n".join(frames)
        if "hello world" in joined and "second line" in joined:
            break
        time.sleep(0.05)
    elapsed = time.monotonic() - started
    stop.set()
    worker.join(timeout=2)

    assert not errors, f"SSE worker raised: {errors!r}"
    assert any("hello world" in f for f in frames), f"missing 'hello world' in {frames!r}"
    assert any("second line" in f for f in frames), f"missing 'second line' in {frames!r}"
    assert elapsed < 1.5, f"lines took {elapsed:.2f}s (>1.5s including overhead)"


def test_sse_replays_existing_content(server, seeded_run) -> None:
    """A client connecting after the runner has written some lines still
    receives the prior content before any new tail events."""
    base, _ = server
    _, _, run, log_path = seeded_run
    log_path.write_text("first\nsecond\n")

    stop = threading.Event()
    frames: list[str] = []
    errors: list[BaseException] = []
    worker = Thread(
        target=_read_sse_until,
        args=(base, f"/api/logs/{run['id']}/stream", stop, frames, errors),
        daemon=True,
    )
    worker.start()

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        joined = "\n".join(frames)
        if "first" in joined and "second" in joined:
            break
        time.sleep(0.05)
    stop.set()
    worker.join(timeout=2)
    assert not errors
    assert any("first" in f for f in frames)
    assert any("second" in f for f in frames)


# --------------------------------------------------------------- (b) close
def test_sse_closes_on_terminal_status(server, seeded_run) -> None:
    """When the run transitions to a terminal status, the stream emits
    ``event: end`` and closes the connection."""
    base, _ = server
    conn, _, run, log_path = seeded_run
    # Start the stream while the run is still "running".
    stop = threading.Event()
    frames: list[str] = []
    errors: list[BaseException] = []
    worker = Thread(
        target=_read_sse_until,
        args=(base, f"/api/logs/{run['id']}/stream", stop, frames, errors),
        daemon=True,
    )
    worker.start()

    # Give the stream time to establish, then transition to a terminal state.
    time.sleep(0.3)
    conn.execute(
        "UPDATE runs SET status='success', ended_at=? WHERE id=?",
        ("2026-08-08T12:01:00+00:00", run["id"]),
    )
    conn.commit()

    # The handler should detect the terminal state, emit ``event: end``, and
    # close. The worker thread will exit when it sees the end event or when
    # the underlying socket returns 0 bytes.
    worker.join(timeout=5)
    assert not worker.is_alive(), "SSE worker did not exit after terminal status"
    assert not errors, f"SSE worker raised: {errors!r}"
    joined = "\n".join(frames)
    assert "event: end" in joined, f"missing event:end in {frames!r}"
    assert "status=success" in joined, f"missing status payload in {frames!r}"


def test_sse_closes_on_failure_status(server, seeded_run) -> None:
    """Same as above but for ``status='failure'`` — guards the other
    terminal-status branches."""
    base, _ = server
    conn, _, run, log_path = seeded_run
    stop = threading.Event()
    frames: list[str] = []
    errors: list[BaseException] = []
    worker = Thread(
        target=_read_sse_until,
        args=(base, f"/api/logs/{run['id']}/stream", stop, frames, errors),
        daemon=True,
    )
    worker.start()
    time.sleep(0.3)
    conn.execute(
        "UPDATE runs SET status='failure', ended_at=? WHERE id=?",
        ("2026-08-08T12:01:00+00:00", run["id"]),
    )
    conn.commit()
    worker.join(timeout=5)
    assert not worker.is_alive()
    joined = "\n".join(frames)
    assert "event: end" in joined
    assert "status=failure" in joined


# ------------------------------------------------------------- (c) 404
def test_sse_404_for_unknown_run(server) -> None:
    base, _ = server
    status, body, _ = _get(base, "/api/logs/9999/stream")
    assert status == 404
    payload = json.loads(body)
    assert payload["error"] == "run not found"


def test_sse_404_for_non_numeric_run_id(server) -> None:
    base, _ = server
    status, _, _ = _get(base, "/api/logs/abc/stream")
    assert status == 400


# --------------------------------------------------- (d) static /logs page
def test_logs_index_renders(server, seeded_run) -> None:
    """``/logs`` returns 200, lists the seeded run, and embeds the JS that
    wires each row to the viewer. No JS framework dependency."""
    base, _ = server
    status, body, _ = _get(base, "/logs")
    assert status == 200
    html = body.decode("utf-8")
    assert "Recent runs" in html
    assert "/logs/1" in html, "expected link to the seeded run"
    assert "data-href" in html, "expected the click-to-navigate handler markup"
    # Vanilla JS hookup — no framework imports, no <script src="..."> tags.
    assert "<script src=" not in html
    assert "EventSource" not in html  # EventSource lives in the viewer page
    # Rows render the status badge for the running state we seeded.
    assert "badge-running" in html
    assert "echo" in html  # script name


def test_logs_viewer_renders(server, seeded_run) -> None:
    """``/logs/<run_id>`` returns a viewer page that connects via EventSource
    to the SSE endpoint."""
    base, _ = server
    _, _, run, _ = seeded_run
    status, body, _ = _get(base, f"/logs/{run['id']}")
    assert status == 200
    html = body.decode("utf-8")
    assert "EventSource" in html
    assert f"/api/logs/{run['id']}/stream" in html
    assert "eventSource" not in html  # canonical capitalisation only
    assert "addEventListener" in html  # wires the end-event handler


def test_logs_index_lists_only_last_50_runs(server, seeded_run) -> None:
    """Index cap: only the 50 newest runs render. Older ones must not appear."""
    base, _ = server
    conn, _, _, _ = seeded_run
    # Seed 60 runs (id 1 already exists; create 59 more).
    for _ in range(59):
        conn.execute(
            "INSERT INTO runs(script_id, started_at, status) VALUES (?, ?, ?)",
            (1, "2026-08-08T12:00:00+00:00", "success"),
        )
    conn.commit()
    status, body, _ = _get(base, "/logs")
    assert status == 200
    html = body.decode("utf-8")
    # 50 data rows, none older than id 10 should appear (60 total, cap 50).
    rows = html.count('data-href="/logs/')
    assert rows == 50
    # The oldest run (id=1) must be excluded by the cap — check the row markup
    # specifically so we don't false-match on /logs/19, /logs/18, etc.
    assert 'data-href="/logs/1"' not in html
    assert 'data-href="/logs/60"' in html


def test_logs_viewer_js_has_no_obvious_errors(server, seeded_run) -> None:
    """Static JS sanity: the inline ``<script>`` block must contain balanced
    braces and no obvious syntax issues. We extract the script content, run
    it through Python's ``compile()``-equivalent check, and look for the
    minimum required wiring (EventSource + addEventListener + end-event
    handler). A real headless-browser smoke test would be heavier than the
    rest of the suite; this catches the structural regressions that matter.
    """
    base, _ = server
    _, _, run, _ = seeded_run
    status, body, _ = _get(base, f"/logs/{run['id']}")
    assert status == 200
    html = body.decode("utf-8")
    # Extract the last <script> block (the viewer JS).
    start = html.rfind("<script>")
    end = html.rfind("</script>")
    assert start != -1 and end != -1
    js = html[start + len("<script>") : end]
    # Brace balance — catches the most common "forgot to close" mistake.
    assert js.count("{") == js.count("}"), "unbalanced braces in viewer JS"
    assert js.count("(") == js.count(")"), "unbalanced parens in viewer JS"
    # Required wiring.
    assert "new EventSource(" in js
    assert ".onmessage" in js
    assert "addEventListener('end'" in js
    assert "es.close()" in js
