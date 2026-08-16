"""Cross-user authorization tests for script-scoped endpoints.

Task 9 + 9b: every endpoint that resolves to a script (directly via
``script_id`` or indirectly via a joined row such as ``schedule.script_id``
or ``run.script_id``) must reject callers whose ``current_user.id`` does
not match ``script.user_id``, unless the caller is an admin.
"""
from __future__ import annotations

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
async def two_users_app(tmp_path):
    """Bootstrap an app with two non-admin users (alice, bob).

    alice owns script ``sid``. bob does not. Returns ``(app, alice_token,
    bob_token, sid)``.
    """
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
                id=1, email="alice@example.com",
                password_hash=hash_password("hunter22"),
                role="editor",
            )
        )
        await s.execute(
            insert(users).values(
                id=2, email="bob@example.com",
                password_hash=hash_password("hunter22"),
                role="editor",
            )
        )
        await s.commit()

    alice_token, _, _ = encode_jwt(1, "editor", settings.jwt_secret)
    bob_token, _, _ = encode_jwt(2, "editor", settings.jwt_secret)

    # alice creates a script (gets user_id=1 from auth.deps).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {alice_token}"},
            json={"name": "alice-s", "language": "python", "source": "print(1)\n"},
        )
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
    return app, alice_token, bob_token, sid


@pytest.mark.asyncio
async def test_user_b_cannot_get_user_a_script(two_users_app):
    app, _alice_token, bob_token, sid = two_users_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/scripts/{sid}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    # The script exists but is owned by alice, so bob must get 403 — NOT
    # 200, NOT 404. (Tightened from `in (403, 404)` so a regression that
    # removes the check fails this test loudly.)
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_a_can_get_own_script(two_users_app):
    app, alice_token, _bob_token, sid = two_users_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/scripts/{sid}",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
    assert r.status_code == 200, r.text


# --- Task 9b: schedules + runs/{run_id}* gaps -----------------------------


@pytest.mark.asyncio
async def test_user_b_cannot_create_schedule_on_user_a_script(two_users_app):
    """POST /api/schedules must verify ownership of body.script_id."""
    app, _alice_token, bob_token, sid = two_users_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/schedules",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={
                "script_id": sid, "kind": "interval",
                "expression": "5m", "enabled": True,
                "retry_max": 0, "retry_backoff": 0,
            },
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_b_cannot_list_user_a_schedules(two_users_app):
    """GET /api/schedules?script_id=<alice's> must reject bob."""
    app, _alice_token, bob_token, sid = two_users_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/schedules?script_id={sid}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    assert r.status_code == 403, r.text


async def _make_run(app, token: str, sid: int) -> int:
    """Trigger a run synchronously enough to read it back; return run_id."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/runs",
            headers={"Authorization": f"Bearer {token}"},
            json={"script_id": sid},
        )
        assert r.status_code == 201, r.text
        return int(r.json()["id"])


@pytest.mark.asyncio
async def test_user_b_cannot_get_user_a_run_detail(two_users_app):
    app, alice_token, bob_token, sid = two_users_app
    run_id = await _make_run(app, alice_token, sid)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/runs/{run_id}",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_b_cannot_read_user_a_run_log(two_users_app):
    app, alice_token, bob_token, sid = two_users_app
    run_id = await _make_run(app, alice_token, sid)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get(
            f"/api/runs/{run_id}/log",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_b_cannot_cancel_user_a_run(two_users_app):
    app, alice_token, bob_token, sid = two_users_app
    run_id = await _make_run(app, alice_token, sid)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            f"/api/runs/{run_id}/cancel",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_user_b_sees_only_own_scripts_in_listing(two_users_app):
    """Non-admin GET /api/scripts must return only the caller's own scripts."""
    app, alice_token, bob_token, sid = two_users_app
    # bob creates his own script
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"name": "bob-s", "language": "python", "source": "pass\n"},
        )
        assert r.status_code == 201, r.text
        bob_sid = r.json()["id"]

        # alice still sees her own
        ra = await ac.get(
            "/api/scripts",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert ra.status_code == 200, ra.text
        alice_ids = {s["id"] for s in ra.json()}
        assert sid in alice_ids
        assert bob_sid not in alice_ids

        # bob sees only his own — not alice's
        rb = await ac.get(
            "/api/scripts",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert rb.status_code == 200, rb.text
        bob_ids = {s["id"] for s in rb.json()}
        assert bob_sid in bob_ids
        assert sid not in bob_ids


@pytest.mark.asyncio
async def test_user_b_sees_only_own_runs_in_listing(two_users_app):
    """Non-admin GET /api/runs must return only the caller's own runs."""
    app, alice_token, bob_token, sid = two_users_app
    # alice triggers a run on her own script
    alice_run_id = await _make_run(app, alice_token, sid)

    # bob triggers a run on his own (new) script
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {bob_token}"},
            json={"name": "bob-runs-s", "language": "python", "source": "pass\n"},
        )
        assert r.status_code == 201, r.text
        bob_sid = r.json()["id"]
    bob_run_id = await _make_run(app, bob_token, bob_sid)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        ra = await ac.get(
            "/api/runs",
            headers={"Authorization": f"Bearer {alice_token}"},
        )
        assert ra.status_code == 200, ra.text
        alice_run_ids = {r_["id"] for r_ in ra.json()}
        assert alice_run_id in alice_run_ids
        assert bob_run_id not in alice_run_ids

        rb = await ac.get(
            "/api/runs",
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert rb.status_code == 200, rb.text
        bob_run_ids = {r_["id"] for r_ in rb.json()}
        assert bob_run_id in bob_run_ids
        assert alice_run_id not in bob_run_ids
