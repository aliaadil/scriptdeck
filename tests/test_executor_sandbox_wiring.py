from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from dataclasses import dataclass

import pytest

from scriptdeck.runner.executor import Script, run_script
from scriptdeck.runner.registry import get_runner
from scriptdeck.services.log_broker import LogBroker


# The sandbox path imports `scriptdeck.runner.sandbox`, which dlopens
# `libc.so.6` at module load time. macOS does not ship libc.so.6, so the
# import itself raises OSError there. Skip on non-Linux platforms.
pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="sandbox requires libc.so.6 (Linux only)",
)


@dataclass
class FakeEnv:
    ciphertext: str | None = None
    nonce: str | None = None

    def decrypt_lines(self, *args, **kwargs):
        return {}


@pytest.mark.asyncio
async def test_executor_sandbox_path_runs_user_script(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_SANDBOX_ENABLED", "true")

    user_root = tmp_path / "users" / "1"
    src_dir = user_root / "scripts" / "1"
    src_dir.mkdir(parents=True)
    src = src_dir / "hello.py"
    src.write_text("print('hi from sandbox')")

    runner = get_runner("python")
    script = Script(
        id=1, user_id=1, name="hello", language="python",
        source_path=src, requirements=[],
    )
    broker = LogBroker()
    semaphore = asyncio.Semaphore(1)
    result = await run_script(
        run_id=1, script=script, env_service=FakeEnv(),
        log_broker=broker, concurrency=semaphore,
        storage_dir=tmp_path,
    )
    assert result.exit_code == 0
    body = result.log_path.read_text()
    assert "hi from sandbox" in body