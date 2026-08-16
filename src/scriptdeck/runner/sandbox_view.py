"""Sandbox view types + env scrubbing.

The subprocess that runs a script gets a hand-built environment that does NOT
inherit the parent process's os.environ. We build a fresh dict from a static
whitelist plus the script's own decrypted env and any runner-specific
overrides.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Core env vars passed to every sandboxed script. Add to this list only when
# the variable is genuinely safe to expose to arbitrary user code.
WHITELIST: dict[str, str] = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/tmp",  # noqa: S108 — sandbox chroots to a private subtree, /tmp is a tmpfs inside it
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "TMPDIR": "/tmp",  # noqa: S108 — same as HOME; tmpfs is created by the sandbox
}

# Names that must NEVER reach a sandboxed script, even if a user somehow
# injected them via per-script env. These are server-side secrets the runner
# itself relies on; leaking them lets a user script forge tokens or escalate.
BLACKLIST: set[str] = {
    "SCRIPTDECK_JWT_SECRET",
}


def scrub_env(script_env: dict[str, str] | None) -> dict[str, str]:
    """Return a fresh env dict built from WHITELIST + script_env + nothing else.

    The parent's os.environ is intentionally NOT consulted. This is the only
    way to guarantee that secrets like SCRIPTDECK_JWT_SECRET never reach a
    user script.
    """
    merged: dict[str, str] = dict(WHITELIST)
    if script_env:
        for key, value in script_env.items():
            if key in BLACKLIST:
                continue
            merged[key] = value
    return merged


@dataclass(frozen=True)
class BindMount:
    """A single bind-mount entry for the sandbox.

    `host` is the path on the host filesystem. `jail` is the path under the
    user's chroot (e.g. `/usr/bin/python3`). `readonly` enforces MS_RDONLY.
    """
    host: Path
    jail: str
    readonly: bool = True


@dataclass(frozen=True)
class SandboxView:
    """What a LanguageRunner needs visible inside the sandbox."""
    binds: list[BindMount] = field(default_factory=list)
    env_overrides: dict[str, str] = field(default_factory=dict)


def _materialise_chroot(user_root: Path, view: SandboxView) -> None:
    """Create the chroot skeleton under `user_root` for `view`'s binds.

    A bind mount requires its mount point to already exist, and to be of the
    same kind as the source: a directory source needs a directory target, a
    file source needs its parent directory (the file target itself is created
    by the mount at bind time). So for each bind we create the leaf directory
    when the host path is a directory, and otherwise only the parent.

    Also ensures the standard skeleton dirs are present.

    `jail` is expected to be a hardcoded literal supplied by a LanguageRunner,
    never a per-script or request-supplied value. We still refuse any jail path
    that escapes `user_root` (e.g. via `..`), because this function is what
    materialises the isolation boundary: a traversal here would create — and
    later bind-mount over — directories inside another user's subtree.

    Shared by `build_bind_plan` (used by the scheduler pre-flight to verify
    the plan) and `_setup_sandbox` (called in the child via preexec_fn before
    mount(2) and chroot(2)). Keeping the classification in one place prevents
    the two code paths from drifting.
    """
    root_normalised = Path(os.path.normpath(user_root.absolute()))
    for bm in view.binds:
        target = user_root / bm.jail.lstrip("/")
        normalised = Path(os.path.normpath(target.absolute()))
        if normalised != root_normalised and not normalised.is_relative_to(root_normalised):
            raise ValueError(
                f"bind jail path {bm.jail!r} escapes user_root {user_root}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        if bm.host.is_dir():
            target.mkdir(parents=True, exist_ok=True)
    for d in ("bin", "usr", "lib", "etc", "tmp", "scripts", "envs",
              "venvs", "node_modules", "logs"):
        (user_root / d).mkdir(parents=True, exist_ok=True)


def build_bind_plan(user_root: Path, view: SandboxView) -> list[BindMount]:
    """Materialise the chroot skeleton and return the view's binds.

    The shared chroot-creation logic lives in `_materialise_chroot`; this
    wrapper is the public entry point used by the scheduler pre-flight so
    callers can compute the plan without performing the actual mount(2).
    """
    _materialise_chroot(user_root, view)
    return list(view.binds)
