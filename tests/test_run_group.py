from __future__ import annotations

import base64

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.auth.jwt import encode_jwt
from kindling.auth.passwords import hash_password
from kindling.config import Settings
from kindling.db.models import runs, scripts, users


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
    # Seed three runs sharing retry_group "XYZ" on script 1. Insert in
    # descending-attempt order (2, 1, 0) with descending started_at so that
    # the natural id ASC order (which matches insertion order) produces the
    # WRONG attempt sequence: ids 1, 2, 3 → attempts 2, 1, 0. Only an
    # explicit ORDER BY attempt ASC re-orders them into attempts 0, 1, 2.
    async with app.state.session_factory() as s:
        for attempt, ts in (
            (2, "2026-08-16T00:03:00+00:00"),
            (1, "2026-08-16T00:02:00+00:00"),
            (0, "2026-08-16T00:01:00+00:00"),
        ):
            await s.execute(
                insert(runs).values(
                    script_id=1,
                    status="failure",
                    retry_group="XYZ",
                    attempt=attempt,
                    started_at=ts,
                )
            )
        await s.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/kindling/runs?group=XYZ",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 3
    # Retry-group responses must be ordered by attempt ASC. RunOut doesn't
    # expose `attempt`, but we chose started_at to match attempt order
    # (attempt 2 = newest, attempt 0 = oldest), so the response's
    # started_at values must be ASCENDING. If the endpoint had fallen
    # back to id ASC / insertion order, started_at would be DESCENDING.
    started_ats = [row["started_at"] for row in body]
    assert started_ats == sorted(started_ats), (
        f"expected started_at ASC (matching attempt ASC), got {started_ats}"
    )
    # All three rows belong to retry_group "XYZ" and share status "failure".
    assert all(row["status"] == "failure" for row in body)
