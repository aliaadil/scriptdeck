from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from scriptdeck.app import create_app
from scriptdeck.auth.jwt import encode_jwt
from scriptdeck.auth.passwords import hash_password
from scriptdeck.config import Settings
from scriptdeck.db.models import schedules, scripts, users


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
        await s.execute(
            insert(scripts).values(
                name="t", language="python", source_path="scripts/1/main.py",
                user_id=1,
            )
        )
        await s.commit()
    token, _, _ = encode_jwt(1, "admin", settings.jwt_secret)
    return app, token


@pytest.mark.asyncio
async def test_presets_endpoint_returns_six(app_and_token):
    app, _ = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/schedule-presets")
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 6
    for p in body:
        assert {"id", "label", "cron"} <= set(p.keys())


@pytest.mark.asyncio
async def test_next_runs_endpoint_uses_croniter(app_and_token):
    app, token = app_and_token
    # Seed a cron schedule on the script (id=1) created by the fixture.
    async with app.state.session_factory() as s:
        await s.execute(
            insert(schedules).values(
                script_id=1, kind="cron", expression="0 9 * * *",
                next_run_at=datetime.now(UTC).isoformat(),
                overlap_policy="skip",
            )
        )
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/schedules/1/next-runs?limit=5",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 5
    now = datetime.now(UTC)
    for ts in body:
        # All returned timestamps must be parseable ISO datetimes in the future.
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed > now
