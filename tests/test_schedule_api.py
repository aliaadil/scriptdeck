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
from scriptdeck.db.models import runs, schedules, scripts, users


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


# ---- Bug 1: GET /api/schedules/{id} prefill support ----


@pytest.mark.asyncio
async def test_get_schedule_returns_full_record(app_and_token):
    """Create via POST, then GET /{id} returns the same ScheduleOut.

    Verifies expression, timezone, blackout_dates, include_days,
    overlap_policy, queue_max, retry_max, retry_backoff round-trip.
    """
    app, token = app_and_token
    payload = {
        "script_id": 1, "kind": "cron", "expression": "* * * * *",
        "timezone": "America/New_York",
        "blackout_dates": ["2026-12-25"],
        "include_days": [0, 1, 2],
        "overlap_policy": "queue",
        "queue_max": 7,
        "retry_max": 3,
        "retry_backoff": 45,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules", json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 201, r.text
    sched_id = r.json()["id"]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/schedules/{sched_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == sched_id
    assert body["script_id"] == 1
    assert body["expression"] == "* * * * *"
    assert body["timezone"] == "America/New_York"
    assert body["blackout_dates"] == ["2026-12-25"]
    assert body["include_days"] == [0, 1, 2]
    assert body["overlap_policy"] == "queue"
    assert body["queue_max"] == 7
    assert body["retry_max"] == 3
    assert body["retry_backoff"] == 45
    # run_count is part of ScheduleOut; for a freshly created schedule it
    # defaults to 0 with no runs yet.
    assert body["run_count"] == 0


@pytest.mark.asyncio
async def test_get_schedule_404_for_unknown_id(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/schedules/9999",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_get_schedule_403_for_other_users_script(app_and_token):
    """User A owns script #1. Build user B inline who owns script #2.

    Schedule lives on script #2 owned by user B; user A's token must
    not be able to read it (mirrors list-endpoint filtering: 404 is
    also fine, but the membership check via require_script_owner gives
    403 first).

    Note: the fixture creates user 1 as admin. We demote them to editor
    so the ownership check fires for a schedule owned by user 2.
    """
    app, _ = app_and_token
    secret = "x" * 32  # matches fixture
    async with app.state.session_factory() as s:
        from sqlalchemy import update
        await s.execute(update(users).where(users.c.id == 1).values(role="editor"))
        await s.execute(
            insert(users).values(
                id=2,
                email="b@b.com",
                password_hash=hash_password("hunter22"),
                role="editor",
            )
        )
        await s.execute(
            insert(scripts).values(
                id=2,
                name="t2", language="python", source_path="scripts/2/main.py",
                user_id=2,
            )
        )
        await s.execute(
            insert(schedules).values(
                script_id=2, kind="cron", expression="0 9 * * *",
                next_run_at=datetime.now(UTC).isoformat(),
                overlap_policy="skip",
            )
        )
        await s.commit()

    user_a_token, _, _ = encode_jwt(1, "editor", secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/schedules/1",  # id=1 is the schedule on user 2's script
            headers={"Authorization": f"Bearer {user_a_token}"},
        )
    # 404 is also acceptable per the spec mirror; both prove isolation.
    assert r.status_code in (403, 404), r.text


# ---- Feature 2: run_count on the list endpoint ----


@pytest.mark.asyncio
async def test_list_schedules_includes_run_count(app_and_token):
    app, token = app_and_token
    # Two schedules via API.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.post(
            "/api/schedules",
            json={"script_id": 1, "kind": "cron", "expression": "0 9 * * *"},
            headers={"Authorization": f"Bearer {token}"},
        )
        r2 = await ac.post(
            "/api/schedules",
            json={"script_id": 1, "kind": "cron", "expression": "0 10 * * *"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r1.status_code == 201
    assert r2.status_code == 201
    sched_with_runs = r1.json()["id"]
    sched_no_runs = r2.json()["id"]

    # Insert runs directly into the runs table for the first schedule.
    async with app.state.session_factory() as s:
        await s.execute(
            insert(runs).values(
                script_id=1, schedule_id=sched_with_runs,
                started_at=datetime.now(UTC).isoformat(),
                status="success",
            )
        )
        await s.execute(
            insert(runs).values(
                script_id=1, schedule_id=sched_with_runs,
                started_at=datetime.now(UTC).isoformat(),
                status="failure",
            )
        )
        await s.execute(
            insert(runs).values(
                script_id=1, schedule_id=sched_with_runs,
                started_at=datetime.now(UTC).isoformat(),
                status="error",
            )
        )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/schedules",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {row["id"]: row for row in body}
    assert by_id[sched_with_runs]["run_count"] == 3
    assert by_id[sched_no_runs]["run_count"] == 0


@pytest.mark.asyncio
async def test_list_schedules_run_count_isolated_per_schedule(app_and_token):
    app, token = app_and_token
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r1 = await ac.post(
            "/api/schedules",
            json={"script_id": 1, "kind": "cron", "expression": "0 9 * * *"},
            headers={"Authorization": f"Bearer {token}"},
        )
        r2 = await ac.post(
            "/api/schedules",
            json={"script_id": 1, "kind": "cron", "expression": "0 10 * * *"},
            headers={"Authorization": f"Bearer {token}"},
        )
    sched_a = r1.json()["id"]
    sched_b = r2.json()["id"]

    async with app.state.session_factory() as s:
        for _ in range(2):
            await s.execute(
                insert(runs).values(
                    script_id=1, schedule_id=sched_a,
                    started_at=datetime.now(UTC).isoformat(),
                    status="success",
                )
            )
        for _ in range(5):
            await s.execute(
                insert(runs).values(
                    script_id=1, schedule_id=sched_b,
                    started_at=datetime.now(UTC).isoformat(),
                    status="success",
                )
            )
        await s.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            "/api/schedules",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    counts = {row["id"]: row["run_count"] for row in body}
    assert counts[sched_a] == 2
    assert counts[sched_b] == 5
    # And neither equals the sum (2 + 5).
    assert counts[sched_a] + counts[sched_b] == 7


