"""Sandbox view types + env scrubbing.

The subprocess that runs a script gets a hand-built environment that does NOT
inherit the parent process's os.environ. We build a fresh dict from a static
whitelist plus the script's own decrypted env and any runner-specific
overrides.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Core env vars passed to every sandboxed script. Add to this list only when
# the variable is genuinely safe to expose to arbitrary user code.
WHITELIST: dict[str, str] = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "TMPDIR": "/tmp",
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
