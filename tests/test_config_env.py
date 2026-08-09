"""Tests for Settings.from_env() — verifies both the canonical `SCRIPTDECK_*`
env-var names and the legacy `SCRIPTRUNNER_*` fallbacks work, and that the
canonical name wins when both are set.

These tests guard against the regression that broke Ali's first v0.7
deploy (2026-08-08): the README advertised `SCRIPTDECK_*` but the code
only read `SCRIPTRUNNER_*`, so the operator's env vars were silently
ignored and the service bound to the hardcoded defaults.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scriptrunner.config import Settings


@pytest.fixture
def clean_env(monkeypatch):
    """Strip every SCRIPTDECK_* and SCRIPTRUNNER_* var before each test."""
    for key in list(os.environ):
        if key.startswith("SCRIPTDECK_") or key.startswith("SCRIPTRUNNER_"):
            monkeypatch.delenv(key, raising=False)
    yield monkeypatch


class TestCanonicalEnvVars:
    """The README-advertised SCRIPTDECK_* names MUST work."""

    def test_db_path(self, clean_env):
        clean_env.setenv("SCRIPTDECK_DB_PATH", "/data/sd.db")
        assert Settings.from_env().db_path == Path("/data/sd.db")

    def test_storage_dir(self, clean_env):
        clean_env.setenv("SCRIPTDECK_STORAGE_DIR", "/data/storage")
        assert Settings.from_env().storage_dir == Path("/data/storage")

    def test_host(self, clean_env):
        clean_env.setenv("SCRIPTDECK_HOST", "0.0.0.0")
        assert Settings.from_env().host == "0.0.0.0"

    def test_port(self, clean_env):
        clean_env.setenv("SCRIPTDECK_PORT", "9999")
        assert Settings.from_env().port == 9999

    def test_all_canonical(self, clean_env):
        clean_env.setenv("SCRIPTDECK_DB_PATH", "/a/b.db")
        clean_env.setenv("SCRIPTDECK_STORAGE_DIR", "/a/storage")
        clean_env.setenv("SCRIPTDECK_HOST", "10.0.0.1")
        clean_env.setenv("SCRIPTDECK_PORT", "8080")
        s = Settings.from_env()
        assert s.db_path == Path("/a/b.db")
        assert s.storage_dir == Path("/a/storage")
        assert s.host == "10.0.0.1"
        assert s.port == 8080


class TestLegacyEnvVars:
    """SCRIPTRUNNER_* names from v0.1-era deployments MUST still work."""

    def test_db_path_legacy(self, clean_env):
        clean_env.setenv("SCRIPTRUNNER_DB_PATH", "/legacy/sd.db")
        assert Settings.from_env().db_path == Path("/legacy/sd.db")

    def test_storage_dir_legacy(self, clean_env):
        clean_env.setenv("SCRIPTRUNNER_STORAGE_DIR", "/legacy/storage")
        assert Settings.from_env().storage_dir == Path("/legacy/storage")

    def test_host_legacy(self, clean_env):
        clean_env.setenv("SCRIPTRUNNER_HOST", "0.0.0.0")
        assert Settings.from_env().host == "0.0.0.0"

    def test_port_legacy(self, clean_env):
        clean_env.setenv("SCRIPTRUNNER_PORT", "8765")
        assert Settings.from_env().port == 8765


class TestCanonicalWins:
    """When both names are set, SCRIPTDECK_* MUST win."""

    def test_port_canonical_wins(self, clean_env):
        clean_env.setenv("SCRIPTDECK_PORT", "11111")
        clean_env.setenv("SCRIPTRUNNER_PORT", "22222")
        assert Settings.from_env().port == 11111

    def test_db_path_canonical_wins(self, clean_env):
        clean_env.setenv("SCRIPTDECK_DB_PATH", "/canonical.db")
        clean_env.setenv("SCRIPTRUNNER_DB_PATH", "/legacy.db")
        assert Settings.from_env().db_path == Path("/canonical.db")

    def test_host_canonical_wins(self, clean_env):
        clean_env.setenv("SCRIPTDECK_HOST", "127.0.0.1")
        clean_env.setenv("SCRIPTRUNNER_HOST", "0.0.0.0")
        assert Settings.from_env().host == "127.0.0.1"


class TestDefaults:
    """No env vars set -> hardcoded defaults from the dataclass."""

    def test_defaults(self, clean_env):
        s = Settings.from_env()
        assert s.db_path == Settings.db_path
        assert s.storage_dir == Settings.storage_dir
        assert s.host == Settings.host
        assert s.port == Settings.port


class TestInvalidPort:
    def test_negative_port_rejected(self, clean_env):
        clean_env.setenv("SCRIPTDECK_PORT", "-1")
        with pytest.raises(ValueError, match="must not be negative"):
            Settings.from_env()

    def test_non_integer_port_rejected(self, clean_env):
        clean_env.setenv("SCRIPTDECK_PORT", "not-a-number")
        with pytest.raises(ValueError, match="must be an integer"):
            Settings.from_env()