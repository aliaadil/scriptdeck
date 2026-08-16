import pytest
from httpx import ASGITransport, AsyncClient

from scriptdeck.app import create_app
from scriptdeck.config import Settings


@pytest.mark.asyncio
async def test_health_endpoint(tmp_db):
    s = Settings(db_path=str(tmp_db), jwt_secret="x" * 32, env_encryption_key="A" * 44)
    app = create_app(s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "scheduler" in body
