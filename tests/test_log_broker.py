import asyncio

import pytest

from kindling.services.log_broker import (
    LogBroker,
    encode_heartbeat,
    encode_sse,
    get_broker,
)


@pytest.mark.asyncio
async def test_subscribe_yields_published_lines():
    broker = LogBroker()
    events: list[str] = []

    async def consume():
        async for chunk in broker.subscribe(run_id=1):
            text = chunk.decode()
            events.append(text)
            if "event: end" in text:
                return

    task = asyncio.create_task(consume())
    # Yield so subscribe() can register its queue before publishes arrive
    await asyncio.sleep(0)
    await broker.publish(1, "hello\n", offset=0)
    await broker.publish(1, "world\n", offset=6)
    await broker.close(1, status="success", exit_code=0)
    await task

    # JSON-serialized text includes the newline escape, so look for "hello and "world
    assert any('"hello\\n"' in e for e in events)
    assert any('"world\\n"' in e for e in events)
    assert any('"offset": 0' in e for e in events)
    assert any('"offset": 6' in e for e in events)
    assert any("event: line" in e for e in events)
    assert any("event: end" in e for e in events)


@pytest.mark.asyncio
async def test_close_is_idempotent():
    broker = LogBroker()
    events: list[str] = []

    async def consume():
        async for chunk in broker.subscribe(run_id=2):
            text = chunk.decode()
            events.append(text)
            if "event: end" in text:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await broker.close(2, "success", 0)
    await broker.close(2, "success", 0)
    await task

    # Exactly one end event delivered to the subscriber, even though
    # close() was called twice.
    end_count = sum(1 for e in events if "event: end" in e)
    assert end_count == 1


def test_encode_sse_with_event():
    out = encode_sse({"offset": 0, "text": "hello"}, event="line")
    assert out == b'event: line\ndata: {"offset": 0, "text": "hello"}\n\n'


def test_encode_sse_without_event():
    out = encode_sse({"x": 1})
    assert out == b'data: {"x": 1}\n\n'


def test_encode_heartbeat():
    assert encode_heartbeat() == b": heartbeat\n\n"


def test_get_broker_singleton():
    a = get_broker()
    b = get_broker()
    assert a is b
