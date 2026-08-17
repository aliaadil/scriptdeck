from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


def encode_sse(data: dict, event: str | None = None) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}\n")
    parts.append(f"data: {json.dumps(data)}\n\n")
    return "".join(parts).encode("utf-8")


def encode_heartbeat() -> bytes:
    return b": heartbeat\n\n"


@dataclass
class _RunChannel:
    queues: set[asyncio.Queue[bytes]] = field(default_factory=set)
    ended: bool = False
    end_status: str | None = None
    end_exit: int | None = None


class LogBroker:
    """In-memory pub/sub for live run logs."""

    def __init__(self, heartbeat_seconds: float = 15.0) -> None:
        self._channels: dict[int, _RunChannel] = {}
        self._heartbeat = heartbeat_seconds
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: int) -> AsyncIterator[bytes]:
        async with self._lock:
            ch = self._channels.get(run_id)
            if ch is None:
                ch = _RunChannel()
                self._channels[run_id] = ch
            if ch.ended:
                yield encode_sse(
                    {"status": ch.end_status, "exit_code": ch.end_exit}, event="end"
                )
                return
            q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1024)
            ch.queues.add(q)
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=self._heartbeat)
                    yield chunk
                except TimeoutError:
                    yield encode_heartbeat()
        finally:
            async with self._lock:
                ch.queues.discard(q)

    async def publish(self, run_id: int, text: str, offset: int) -> None:
        async with self._lock:
            ch = self._channels.get(run_id)
            if ch is None or ch.ended:
                return
            queues = list(ch.queues)
            payload = encode_sse({"offset": offset, "text": text}, event="line")
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def close(self, run_id: int, status: str, exit_code: int) -> None:
        async with self._lock:
            ch = self._channels.get(run_id)
            if ch is None:
                ch = _RunChannel()
                self._channels[run_id] = ch
            if ch.ended:
                return
            ch.ended = True
            ch.end_status = status
            ch.end_exit = exit_code
            queues = list(ch.queues)
            payload = encode_sse({"status": status, "exit_code": exit_code}, event="end")
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


_broker: LogBroker | None = None


def get_broker() -> LogBroker:
    global _broker
    if _broker is None:
        _broker = LogBroker()
    return _broker
