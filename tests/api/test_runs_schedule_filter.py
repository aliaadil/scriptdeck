"""Tests for GET /api/kindling/runs schedule_id + offset filter.

Task 1 of feat/run-logs runs-page refresh.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import runs, schedules, scripts, users


@pytest.fixture
async def app_ctx(tmp_path):
    """Two users, two scripts, two schedules, four runs."""
    db = tmp_path / "t.db"
    settings = Settings(
        db_path=str(db),
        storage_dir=str(tmp_path / "s"),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(users).values(
            id=2, email="bob@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=10, user_id=1, name="hello", language="python", source_path="x.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=20, user_id=2, name="bob-scr", language="python", source_path="y.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(schedules).values(
            id=100, script_id=10, kind="cron", expression="* * * * *",
            enabled=1, next_run_at="2030-01-01T00:00:00+00:00",
            retry_max=0, retry_backoff=0, overlap_policy="skip",
            queue_max=10, queue_dropped=0, timezone="UTC",
        ))
        await s.execute(insert(schedules).values(
            id=200, script_id=20, kind="cron", expression="* * * * *",
            enabled=1, next_run_at="2030-01-01T00:00:00+00:00",
            retry_max=0, retry_backoff=0, overlap_policy="skip",
            queue_max=10, queue_dropped=0, timezone="UTC",
        ))
        for i in range(3):
            await s.execute(insert(runs).values(
                id=1000 + i, script_id=10, schedule_id=100,
                started_at="2030-01-01T00:00:00+00:00", status="success",
                exit_code=0, retry_group=str(i),
            ))
        for i in range(2):
            await s.execute(insert(runs).values(
                id=2000 + i, script_id=20, schedule_id=200,
                started_at="2030-01-01T00:00:00+00:00", status="success",
                exit_code=0, retry_group=str(i + 10),
            ))
        # One skipped run with a reason — must round-trip to the API.
        await s.execute(insert(runs).values(
            id=3000, script_id=10, schedule_id=100,
            started_at="2030-01-01T00:00:00+00:00", status="skipped",
            exit_code=-1, retry_group="sk1",
            skip_reason="previous run still in progress",
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_schedule_id_returns_only_matching(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"schedule_id": 100})
    assert r.status_code == 200, r.text
    runs_out = r.json()
    assert {x["script_id"] for x in runs_out} == {10}
    assert len(runs_out) == 4  # 3 success + 1 skipped (id 3000)


@pytest.mark.asyncio
async def test_script_name_populated(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"schedule_id": 100})
    assert r.status_code == 200, r.text
    runs_out = r.json()
    assert len(runs_out) > 0
    # Every row in this fixture belongs to script "hello" (id=10).
    assert all(x["script_name"] == "hello" for x in runs_out)


@pytest.mark.asyncio
async def test_schedule_id_owner_check(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"schedule_id": 200})  # belongs to bob
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_schedule_id_404(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"schedule_id": 999})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_offset_and_limit(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"schedule_id": 100, "limit": 2, "offset": 1})
    runs_out = r.json()
    assert len(runs_out) == 2
    # Newest-first default ordering. Schedule 100 owns 4 rows now (1000-1002
    # plus the skipped 3000); offset=1 skips 3000, leaving ids 1002+1001.
    assert [x["id"] for x in runs_out] == [1002, 1001]


@pytest.mark.asyncio
async def test_offset_clamps_upper(app_ctx, monkeypatch_auth):
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"offset": 99999})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_status_filter_returns_only_matching(app_ctx, monkeypatch_auth):
    """?status=running must filter server-side. Regression: backend param was
    named status_filter and the frontend sent status=, so the running section
    showed every run regardless of status."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    # Mark one of alice's existing success runs as running.
    async with app.state.session_factory() as s:
        from sqlalchemy import update
        await s.execute(update(runs).where(runs.c.id == 1000).values(status="running"))
        await s.commit()
    r = await ac.get("/api/kindling/runs", params={"status": "running"})
    assert r.status_code == 200, r.text
    runs_out = r.json()
    assert {x["id"] for x in runs_out} == {1000}
    assert all(x["status"] == "running" for x in runs_out)


@pytest.mark.asyncio
async def test_skip_reason_round_trips(app_ctx, monkeypatch_auth):
    """RunOut exposes skip_reason so the UI can show why a run was skipped."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"status": "skipped"})
    assert r.status_code == 200, r.text
    runs_out = r.json()
    assert len(runs_out) == 1
    assert runs_out[0]["skip_reason"] == "previous run still in progress"


@pytest.mark.asyncio
async def test_schedule_timezone_round_trips(app_ctx, monkeypatch_auth):
    """RunOut exposes schedule_timezone so the UI can show why a run fired
    at the instant it did (UTC vs local timezone schedule)."""
    ac, app = app_ctx
    monkeypatch_auth(user_id=1, role="editor", app=app)
    r = await ac.get("/api/kindling/runs", params={"schedule_id": 100})
    assert r.status_code == 200, r.text
    runs_out = r.json()
    assert all(x["schedule_timezone"] == "UTC" for x in runs_out)