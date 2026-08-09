"""Per-script language isolation (ScriptDeck v0.4).

Each script gets its own filesystem area under ``<storage>/scripts/<id>/`` so
two scripts can pin different dependency versions without colliding.

* ``language='python'`` — a per-script ``uv`` virtualenv is provisioned on first
  run; ``requirements.txt`` content is hashed so changes trigger a reinstall.
* ``language='node'`` — ``node_modules/`` is resolved from the per-script dir,
  with ``npm install`` called on first run.
* ``language='bash'`` — no interpreter state to provision, but the runner is
  handed a stripped-down environment (``PATH=/usr/bin:/bin``).

A file lock at ``<storage>/scripts/<id>/.lock`` serialises first-run
provisioning across multiple runner invocations hitting the same script.
The lock is ``fcntl.flock``-based, so it's released automatically when the
holding process exits (even on crash).

The functions here are pure-side-effect; they mutate the filesystem and
update the ``scripts`` row in place with the resolved ``interpreter_path``.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import repository

# Languages the API accepts. Kept here so server-side validation can share it.
SUPPORTED_LANGUAGES = {"python", "node", "bash"}

# Environment for bash scripts. Per the v0.4 spec: clean environment, only a
# minimal PATH so cron-style scripts can't accidentally inherit secrets from
# the runner process.
BASH_CLEAN_ENV = {"PATH": "/usr/bin:/bin"}

# Sentinel: the runner shouldn't try to re-provision a venv once it's been
# hashed and locked; the runner passes the path of the interpreter that
# ``resolve_interpreter`` returned.


@dataclass(frozen=True)
class IsolationResult:
    """What ``provision`` returned: enough info to invoke the script."""

    interpreter_path: Path
    working_dir: Path
    # For python: the directory containing site-packages (used to build PATH).
    # For node: the directory containing node_modules/.
    # For bash: None.
    env_dir: Path | None = None


def script_dir(storage_dir: Path, script_id: int) -> Path:
    """Per-script working directory; created lazily."""
    d = storage_dir / "scripts" / str(script_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def lock_path(storage_dir: Path, script_id: int) -> Path:
    """File used to serialise first-run provisioning."""
    return script_dir(storage_dir, script_id) / ".lock"


@contextlib.contextmanager
def provision_lock(storage_dir: Path, script_id: int):
    """Block on ``<storage>/scripts/<id>/.lock`` so only one process provisions.

    Uses ``fcntl.flock`` so the lock is released even if the process is killed.
    The held file lives next to the script directory and is left behind (cheap;
    its presence has no meaning once unlocked).
    """
    path = lock_path(storage_dir, script_id)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class _ProvisionLock:
    """Standalone lock object so callers can hold a reference across threads.

    ``@contextlib.contextmanager`` produces a fresh generator each call, which
    loses the captured file descriptor and confuses Python 3.13's stricter
    ``_GeneratorContextManager`` (``AttributeError: no attribute 'args'``).
    Using a small class avoids the issue and lets tests pass the SAME lock to
    two threads.
    """

    __slots__ = ("_fd", "_path")

    def __init__(self, path: Path, fd: int) -> None:
        self._path = path
        self._fd = fd

    def __enter__(self) -> _ProvisionLock:
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        fcntl.flock(self._fd, fcntl.LOCK_UN)
        os.close(self._fd)


def open_lock(storage_dir: Path, script_id: int) -> _ProvisionLock:
    """Open a provision lock that can be acquired by multiple threads serially.

    The returned object supports the context-manager protocol via ``__enter__``
    / ``__exit__``. Use this when you need to share the lock between threads;
    use ``provision_lock()`` for the simple blocking-once case.
    """
    path = lock_path(storage_dir, script_id)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o644)
    return _ProvisionLock(path, fd)


def _requirements_hash(requirements_path: Path | None) -> str:
    """Stable fingerprint of the requirements.txt (if any)."""
    if requirements_path is None or not requirements_path.exists():
        return "no-requirements"
    return hashlib.sha256(requirements_path.read_bytes()).hexdigest()


def _marker_path(env_dir: Path, label: str) -> Path:
    return env_dir / f".{label}"


def _read_marker(env_dir: Path, label: str) -> str | None:
    p = _marker_path(env_dir, label)
    return p.read_text().strip() if p.exists() else None


def _write_marker(env_dir: Path, label: str, value: str) -> None:
    _marker_path(env_dir, label).write_text(value)


def _uv() -> str:
    """Locate the ``uv`` binary. Hard error if not installed (the v0.4 spec
    assumes it)."""
    path = shutil.which("uv")
    if not path:
        raise RuntimeError(
            "uv is required for python-script isolation but was not found on PATH"
        )
    return path


def _node() -> str:
    path = shutil.which("node")
    if not path:
        raise RuntimeError(
            "node is required for node-script isolation but was not found on PATH"
        )
    return path


def _bash() -> str:
    path = shutil.which("bash")
    if not path:
        raise RuntimeError("bash is required but was not found on PATH")
    return path


def _python_bin(env_dir: Path) -> Path:
    """Path to the python executable inside the venv."""
    return env_dir / ".venv" / "bin" / "python"


def _provision_python(env_dir: Path, requirements_path: Path | None) -> Path:
    """Create ``<env_dir>/.venv`` and install requirements if provided.

    Idempotent: re-runs without a changed ``requirements.txt`` are a no-op.
    """
    venv = env_dir / ".venv"
    target_hash = _requirements_hash(requirements_path)
    marker = _read_marker(env_dir, "requirements_hash")
    python_in_venv = venv / "bin" / "python"

    if venv.exists() and marker == target_hash and python_in_venv.exists():
        # Already provisioned; nothing to do.
        return python_in_venv

    uv = _uv()
    if not venv.exists():
        subprocess.run(
            [uv, "venv", "--python", "3.13", str(venv)],
            check=True,
            capture_output=True,
        )
    if requirements_path is not None:
        subprocess.run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python_in_venv),
                "-r",
                str(requirements_path),
            ],
            check=True,
            capture_output=True,
        )
    _write_marker(env_dir, "requirements_hash", target_hash)
    return python_in_venv


def _provision_node(env_dir: Path, source_path: Path) -> Path:
    """Run ``npm install`` next to the source if ``package.json`` exists.

    The runner invokes ``node`` directly with the script path; this function
    only ensures dependencies are installed.
    """
    marker = _read_marker(env_dir, "node_provisioned")
    pkg_json = source_path.parent / "package.json"
    if marker == "1" and pkg_json.exists() and (source_path.parent / "node_modules").exists():
        return Path(_node())

    if pkg_json.exists():
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("npm is required for node scripts with package.json")
        subprocess.run(
            [npm, "install", "--silent", "--no-audit", "--no-fund"],
            cwd=str(source_path.parent),
            check=True,
            capture_output=True,
        )
    _write_marker(env_dir, "node_provisioned", "1")
    return Path(_node())


def provision(
    *,
    storage_dir: Path,
    script_id: int,
    language: str,
    source_path: Path,
    requirements_path: Path | None,
    connection: sqlite3.Connection,
) -> IsolationResult:
    """Make sure the per-script env exists, return what the runner needs.

    Updates ``scripts.interpreter_path`` in place once the path is known.
    Re-entrant: callers from concurrent runs all wait on the same lock.
    """
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"unsupported language: {language!r}")

    env_dir = script_dir(storage_dir, script_id)

    with provision_lock(storage_dir, script_id):
        if language == "python":
            interpreter = _provision_python(env_dir, requirements_path)
            result = IsolationResult(
                interpreter_path=interpreter,
                working_dir=env_dir,
                env_dir=env_dir / ".venv",
            )
        elif language == "node":
            interpreter = _provision_node(env_dir, source_path)
            result = IsolationResult(
                interpreter_path=interpreter,
                working_dir=source_path.parent,
                env_dir=source_path.parent,
            )
        else:  # bash
            interpreter = Path(_bash())
            result = IsolationResult(
                interpreter_path=interpreter,
                working_dir=env_dir,
                env_dir=None,
            )

    # Persist the resolved interpreter so the API can surface it without
    # re-provisioning. We store the absolute path as a string.
    connection.execute(
        "UPDATE scripts SET interpreter_path = ? WHERE id = ?",
        (str(result.interpreter_path), script_id),
    )
    connection.commit()
    return result


def resolve_interpreter(
    *,
    storage_dir: Path,
    script_id: int,
    language: str,
    source_path: Path,
    requirements_path: Path | None,
    connection: sqlite3.Connection,
) -> IsolationResult:
    """Fast path: if ``scripts.interpreter_path`` is already populated AND the
    requirements hash matches, skip the heavy provisioning. Otherwise fall
    through to ``provision``."""
    if language == "python":
        env_dir = script_dir(storage_dir, script_id)
        cached_marker = _read_marker(env_dir, "requirements_hash")
        target_hash = _requirements_hash(requirements_path)
        row = repository.get_script(connection, script_id)
        if (
            row
            and row.get("interpreter_path")
            and cached_marker == target_hash
            and _python_bin(env_dir).exists()
        ):
            interp = Path(row["interpreter_path"])
            if interp.exists():
                return IsolationResult(
                    interpreter_path=interp,
                    working_dir=env_dir,
                    env_dir=env_dir / ".venv",
                )

    return provision(
        storage_dir=storage_dir,
        script_id=script_id,
        language=language,
        source_path=source_path,
        requirements_path=requirements_path,
        connection=connection,
    )


def runner_env(
    *,
    language: str,
    isolation: IsolationResult,
    script_row: dict,
) -> dict[str, str]:
    """Environment dict handed to ``subprocess.run`` when executing the script.

    For python, the venv's bin dir is prepended to PATH so spawned subprocesses
    inherit the same interpreter. For node, the per-script dir (with
    node_modules) is prepended so ``require()`` resolves locally. For bash, we
    use the clean env from the spec.
    """
    if language == "python":
        if isolation.env_dir is None:
            raise RuntimeError("python isolation result missing env_dir")
        env = os.environ.copy()
        venv_bin = str(isolation.env_dir / "bin")
        env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
        env["VIRTUAL_ENV"] = str(isolation.env_dir)
        # Remove PYTHONHOME so the venv isn't shadowed.
        env.pop("PYTHONHOME", None)
        return env
    if language == "node":
        if isolation.env_dir is None:
            raise RuntimeError("node isolation result missing env_dir")
        env = os.environ.copy()
        env["NODE_PATH"] = str(isolation.env_dir)
        return env
    # bash: clean, no inherited env.
    return dict(BASH_CLEAN_ENV)


def upload_script_files(
    *,
    storage_dir: Path,
    script_id: int,
    name: str,
    source: str,
    requirements: str | None,
) -> tuple[Path, Path | None]:
    """Write the uploaded source (and optional requirements.txt) to disk.

    Returns ``(source_path, requirements_path)`` so the caller can pass them
    to ``repository.create_script`` and ``isolation.provision``.
    """
    if not source:
        raise ValueError("source is required")
    if not name:
        raise ValueError("name is required")

    base = script_dir(storage_dir, script_id)
    source_path = base / "source.py"  # extension is cosmetic; runner doesn't care
    source_path.write_text(source)

    req_path: Path | None = None
    if requirements:
        req_path = base / "requirements.txt"
        req_path.write_text(requirements)
    return source_path, req_path


# Used by tests + the doctor command to enumerate provisioned envs.
def list_envs(storage_dir: Path) -> list[Path]:
    root = storage_dir / "scripts"
    if not root.exists():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


# Used by the doctor command to print interpreter paths without touching the DB.
def env_summary(env_dir: Path) -> dict[str, str]:
    info: dict[str, str] = {"id": env_dir.name}
    marker = _marker_path(env_dir, "requirements_hash")
    if marker.exists():
        info["requirements_hash"] = marker.read_text().strip()[:12]
    venv_python = _python_bin(env_dir)
    if venv_python.exists():
        info["interpreter"] = str(venv_python)
    return info


__all__ = [
    "SUPPORTED_LANGUAGES",
    "BASH_CLEAN_ENV",
    "IsolationResult",
    "script_dir",
    "lock_path",
    "provision_lock",
    "open_lock",
    "provision",
    "resolve_interpreter",
    "runner_env",
    "upload_script_files",
    "list_envs",
    "env_summary",
]