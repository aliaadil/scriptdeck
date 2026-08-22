"""Tests for POST /api/kindling/scripts/{id}/install.

The endpoint shells out to uv pip / npm into the script's per-user
work_dir. We patch install_packages so the test doesn't require uv/npm
on the runner (CI has neither) — the contract we care about is
ownership, validation, and the script_deps update.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import script_deps, scripts, users


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
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(users).values(
            id=2, email="bob@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=10, user_id=1, name="alice-scr", language="python",
            source_path="scripts/10/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=20, user_id=2, name="bob-scr", language="python",
            source_path="scripts/20/main.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_install_persists_deps_and_returns_output(
    app_ctx, monkeypatch_auth,
):
    """Happy path: editor installs 'boto3' on their own script, the
    endpoint returns the captured pip output and writes a script_deps
    row tagged source='manual'."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    fake = AsyncMock(return_value="Resolved 1 package in 0.5s\nboto3-1.34")
    with patch(
        "kindling.api.install.install_service.install_packages", fake,
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["boto3"]},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["installed"] == ["boto3"]
    assert "boto3-1.34" in body["output"]
    fake.assert_awaited_once()
    # Verify the kwargs hit the right (user, script) pair.
    kwargs = fake.await_args.kwargs
    assert kwargs["user_id"] == 1
    assert kwargs["script_id"] == 10
    assert kwargs["packages"] == ["boto3"]
    assert kwargs["language"] == "python"

    async with app.state.session_factory() as s:
        row = (
            await s.execute(
                select(script_deps).where(script_deps.c.script_id == 10)
            )
        ).mappings().one()
    assert json.loads(row["deps_json"]) == ["boto3"]
    assert row["source"] == "manual"


@pytest.mark.asyncio
async def test_install_merges_with_existing_deps(app_ctx, monkeypatch_auth):
    """A second install should append to the existing list, not blow
    it away — installing boto3 must not drop the requests someone
    already manually added."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    # Seed an existing manual deps row.
    async with app.state.session_factory() as s:
        await s.execute(insert(script_deps).values(
            script_id=10, deps_json=json.dumps(["requests"]),
            source="manual", updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    with patch(
        "kindling.api.install.install_service.install_packages",
        AsyncMock(return_value="ok"),
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["boto3"]},
        )
    assert r.status_code == 200, r.text
    async with app.state.session_factory() as s:
        row = (
            await s.execute(
                select(script_deps).where(script_deps.c.script_id == 10)
            )
        ).mappings().one()
    assert json.loads(row["deps_json"]) == ["requests", "boto3"]


@pytest.mark.asyncio
async def test_install_rejects_non_owner(app_ctx, monkeypatch_auth):
    """Bob (user 2) cannot install into Alice's script (id 10)."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=2, role="editor", app=app)
    fake = AsyncMock(return_value="ok")
    with patch(
        "kindling.api.install.install_service.install_packages", fake,
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["boto3"]},
        )
    assert r.status_code == 403, r.text
    fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_install_rejects_viewer(app_ctx, monkeypatch_auth):
    """Viewers can read but not write — install must be 403 for them."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="viewer", app=app)
    with patch(
        "kindling.api.install.install_service.install_packages",
        AsyncMock(return_value="ok"),
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["boto3"]},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_install_rejects_invalid_package_name(
    app_ctx, monkeypatch_auth,
):
    """Shell-metacharacter-y names are rejected before we ever shell
    out. Defense-in-depth: install_packages itself has the same regex,
    but rejecting at the API boundary means the UI gets a clean 400."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    fake = AsyncMock(return_value="ok")
    with patch(
        "kindling.api.install.install_service.install_packages", fake,
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["boto3; rm -rf /"]},
        )
    assert r.status_code == 422, r.text
    fake.assert_not_awaited()


@pytest.mark.asyncio
async def test_install_empty_packages_rejected(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.post(
        "/api/kindling/scripts/10/install",
        json={"packages": []},
    )
    # Pydantic min_length=1 → 422 from the model validator.
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_install_422_when_pip_fails(app_ctx, monkeypatch_auth):
    """If pip exits non-zero, the endpoint returns 422 with the captured
    pip output so the UI can show "why didn't it install?" without a
    second round trip."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    fake = AsyncMock(side_effect=RuntimeError("ERROR: No matching distribution"))
    with patch(
        "kindling.api.install.install_service.install_packages", fake,
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["nonexistent_pkg_xyz"]},
        )
    assert r.status_code == 422, r.text
    assert "No matching distribution" in r.json()["detail"]


@pytest.mark.asyncio
async def test_install_bash_rejected(app_ctx, monkeypatch_auth):
    """There's no module concept for bash; reject explicitly so the
    user gets a useful 400 instead of 'language=bash not supported'."""
    from sqlalchemy import update

    ac, app = app_ctx
    # Promote script 10 to bash for this test.
    async with app.state.session_factory() as s:
        await s.execute(
            update(scripts).where(scripts.c.id == 10).values(language="bash")
        )
        await s.commit()
    monkeypatch_auth(user_id=1, role="editor", app=app)
    with patch(
        "kindling.api.install.install_service.install_packages",
        AsyncMock(return_value="ok"),
    ):
        r = await ac.post(
            "/api/kindling/scripts/10/install",
            json={"packages": ["foo"]},
        )
    assert r.status_code == 400, r.text
    assert "bash" in r.json()["detail"]
