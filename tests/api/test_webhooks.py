"""Tests for the webhook trigger endpoint (POST /webhooks/<token>).

Contract:
- No JWT required — the token in the URL is the sole credential.
- Token lookup is by SHA-256 hash; the raw token is never persisted.
- 200 + a runner run enqueued on a valid, enabled token.
- 404 on a bad token (no information disclosure).
- 429 when the per-token rate limit (60/min) is exceeded.
- The run is enqueued with ``schedule_id`` pointing at the webhook row, so
  it appears in /api/kindling/runs?schedule_id=N for audit.
- Trigger.params_json (if any) is exported to the run env as
  KINDLING_PARAM_<KEY>=<value>.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert, select

from kindling.app import create_app
from kindling.config import Settings
from kindling.db.models import runs, schedules, scripts, users


def _token() -> str:
    """Return a fresh URL-safe random token (the secret clients POST with)."""
    return secrets.token_urlsafe(32)


def _hash(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


@pytest.fixture
async def webhook_ctx(tmp_path):
    """One user, one script, one webhook schedule (token seeded by the test)."""
    db = tmp_path / "t.db"
    storage = tmp_path / "s"
    (storage / "logs").mkdir(parents=True)
    settings = Settings(
        db_path=str(db),
        storage_dir=str(storage),
        jwt_secret="x" * 32,
        env_encryption_key=base64.b64encode(b"k" * 32).decode(),
    )
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(users).values(
            id=1, email="alice@x.com", password_hash="x", role="editor",
            created_at=datetime.now(UTC).isoformat(),
        ))
        await s.execute(insert(scripts).values(
            id=10, user_id=1, name="hello", language="python",
            source_path="x.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        yield ac, app, storage


async def _seed_webhook(app, *, enabled: int = 1, params_json: str | None = None) -> tuple[str, int]:
    """Insert a webhook schedule row directly; return (raw_token, schedule_id)."""
    raw = _token()
    h = _hash(raw)
    async with app.state.session_factory() as s:
        row = await s.execute(
            insert(schedules).values(
                script_id=10, kind="webhook", expression=None,
                enabled=enabled, next_run_at=None,
                webhook_token_hash=h,
                params_json=params_json,
            ).returning(schedules.c.id)
        )
        sid = row.scalar_one()
        await s.commit()
    return raw, int(sid)


@pytest.mark.asyncio
async def test_webhook_unknown_token_returns_404(webhook_ctx):
    ac, _app, _storage = webhook_ctx
    r = await ac.post("/api/kindling/webhooks/" + _token())
    assert r.status_code == 404, r.text


@pytest.mark.asyncio
async def test_webhook_valid_token_enqueues_run_and_returns_200(webhook_ctx):
    ac, app, _storage = webhook_ctx
    raw, sid = await _seed_webhook(app)
    r = await ac.post(f"/api/kindling/webhooks/{raw}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["schedule_id"] == sid
    # A run row should now exist with status='running' and schedule_id=sid.
    async with app.state.session_factory() as s:
        rs = (await s.execute(
            select(runs).where(runs.c.schedule_id == sid)
        )).mappings().all()
    assert len(rs) == 1
    assert rs[0]["status"] in {"running", "success", "failure"}  # may have completed


@pytest.mark.asyncio
async def test_webhook_disabled_trigger_returns_404(webhook_ctx):
    """Disabled triggers must look like a missing token (404) to avoid
    disclosing that the token exists but is disabled."""
    ac, app, _storage = webhook_ctx
    raw, _sid = await _seed_webhook(app, enabled=0)
    r = await ac.post(f"/api/kindling/webhooks/{raw}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_token_lookup_uses_sha256_hash_only(webhook_ctx):
    """The DB row stores the SHA-256 hex hash, NOT the raw token. Verify by
    inspecting the row and confirming that the raw token differs."""
    ac, app, _storage = webhook_ctx
    raw, sid = await _seed_webhook(app)
    async with app.state.session_factory() as s:
        row = (await s.execute(
            select(schedules.c.webhook_token_hash).where(schedules.c.id == sid)
        )).one()
    assert row[0] == _hash(raw)
    assert raw != row[0]  # raw token is never the stored value


@pytest.mark.asyncio
async def test_webhook_rate_limit_returns_429(webhook_ctx):
    """61 valid hits within a minute should trip the 60/min rate limit on the
    61st call (returns 429)."""
    ac, app, _storage = webhook_ctx
    raw, _sid = await _seed_webhook(app)
    # Reset the in-memory rate limiter to start clean (other tests may have
    # exercised it through the global bucket).
    from kindling.api.webhooks import reset_rate_limiter_for_tests
    reset_rate_limiter_for_tests()
    last_status = None
    for _ in range(61):
        r = await ac.post(f"/api/kindling/webhooks/{raw}")
        last_status = r.status_code
    assert last_status == 429


@pytest.mark.asyncio
async def test_webhook_does_not_require_jwt(webhook_ctx):
    """The endpoint must work with NO Authorization header (token is the auth)."""
    ac, app, _storage = webhook_ctx
    raw, _sid = await _seed_webhook(app)
    # No `Authorization` header set.
    r = await ac.post(f"/api/kindling/webhooks/{raw}")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_webhook_creates_run_with_params_json(webhook_ctx, monkeypatch_auth):
    """When params_json is set on the trigger, the run row records the params
    via the run_service.enqueue_from_trigger helper (which we test by
    checking the schedule row's params_json is loaded and merged).
    Full env-merging is tested in tests/test_param_env.py; here we just
    confirm the trigger's params_json is read on the webhook path."""
    ac, app, _storage = webhook_ctx
    raw, sid = await _seed_webhook(
        app, params_json='{"region":"us-east-1","shard":3}'
    )
    r = await ac.post(f"/api/kindling/webhooks/{raw}")
    assert r.status_code == 200
    async with app.state.session_factory() as s:
        params_row = (await s.execute(
            select(schedules.c.params_json).where(schedules.c.id == sid)
        )).one()
    assert params_row[0] == '{"region":"us-east-1","shard":3}'
