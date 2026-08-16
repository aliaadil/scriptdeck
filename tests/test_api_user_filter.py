"""Cross-user authorization tests for script-scoped endpoints.

Task 9: every endpoint that takes a ``script_id`` must reject callers whose
``current_user.id`` does not match ``script.user_id``, unless the caller is an
admin.

This test exercises a representative endpoint (GET /api/scripts/{id}) to prove
the dependency works end-to-end. Full audit of the other endpoints is by
implementation, not test.
"""
from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from scriptdeck.app import create_app
from scriptdeck.auth.jwt import encode_jwt
from scriptdeck.auth.passwords import hash_password
from scriptdeck.config import Settings
from scriptdeck.db.models import users


@pytest.fixture
async def two_users_app(tmp_path):
    """Bootstrap an app with two non-admin users (alice, bob).

    alice owns script ``sid``. bob does not. Returns ``(app, alice_token,
    bob_token, sid)``.
    """
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(
            insert(users).values(
                id=1, email="alice@example.com",
                password_hash=hash_password("hunter22"),
                role="editor",
            )
        )
        await s.execute(
            insert(users).values(
                id=2, email="bob@example.com",
                password_hash=hash_password("hunter22"),
                role="editor",
            )
        )
        await s.commit()

    alice_token, _, _ = encode_jwt(1, "editor", settings.jwt_secret)
    bob_token, _, _ = encode_jwt(2, "editor", settings.jwt_secret)

    # alice creates a script (gets user_id=1 from auth.deps).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"name": "alice-s", "language": "python", "source": "print(1)\n"},
        )
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
    return app, alice_token, bob_token, sid


@pytest.mark.asyncio
async def test_user_b_cannot_get_user_a_script(two_users_app):
    app, _alice_token, bob_token, sid = two_users_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/scripts/{sid}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    assert r.status_code in (403, 404), r.text


@pytest.mark.asyncio
async def test_user_a_can_get_own_script(two_users_app):
    app, alice_token, _bob_token, sid = two_users_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/scripts/{sid}",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
    assert r.status_code == 200, r.text
