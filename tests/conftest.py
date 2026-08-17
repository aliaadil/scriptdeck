"""Shared pytest fixtures."""
import pytest

from scriptdeck.auth import deps as auth_deps


@pytest.fixture
def tmp_storage(tmp_path):
    """Per-test storage directory."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture
def tmp_db(tmp_path):
    """Per-test SQLite path."""
    return tmp_path / "test.db"


@pytest.fixture
def monkeypatch_auth(monkeypatch):
    """Returns a factory that fakes current_user for the duration of the test.

    Uses FastAPI's ``app.dependency_overrides`` so ``Depends(current_user)``
    resolves to the fake at request time. The factory wires up the override
    on any FastAPI app the test creates via the ``app_ctx`` fixture (see
    ``tests/api/test_runs_schedule_filter.py``).

    Usage::

        async def test_xxx(app_ctx, monkeypatch_auth):
            ac, app = app_ctx
            monkeypatch_auth(user_id=1, role="editor", app=app)
            ...
    """
    def _set(
        user_id: int,
        role: str = "editor",
        email: str = "tester@x.com",
        app=None,
    ):
        async def _fake():
            from scriptdeck.auth.users import User
            return User(
                id=user_id,
                email=email,
                password_hash="x",
                role=role,
                created_at="2026-01-01T00:00:00+00:00",
                last_login_at=None,
                timezone="UTC",
            )
        if app is not None:
            app.dependency_overrides[auth_deps.current_user] = _fake
        else:
            monkeypatch.setattr(auth_deps, "current_user", _fake)
    return _set