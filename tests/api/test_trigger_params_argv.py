"""Tests for trigger params_argv path: same on-wire shape as the Manual
Run button so a user can copy-paste working args into a schedule.

Both /scripts/<id>/triggers (Create) and /scripts/<id>/triggers/<id>
(Update) accept params_argv mutually exclusive with params_json.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import schedules, scripts, users


@pytest.fixture
async def trig_argv_ctx(tmp_path):
    db = tmp_path / "t.db"
    storage = tmp_path / "s"
    (storage / "logs").mkdir(parents=True)
    settings = Settings(
        db_path=str(db),
        storage_dir=str(storage),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=10, user_id=1, name="hello", language="python",
            source_path="x.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_create_cron_trigger_with_params_argv_persists_list(trig_argv_ctx, monkeypatch_auth):
    ac, app = trig_argv_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={
            "kind": "cron",
            "expression": "* * * * *",
            "enabled": True,
            "params_argv": ["users", "-p", "9000"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["params_json"] == ["users", "-p", "9000"]

    # Confirm the column stores the JSON-encoded list, not a stringified blob.
    async with app.state.session_factory() as s:
        row = (await s.execute(
            select(schedules.c.params_json).where(schedules.c.id == body["id"])
        )).one()
    import json as _json
    assert _json.loads(row[0]) == ["users", "-p", "9000"]


@pytest.mark.asyncio
async def test_create_cron_trigger_with_both_params_422(trig_argv_ctx, monkeypatch_auth):
    ac, app = trig_argv_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={
            "kind": "cron",
            "expression": "* * * * *",
            "params_json": {"region": "us-east-1"},
            "params_argv": ["--region", "us-east-1"],
        },
    )
    assert r.status_code == 422
    assert "params_json or params_argv" in r.text


@pytest.mark.asyncio
async def test_create_cron_trigger_params_argv_non_string_422(trig_argv_ctx, monkeypatch_auth):
    ac, app = trig_argv_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={
            "kind": "cron",
            "expression": "* * * * *",
            "params_argv": ["ok", 3],
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_trigger_swap_dict_for_argv(trig_argv_ctx, monkeypatch_auth):
    """A legacy trigger stored with params_json can be re-saved as
    params_argv; the column shape flips and the response mirrors it."""
    ac, app = trig_argv_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    created = (await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={
            "kind": "cron",
            "expression": "* * * * *",
            "params_json": {"region": "us-east-1"},
        },
    )).json()

    updated = (await ac.put(
        f"/api/kindling/scripts/10/triggers/{created['id']}",
        json={
            "kind": "cron",
            "expression": "* * * * *",
            "params_argv": ["--region", "eu-west-2"],
        },
    )).json()
    assert updated["params_json"] == ["--region", "eu-west-2"]


@pytest.mark.asyncio
async def test_list_trigger_round_trips_dict_params(trig_argv_ctx, monkeypatch_auth):
    """Legacy dict params still load correctly via GET — the column may
    hold a JSON object, in which case params_json is the dict."""
    ac, app = trig_argv_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={
            "kind": "cron",
            "expression": "* * * * *",
            "params_json": {"region": "us-east-1", "shard": 3},
        },
    )
    r = await ac.get("/api/kindling/scripts/10/triggers")
    items = r.json()
    assert items[0]["params_json"] == {"region": "us-east-1", "shard": 3}


@pytest.mark.asyncio
async def test_create_webhook_trigger_with_params_argv(trig_argv_ctx, monkeypatch_auth):
    """Webhooks historically only accepted params_json; they now also
    accept params_argv."""
    ac, app = trig_argv_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={
            "kind": "webhook",
            "enabled": True,
            "params_argv": ["--region", "us-east-1", "--verbose"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["params_json"] == ["--region", "us-east-1", "--verbose"]
    # Token returned exactly once.
    assert "token" in body
