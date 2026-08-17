import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def kindling_app(tmp_path, monkeypatch):
    """Build a Kindling app whose SQLite database lives under tmp_path.

    `create_app()` defaults to `./data/kindling.db` which won't exist under
    a clean test checkout; pointing `KINDLING_DB_PATH` at a tmp_path file
    before app construction avoids `sqlite3.OperationalError` from
    `make_engine()` and the eager `run_migrations_sync()` call.
    """
    db_file = tmp_path / "kindling.db"
    monkeypatch.setenv("KINDLING_DB_PATH", str(db_file))
    monkeypatch.setenv("KINDLING_ENV_ENCRYPTION_KEY", "A" * 44)
    from kindling.app import create_app
    return create_app()


def test_api_under_kindling_prefix(kindling_app):
    client = TestClient(kindling_app)
    res = client.get('/api/kindling/health')
    assert res.status_code in (200, 401, 403)  # any non-404 means routed


def test_dashboard_served_at_kindling(kindling_app):
    client = TestClient(kindling_app)
    res = client.get('/kindling/')
    assert res.status_code == 200


def test_old_paths_return_404(kindling_app):
    client = TestClient(kindling_app)
    # Legacy API paths from the pre-rebrand ScriptDeck surface must be gone.
    # (Legacy /dashboard/* paths fall through to the SPA catch-all and serve
    # the dashboard index.html — that is intentional after the rebrand.)
    assert client.get('/api/health').status_code == 404
    assert client.get('/api/scripts').status_code == 404