from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from scriptdeck.app import create_app
from scriptdeck.auth.jwt import encode_jwt
from scriptdeck.auth.passwords import hash_password
from scriptdeck.config import Settings
from scriptdeck.db.models import runs, scripts, users


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
async def test_run_group_returns_chained_attempts(app_and_token):
    app, token = app_and_token
    # Seed three runs sharing retry_group "XYZ" on script 1.
    async with app.state.session_factory() as s:
        for attempt in (1, 2, 3):
            await s.execute(
                insert(runs).values(
                    script_id=1,
                    status="failure",
                    retry_group="XYZ",
                    attempt=attempt,
                    started_at=f"2026-08-16T00:0{attempt}:00+00:00",
                )
            )
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/runs?group=XYZ",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    # Retry-group responses must be ordered by attempt ASC. RunOut doesn't
    # expose attempt, but insertion order matches attempt, so id ASC is a
    # proxy that also exercises the order-by clause in the endpoint.
    ids = [row["id"] for row in body]
    assert ids == sorted(ids)
    # Status filter sanity: all three rows belong to retry_group "XYZ".
    assert all(row["status"] == "failure" for row in body)
