"""Tests for the multi-file script CRUD endpoints under /scripts/{id}/files.

Task 3 of feat/script-editor.
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


def _build_app(tmp_path):
    """Helper: build a fresh app rooted at a tmp storage directory."""
    db = tmp_path / "t.db"
    storage = tmp_path / "s"
    storage.mkdir(parents=True)
    settings = Settings(
        db_path=str(db),
        storage_dir=str(storage),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    return create_app(settings)


@pytest.fixture
async def app_ctx(tmp_path):
    """One admin user; one python script (id=1) with main.py already on disk."""
    app = _build_app(tmp_path)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="admin",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=1, user_id=1, name="hello", language="python",
            source_path="scripts/1/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    src_dir = tmp_path / "s" / "scripts" / "1"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "main.py").write_text("x", encoding="utf-8")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_file_list_includes_entrypoint(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.get("/api/kindling/scripts/1/files")
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    assert any(e["path"] == "main.py" for e in entries)


@pytest.mark.asyncio
async def test_file_put_creates_and_updates(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.put(
        "/api/kindling/scripts/1/files/main.py",
        json={"content": "print('hi')"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "main.py"
    r2 = await ac.get("/api/kindling/scripts/1/files/main.py")
    assert r2.status_code == 200, r2.text
    assert r2.json()["content"] == "print('hi')"


@pytest.mark.asyncio
async def test_file_get_missing_returns_404(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.get("/api/kindling/scripts/1/files/does_not_exist.py")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_file_delete_refuses_entrypoint(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.delete("/api/kindling/scripts/1/files/main.py")
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_file_delete_other_succeeds(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    # Put a second file we can safely delete.
    await ac.put(
        "/api/kindling/scripts/1/files/util.py",
        json={"content": "y"},
    )
    r = await ac.delete("/api/kindling/scripts/1/files/util.py")
    assert r.status_code == 204, r.text


@pytest.mark.asyncio
async def test_file_path_traversal_rejected(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.put(
        "/api/kindling/scripts/1/files/..%2Fetc%2Fpasswd",
        json={"content": "x"},
    )
    assert r.status_code in (400, 404)


@pytest.mark.asyncio
async def test_file_post_creates_new_file(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts/1/files",
        json={"path": "lib/helper.py", "content": "# helper"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["path"] == "lib/helper.py"


@pytest.mark.asyncio
async def test_file_post_caps_at_50_files(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    # Start by writing the entrypoint + 49 sibling files via PUT.
    # main.py already exists from the fixture (1 file).
    # Write 49 more (named to avoid collisions and pass path validation).
    for i in range(49):
        r = await ac.put(
            f"/api/kindling/scripts/1/files/f_{i:02d}.py",
            json={"content": "x"},
        )
        assert r.status_code == 200, (i, r.text)
    # Now there are 50 files. The next POST must be rejected.
    r = await ac.post(
        "/api/kindling/scripts/1/files",
        json={"path": "overflow.py", "content": "x"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_file_viewer_cannot_put(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="viewer", app=app)
    r = await ac.put(
        "/api/kindling/scripts/1/files/main.py",
        json={"content": "y"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_file_unowned_returns_403(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    # User 2 doesn't own script 1. Use editor role to bypass the viewer 403
    # so we can see the actual ownership check.
    monkeypatch_auth(user_id=2, role="editor", app=app)
    r = await ac.get("/api/kindling/scripts/1/files")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_source_returns_entrypoint_content(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    # The fixture writes "x" to main.py; PUT a known payload first.
    await ac.put(
        "/api/kindling/scripts/1/files/main.py",
        json={"content": "print('hello')\n"},
    )
    r = await ac.get("/api/kindling/scripts/1/source")
    assert r.status_code == 200, r.text
    assert r.json() == {"content": "print('hello')\n"}