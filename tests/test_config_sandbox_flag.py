from __future__ import annotations

from kindling.config import Settings


def test_sandbox_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("KINDLING_SANDBOX_ENABLED", raising=False)
    assert Settings().sandbox_enabled is False


def test_sandbox_enabled_parses_true(monkeypatch):
    monkeypatch.setenv("KINDLING_SANDBOX_ENABLED", "true")
    assert Settings().sandbox_enabled is True


def test_sandbox_enabled_parses_one(monkeypatch):
    monkeypatch.setenv("KINDLING_SANDBOX_ENABLED", "1")
    assert Settings().sandbox_enabled is True
