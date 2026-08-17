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


# ---- Task 9: new fields on ScheduleCreate / ScheduleOut ----


@pytest.mark.asyncio
async def test_create_schedule_validates_blackout_dates(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "blackout_dates": ["not-a-date"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_schedule_validates_overlap_policy(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "overlap_policy": "explode",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_schedule_validates_include_days_range(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "include_days": [7],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_schedule_with_blackout_round_trips(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "timezone": "UTC",
                "blackout_dates": ["2026-12-25"],
                "include_days": [0, 1, 2],
                "overlap_policy": "skip",
                "queue_max": 5,
                "retry_max": 2,
                "retry_backoff": 30,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 201, r.text
    body = r.json()
    # The API returns lists (deserialized), not JSON strings.
    assert body["blackout_dates"] == ["2026-12-25"]
    assert body["include_days"] == [0, 1, 2]
    assert isinstance(body["blackout_dates"], list)
    assert isinstance(body["include_days"], list)


@pytest.mark.asyncio
async def test_queue_dropped_visible_in_schedule_out(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 201, r.text
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/schedules", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["queue_dropped"] == 0


# ---- Final-review fix M11: retry_max / retry_backoff bounds ----

@pytest.mark.asyncio
async def test_create_schedule_rejects_negative_retry_max(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "retry_max": -1,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_create_schedule_rejects_negative_retry_backoff(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "retry_backoff": -5,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_update_schedule_rejects_negative_retry_max(app_and_token):
    app, token = app_and_token
    # Create a schedule first.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 201, r.text
    sched_id = r.json()["id"]
    # Update with negative retry_max — must be rejected.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.put(
            f"/api/schedules/{sched_id}",
            json={
                "script_id": 1, "kind": "cron", "expression": "0 9 * * *",
                "retry_max": -1,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 422, r.text

