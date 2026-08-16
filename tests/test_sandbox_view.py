from __future__ import annotations

from pathlib import Path

from scriptdeck.runner.sandbox_view import (
    BindMount,
    SandboxView,
    scrub_env,
    WHITELIST,
)


def test_scrub_env_strips_blacklisted_keys():
    out = scrub_env({"SCRIPTDECK_JWT_SECRET": "leaky", "PYTHONPATH": "/foo"})
    assert "SCRIPTDECK_JWT_SECRET" not in out
    assert out["PYTHONPATH"] == "/foo"


def test_scrub_env_ignores_parent_os_environ(monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_JWT_SECRET", "parent-secret")
    out = scrub_env({})
    assert "SCRIPTDECK_JWT_SECRET" not in out


def test_scrub_env_keeps_whitelist():
    out = scrub_env({})
    for key in WHITELIST:
        assert key in out


def test_scrub_env_merges_script_env():
    out = scrub_env({"MY_API_KEY": "abc"})
    assert out["MY_API_KEY"] == "abc"
    assert "PATH" in out


def test_scrub_env_script_overrides_whitelist():
    out = scrub_env({"PATH": "/custom/bin"})
    assert out["PATH"] == "/custom/bin"


def test_sandbox_view_empty():
    v = SandboxView(binds=[], env_overrides={})
    assert v.binds == []
    assert v.env_overrides == {}


def test_bind_mount_construction():
    bm = BindMount(host=Path("/usr/bin/python3"), jail="/usr/bin/python3", readonly=True)
    assert bm.host == Path("/usr/bin/python3")
    assert bm.readonly is True
