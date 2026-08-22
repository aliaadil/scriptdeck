"""POST /scripts/{id}/run with params_argv (raw CLI argv) — separate from
the params_json path so the frontend can capture shell-style input
verbatim instead of forcing the user to type JSON.
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
async def test_manual_run_with_params_argv_persists_list(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/run",
        json={"params_argv": ["users", "-p", "9000"]},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    # The argv list is what's stored; downstream callers see it as a list.
    assert body["params_json"] == ["users", "-p", "9000"]
    assert body["trigger_kind"] == "manual"

    listed = await ac.get("/api/kindling/runs?script_id=1")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert isinstance(rows[0]["params_json"], list)
    assert rows[0]["params_json"] == ["users", "-p", "9000"]


@pytest.mark.asyncio
async def test_manual_run_with_both_params_422(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/run",
        json={
            "params_json": {"region": "us-east-1"},
            "params_argv": ["users", "-p", "9000"],
        },
    )
    assert r.status_code == 422, r.text
    # Mutually exclusive — error must mention the conflict.
    assert "params_json" in r.text and "params_argv" in r.text


@pytest.mark.asyncio
async def test_manual_run_params_argv_non_string_422(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/run",
        json={"params_argv": ["users", 9000]},  # int in list
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_manual_run_params_argv_empty_list_accepted(app_ctx, monkeypatch_auth):
    """Empty argv == no-args run; same as a bodyless POST."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/run",
        json={"params_argv": []},
    )
    assert r.status_code == 201, r.text
    assert r.json()["params_json"] in (None, [])
