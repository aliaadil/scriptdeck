"""Tests for GET /api/kindling/scripts/{id}/source returning JSON {content}.

Task 4 of feat/run-logs runs-page refresh.
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


def _build_app(tmp_path, *, write_source: bool):
    """Helper: build app + (ac, app) tuple; optionally seed the source file."""
    db = tmp_path / "t.db"
    storage = tmp_path / "s"
    storage.mkdir(parents=True)
    settings = Settings(
        db_path=str(db),
        storage_dir=str(storage),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    return app, storage


@pytest.fixture
async def app_ctx(tmp_path):
    """One user, one script, source file on disk."""
    app, storage = _build_app(tmp_path, write_source=True)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=1, user_id=1, name="hello", language="python",
            source_path="scripts/1/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    source_file = storage / "scripts" / "1" / "main.py"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    source_file.write_text("print('hi')\n", encoding="utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.fixture
async def app_ctx_missing(tmp_path):
    """One user, one script, NO source file on disk."""
    app, _ = _build_app(tmp_path, write_source=False)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=1, user_id=1, name="hello", language="python",
            source_path="scripts/1/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_source_returns_json_content(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/scripts/1/source")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"content": "print('hi')\n"}


@pytest.mark.asyncio
async def test_source_missing_file_returns_404(app_ctx_missing, monkeypatch_auth):
    ac, app = app_ctx_missing
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/scripts/1/source")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_source_unowned_returns_403(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    # User 2 is not the owner of script 1.
    monkeypatch_auth(user_id=2, role="editor", app=app)
    r = await ac.get("/api/kindling/scripts/1/source")
    assert r.status_code == 403
