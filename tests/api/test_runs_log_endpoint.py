"""Tests for GET /api/kindling/runs/{id}/log returning JSON {content}.

Task 3 of feat/run-logs runs-page refresh.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import runs, scripts, users


@pytest.fixture
async def app_ctx(tmp_path):
    """One user, one script, one run."""
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
            id=10, user_id=1, name="hello", language="python", source_path="x.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(runs).values(
            id=42, script_id=10, schedule_id=None,
            started_at="2030-01-01T00:00:00+00:00", status="success",
            exit_code=0,
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app, storage


@pytest.mark.asyncio
async def test_log_returns_json_with_content(app_ctx, monkeypatch_auth):
    ac, app, storage = app_ctx
    log_file = storage / "logs" / "42.log"
    log_file.write_text("hello\nworld\n", encoding="utf-8")
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs/42/log")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body == {"content": "hello\nworld\n"}


@pytest.mark.asyncio
async def test_log_missing_returns_404(app_ctx, monkeypatch_auth):
    ac, app, storage = app_ctx
    # No log file written.
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs/42/log")
    assert r.status_code == 404