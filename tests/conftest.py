"""Shared pytest fixtures."""
import pytest


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