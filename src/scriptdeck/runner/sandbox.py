"""Run a subprocess inside a private mount namespace chrooted to a per-user
subtree.

The parent process retains full host filesystem access. The child process
(preexec_fn) unshare(CLONE_NEWNS), bind-mounts the user's data + readonly
host tools, mounts tmpfs at /tmp, then chroot and exec. The child cannot
see /storage/users/<other> because that path is not mounted anywhere.
"""
from __future__ import annotations

import asyncio
import ctypes
import errno
import os
from pathlib import Path

from scriptdeck.runner.sandbox_view import (
    SandboxView,
    _materialise_chroot,
)

# Linux mount(2) flags. Hardcoded — these are stable across kernel versions.
CLONE_NEWNS = 0x00020000
MS_BIND = 0x1000
MS_RDONLY = 0x1
MS_REC = 0x4000
MS_PRIVATE = 0x40000

_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_unshare = _libc.unshare
_unshare.argtypes = [ctypes.c_int]
_unshare.restype = ctypes.c_int
_mount = _libc.mount
_mount.argtypes = [
    ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p,
    ctypes.c_ulong, ctypes.c_void_p,
]
_mount.restype = ctypes.c_int


def _setup_sandbox(user_root: Path, view: SandboxView, tmp_size: str) -> None:
    """Runs in child after fork, before exec.

    Materialises the chroot skeleton (via the shared helper), enters a private
    mount namespace, bind-mounts each entry from `view`, mounts tmpfs at /tmp,
    then chroot.
    """
    if _unshare(CLONE_NEWNS) != 0:
        e = ctypes.get_errno()
        raise OSError(errno.errorcode.get(e, str(e)), "unshare(CLONE_NEWNS) failed")
    # Don't propagate our mounts to the host mount namespace.
    if _mount(None, b"/", None, MS_REC | MS_PRIVATE, None) != 0:
        e = ctypes.get_errno()
        raise OSError(errno.errorcode.get(e, str(e)), "mount MS_PRIVATE failed on /")

    _materialise_chroot(user_root, view)

    for bm in view.binds:
        target = user_root / bm.jail.lstrip("/")
        flags = MS_BIND | (MS_RDONLY if bm.readonly else 0)
        rc = _mount(
            str(bm.host).encode(), str(target).encode(),
            None, ctypes.c_ulong(flags), None,
        )
        if rc != 0:
            e = ctypes.get_errno()
            raise OSError(errno.errorcode.get(e, str(e)), f"mount({bm.host} -> {target}) failed")

    tmp_target = user_root / "tmp"
    rc = _mount(
        b"tmpfs", str(tmp_target).encode(),
        b"tmpfs", 0, f"size={tmp_size},mode=1777".encode(),
    )
    if rc != 0:
        e = ctypes.get_errno()
        raise OSError(errno.errorcode.get(e, str(e)), "mount tmpfs failed")

    os.chroot(user_root)
    os.chdir("/")


async def run_sandboxed(
    *,
    user_id: int,
    script_id: int,
    cmd: list[str],
    env: dict[str, str],
    user_root: Path,
    view: SandboxView,
    run_id: int,
    log_path: Path,
    tmp_size: str = "64M",
) -> int:
    """Run `cmd` inside the user's sandbox. Returns exit code. Streams
    stdout/stderr line-by-line to `log_path`."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_fh = log_path.open("wb")

    import subprocess

    def _popen() -> "subprocess.Popen[bytes]":
        return subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(user_root / "venvs" / str(script_id)),
            preexec_fn=lambda: _setup_sandbox(user_root, view, tmp_size),
        )

    loop = asyncio.get_running_loop()
    proc = await loop.run_in_executor(None, _popen)
    assert proc.stdout is not None

    def _readline() -> bytes:
        return proc.stdout.readline()

    try:
        while True:
            line = await loop.run_in_executor(None, _readline)
            if not line:
                break
            await loop.run_in_executor(None, log_fh.write, line)
            await loop.run_in_executor(None, log_fh.flush)
    finally:
        await loop.run_in_executor(None, log_fh.close)

    return await loop.run_in_executor(None, proc.wait)
