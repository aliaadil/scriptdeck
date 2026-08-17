import pytest
from httpx import ASGITransport, AsyncClient

from kindling.app import create_app


@pytest.mark.asyncio
async def test_setup_then_login(tmp_db, tmp_storage, monkeypatch):
    monkeypatch.setenv("KINDLING_STORAGE_DIR", str(tmp_storage))
    s = type("S", (), {})()
    from kindling.config import Settings

    settings = Settings(
        db_path=str(tmp_db),
        jwt_secret="x" * 32,
        env_encryption_key="A" * 44,
        storage_dir=str(tmp_storage),
    )
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/api/kindling/auth/setup", json={"email": "a@b.com", "password": "hunter22"}
        )
        assert r.status_code == 201
        token = r.json()["token"]
        r2 = await ac.get("/api/kindling/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["email"] == "a@b.com"
        # Setup is now disabled
        r3 = await ac.post(
            "/api/kindling/auth/setup", json={"email": "b@b.com", "password": "hunter22"}
        )
        assert r3.status_code == 404