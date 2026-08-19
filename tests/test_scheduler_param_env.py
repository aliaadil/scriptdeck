"""Tests that the scheduler tick propagates ``params_json`` from cron/interval
triggers into the run subprocess env as ``KINDLING_PARAM_<KEY>=<value>``.

Webhook triggers exercise the same code path through ``webhooks.py`` and are
covered separately in ``tests/test_param_env.py`` and ``tests/api/test_webhooks.py``.
This test is specifically for the cron/interval side.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert

from kindling.config import Settings
from kindling.db.engine import make_engine, session_factory
from kindling.db.migrations import run_migrations
from kindling.db.models import schedules, scripts, users
from kindling.scheduler.tick import _tick
from kindling.services.log_broker import LogBroker


_DUMP_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "kindling_scheduler_param_dump.json"


@pytest.mark.asyncio
async def test_tick_cron_with_params_json_exports_kindling_param_env(tmp_path):
    """A cron trigger with params_json={'region':'eu','shard':'9'} makes the
    subprocess see KINDLING_PARAM_region=eu and KINDLING_PARAM_shard=9 in env."""
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    now_iso = datetime.now(UTC).isoformat()

    async with Sf() as s:
        await s.execute(insert(users).values(
            id=1, email="a@x.com", password_hash="x", role="editor",
            created_at=now_iso,
        ))
        await s.execute(insert(scripts).values(
            id=1, user_id=1, name="t", language="python",
            source_path="scripts/1/main.py",
            entrypoint="main.py",
            created_at=now_iso, updated_at=now_iso,
        ))
        await s.execute(insert(schedules).values(
            script_id=1, kind="cron", expression="* * * * *",
            enabled=1, next_run_at=now_iso,
            params_json=json.dumps({"region": "eu", "shard": 9}),
        ))
        await s.commit()

    # Write the script that dumps its env to the side-channel file so we can
    # assert what the child process actually saw.
    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text(
        "import os, json\n"
        f"with open('{_DUMP_PATH}', 'w') as f:\n"
        "    keys = ['KINDLING_PARAM_region', 'KINDLING_PARAM_shard']\n"
        "    json.dump({k: os.environ.get(k) for k in keys}, f)\n",
        encoding="utf-8",
    )
    # Wipe any stale dump from a prior test run.
    try:
        _DUMP_PATH.unlink()
    except FileNotFoundError:
        pass

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw):
            return {}

    await _tick(
        settings=settings,
        session_factory=Sf,
        log_broker=broker,
        env_service=FakeEnv(),
        concurrency=sem,
        storage_dir=tmp_path / "s",
    )
    # Allow the background run_script to complete and write the dump.
    for _ in range(40):
        await asyncio.sleep(0.25)
        if _DUMP_PATH.exists():
            break
    assert _DUMP_PATH.exists(), "script did not write the env dump in time"
    captured = json.loads(_DUMP_PATH.read_text())
    assert captured == {
        "KINDLING_PARAM_region": "eu",
        "KINDLING_PARAM_shard": "9",
    }
    _DUMP_PATH.unlink()