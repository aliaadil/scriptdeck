"""Webhook service unit tests (token gen, JSON encoding, CRUD, regenerate)."""

from __future__ import annotations

import base64
import json

import pytest
from sqlalchemy import insert

from kindling.auth.passwords import hash_password
from kindling.config import Settings
from kindling.db.engine import make_engine, session_factory
from kindling.db.migrations import run_migrations
from kindling.db.models import scripts, users
from kindling.services import webhook_service


@pytest.fixture
async def session(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    Session = session_factory(engine)
    async with Session() as sess:
        await sess.execute(
            insert(users).values(
                email="a@b.com", password_hash=hash_password("hunter22"), role="admin"
            )
        )
        await sess.execute(
            insert(scripts).values(
                name="s1", language="python", source_path="scripts/1/main.py", user_id=1
            )
        )
        await sess.commit()
        yield sess


@pytest.mark.asyncio
async def test_encode_params_round_trip():
    encoded = webhook_service.encode_params({"region": "eu", "tier": "gold"})
    assert json.loads(encoded) == {"region": "eu", "tier": "gold"}
    decoded = webhook_service.decode_params(encoded)
    assert decoded == {"region": "eu", "tier": "gold"}


@pytest.mark.asyncio
async def test_encode_params_coerces_values_to_str():
    encoded = webhook_service.encode_params({"n": 7, "b": True, "s": "x"})
    decoded = webhook_service.decode_params(encoded)
    assert decoded == {"n": "7", "b": "True", "s": "x"}


@pytest.mark.asyncio
async def test_encode_params_empty_collapses_to_object():
    assert webhook_service.encode_params(None) == "{}"
    assert webhook_service.encode_params({}) == "{}"


@pytest.mark.asyncio
async def test_encode_params_rejects_non_object():
    with pytest.raises(ValueError):
        webhook_service.encode_params("not a dict")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_decode_params_bad_json_returns_empty():
    assert webhook_service.decode_params("{not json") == {}
    assert webhook_service.decode_params(None) == {}
    assert webhook_service.decode_params("") == {}


@pytest.mark.asyncio
async def test_create_webhook_generates_token(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    assert row["script_id"] == 1
    assert row["secret_token"]
    assert len(row["secret_token"]) >= 40  # token_urlsafe(32) -> 43 chars
    assert row["enabled"] == 1
    assert row["fire_count"] == 0


@pytest.mark.asyncio
async def test_create_webhook_requires_existing_script(session):
    with pytest.raises(ValueError):
        await webhook_service.create_webhook(session, script_id=99999)


@pytest.mark.asyncio
async def test_create_webhook_with_params(session):
    row = await webhook_service.create_webhook(
        session,
        script_id=1,
        params={"flag": "1"},
        description="nightly",
    )
    assert json.loads(row["params_json"]) == {"flag": "1"}
    assert row["description"] == "nightly"


@pytest.mark.asyncio
async def test_get_by_token_returns_only_enabled(session):
    a = await webhook_service.create_webhook(session, script_id=1)
    b = await webhook_service.create_webhook(session, script_id=1, enabled=False)
    await session.commit()
    # active token is lookup-able
    found = await webhook_service.get_webhook_by_token(session, a["secret_token"])
    assert found and found["id"] == a["id"]
    # disabled token is NOT lookup-able
    not_found = await webhook_service.get_webhook_by_token(session, b["secret_token"])
    assert not_found is None


@pytest.mark.asyncio
async def test_regenerate_token_changes_secret_token(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    await session.commit()
    old_token = row["secret_token"]
    updated = await webhook_service.regenerate_token(session, row["id"])
    assert updated is not None
    assert updated["secret_token"] != old_token
    # Old URL is dead.
    assert (
        await webhook_service.get_webhook_by_token(session, old_token) is None
    )
    # New URL works.
    assert (
        await webhook_service.get_webhook_by_token(
            session, updated["secret_token"]
        )
        is not None
    )


@pytest.mark.asyncio
async def test_update_webhook_partial_sentinel(session):
    row = await webhook_service.create_webhook(
        session, script_id=1, description="orig", params={"k": "v"}
    )
    await session.commit()
    # Bump enabled only — description + params must be preserved.
    updated = await webhook_service.update_webhook(
        session, row["id"], updates={"enabled": False}
    )
    assert updated is not None
    assert updated["enabled"] == 0
    assert updated["description"] == "orig"
    assert json.loads(updated["params_json"]) == {"k": "v"}


@pytest.mark.asyncio
async def test_update_webhook_explicit_null_clears(session):
    row = await webhook_service.create_webhook(
        session, script_id=1, description="orig"
    )
    await session.commit()
    updated = await webhook_service.update_webhook(
        session, row["id"], updates={"description": None}
    )
    assert updated is not None
    assert updated["description"] is None


@pytest.mark.asyncio
async def test_update_webhook_no_fields_raises(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    await session.commit()
    with pytest.raises(ValueError):
        await webhook_service.update_webhook(session, row["id"], updates={})


@pytest.mark.asyncio
async def test_delete_webhook(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    await session.commit()
    assert await webhook_service.delete_webhook(session, row["id"]) is True
    # Second delete returns False (no row matched).
    assert await webhook_service.delete_webhook(session, row["id"]) is False


@pytest.mark.asyncio
async def test_record_fire_bumps_count(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    await session.commit()
    await webhook_service.record_fire(session, row["id"])
    await webhook_service.record_fire(session, row["id"])
    await session.commit()
    fresh = await webhook_service.get_webhook(session, row["id"])
    assert fresh is not None
    assert fresh["fire_count"] == 2
    assert fresh["last_fired_at"]


@pytest.mark.asyncio
async def test_row_to_out_drops_secret_token(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    out = webhook_service.row_to_out(row)
    assert "secret_token" not in out
    assert "url" not in out
    assert out["id"] == row["id"]
    assert out["script_id"] == 1
    assert isinstance(out["params"], dict)


@pytest.mark.asyncio
async def test_row_with_token_includes_url(session):
    row = await webhook_service.create_webhook(session, script_id=1)
    out = webhook_service.row_with_token(row, base_url="https://h.local")
    assert out["secret_token"] == row["secret_token"]
    assert out["url"] == f"https://h.local/webhooks/{row['secret_token']}"


@pytest.mark.asyncio
async def test_list_webhooks_filters_by_script_ids(session):
    await webhook_service.create_webhook(session, script_id=1)
    await session.commit()
    # Empty filter returns nothing.
    assert await webhook_service.list_webhooks(session, script_ids=[]) == []
    # Right filter returns our row.
    rows = await webhook_service.list_webhooks(session, script_ids=[1])
    assert len(rows) == 1
