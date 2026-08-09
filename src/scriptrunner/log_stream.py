"""Live log streaming over Server-Sent Events.

The runner writes stdout + stderr to ``<storage>/logs/<run_id>.log`` while a
script runs. The HTTP service tails that file and pushes new lines to a client
over SSE until the run's ``runs.status`` reaches a terminal state.

Two pieces of logic live here, separated from the HTTP handler so they are
unit-testable:

* :func:`read_new_lines` — open a file and read every full line past an offset.
  Returns the new lines (without trailing newlines) and the new offset. Handles
  missing files (returns empty, no error) and truncation (size shrinks below
  the current offset, resets to 0).
* :func:`encode_sse` — format a single SSE event frame.

The handler in :mod:`scriptrunner.server` is responsible for the HTTP framing,
content-type, keep-alive, and the polling loop that glues these two together.
"""

from __future__ import annotations

from pathlib import Path

# How long the SSE handler sleeps between tail polls. Short enough to satisfy
# the v0.5 SLA ("sent within 1 second of the line appearing in the file"),
# long enough to avoid pegging a CPU when no work is happening.
TAIL_POLL_INTERVAL_SECONDS = 0.25


def read_new_lines(path: str | Path, offset: int) -> tuple[list[str], int]:
    """Return any full lines in ``path`` past ``offset`` and the new offset.

    The file is opened in binary mode and decoded as UTF-8 with ``errors='replace'``
    so a runner that emits non-UTF-8 bytes cannot crash the stream. A partial
    trailing line (no newline yet) is held back — it is returned when the next
    byte completes the line.

    If the file does not exist yet, returns ``([], offset)`` — the caller should
    keep polling, the runner may not have created the file yet. If the file was
    truncated (current size < ``offset``), the offset is reset to 0 so the
    caller will replay the new file from the start.
    """
    try:
        size = Path(path).stat().st_size
    except FileNotFoundError:
        return [], offset
    if size < offset:
        # Truncated or rotated; replay from the top of the new file.
        offset = 0
    if size == offset:
        return [], offset
    with open(path, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    if data.endswith(b"\n"):
        # Every byte read is part of a complete line.
        new_offset = offset + len(data)
        text = data.decode("utf-8", errors="replace")
        lines = text.split("\n")
        # `split("\n")` on a string ending with "\n" produces an empty
        # trailing element — drop it so callers don't see a phantom blank line.
        if lines and lines[-1] == "":
            lines.pop()
        return lines, new_offset
    # Partial trailing line — hold it back, only emit the lines that ended
    # in the bytes we just read.
    last_nl = data.rfind(b"\n")
    if last_nl == -1:
        # No newline at all yet — keep everything in the partial buffer.
        return [], offset
    complete = data[: last_nl + 1]
    new_offset = offset + last_nl + 1
    text = complete.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines, new_offset


def encode_sse(data: str, event: str | None = None) -> bytes:
    """Format a single SSE frame.

    The ``data`` field is written as one or more ``data: <line>`` lines, one
    per line of the payload (SSE spec — newline-separated lines inside the
    payload each get their own ``data:`` prefix). Optional ``event`` becomes
    the ``event: <name>`` field, which the browser exposes as
    ``event.event`` on the receiving EventSource.
    """
    parts: list[str] = []
    if event is not None:
        parts.append(f"event: {event}")
    for line in data.split("\n"):
        parts.append(f"data: {line}")
    # SSE frames are terminated by a blank line.
    parts.append("")
    parts.append("")
    return "\n".join(parts).encode("utf-8")


def encode_sse_heartbeat() -> bytes:
    """SSE comment line — keeps proxies from closing an idle connection."""
    return b": heartbeat\n\n"
