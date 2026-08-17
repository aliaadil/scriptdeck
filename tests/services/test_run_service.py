"""Tests for scriptdeck.services.run_service.

Task 2 of feat/run-logs runs-page refresh: ``create_run`` must write a
tz-aware ISO-8601 ``started_at`` rather than relying on the SQL default.
"""
from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert

from scriptdeck.app import create_app
from scriptdeck.config import Settings
from scriptdeck.db.models import scripts, users
from scriptdeck.services.run_service import create_run


@pytest.fixture
async def session_ctx(tmp_path):
    """One user + one script, yielding an open AsyncSession."""
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
        await s.execute(insert(scripts).values(
            id=10, user_id=1, name="hello", language="python", source_path="x.py",
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        ))
        await s.commit()
        yield s


@pytest.mark.asyncio
async def test_create_run_writes_tz_aware_started_at(session_ctx):
    s = session_ctx
    _run_id, started_at, _retry_group = await create_run(
        s, script_id=10, schedule_id=None
    )
    parsed = datetime.fromisoformat(started_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
