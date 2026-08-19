"""Tests for the per-trigger params env merge.

Contract: when a trigger has params_json like {"region": "us-east-1", "shard": 3},
every run enqueued from that trigger gets:

    KINDLING_PARAM_region=us-east-1
    KINDLING_PARAM_shard=3

…and nothing else. The user's encrypted .env values (if any) win on conflict —
a webhook MUST NOT be able to overwrite a secret the script owner set.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from kindling.api.webhooks import trigger_params_env
from kindling.runner.executor import run_script


# Use a per-process /tmp dump path so the background task can write to a
# location we know. We resolve to the user's real temp (still acceptable —
# these are test-only artifacts cleaned up at the end of each test).
_DUMP_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "kindling_param_env_dump.json"
_PRECEDENCE_PATH = Path(os.environ.get("TMPDIR", "/tmp")) / "kindling_param_precedence.txt"

def test_trigger_params_env_empty():
    assert trigger_params_env(None) == {}
    assert trigger_params_env("") == {}
    assert trigger_params_env("not json") == {}


def test_trigger_params_env_basic_dict():
    env = trigger_params_env('{"region": "us-east-1", "shard": 3}')
    assert env == {
        "KINDLING_PARAM_region": "us-east-1",
        "KINDLING_PARAM_shard": "3",
    }


def test_trigger_params_env_coerces_types():
    env = trigger_params_env('{"a": true, "b": 1.5, "c": false, "d": "ok"}')
    assert env == {
        "KINDLING_PARAM_a": "True",
        "KINDLING_PARAM_b": "1.5",
        "KINDLING_PARAM_c": "False",
        "KINDLING_PARAM_d": "ok",
    }


def test_trigger_params_env_non_object_returns_empty():
    assert trigger_params_env('[1,2,3]') == {}
    assert trigger_params_env('"hello"') == {}


@pytest.mark.asyncio
async def test_run_script_merges_param_env_into_process_env(tmp_path):
    """When run_script is called with param_env, each KINDLING_PARAM_<KEY>
    is exported into the script's environment."""
    work = tmp_path / "work"
    work.mkdir()
    # Script writes the relevant subset of its env to a file so the test can
    # assert what the child process actually saw.
    src = work / "main.py"
    src.write_text(
        "import os, json\n"
        f"with open('{_DUMP_PATH}', 'w') as f:\n"
        "    keys = ['KINDLING_PARAM_region', 'KINDLING_PARAM_shard', "
        "            'KINDLING_PARAM_FROM_USER_ENV']\n"
        "    json.dump({k: os.environ.get(k) for k in keys}, f)\n",
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()
    try:
        _DUMP_PATH.unlink()
    except FileNotFoundError:
        pass

    class FakeScript:
        id = 1
        user_id = 1
        name = "hi"
        language = "python"
        source_path = src
        entrypoint = "main.py"
        scripts_dir = work
        requirements: list[str] = []

    class FakeEnvService:
        def decrypt_lines(self, *args, **kwargs):
            return {}

    from kindling.services.log_broker import LogBroker
    broker = LogBroker()
    sem = asyncio.Semaphore(4)

    result = await run_script(
        run_id=42,
        script=FakeScript(),  # type: ignore[arg-type]
        env_service=FakeEnvService(),  # type: ignore[arg-type]
        log_broker=broker,
        concurrency=sem,
        storage_dir=tmp_path,
        param_env={
            "KINDLING_PARAM_region": "us-east-1",
            "KINDLING_PARAM_shard": "3",
        },
    )
    assert result.exit_code == 0
    import json as _json
    captured = _json.loads(_DUMP_PATH.read_text())
    assert captured["KINDLING_PARAM_region"] == "us-east-1"
    assert captured["KINDLING_PARAM_shard"] == "3"
    _DUMP_PATH.unlink()


@pytest.mark.asyncio
async def test_run_script_param_env_does_not_overwrite_user_env(tmp_path):
    """If both the user's encrypted .env and the trigger's param_env set
    the same KINDLING_PARAM_<KEY>, the user's value wins — a webhook MUST
    NOT be able to overwrite a script owner's secret."""
    work = tmp_path / "work"
    work.mkdir()
    src = work / "main.py"
    src.write_text(
        "import os\n"
        f"with open('{_PRECEDENCE_PATH}', 'w') as f:\n"
        "    f.write(os.environ.get('KINDLING_PARAM_token', 'MISSING'))\n",
        encoding="utf-8",
    )
    logs = tmp_path / "logs"
    logs.mkdir()

    class FakeScript:
        id = 1
        user_id = 1
        name = "hi"
        language = "python"
        source_path = src
        entrypoint = "main.py"
        scripts_dir = work
        requirements: list[str] = []

    class FakeEnvService:
        # User's .env says token=user-secret
        def decrypt_lines(self, *args, **kwargs):
            return {"KINDLING_PARAM_token": "user-secret"}

    from kindling.services.log_broker import LogBroker
    broker = LogBroker()
    sem = asyncio.Semaphore(4)

    # Trigger's param_env tries to override with attacker-secret
    await run_script(
        run_id=42,
        script=FakeScript(),  # type: ignore[arg-type]
        env_service=FakeEnvService(),  # type: ignore[arg-type]
        log_broker=broker,
        concurrency=sem,
        storage_dir=tmp_path,
        env_ciphertext="placeholder",
        env_nonce="placeholder",
        param_env={"KINDLING_PARAM_token": "attacker-secret"},
    )
    assert _PRECEDENCE_PATH.read_text() == "user-secret"
