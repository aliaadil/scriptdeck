"""Webhook API tests — authed CRUD + public fire endpoint."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.auth.jwt import encode_jwt
from kindling.auth.passwords import hash_password
from kindling.config import Settings
from kindling.db.models import runs, scripts, users


@pytest.fixture
async def app_ctx(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
        allow_insecure_defaults_for_tests=True,
        scheduler_interval=3600,  # don't let the scheduler tick fire in tests
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
                name="t", language="python", source_path="scripts/1/main.py",
                user_id=1,
            )
        )
        await s.commit()
    # Tests don't trigger the lifespan; populate the bits the runner
    # background tasks expect (semaphore + background_tasks set) so the
    # webhook fire path doesn't AttributeError.
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
async def test_create_webhook_returns_url_once(app_ctx):
    ac, _, token, _ = app_ctx
    r = await ac.post(
        "/api/kindling/webhooks",
        json={"script_id": 1, "description": "hi"},
        headers=_h(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["script_id"] == 1
    assert body["enabled"] is True
    assert body["fire_count"] == 0
    assert body["description"] == "hi"
    assert body["secret_token"]
    assert body["url"].endswith(f"/webhooks/{body['secret_token']}")
    assert len(body["secret_token"]) >= 40


@pytest.mark.asyncio
async def test_list_webhooks_hides_secret_token(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1},
            headers=_h(token),
        )
    ).json()
    listed = (
        await ac.get(
            "/api/kindling/webhooks?script_id=1", headers=_h(token)
        )
    ).json()
    assert len(listed) == 1
    assert "secret_token" not in listed[0]
    assert listed[0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_get_webhook_owner_scoped(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1},
            headers=_h(token),
        )
    ).json()
    r = await ac.get(
        f"/api/kindling/webhooks/{created['id']}", headers=_h(token)
    )
    assert r.status_code == 200
    assert r.json()["id"] == created["id"]


@pytest.mark.asyncio
async def test_patch_webhook_toggle_enabled(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1, "enabled": True},
            headers=_h(token),
        )
    ).json()
    r = await ac.patch(
        f"/api/kindling/webhooks/{created['id']}",
        json={"enabled": False},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


@pytest.mark.asyncio
async def test_patch_webhook_params(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1},
            headers=_h(token),
        )
    ).json()
    r = await ac.patch(
        f"/api/kindling/webhooks/{created['id']}",
        json={"params": {"region": "eu"}},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["params"] == {"region": "eu"}


@pytest.mark.asyncio
async def test_regenerate_webhook_invalidates_old_url(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1},
            headers=_h(token),
        )
    ).json()
    old_token = created["secret_token"]
    r = await ac.post(
        f"/api/kindling/webhooks/{created['id']}/regenerate",
        headers=_h(token),
    )
    assert r.status_code == 200
    new_token = r.json()["secret_token"]
    assert new_token != old_token
    # Old URL is dead.
    fire = await ac.post(f"/webhooks/{old_token}")
    assert fire.status_code == 404
    # New URL works.
    fire2 = await ac.post(f"/webhooks/{new_token}")
    assert fire2.status_code == 202


@pytest.mark.asyncio
async def test_delete_webhook(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1},
            headers=_h(token),
        )
    ).json()
    r = await ac.delete(
        f"/api/kindling/webhooks/{created['id']}", headers=_h(token)
    )
    assert r.status_code == 204
    # GET now 404s.
    r2 = await ac.get(
        f"/api/kindling/webhooks/{created['id']}", headers=_h(token)
    )
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_viewer_cannot_create_webhook(app_ctx):
    ac, app, _, settings = app_ctx
    from kindling.auth.passwords import hash_password
    from sqlalchemy import insert as _insert

    from kindling.db.models import users as _users

    # Create a viewer user + jwt
    async with app.state.session_factory() as s:
        await s.execute(
            _insert(_users).values(
                id=99,
                email="v@b.com",
                password_hash=hash_password("hunter22"),
                role="viewer",
            )
        )
        await s.commit()
    vtoken, _, _ = encode_jwt(99, "viewer", settings.jwt_secret)
    r = await ac.post(
        "/api/kindling/webhooks",
        json={"script_id": 1},
        headers=_h(vtoken),
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_nested_per_script_webhooks(app_ctx):
    """``GET /scripts/<id>/webhooks`` mirrors the per-script schedule pattern."""
    ac, _, token, _ = app_ctx
    # Create two webhooks on script 1.
    await ac.post(
        "/api/kindling/scripts/1/webhooks",
        json={"description": "first"},
        headers=_h(token),
    )
    await ac.post(
        "/api/kindling/scripts/1/webhooks",
        json={"description": "second"},
        headers=_h(token),
    )
    r = await ac.get(
        "/api/kindling/scripts/1/webhooks", headers=_h(token)
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    descriptions = sorted([w["description"] for w in body])
    assert descriptions == ["first", "second"]
    # secret_token is hidden.
    for w in body:
        assert "secret_token" not in w


@pytest.mark.asyncio
async def test_public_fire_creates_run(app_ctx):
    """POST /webhooks/<token> with no auth headers creates a run."""
    ac, app, token, settings = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1},
            headers=_h(token),
        )
    ).json()
    webhook_token = created["secret_token"]
    r = await ac.post(f"/webhooks/{webhook_token}")
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "running"
    assert body["run_id"] > 0
    # Row exists in the runs table.
    async with app.state.session_factory() as s:
        from sqlalchemy import select

        row = (
            await s.execute(
                select(runs.c.id, runs.c.script_id, runs.c.schedule_id)
            )
        ).first()
    assert row is not None
    assert row[0] == body["run_id"]
    assert row[1] == 1
    # Webhook-fired runs are NOT linked to a schedule.
    assert row[2] is None


@pytest.mark.asyncio
async def test_public_fire_unknown_token_returns_404(app_ctx):
    ac, _, _, _ = app_ctx
    r = await ac.post("/webhooks/totally-bogus-token-xyz")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_public_fire_inactive_webhook_returns_404(app_ctx):
    ac, _, token, _ = app_ctx
    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1, "enabled": False},
            headers=_h(token),
        )
    ).json()
    r = await ac.post(f"/webhooks/{created['secret_token']}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_public_fire_exports_params_to_subprocess_env(app_ctx):
    """Webhook params land in os.environ as SCRIPTDECK_PARAM_<KEY> + JSON blob.

    Spawns a Python script that prints the env vars and confirms the
    runner thread sees them.
    """
    ac, app, token, settings = app_ctx
    storage = Path(settings.storage_dir)
    scripts_dir = storage / "scripts" / "1"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    src = scripts_dir / "main.py"
    src.write_text(
        "import os, json\n"
        "open('/tmp/webhook_env.txt', 'w').write(\n"
        "    repr({\n"
        "        'flag': os.environ.get('SCRIPTDECK_PARAM_FLAG'),\n"
        "        'json': os.environ.get('SCRIPTDECK_PARAMS_JSON'),\n"
        "    })\n"
        ")\n",
        encoding="utf-8",
    )
    if os.path.exists("/tmp/webhook_env.txt"):
        os.unlink("/tmp/webhook_env.txt")

    created = (
        await ac.post(
            "/api/kindling/webhooks",
            json={"script_id": 1, "params": {"flag": "yes"}},
            headers=_h(token),
        )
    ).json()
    r = await ac.post(f"/webhooks/{created['secret_token']}")
    assert r.status_code == 202
    run_id = r.json()["run_id"]

    # Wait for the background task to finish (it writes /tmp/webhook_env.txt).
    import asyncio

    for _ in range(40):
        async with app.state.session_factory() as s:
            from sqlalchemy import select as _select

            row = (
                await s.execute(_select(runs.c.status).where(runs.c.id == run_id))
            ).first()
        if row and row[0] in {"success", "failure", "error"}:
            break
        await asyncio.sleep(0.25)

    assert os.path.exists("/tmp/webhook_env.txt"), "subprocess didn't write env file"
    parsed = eval(open("/tmp/webhook_env.txt").read())  # noqa: S307 — controlled content
    assert parsed["flag"] == "yes"
    assert json.loads(parsed["json"]) == {"flag": "yes"}
    os.unlink("/tmp/webhook_env.txt")
