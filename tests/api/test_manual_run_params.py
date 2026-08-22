"""POST /scripts/{id}/run with params_json accepts the body and persists it.

We don't actually run the subprocess here — that's covered by the
existing /runs endpoint tests. This test exercises only the request
shape and the row write: send a valid params_json, get a 201 with the
params echoed back, and confirm the response carries the parsed object.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import scripts, users


@pytest.fixture
async def app_ctx(tmp_path):
    """One admin user + one python script."""
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
            id=1, email="alice@x.com", password_hash="x", role="admin",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=1, user_id=1, name="hello", language="python",
            source_path="x.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_manual_run_with_params_returns_parsed_body(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/run",
        json={"params_json": {"region": "us-east-1", "shard": 3}},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["params_json"] == {"region": "us-east-1", "shard": 3}
    assert body["trigger_kind"] == "manual"

    # Round-trip through the list endpoint: the column is stored as a
    # JSON string, so the validator on RunOut.params_json must decode it
    # back to a dict. Without that, every list/detail call after a manual
    # run with params would 500 with a Pydantic ValidationError.
    listed = await ac.get("/api/kindling/runs?script_id=1")
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) == 1
    assert isinstance(rows[0]["params_json"], dict)
    assert rows[0]["params_json"] == {"region": "us-east-1", "shard": 3}


@pytest.mark.asyncio
async def test_manual_run_invalid_params_422(app_ctx, monkeypatch_auth):
    # Non-primitive value — list — should be rejected by the Pydantic
    # validator before any DB row is created.
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/run",
        json={"params_json": {"region": ["us-east-1"]}},
    )
    assert r.status_code == 422


@pytest.fixture(autouse=True)
def _stub_finalize(monkeypatch):
    """No-op the background ``_execute_and_finalize`` so the request-handler
    task the test fires doesn't leak across pytest teardown and stall on an
    aiosqlite future the test never resolves. These tests only assert on
    the HTTP response, not the script execution.
    """
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr("kindling.api.runs._execute_and_finalize", _noop)


@pytest.mark.asyncio
async def test_manual_run_without_params_unchanged(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post("/api/kindling/scripts/1/run")
    assert r.status_code == 201
    assert r.json()["params_json"] is None
