from __future__ import annotations

import asyncio
import fcntl
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

_process_locks: dict[int, asyncio.Lock] = {}
_process_locks_guard = asyncio.Lock()


async def _get_lock(script_id: int) -> asyncio.Lock:
    async with _process_locks_guard:
        lock = _process_locks.get(script_id)
        if lock is None:
            lock = asyncio.Lock()
            _process_locks[script_id] = lock
        return lock


@asynccontextmanager
async def per_script_lock(script_id: int, locks_dir: Path) -> AsyncIterator[None]:
    """Per-script lock combining asyncio.Lock + fcntl.flock sentinel.

    fcntl layer survives crashes; asyncio layer prevents intra-process races.
    """
    locks_dir.mkdir(parents=True, exist_ok=True)
    sentinel = locks_dir / f"{script_id}.lock"
    inner = await _get_lock(script_id)
    async with inner:
        with sentinel.open("a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
