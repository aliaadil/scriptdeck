"""Tests for /kindling SPA fallback (rebrand Task 3 fix).

The dashboard static is mounted under /kindling. Deep links like
/kindling/dashboard and /kindling/runs/5 must resolve to index.html so
client-side routing can take over; otherwise the SPA 404s on refresh.

These tests temporarily symlink dashboard_static/ into a real path the
create_app function expects, then exercise both a real asset and a
deep-link fallback.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from kindling.app import create_app
from kindling.config import Settings


# Path where create_app() looks for the dashboard build output.
DASHBOARD_DIR = Path(__file__).resolve().parents[1] / "src" / "kindling" / "dashboard_static"


def _index_html_content() -> str:
    """Return an index.html that matches what the SPA expects."""
    return (
        "<!doctype html><html><head><title>Kindling</title></head>"
        "<body><div id=\"root\"></div></body></html>"
    )


@pytest.fixture
def dashboard_in_place(monkeypatch):
    """Ensure the dashboard_static directory exists with a real asset, so
    create_app picks it up and we can verify the SPA fallback does NOT
    intercept genuine asset requests."""
    created = False
    if not (DASHBOARD_DIR.is_dir() and (DASHBOARD_DIR / "index.html").is_file()):
        DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
        (DASHBOARD_DIR / "index.html").write_text(_index_html_content(), encoding="utf-8")
        created = True
    asset_dir = DASHBOARD_DIR / "assets"
    asset_dir.mkdir(exist_ok=True)
    asset_file = asset_dir / "index-fake.js"
    had_asset = asset_file.is_file()
    if not had_asset:
        asset_file.write_text("// stub\n", encoding="utf-8")
    try:
        yield DASHBOARD_DIR
    finally:
        if created:
            shutil.rmtree(DASHBOARD_DIR)
        elif not had_asset:
            asset_file.unlink()


@pytest.mark.asyncio
async def test_kindling_deep_link_returns_index_html(dashboard_in_place, tmp_db):
    """Refresh on /kindling/dashboard must return 200 with text/html so the
    SPA boots instead of 404-ing."""
    s = Settings(db_path=str(tmp_db), jwt_secret="x" * 32, env_encryption_key="A" * 44)
    app = create_app(s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/kindling/dashboard")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    assert "Kindling" in r.text


@pytest.mark.asyncio
async def test_kindling_unknown_route_returns_index_html(dashboard_in_place, tmp_db):
    """Other SPA paths under /kindling (e.g. /kindling/runs/5) also fall back."""
    s = Settings(db_path=str(tmp_db), jwt_secret="x" * 32, env_encryption_key="A" * 44)
    app = create_app(s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/kindling/runs/5")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_kindling_real_asset_still_served(dashboard_in_place, tmp_db):
    """Static asset requests must NOT trigger the SPA fallback."""
    s = Settings(db_path=str(tmp_db), jwt_secret="x" * 32, env_encryption_key="A" * 44)
    app = create_app(s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/kindling/assets/index-fake.js")
    assert r.status_code == 200
    # Real assets are returned as their native content type (application/javascript
    # for .js), not text/html.
    assert not r.headers["content-type"].startswith("text/html")


@pytest.mark.asyncio
async def test_root_redirects_to_kindling(dashboard_in_place, tmp_db):
    """The bare / root must redirect into the dashboard."""
    s = Settings(db_path=str(tmp_db), jwt_secret="x" * 32, env_encryption_key="A" * 44)
    app = create_app(s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Don't follow — we want to inspect the redirect.
        r = await ac.get("/", follow_redirects=False)
    assert r.status_code in (307, 308)
    assert r.headers["location"].endswith("/kindling/")
