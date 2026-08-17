from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from scriptdeck.app import create_app
from scriptdeck.auth.jwt import encode_jwt
from scriptdeck.auth.passwords import hash_password
from scriptdeck.config import Settings
from scriptdeck.db.models import users


@pytest.fixture
async def app_and_token(tmp_path):
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
                email="a@b.com",
                password_hash=hash_password("hunter22"),
                role="admin",
            )
        )
        await s.commit()
    token, _, _ = encode_jwt(1, "admin", settings.jwt_secret)
    return app, token


@pytest.mark.asyncio
async def test_patch_user_me_timezone_round_trips(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.patch(
            "/api/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"timezone": "America/Los_Angeles"},
        )
        assert r.status_code == 200, r.text
        # Confirm the DB row reflects the change.
        async with app.state.session_factory() as s:
            row = (await s.execute(
                select(users.c.timezone).where(users.c.id == 1)
            )).scalar_one()
        assert row == "America/Los_Angeles"


@pytest.mark.asyncio
async def test_invalid_timezone_rejected(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.patch(
            "/api/users/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"timezone": "Not/AZone"},
        )
    assert r.status_code == 422
