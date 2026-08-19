from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest


def _sandbox_runnable() -> tuple[bool, str]:
    """Return (can_run, reason). Skip if libc.so.6 missing or no SYS_ADMIN cap."""
    if not os.path.exists("/usr/bin/python3"):
        return False, "python3 not available"
    try:
        import ctypes
        ctypes.CDLL("libc.so.6", use_errno=True)
    except OSError:
        return False, "libc.so.6 not loadable (non-Linux host)"
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("CapEff:"):
                    # CapEff bit 21 = SYS_ADMIN. Nonzero = some caps present.
                    if int(line.split()[1], 16) == 0:
                        return False, "no effective capabilities (needs SYS_ADMIN + SYS_CHROOT)"
                    return True, ""
    except OSError:
        return False, "/proc/self/status unreadable"
    return False, "CapEff not found in /proc/self/status"


_RUNNABLE, _REASON = _sandbox_runnable()

pytestmark = pytest.mark.skipif(
    not _RUNNABLE,
    reason=f"sandbox not runnable: {_REASON}",
)


def _setup_user_storage(root: Path, user_id: int, script_id: int) -> Path:
    user_root = root / "users" / str(user_id)
    (user_root / "scripts" / str(script_id)).mkdir(parents=True)
    (user_root / "envs" / str(script_id)).mkdir(parents=True)
    (user_root / "venvs" / str(script_id) / ".venv").mkdir(parents=True)
    (user_root / "node_modules" / str(script_id)).mkdir(parents=True)
    (user_root / "logs").mkdir(parents=True)
    return user_root


def _populate_other_user(root: Path, other_user_id: int, script_id: int) -> Path:
    other_root = root / "users" / str(other_user_id)
    (other_root / "scripts" / str(script_id)).mkdir(parents=True)
    src = other_root / "scripts" / str(script_id) / "secret.py"
    src.write_text("SECRET = 'bob-password'\n")
    return other_root


@pytest.mark.asyncio
async def test_sandbox_blocks_read_of_other_user(tmp_path: Path):
    user_id = 1
    other_user_id = 2
    _setup_user_storage(tmp_path, user_id, 1)
    _populate_other_user(tmp_path, other_user_id, 7)

    from kindling.runner.sandbox_view import (
        BindMount, SandboxView, scrub_env, build_bind_plan,
    )
    from kindling.runner.sandbox import run_sandboxed

    user_root = tmp_path / "users" / str(user_id)
    src = user_root / "scripts" / "1" / "sniff.py"
    src.write_text(textwrap.dedent("""
        import sys
        try:
            with open('/storage/users/2/scripts/7/secret.py') as f:
                content = f.read()
        except OSError as e:
            print('BLOCKED', e.errno)
            sys.exit(0)
        print('LEAKED', content)
        sys.exit(99)
    """))

    view = SandboxView(binds=[
        BindMount(host=Path("/usr"), jail="/usr"),
        BindMount(host=Path("/lib"), jail="/lib"),
        BindMount(host=Path("/bin"), jail="/bin"),
        BindMount(host=Path("/etc"), jail="/etc"),
    ])
    log_path = user_root / "logs" / "1.log"
    rc = await run_sandboxed(
        user_id=user_id, script_id=1,
        cmd=["/usr/bin/python3", "/scripts/1/sniff.py"],
        env=scrub_env({}),
        user_root=user_root,
        view=view,
        run_id=1,
        log_path=log_path,
    )
    out = log_path.read_text()
    assert rc == 0, f"got: {out}"
    assert "BLOCKED" in out
    assert "LEAKED" not in out


@pytest.mark.asyncio
async def test_sandbox_strips_parent_env_secrets(tmp_path: Path, monkeypatch):
    user_id = 1
    _setup_user_storage(tmp_path, user_id, 1)
    monkeypatch.setenv("KINDLING_JWT_SECRET", "parent-secret")

    from kindling.runner.sandbox_view import SandboxView, scrub_env, BindMount
    from kindling.runner.sandbox import run_sandboxed

    user_root = tmp_path / "users" / str(user_id)
    src = user_root / "scripts" / "1" / "print_env.py"
    src.write_text("import os; print('JWT=', os.environ.get('KINDLING_JWT_SECRET'))")

    view = SandboxView(binds=[
        BindMount(Path("/usr"), "/usr"),
        BindMount(Path("/lib"), "/lib"),
        BindMount(Path("/bin"), "/bin"),
        BindMount(Path("/etc"), "/etc"),
    ])
    log_path = user_root / "logs" / "2.log"
    rc = await run_sandboxed(
        user_id=user_id, script_id=1,
        cmd=["/usr/bin/python3", "/scripts/1/print_env.py"],
        env=scrub_env({}),
        user_root=user_root,
        view=view,
        run_id=2,
        log_path=log_path,
    )
    assert rc == 0
    out = log_path.read_text()
    assert "JWT= None" in out
