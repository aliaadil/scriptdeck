from __future__ import annotations

from pathlib import Path

import pytest

from kindling.runner.sandbox_view import (
    BindMount,
    SandboxView,
    build_bind_plan,
    scrub_env,
    WHITELIST,
)


def test_scrub_env_strips_blacklisted_keys():
    out = scrub_env({"KINDLING_JWT_SECRET": "leaky", "PYTHONPATH": "/foo"})
    assert "KINDLING_JWT_SECRET" not in out
    assert out["PYTHONPATH"] == "/foo"


def test_scrub_env_ignores_parent_os_environ(monkeypatch):
    monkeypatch.setenv("KINDLING_JWT_SECRET", "parent-secret")
    out = scrub_env({})
    assert "KINDLING_JWT_SECRET" not in out


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


def test_build_bind_plan_resolves_jail_paths(tmp_path):
    user_root = tmp_path / "user1"
    view = SandboxView(binds=[
        BindMount(host=Path("/usr/bin/python3"), jail="/usr/bin/python3"),
        BindMount(host=Path("/usr/lib"), jail="/usr/lib"),
    ])
    plan = build_bind_plan(user_root, view)
    assert plan[0].host == Path("/usr/bin/python3")
    assert plan[0].jail == "/usr/bin/python3"
    assert (user_root / "usr/bin/python3").parent.exists()
    assert (user_root / "usr/lib").exists()


def test_build_bind_plan_creates_chroot_skeleton(tmp_path):
    user_root = tmp_path / "user2"
    view = SandboxView(binds=[
        BindMount(host=Path("/bin"), jail="/bin"),
        BindMount(host=Path("/usr"), jail="/usr"),
        BindMount(host=Path("/lib"), jail="/lib"),
        BindMount(host=Path("/etc"), jail="/etc"),
    ])
    build_bind_plan(user_root, view)
    for d in ("bin", "usr", "lib", "etc", "tmp"):
        assert (user_root / d).is_dir()


def test_build_bind_plan_rejects_jail_path_escaping_user_root(tmp_path):
    user_root = tmp_path / "users" / "1"
    view = SandboxView(binds=[
        BindMount(host=Path("/usr/lib"), jail="/../2/stolen"),
    ])
    with pytest.raises(ValueError, match="escapes user_root"):
        build_bind_plan(user_root, view)
    assert not (tmp_path / "users" / "2").exists()
