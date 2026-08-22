"""Manually install packages into a script's working directory.

Used by the RunView escape hatch: when a run fails with
``ModuleNotFoundError: No module named 'boto3'`` (or its npm equivalent),
the user types the missing package name and the endpoint shells out to
the same tool the runner uses during provisioning (``uv pip install``
for Python, ``npm install`` for Node).

The shell-out is intentionally identical to what the runners do, so an
"install" here is equivalent to one that would have happened
automatically had the package been in the requirements list / package.json
before the run started.

Security note: subprocess invocations use ``asyncio.create_subprocess_exec``
with an arg list (no ``shell=True``), so user input is passed as argv
tokens rather than parsed by a shell. The package-name regex below
additionally rejects anything that wouldn't be a valid pip/npm target.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path


def _python_work_dir(storage_dir: Path, user_id: int, script_id: int) -> Path:
    """Mirror executor.py:87 — user_root / venvs / <script_id>."""
    return (storage_dir / "users" / str(user_id) / "venvs" / str(script_id)).resolve()


def _node_work_dir(storage_dir: Path, user_id: int, script_id: int) -> Path:
    """Mirror executor.py:89 — user_root / node_modules / <script_id>."""
    return (storage_dir / "users" / str(user_id) / "node_modules" / str(script_id)).resolve()


# Reject anything that wouldn't be a valid pip/npm package target.
# Allows scope (``@types/node``), extras (``boto3[crt]``), and version
# specifiers, but blocks whitespace, quotes, backticks, ``$``, etc. that
# would let a user smuggle a shell metacharacter even though exec
# never spawns a shell here.
_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.+:\-/@\[\]^~=<>!*,]+$")


async def _run_capture(cmd: list[str], cwd: Path) -> str:
    """Run a subprocess, return combined stdout+stderr. Raise on non-zero.

    No wall-clock timeout here — the FastAPI handler runs the call inside
    an ``asyncio.timeout`` context so the whole shell-out (including
    pip's resolver) is bounded without per-call timeout plumbing.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await proc.communicate()
    except TimeoutError:
        proc.kill()
        raise RuntimeError(f"install timed out: {' '.join(cmd)}")
    text = out.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(text or f"command failed: {' '.join(cmd)}")
    return text


async def install_packages(
    *,
    language: str,
    user_id: int,
    script_id: int,
    storage_dir: Path,
    packages: list[str],
) -> str:
    """Install ``packages`` into the script's working directory. Returns
    the combined stdout+stderr text from the underlying package manager.

    For Python: runs ``uv pip install --python <venv>/bin/python <pkgs>``
    inside ``<storage>/users/<user>/venvs/<script>`` — the same venv the
    runner later resolves to when executing the script. Creates the venv
    if it doesn't exist yet (mirrors python_runner.provision).

    For Node: runs ``npm install --silent --no-audit --no-fund <pkgs>``
    inside the script's node_modules work_dir. npm creates/updates
    package.json on first run.

    For Bash: raises ValueError — there's no module concept.
    """
    if not packages:
        raise ValueError("no packages provided")
    for p in packages:
        if not _PACKAGE_RE.match(p):
            raise ValueError(f"invalid package name: {p!r}")

    if language == "python":
        work_dir = _python_work_dir(storage_dir, user_id, script_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        venv = work_dir / ".venv"
        if not (venv / "bin" / "python").exists():
            await _run_capture(["uv", "venv", str(venv)], cwd=work_dir)
        return await _run_capture(
            [
                "uv", "pip", "install",
                "--python", str((venv / "bin" / "python").resolve()),
                *packages,
            ],
            cwd=work_dir,
        )
    if language == "node":
        work_dir = _node_work_dir(storage_dir, user_id, script_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        if not (work_dir / "package.json").exists():
            # Initialize so `npm install <pkg>` has something to attach to.
            await _run_capture(
                ["npm", "init", "-y", "--silent"],
                cwd=work_dir,
            )
        return await _run_capture(
            ["npm", "install", "--silent", "--no-audit", "--no-fund", *packages],
            cwd=work_dir,
        )
    raise ValueError(f"install not supported for language={language!r}")


def detect_missing_modules(output: str) -> list[str]:
    """Pull ``ModuleNotFoundError`` / ``Cannot find module`` targets out
    of a run's log so the UI can pre-fill click-to-install chips.
    Best-effort — duplicates and false positives are tolerable; the
    user re-types anything weird.
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"ModuleNotFoundError:\s*No module named\s*'([^']+)'", output):
        # ``boto3`` from ``from boto3.session import Session`` etc.
        name = m.group(1).split(".")[0]
        if name and name not in seen:
            seen.add(name)
            found.append(name)
    for m in re.finditer(r"Cannot find module '([^']+)'", output):
        raw = m.group(1)
        # Scoped packages: keep the scope — ``@types/node`` installs as-is.
        # Unscoped subpaths: keep just the first segment — ``lodash/foo`` -> ``lodash``.
        if raw.startswith("@"):
            parts = raw.split("/")
            name = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        else:
            name = raw.split("/")[0]
        if name and name not in seen:
            seen.add(name)
            found.append(name)
    return found
