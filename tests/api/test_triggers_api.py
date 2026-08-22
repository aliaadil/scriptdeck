"""Tests for the per-script triggers management API.

Endpoints (under /api/kindling/scripts/<id>/triggers):
- GET    /                       list triggers grouped by kind
- POST   /                       create trigger (returns the token ONCE for webhook)
- PUT    /<trigger_id>           update trigger (optionally rotate token)
- DELETE /<trigger_id>           delete trigger
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import schedules, scripts, users


@pytest.fixture
async def trig_ctx(tmp_path):
    """One user + one script. Migrations + happy-path FK chain."""
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
        yield ac, app, storage


@pytest.mark.asyncio
async def test_list_triggers_empty(trig_ctx, monkeypatch_auth):
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/scripts/10/triggers")
    assert r.status_code == 200, r.text
    assert r.json() == []


@pytest.mark.asyncio
async def test_create_webhook_trigger_returns_token_once(trig_ctx, monkeypatch_auth):
    """The token must be returned in the POST response (we can't show it later
    since we only store the hash)."""
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={"kind": "webhook", "params_json": {"region": "us-east-1"}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "webhook"
    assert body["script_id"] == 10
    assert body["params_json"] == {"region": "us-east-1"}
    # Token returned on creation
    assert "token" in body
    assert isinstance(body["token"], str)
    assert len(body["token"]) >= 32
    # Subsequent GET must NOT return the token
    r2 = await ac.get("/api/kindling/scripts/10/triggers")
    assert r2.status_code == 200
    for t in r2.json():
        assert "token" not in t


@pytest.mark.asyncio
async def test_create_webhook_stores_only_hash(trig_ctx, monkeypatch_auth):
    """The DB must hold the SHA-256 of the token, not the token itself."""
    import hashlib
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={"kind": "webhook"},
    )
    body = r.json()
    expected_hash = hashlib.sha256(body["token"].encode()).hexdigest()
    # The DB row's webhook_token_hash must equal the SHA-256 of the returned token.
    async with app.state.session_factory() as s:
        from sqlalchemy import select
        row = (await s.execute(
            select(schedules.c.webhook_token_hash).where(schedules.c.id == body["id"])
        )).one()
    assert row[0] == expected_hash


@pytest.mark.asyncio
async def test_create_cron_trigger_via_triggers_endpoint(trig_ctx, monkeypatch_auth):
    """Cron/interval triggers can also be created via the triggers endpoint
    (the /schedules endpoint is preserved for backward compatibility)."""
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={"kind": "cron", "expression": "* * * * *"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["kind"] == "cron"
    assert body["expression"] == "* * * * *"
    assert body["next_run_at"]  # computed on create
    # Webhook token must NOT be present for cron
    assert "token" not in body


@pytest.mark.asyncio
async def test_delete_trigger(trig_ctx, monkeypatch_auth):
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post("/api/kindling/scripts/10/triggers", json={"kind": "webhook"})
    tid = r.json()["id"]
    r2 = await ac.delete(f"/api/kindling/scripts/10/triggers/{tid}")
    assert r2.status_code == 204
    # Subsequent GET is empty.
    r3 = await ac.get("/api/kindling/scripts/10/triggers")
    assert r3.json() == []


@pytest.mark.asyncio
async def test_rotate_webhook_token(trig_ctx, monkeypatch_auth):
    """PUT /triggers/<id> with rotate_token=True generates a fresh token
    and returns it ONCE (next GET hides it)."""
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post("/api/kindling/scripts/10/triggers", json={"kind": "webhook"})
    body = r.json()
    old_token = body["token"]
    r2 = await ac.put(
        f"/api/kindling/scripts/10/triggers/{body['id']}",
        json={"kind": "webhook", "rotate_token": True},
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert "token" in body2
    assert body2["token"] != old_token


@pytest.mark.asyncio
async def test_create_trigger_unowned_returns_403(trig_ctx, monkeypatch_auth):
    """A non-owner cannot create triggers on someone else's script."""
    ac, app, _ = trig_ctx
    monkeypatch_auth(user_id=2, role="editor", app=app)  # not user 1
    r = await ac.post(
        "/api/kindling/scripts/10/triggers",
        json={"kind": "webhook"},
    )
    assert r.status_code == 403
