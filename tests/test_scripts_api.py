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
async def test_create_get_script(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "hi", "language": "python", "source": "print(1)\n"},
        )
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        r2 = await ac.get(
            f"/api/scripts/{sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200


@pytest.mark.asyncio
async def test_deps_roundtrip(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "d", "language": "python", "source": "import requests\n"},
        )
        sid = r.json()["id"]
        r2 = await ac.put(
            f"/api/scripts/{sid}/deps",
            headers={"Authorization": f"Bearer {token}"},
            json={"deps": ["requests"], "source": "manual"},
        )
        assert r2.status_code == 200, r2.text
        r3 = await ac.get(
            f"/api/scripts/{sid}/deps",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 200
        assert "requests" in r3.json()["deps"]


@pytest.mark.asyncio
async def test_env_roundtrip(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "e", "language": "python", "source": "pass\n"},
        )
        sid = r.json()["id"]
        r2 = await ac.put(
            f"/api/scripts/{sid}/env",
            headers={"Authorization": f"Bearer {token}"},
            json={"content": "FOO=bar\nBAZ=qux\n"},
        )
        assert r2.status_code == 200, r2.text
        r3 = await ac.get(
            f"/api/scripts/{sid}/env",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 200
        assert r3.json()["has_env"] is True


@pytest.mark.asyncio
async def test_schedules_roundtrip(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "s", "language": "python", "source": "pass\n"},
        )
        sid = r.json()["id"]
        r2 = await ac.post(
            "/api/schedules",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "script_id": sid,
                "kind": "interval",
                "expression": "5m",
                "enabled": True,
                "retry_max": 0,
                "retry_backoff": 0,
            },
        )
        assert r2.status_code == 201, r2.text
        sched_id = r2.json()["id"]
        r3 = await ac.get(
            f"/api/schedules?script_id={sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 200
        assert any(s["id"] == sched_id for s in r3.json())


@pytest.mark.asyncio
async def test_runs_trigger_and_list(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "r", "language": "python", "source": "pass\n"},
        )
        sid = r.json()["id"]
        r2 = await ac.post(
            "/api/runs",
            headers={"Authorization": f"Bearer {token}"},
            json={"script_id": sid},
        )
        assert r2.status_code == 201, r2.text
        r3 = await ac.get(
            "/api/runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r3.status_code == 200
        assert len(r3.json()) >= 1


@pytest.mark.asyncio
async def test_scripts_run_shim(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "r2", "language": "python", "source": "pass\n"},
        )
        sid = r.json()["id"]
        r2 = await ac.post(
            f"/api/scripts/{sid}/run",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 201, r2.text
        assert r2.json()["script_id"] == sid