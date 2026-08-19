"""Per-schedule params (Issue #17): two schedules on one script pass
different params and the runner sees them."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from kindling.app import create_app
from kindling.auth.jwt import encode_jwt
from kindling.auth.passwords import hash_password
from kindling.config import Settings
from kindling.db.models import runs, schedules, scripts, users
from kindling.services.schedule_service import advance_next_run


@pytest.fixture
async def app_ctx(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
        allow_insecure_defaults_for_tests=True,
        scheduler_interval=3600,
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(
            insert(users).values(
                email="a@b.com",
                password_hash=hash_password("hunter22"),
                role="admin",
            )
        )
        await s.execute(
            insert(scripts).values(
                name="t",
                language="python",
                source_path="scripts/1/main.py",
                user_id=1,
            )
        )
        await s.commit()
    # Tests don't trigger the lifespan; populate the bits the runner
    # background tasks expect (semaphore + background_tasks set) so the
    # executor doesn't AttributeError when invoked directly.
    import asyncio

    app.state.runner_sem = asyncio.Semaphore(4)
    app.state.background_tasks = set()
    app.state.active_procs = {}
    token, _, _ = encode_jwt(1, "admin", settings.jwt_secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        yield ac, app, token, settings


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_two_schedules_one_script_different_params(app_ctx):
    """A script can carry two schedules with different params."""
    ac, _, token, _ = app_ctx
    body_a = {
        "script_id": 1,
        "kind": "cron",
        "expression": "0 9 * * *",
        "enabled": True,
        "timezone": "UTC",
        "blackout_dates": None,
        "include_days": None,
        "overlap_policy": "skip",
        "queue_max": 10,
        "retry_max": 0,
        "retry_backoff": 0,
        "params": {"flag": "morning"},
    }
    body_b = {**body_a, "expression": "0 17 * * *", "params": {"flag": "evening"}}
    a = (await ac.post("/api/kindling/schedules", json=body_a, headers=_h(token))).json()
    b = (await ac.post("/api/kindling/schedules", json=body_b, headers=_h(token))).json()
    assert a["id"] != b["id"]
    assert a["script_id"] == 1
    assert b["script_id"] == 1
    assert a["params"] == {"flag": "morning"}
    assert b["params"] == {"flag": "evening"}


@pytest.mark.asyncio
async def test_schedule_create_without_params_defaults_to_none(app_ctx):
    ac, _, token, _ = app_ctx
    body = {
        "script_id": 1,
        "kind": "cron",
        "expression": "0 9 * * *",
        "enabled": True,
        "timezone": "UTC",
        "blackout_dates": None,
        "include_days": None,
        "overlap_policy": "skip",
        "queue_max": 10,
        "retry_max": 0,
        "retry_backoff": 0,
    }
    r = await ac.post("/api/kindling/schedules", json=body, headers=_h(token))
    assert r.status_code == 201, r.text
    # Default '{}' collapses to None on the wire.
    assert r.json()["params"] is None


@pytest.mark.asyncio
async def test_schedule_update_persists_params(app_ctx):
    ac, _, token, _ = app_ctx
    create = await ac.post(
        "/api/kindling/schedules",
        json={
            "script_id": 1,
            "kind": "cron",
            "expression": "0 9 * * *",
            "enabled": True,
            "timezone": "UTC",
            "blackout_dates": None,
            "include_days": None,
            "overlap_policy": "skip",
            "queue_max": 10,
            "retry_max": 0,
            "retry_backoff": 0,
        },
        headers=_h(token),
    )
    assert create.status_code == 201
    sid = create.json()["id"]
    upd = await ac.put(
        f"/api/kindling/schedules/{sid}",
        json={
            "script_id": 1,
            "kind": "cron",
            "expression": "0 9 * * *",
            "enabled": True,
            "timezone": "UTC",
            "blackout_dates": None,
            "include_days": None,
            "overlap_policy": "skip",
            "queue_max": 10,
            "retry_max": 0,
            "retry_backoff": 0,
            "params": {"k": "v"},
        },
        headers=_h(token),
    )
    assert upd.status_code == 200
    assert upd.json()["params"] == {"k": "v"}


@pytest.mark.asyncio
async def test_legacy_schedule_round_trip(app_ctx):
    """A schedule with params_json='{}' round-trips with params=None."""
    ac, app, token, _ = app_ctx
    body = {
        "script_id": 1,
        "kind": "cron",
        "expression": "0 9 * * *",
        "enabled": True,
        "timezone": "UTC",
        "blackout_dates": None,
        "include_days": None,
        "overlap_policy": "skip",
        "queue_max": 10,
        "retry_max": 0,
        "retry_backoff": 0,
    }
    create = await ac.post("/api/kindling/schedules", json=body, headers=_h(token))
    sid = create.json()["id"]
    listed = await ac.get(
        "/api/kindling/schedules", headers=_h(token)
    )
    found = [r for r in listed.json() if r["id"] == sid][0]
    assert found["params"] is None


@pytest.mark.asyncio
async def test_executor_merges_trigger_params_into_env(app_ctx):
    """Direct unit test: ``executor.run_script`` exports trigger params.

    Spawns a Python script that prints env, confirms both
    ``SCRIPTDECK_PARAM_<KEY>`` and ``SCRIPTDECK_PARAMS_JSON`` are set.
    """
    from kindling.runner.executor import Script, run_script

    _, app, _, settings = app_ctx
    storage = Path(settings.storage_dir)
    scripts_dir = storage / "scripts" / "1"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    src = scripts_dir / "main.py"
    src.write_text(
        "import os\n"
        "open('/tmp/trigger_env.txt', 'w').write(\n"
        "    os.environ.get('SCRIPTDECK_PARAM_REGION', '') + '|' + "
        "os.environ.get('SCRIPTDECK_PARAMS_JSON', '')\n"
        ")\n",
        encoding="utf-8",
    )
    if os.path.exists("/tmp/trigger_env.txt"):
        os.unlink("/tmp/trigger_env.txt")

    script = Script(
        id=1,
        user_id=1,
        name="t",
        language="python",
        source_path=src,
        entrypoint="main.py",
        scripts_dir=scripts_dir,
        requirements=[],
    )
    # Need a run_id so the executor writes its log under logs/.
    async with app.state.session_factory() as s:
        await s.execute(
            insert(runs).values(script_id=1, status="running", schedule_id=None)
        )
        await s.commit()
        run_id = (
            await s.execute(select(runs.c.id).order_by(runs.c.id.desc()))
        ).first()[0]

    result = await run_script(
        run_id=run_id,
        script=script,
        env_service=app.state.env_service,
        log_broker=app.state.log_broker,
        concurrency=app.state.runner_sem,
        storage_dir=storage,
        trigger_params={"region": "eu", "tier": "gold"},
    )
    assert result.exit_code == 0
    assert os.path.exists("/tmp/trigger_env.txt")
    contents = open("/tmp/trigger_env.txt").read()
    region, blob = contents.split("|", 1)
    assert region == "eu"
    import json as _json

    assert _json.loads(blob) == {"region": "eu", "tier": "gold"}
    os.unlink("/tmp/trigger_env.txt")
