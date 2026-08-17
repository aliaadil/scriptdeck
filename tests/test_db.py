"""Tests for config + async engine."""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from kindling.config import Settings
from kindling.db.engine import make_engine


def test_settings_defaults():
    s = Settings()
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.db_path == Path('./data/kindling.db')
    assert s.storage_dir == "storage"
    assert s.runner_concurrency == 4
    assert s.scheduler_interval == 5


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("KINDLING_PORT", "9000")
    monkeypatch.setenv("KINDLING_JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.port == 9000
    assert s.jwt_secret == "x" * 32


def test_engine_creation(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    assert isinstance(engine, AsyncEngine)