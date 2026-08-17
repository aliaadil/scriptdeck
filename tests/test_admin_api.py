import base64
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.auth.jwt import encode_jwt
from kindling.auth.passwords import hash_password
from kindling.config import Settings
from kindling.db.models import users


@pytest.fixture
async def app_and_tokens(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="v@b.com", password_hash=hash_password("hunter22"),
            role="viewer",
        ))
        await s.execute(insert(users).values(
            id=2, email="a@b.com", password_hash=hash_password("hunter22"),
            role="admin",
        ))
        await s.commit()
    vtok, _, _ = encode_jwt(1, "viewer", settings.jwt_secret)
    atok, _, _ = encode_jwt(2, "admin", settings.jwt_secret)
    return app, vtok, atok


@pytest.mark.asyncio
async def test_audit_requires_admin(app_and_tokens):
    app, vtok, _ = app_and_tokens
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/kindling/admin/audit",
                         headers={"Authorization": f"Bearer {vtok}"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_audit_admin_returns_list(app_and_tokens):
    app, _, atok = app_and_tokens
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/kindling/admin/audit",
                         headers={"Authorization": f"Bearer {atok}"})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


@pytest.mark.asyncio
async def test_stats_returns_expected_keys(app_and_tokens):
    app, _, atok = app_and_tokens
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/kindling/stats",
                         headers={"Authorization": f"Bearer {atok}"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "total_scripts", "total_runs_24h", "success_rate_24h",
        "running_now", "recent_runs",
    }
