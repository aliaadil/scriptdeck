import asyncio
from pathlib import Path

import pytest

from scriptdeck.runner.executor import run_script


@pytest.mark.asyncio
async def test_run_script_success(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    src = work / "hi.py"
    src.write_text("print('hello')\n")
    logs = tmp_path / "logs"
    logs.mkdir()

    class FakeScript:
        id = 1
        name = "hi"
        language = "python"
        source_path = src
        requirements: list[str] = []

    class FakeEnvService:
        def decrypt_lines(self, *args, **kwargs):
            return {}

    from scriptdeck.services.log_broker import LogBroker
    broker = LogBroker()
    sem = asyncio.Semaphore(4)

    result = await run_script(
        run_id=42,
        script=FakeScript(),  # type: ignore[arg-type]
        env_service=FakeEnvService(),  # type: ignore[arg-type]
        log_broker=broker,
        concurrency=sem,
        storage_dir=tmp_path,
    )
    assert result.exit_code == 0
    assert (logs / "42.log").exists()
    assert "hello" in (logs / "42.log").read_text()