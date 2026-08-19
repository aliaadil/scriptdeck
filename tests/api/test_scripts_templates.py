"""Tests for script template seeding (Task 4 of feat/script-editor).

POST /scripts should accept a ``template`` value (``python``, ``node``, ``bash``)
that seeds ``main.<ext>`` and an empty ``.env`` in the script directory.
Without ``template``, callers continue to provide ``source`` and a default
entrypoint is used (still backwards-compatible). Each template's entrypoint
filename is recorded in the DB ``entrypoint`` column.

PUT /scripts/{id} should accept ``entrypoint`` so the entrypoint can change.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import scripts, users


def _build_app(tmp_path):
    """Build a fresh app with tmp storage."""
    db = tmp_path / "t.db"
    storage = tmp_path / "s"
    storage.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        db_path=str(db),
        storage_dir=str(storage),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    return create_app(settings)


@pytest.fixture
async def app_ctx(tmp_path):
    """One admin user; empty filesystem."""
    app = _build_app(tmp_path)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="admin",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_python_template_seeds_main_and_env(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts",
        json={"name": "t-py", "language": "python", "template": "python"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["entrypoint"] == "main.py"
    sid = data["id"]
    files_r = await ac.get(f"/api/kindling/scripts/{sid}/files")
    assert files_r.status_code == 200, files_r.text
    paths = {f["path"] for f in files_r.json()["entries"]}
    assert {"main.py", ".env"}.issubset(paths)
    # main.py should contain the placeholder source, not be empty.
    main_r = await ac.get(f"/api/kindling/scripts/{sid}/files/main.py")
    assert main_r.status_code == 200
    content = main_r.json()["content"]
    assert "Hello from Kindling" in content
    # .env should exist (empty is fine).
    env_r = await ac.get(f"/api/kindling/scripts/{sid}/files/.env")
    assert env_r.status_code == 200


@pytest.mark.asyncio
async def test_node_template_uses_main_js(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts",
        json={"name": "t-node", "language": "node", "template": "node"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["entrypoint"] == "main.js"
    sid = data["id"]
    files_r = await ac.get(f"/api/kindling/scripts/{sid}/files")
    assert files_r.status_code == 200
    paths = {f["path"] for f in files_r.json()["entries"]}
    assert {"main.js", ".env"}.issubset(paths)


@pytest.mark.asyncio
async def test_bash_template_uses_main_sh(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts",
        json={"name": "t-bash", "language": "bash", "template": "bash"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["entrypoint"] == "main.sh"
    sid = data["id"]
    files_r = await ac.get(f"/api/kindling/scripts/{sid}/files")
    assert files_r.status_code == 200
    paths = {f["path"] for f in files_r.json()["entries"]}
    assert {"main.sh", ".env"}.issubset(paths)


@pytest.mark.asyncio
async def test_create_without_template_falls_back_to_default_entrypoint(
    app_ctx, monkeypatch_auth
):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts",
        json={
            "name": "t-fallback",
            "language": "python",
            "source": "print('plain')\n",
        },
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["entrypoint"] == "main.py"
    sid = data["id"]
    main_r = await ac.get(f"/api/kindling/scripts/{sid}/files/main.py")
    assert main_r.status_code == 200
    assert main_r.json()["content"] == "print('plain')\n"


@pytest.mark.asyncio
async def test_invalid_template_rejected(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts",
        json={"name": "t-bad", "language": "python", "template": "ruby"},
    )
    # Pydantic validation rejects the unknown template (422).
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_update_entrypoint_only(app_ctx, monkeypatch_auth):
    """PUT /scripts/{id} without ``source`` should accept entrypoint-only edit."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="admin", app=app)
    r = await ac.post(
        "/api/kindling/scripts",
        json={"name": "t-upd", "language": "python", "template": "python"},
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    r2 = await ac.put(
        f"/api/kindling/scripts/{sid}",
        json={"entrypoint": "alt.py"},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["entrypoint"] == "alt.py"


def test_seed_template_module_helpers(tmp_path):
    """Direct unit test of the templates module."""
    from kindling.script_templates import (
        BASH_MAIN,
        ENTRYPOINTS,
        NODE_MAIN,
        PYTHON_MAIN,
        SOURCES,
        seed_template,
    )

    assert ENTRYPOINTS == {"python": "main.py", "node": "main.js", "bash": "main.sh"}
    assert SOURCES["python"] is PYTHON_MAIN
    assert SOURCES["node"] is NODE_MAIN
    assert SOURCES["bash"] is BASH_MAIN

    script_dir = tmp_path / "scripts" / "1"
    ep = seed_template("python", script_dir)
    assert ep == "main.py"
    assert (script_dir / "main.py").read_text(encoding="utf-8") == PYTHON_MAIN
    assert (script_dir / ".env").read_text(encoding="utf-8") == ""


def test_seed_template_raises_for_unsupported(tmp_path):
    from kindling.script_templates import seed_template

    script_dir = tmp_path / "scripts" / "1"
    with pytest.raises(ValueError):
        seed_template("ruby", script_dir)


def test_bash_template_runs_in_bash(tmp_path):
    """The seeded bash starter must execute cleanly under bash (no syntax errors).

    Guards against bash syntax errors like ``${#VAR:-default}`` (length with default
    expansion is not a valid form in bash). Runs the template with and without
    ``API_KEY`` set.
    """
    import subprocess

    from kindling.script_templates import BASH_MAIN, seed_template

    script_dir = tmp_path / "scripts" / "bash-run"
    entrypoint = seed_template("bash", script_dir)
    assert entrypoint == "main.sh"
    main_sh = script_dir / "main.sh"
    assert main_sh.read_text(encoding="utf-8") == BASH_MAIN

    env_without = {"PATH": "/usr/bin:/bin"}
    env_with = {"PATH": "/usr/bin:/bin", "API_KEY": "abc"}

    r = subprocess.run(
        ["bash", str(main_sh)],
        capture_output=True,
        text=True,
        env=env_without,
        timeout=10,
    )
    assert r.returncode == 0, f"bash failed (no API_KEY): {r.stderr}"
    assert r.stdout.strip() == "Hello from Kindling (api_key length: 0)"

    r = subprocess.run(
        ["bash", str(main_sh)],
        capture_output=True,
        text=True,
        env=env_with,
        timeout=10,
    )
    assert r.returncode == 0, f"bash failed (with API_KEY): {r.stderr}"
    assert r.stdout.strip() == "Hello from Kindling (api_key length: 3)"
