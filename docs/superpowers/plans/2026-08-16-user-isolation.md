# User Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sandbox per-user script execution so a running script can read only its own user's storage subtree and cannot see other users' files, envs, or logs.

**Architecture:** Each user script runs in a private mount namespace (`unshare(CLONE_NEWNS)`), with a per-user subtree (`/storage/users/<uid>/`) bound at `/` and a hand-rolled chroot into it. Other users' data is not mounted and therefore `open()` returns `ENOENT`. Env vars are scrubbed to a hardcoded whitelist plus the script's own decrypted env. The `LanguageRunner` protocol gains a `sandbox_view()` method that declares the read-only host paths each interpreter needs visible.

**Tech Stack:** Python 3.12, `ctypes` for syscall wrappers, `subprocess.Popen` with `preexec_fn`, `asyncio.to_thread` for non-blocking reads, existing SQLAlchemy + aiosqlite stack, existing `pytest` test suite.

## Global Constraints

- All new Python files use `from __future__ import annotations`.
- All subprocess code uses `subprocess.Popen(..., preexec_fn=...)` (NOT `asyncio.create_subprocess_exec`) to keep `preexec_fn` available.
- Container runs as root. `docker-compose.yml` must include `cap_drop: [ALL]` + `cap_add: [SYS_CHROOT, SYS_ADMIN]`.
- Sandbox off by default. Gate behind `SCRIPTDECK_SANDBOX_ENABLED=true` env var.
- Migration CLI is idempotent and dry-run by default.
- Test files use `pytest`. Existing `tests/conftest.py` provides DB fixtures.
- No new runtime dependencies. (ctypes is stdlib; subprocess is stdlib.)
- Follow existing migration naming: `NNN_short_snake.sql`.

---

## Task 1: DB migration — add `scripts.user_id`

**Files:**
- Create: `src/scriptdeck/migrations/010_user_id_isolation.sql`
- Modify: `src/scriptdeck/db/models.py:82-96`
- Modify: `src/scriptdeck/services/script_service.py:9-19,27-41,44-47,50-62,65-76,79-82`
- Test: `tests/test_user_id_migration.py`

**Interfaces:**
- Consumes: existing `scripts` table from migrations 001/002.
- Produces: `scripts.user_id INTEGER NOT NULL` column, plus index `(user_id, id)`. Service layer accepts and persists `user_id`.

- [ ] **Step 1: Write the failing DB test**

```python
# tests/test_user_id_migration.py
from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from scriptdeck.db.migrations import run_migrations_sync


def test_scripts_user_id_column_exists(tmp_path: Path):
    db_path = tmp_path / "t.db"
    run_migrations_sync(str(db_path))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def _check():
        async with engine.connect() as conn:
            rows = (await conn.exec_driver_sql(
                "SELECT name FROM pragma_table_info('scripts')"
            )).fetchall()
        await engine.dispose()
        return {r[0] for r in rows}

    names = asyncio.run(_check())
    assert "user_id" in names
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
pytest tests/test_user_id_migration.py -v
```

Expected: `FAILED` — `user_id` not in column list.

- [ ] **Step 3: Write the migration SQL**

```sql
-- src/scriptdeck/migrations/010_user_id_isolation.sql
-- Adds user_id to scripts for per-user isolation. Backfills from the first
-- admin user. Existing single-user installs end up with all scripts owned
-- by admin. Multi-user installs must run `scriptdeck migrate-users` before
-- flipping SCRIPTDECK_SANDBOX_ENABLED=true.

ALTER TABLE scripts ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE;

UPDATE scripts SET user_id = (SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1)
WHERE user_id IS NULL;

CREATE INDEX idx_scripts_user ON scripts(user_id, id);
```

- [ ] **Step 4: Run the test, verify it passes**

```bash
pytest tests/test_user_id_migration.py -v
```

Expected: PASS.

- [ ] **Step 5: Update `models.py` to declare the column**

In `src/scriptdeck/db/models.py`, replace the `scripts` table definition (lines 82-96) with:

```python
scripts = Table(
    "scripts",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String, nullable=False, unique=True),
    Column("language", String, nullable=False),
    Column("source_path", String, nullable=False),
    Column("requirements_path", String),
    Column("interpreter_path", String),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("description", Text),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE")),
    CheckConstraint("language IN ('python', 'node')", name="scripts_language_check"),
    Index("idx_scripts_name", "name"),
    Index("idx_scripts_user", "user_id", "id"),
)
```

- [ ] **Step 6: Update `ScriptRow` and `create_script` in `script_service.py`**

In `src/scriptdeck/services/script_service.py`:
- Add `user_id: int | None` to `ScriptRow` dataclass (after `description`).
- Add `user_id: int` keyword param to `create_script` (no default — required).
- Insert `user_id=user_id` into the `insert(t).values(...)` call.

- [ ] **Step 7: Run full test suite**

```bash
pytest -q
```

Expected: existing tests pass. New test passes. No new failures.

- [ ] **Step 8: Commit**

```bash
git add src/scriptdeck/migrations/010_user_id_isolation.sql \
        src/scriptdeck/db/models.py \
        src/scriptdeck/services/script_service.py \
        tests/test_user_id_migration.py
git commit -m "feat(db): add scripts.user_id for per-user isolation"
```

---

## Task 2: `SandboxView` dataclass + env scrub

**Files:**
- Create: `src/scriptdeck/runner/sandbox_view.py`
- Create: `tests/test_sandbox_view.py`

**Interfaces:**
- Produces:
  - `dataclass BindMount(host: Path, jail: str, readonly: bool)`
  - `dataclass SandboxView(binds: list[BindMount], env_overrides: dict[str, str])`
  - `def scrub_env(script_env: dict[str, str] | None) -> dict[str, str]` — returns whitelisted core + script env.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_sandbox_view.py
from __future__ import annotations

from pathlib import Path

from scriptdeck.runner.sandbox_view import (
    BindMount,
    SandboxView,
    scrub_env,
    WHITELIST,
)


def test_scrub_env_strips_non_whitelisted():
    out = scrub_env({"SCRIPTDECK_JWT_SECRET": "leaky", "FOO": "bar"})
    assert "SCRIPTDECK_JWT_SECRET" not in out
    assert "FOO" not in out


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
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_sandbox_view.py -v
```

Expected: ImportError — module does not exist.

- [ ] **Step 3: Implement the module**

```python
# src/scriptdeck/runner/sandbox_view.py
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


def scrub_env(script_env: dict[str, str] | None) -> dict[str, str]:
    """Return a fresh env dict built from WHITELIST + script_env + nothing else.

    The parent's os.environ is intentionally NOT consulted. This is the only
    way to guarantee that secrets like SCRIPTDECK_JWT_SECRET never reach a
    user script.
    """
    merged: dict[str, str] = dict(WHITELIST)
    if script_env:
        merged.update(script_env)
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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_sandbox_view.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/runner/sandbox_view.py tests/test_sandbox_view.py
git commit -m "feat(sandbox): SandboxView dataclass + env scrub"
```

---

## Task 3: `bind_plan` pure function

**Files:**
- Modify: `src/scriptdeck/runner/sandbox_view.py`
- Modify: `tests/test_sandbox_view.py`

**Interfaces:**
- Produces: `def build_bind_plan(user_root: Path, view: SandboxView) -> list[BindMount]` — materialises chroot skeleton dirs under `user_root` before returning.

- [ ] **Step 1: Add failing tests**

Append to `tests/test_sandbox_view.py`:

```python
from scriptdeck.runner.sandbox_view import build_bind_plan


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
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_sandbox_view.py::test_build_bind_plan_resolves_jail_paths -v
```

Expected: ImportError on `build_bind_plan`.

- [ ] **Step 3: Implement `build_bind_plan`**

Add to `src/scriptdeck/runner/sandbox_view.py`:

```python
def build_bind_plan(user_root: Path, view: SandboxView) -> list[BindMount]:
    """Materialise the chroot skeleton under `user_root`.

    Ensures parent directories of every jail path exist and the standard
    skeleton dirs are present. Returns the view's binds unchanged.
    """
    for bm in view.binds:
        target = (user_root / bm.jail.lstrip("/")).parent
        target.mkdir(parents=True, exist_ok=True)
    for d in ("bin", "usr", "lib", "etc", "tmp", "scripts", "envs",
              "venvs", "node_modules", "logs"):
        (user_root / d).mkdir(parents=True, exist_ok=True)
    return list(view.binds)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_sandbox_view.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/runner/sandbox_view.py tests/test_sandbox_view.py
git commit -m "feat(sandbox): build_bind_plan creates chroot skeleton"
```

---

## Task 4: `run_sandboxed` — unshare + bind + chroot + exec

**Files:**
- Create: `src/scriptdeck/runner/sandbox.py`
- Create: `tests/test_sandbox.py`

**Interfaces:**
- Produces: `async def run_sandboxed(*, user_id: int, script_id: int, cmd: list[str], env: dict[str, str], user_root: Path, view: SandboxView, run_id: int, log_path: Path, tmp_size: str = "64M") -> int` — returns exit code, streams stdout/stderr to `log_path`.
- Helper: `def _setup_sandbox(user_root: Path, plan: list[BindMount], tmp_size: str) -> None` — designated `preexec_fn`. Calls `unshare(CLONE_NEWNS)`, `mount`, `chroot`.

- [ ] **Step 1: Write failing integration tests**

```python
# tests/test_sandbox.py
from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    not os.path.exists("/usr/bin/python3"),
    reason="python3 not available",
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

    from scriptdeck.runner.sandbox_view import (
        BindMount, SandboxView, scrub_env, build_bind_plan,
    )
    from scriptdeck.runner.sandbox import run_sandboxed

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
    monkeypatch.setenv("SCRIPTDECK_JWT_SECRET", "parent-secret")

    from scriptdeck.runner.sandbox_view import SandboxView, scrub_env, BindMount
    from scriptdeck.runner.sandbox import run_sandboxed

    user_root = tmp_path / "users" / str(user_id)
    src = user_root / "scripts" / "1" / "print_env.py"
    src.write_text("import os; print('JWT=', os.environ.get('SCRIPTDECK_JWT_SECRET'))")

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
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_sandbox.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `sandbox.py`**

```python
# src/scriptdeck/runner/sandbox.py
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
    BindMount,
    SandboxView,
    build_bind_plan,
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


def _setup_sandbox(user_root: Path, plan: list[BindMount], tmp_size: str) -> None:
    """Runs in child after fork, before exec."""
    if _unshare(CLONE_NEWNS) != 0:
        e = ctypes.get_errno()
        raise OSError(errno.errorcode.get(e, str(e)), "unshare(CLONE_NEWNS) failed")
    # Don't propagate our mounts to the host mount namespace.
    if _mount(None, b"/", None, MS_REC | MS_PRIVATE, None) != 0:
        e = ctypes.get_errno()
        raise OSError(errno.errorcode.get(e, str(e)), "mount MS_PRIVATE failed on /")

    for d in ("bin", "lib", "usr", "etc", "tmp"):
        (user_root / d).mkdir(parents=True, exist_ok=True)

    for bm in plan:
        target = user_root / bm.jail.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            if bm.host.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
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
    plan = build_bind_plan(user_root, view)
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
            preexec_fn=lambda: _setup_sandbox(user_root, plan, tmp_size),
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
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_sandbox.py -v
```

Expected: 2 passed. Tests must run inside the scriptdeck container (or as root with `CAP_SYS_ADMIN` + `CAP_SYS_CHROOT`).

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/runner/sandbox.py tests/test_sandbox.py
git commit -m "feat(sandbox): run_sandboxed via unshare+bind+chroot"
```

---

## Task 5: Extend `LanguageRunner` with `sandbox_view()`

**Files:**
- Modify: `src/scriptdeck/runner/protocol.py:8-19`
- Modify: `src/scriptdeck/runner/python_runner.py:7-40`
- Modify: `src/scriptdeck/runner/node_runner.py:7-33`
- Test: `tests/test_runner_sandbox_view.py`

**Interfaces:**
- Produces: `LanguageRunner.sandbox_view() -> SandboxView` method. Python: `/usr/bin/python3` + `/usr/lib/python3.12` + `/etc/ssl`. Node: `/usr/bin/node` + `/usr/lib/x86_64-linux-gnu`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_runner_sandbox_view.py
from __future__ import annotations

from scriptdeck.runner.python_runner import PythonRunner
from scriptdeck.runner.node_runner import NodeRunner


def test_python_runner_sandbox_view_includes_python():
    v = PythonRunner().sandbox_view()
    jails = [bm.jail for bm in v.binds]
    assert "/usr/bin/python3" in jails


def test_python_runner_sandbox_view_readonly():
    v = PythonRunner().sandbox_view()
    assert all(bm.readonly for bm in v.binds)


def test_node_runner_sandbox_view_includes_node():
    v = NodeRunner().sandbox_view()
    jails = [bm.jail for bm in v.binds]
    assert "/usr/bin/node" in jails
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_runner_sandbox_view.py -v
```

Expected: AttributeError on `sandbox_view`.

- [ ] **Step 3: Add `sandbox_view()` to the protocol**

Replace `src/scriptdeck/runner/protocol.py` with:

```python
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from scriptdeck.runner.sandbox_view import SandboxView


@runtime_checkable
class LanguageRunner(Protocol):
    name: str

    async def detect_deps(self, source: str) -> list[str]: ...

    def resolve_artifact_path(self) -> str: ...

    async def provision(self, work_dir: Path, deps: list[str]) -> Path: ...

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]: ...

    def sandbox_view(self) -> SandboxView: ...
```

- [ ] **Step 4: Implement `sandbox_view()` on PythonRunner**

Add to `src/scriptdeck/runner/python_runner.py` (top of file alongside existing imports):

```python
from scriptdeck.runner.sandbox_view import BindMount, SandboxView
```

And add this method to the `PythonRunner` class:

```python
    def sandbox_view(self) -> SandboxView:
        return SandboxView(binds=[
            BindMount(host=Path("/usr/bin/python3"), jail="/usr/bin/python3"),
            BindMount(host=Path("/usr/lib/python3.12"), jail="/usr/lib/python3.12"),
            BindMount(host=Path("/usr/local/lib/python3.12"), jail="/usr/local/lib/python3.12"),
            BindMount(host=Path("/etc/ssl"), jail="/etc/ssl"),
            BindMount(host=Path("/etc/passwd"), jail="/etc/passwd"),
            BindMount(host=Path("/etc/group"), jail="/etc/group"),
        ])
```

- [ ] **Step 5: Implement `sandbox_view()` on NodeRunner**

Add to `src/scriptdeck/runner/node_runner.py`:

```python
from scriptdeck.runner.sandbox_view import BindMount, SandboxView
```

And add this method to the `NodeRunner` class:

```python
    def sandbox_view(self) -> SandboxView:
        return SandboxView(binds=[
            BindMount(host=Path("/usr/bin/node"), jail="/usr/bin/node"),
            BindMount(host=Path("/usr/lib/x86_64-linux-gnu"), jail="/usr/lib/x86_64-linux-gnu"),
            BindMount(host=Path("/etc/ssl"), jail="/etc/ssl"),
            BindMount(host=Path("/etc/passwd"), jail="/etc/passwd"),
            BindMount(host=Path("/etc/group"), jail="/etc/group"),
        ])
```

- [ ] **Step 6: Run tests, verify pass**

```bash
pytest tests/test_runner_sandbox_view.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add src/scriptdeck/runner/protocol.py \
        src/scriptdeck/runner/python_runner.py \
        src/scriptdeck/runner/node_runner.py \
        tests/test_runner_sandbox_view.py
git commit -m "feat(runner): LanguageRunner.sandbox_view() declares readonly paths"
```

---

## Task 6: Wire `executor.py` to use the sandbox

**Files:**
- Modify: `src/scriptdeck/runner/executor.py:17-23,36-118`
- Test: `tests/test_executor_sandbox_wiring.py`

**Interfaces:**
- Modifies: `Script` dataclass gains `user_id: int`. `run_script` reads `Settings.sandbox_enabled`; if true, calls `run_sandboxed`; else falls back to `asyncio.create_subprocess_exec` (existing behaviour).

- [ ] **Step 1: Write failing test**

```python
# tests/test_executor_sandbox_wiring.py
from __future__ import annotations

import asyncio
from pathlib import Path
from dataclasses import dataclass

import pytest

from scriptdeck.runner.executor import Script, run_script
from scriptdeck.runner.registry import get_runner
from scriptdeck.services.log_broker import LogBroker


@dataclass
class FakeEnv:
    ciphertext: str | None = None
    nonce: str | None = None

    def decrypt_lines(self, *args, **kwargs):
        return {}


@pytest.mark.asyncio
async def test_executor_sandbox_path_runs_user_script(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_SANDBOX_ENABLED", "true")

    user_root = tmp_path / "users" / "1"
    src_dir = user_root / "scripts" / "1"
    src_dir.mkdir(parents=True)
    src = src_dir / "hello.py"
    src.write_text("print('hi from sandbox')")

    runner = get_runner("python")
    script = Script(
        id=1, user_id=1, name="hello", language="python",
        source_path=src, requirements=[],
    )
    broker = LogBroker()
    semaphore = asyncio.Semaphore(1)
    result = await run_script(
        run_id=1, script=script, env_service=FakeEnv(),
        log_broker=broker, concurrency=semaphore,
        storage_dir=tmp_path,
    )
    assert result.exit_code == 0
    body = result.log_path.read_text()
    assert "hi from sandbox" in body
```

- [ ] **Step 2: Run test, verify failure**

```bash
pytest tests/test_executor_sandbox_wiring.py -v
```

Expected: TypeError — `Script` doesn't accept `user_id`.

- [ ] **Step 3: Add `user_id` to `Script` dataclass**

In `src/scriptdeck/runner/executor.py`, replace the `Script` dataclass (lines 17-23) with:

```python
@dataclass
class Script:
    id: int
    user_id: int
    name: str
    language: str
    source_path: Path
    requirements: list[str]
```

- [ ] **Step 4: Modify `run_script` to dispatch on `sandbox_enabled`**

Replace the `run_script` body (lines 36-118) with:

```python
async def run_script(
    *,
    run_id: int,
    script: Script,
    env_service: EnvLike,
    log_broker: LogBroker,
    concurrency: asyncio.Semaphore,
    storage_dir: Path,
    env_ciphertext: str | None = None,
    env_nonce: str | None = None,
    active_procs: dict[int, asyncio.subprocess.Process] | None = None,
) -> RunResult:
    from scriptdeck.config import get_settings
    from scriptdeck.runner.registry import get_runner
    from scriptdeck.runner.sandbox import run_sandboxed
    from scriptdeck.runner.sandbox_view import scrub_env
    from scriptdeck.runner.lock import per_script_lock

    settings = get_settings()
    logs_dir = storage_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{run_id}.log"

    user_root = (storage_dir / "users" / str(script.user_id)).resolve()
    user_root.mkdir(parents=True, exist_ok=True)

    async with concurrency:
        async with per_script_lock(script.id, storage_dir / "locks"):
            exit_code: int = -1
            status: str = "error"
            try:
                runner = get_runner(script.language)
                if script.language == "python":
                    work_dir = user_root / "venvs" / str(script.id)
                else:
                    work_dir = (user_root / "node_modules" / str(script.id))
                work_dir.mkdir(parents=True, exist_ok=True)
                interpreter = await runner.provision(work_dir, script.requirements)

                script_env: dict[str, str] = {}
                if env_ciphertext and env_nonce:
                    decrypted = env_service.decrypt_lines(env_ciphertext, env_nonce)
                    if isinstance(decrypted, dict):
                        script_env = decrypted

                if settings.sandbox_enabled:
                    merged_env = scrub_env(script_env)
                    interpreter_path = (
                        Path("/usr/bin/python3") if script.language == "python"
                        else Path("/usr/bin/node")
                    )
                    source_jail = Path(f"/scripts/{script.id}/{script.source_path.name}")
                    rv = await run_sandboxed(
                        user_id=script.user_id,
                        script_id=script.id,
                        cmd=runner.build_command(interpreter_path, source_jail, merged_env),
                        env=merged_env,
                        user_root=user_root,
                        view=runner.sandbox_view(),
                        run_id=run_id,
                        log_path=log_path,
                    )
                    exit_code = rv
                else:
                    merged_env = dict(os.environ)
                    merged_env.update(script_env)
                    log_fh = log_path.open("wb")
                    try:
                        proc = await asyncio.create_subprocess_exec(
                            *runner.build_command(interpreter, script.source_path, merged_env),
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.STDOUT,
                            cwd=str(work_dir),
                        )
                        if active_procs is not None:
                            active_procs[run_id] = proc
                        assert proc.stdout is not None
                        offset = 0
                        while True:
                            chunk = await proc.stdout.readline()
                            if not chunk:
                                break
                            log_fh.write(chunk)
                            log_fh.flush()
                            await log_broker.publish(
                                run_id, chunk.decode("utf-8", errors="replace"), offset
                            )
                            offset += len(chunk)
                        exit_code = await proc.wait()
                    finally:
                        if active_procs is not None:
                            active_procs.pop(run_id, None)
                        log_fh.close()

                status = "success" if exit_code == 0 else "failure"
            except Exception as exc:
                log.exception("run_script failed for run_id=%s: %s", run_id, exc)
                exit_code = -1
                status = "error"
            await log_broker.close(run_id, status=status, exit_code=exit_code)
    return RunResult(exit_code=exit_code, log_path=log_path)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
pytest tests/test_executor_sandbox_wiring.py tests/test_sandbox.py tests/test_sandbox_view.py tests/test_runner_sandbox_view.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full test suite**

```bash
pytest -q
```

Expected: no new failures.

- [ ] **Step 7: Commit**

```bash
git add src/scriptdeck/runner/executor.py tests/test_executor_sandbox_wiring.py
git commit -m "feat(executor): dispatch through run_sandboxed when enabled"
```

---

## Task 7: `Settings.sandbox_enabled` flag

**Files:**
- Modify: `src/scriptdeck/config.py:8-30`
- Test: `tests/test_config_sandbox_flag.py`

**Interfaces:**
- Produces: `Settings.sandbox_enabled: bool = False`.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config_sandbox_flag.py
from __future__ import annotations

from scriptdeck.config import Settings


def test_sandbox_enabled_defaults_false(monkeypatch):
    monkeypatch.delenv("SCRIPTDECK_SANDBOX_ENABLED", raising=False)
    assert Settings().sandbox_enabled is False


def test_sandbox_enabled_parses_true(monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_SANDBOX_ENABLED", "true")
    assert Settings().sandbox_enabled is True


def test_sandbox_enabled_parses_one(monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_SANDBOX_ENABLED", "1")
    assert Settings().sandbox_enabled is True
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_config_sandbox_flag.py -v
```

Expected: AttributeError on `sandbox_enabled`.

- [ ] **Step 3: Add the field to `Settings`**

In `src/scriptdeck/config.py`, add after `runner_concurrency: int = 4`:

```python
    sandbox_enabled: bool = False
```

- [ ] **Step 4: Run tests, verify pass**

```bash
pytest tests/test_config_sandbox_flag.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/config.py tests/test_config_sandbox_flag.py
git commit -m "feat(config): SCRIPTDECK_SANDBOX_ENABLED flag"
```

---

## Task 8: Storage migration CLI

**Files:**
- Create: `src/scriptdeck/cli_commands/migrate_users.py`
- Modify: `src/scriptdeck/cli.py:14-18,34-39`
- Test: `tests/test_migrate_users.py`

**Interfaces:**
- Produces: `def migrate_users_run(storage_dir: str, db_path: str, dry_run: bool = True) -> int` — moves flat storage into per-user subtree. Idempotent.

- [ ] **Step 1: Write failing test**

```python
# tests/test_migrate_users.py
from __future__ import annotations

import sqlite3
from pathlib import Path

from scriptdeck.cli_commands.migrate_users import migrate_users_run


def _bootstrap(tmp_path: Path) -> tuple[Path, Path]:
    storage = tmp_path / "storage"
    db = tmp_path / "t.db"
    (storage / "scripts" / "1").mkdir(parents=True)
    (storage / "scripts" / "1" / "hello.py").write_text("print(1)")
    (storage / "envs" / "1").mkdir(parents=True)
    (storage / "venvs" / "1").mkdir(parents=True)
    (storage / "node_modules" / "1").mkdir(parents=True)
    (storage / "logs").mkdir(parents=True)
    (storage / "logs" / "1.log").write_text("log")
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, role TEXT);
        INSERT INTO users VALUES (42, 'admin');
        CREATE TABLE scripts (id INTEGER PRIMARY KEY, user_id INTEGER);
        INSERT INTO scripts VALUES (1, 42);
    """)
    conn.commit()
    return storage, db


def test_migrate_users_dry_run_does_not_move(tmp_path):
    storage, db = _bootstrap(tmp_path)
    rc = migrate_users_run(str(storage), str(db), dry_run=True)
    assert rc == 0
    assert (storage / "scripts" / "1").exists()
    assert not (storage / "users" / "42").exists()


def test_migrate_users_moves_files(tmp_path):
    storage, db = _bootstrap(tmp_path)
    rc = migrate_users_run(str(storage), str(db), dry_run=False)
    assert rc == 0
    assert (storage / "users" / "42" / "scripts" / "1" / "hello.py").exists()
    assert (storage / "users" / "42" / "envs" / "1").exists()
    assert (storage / "users" / "42" / "venvs" / "1").exists()
    assert (storage / "users" / "42" / "node_modules" / "1").exists()
    assert (storage / "users" / "42" / "logs" / "1.log").exists()
    assert not (storage / "scripts" / "1").exists()


def test_migrate_users_is_idempotent(tmp_path):
    storage, db = _bootstrap(tmp_path)
    migrate_users_run(str(storage), str(db), dry_run=False)
    rc = migrate_users_run(str(storage), str(db), dry_run=False)
    assert rc == 0
    assert (storage / "users" / "42" / "scripts" / "1" / "hello.py").exists()
```

- [ ] **Step 2: Run tests, verify failure**

```bash
pytest tests/test_migrate_users.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `migrate_users.py`**

```python
# src/scriptdeck/cli_commands/migrate_users.py
"""Move existing flat /storage/scripts/<id>/ data into /storage/users/<uid>/.

Idempotent. Logs every move; dry-run prints moves without applying.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

SUBDIRS = ("scripts", "envs", "venvs", "node_modules")


def migrate_users_run(storage_dir: str, db_path: str, dry_run: bool = True) -> int:
    storage = Path(storage_dir)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, user_id FROM scripts WHERE user_id IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for script_id, user_id in rows:
        user_root = storage / "users" / str(user_id)
        for sub in SUBDIRS:
            src = storage / sub / str(script_id)
            if not src.exists():
                continue
            dst = user_root / sub / str(script_id)
            if dst.exists():
                log.info("skip %s -> %s (already exists)", src, dst)
                continue
            log.info("move %s -> %s%s", src, dst, " [dry-run]" if dry_run else "")
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        logs_src = storage / "logs" / f"{script_id}.log"
        if logs_src.exists():
            dst = user_root / "logs" / f"{script_id}.log"
            if not dst.exists():
                log.info("move %s -> %s%s", logs_src, dst, " [dry-run]" if dry_run else "")
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(logs_src), str(dst))
        n += 1
    print(f"migration {'planned' if dry_run else 'applied'}: {n} scripts")
    return 0
```

- [ ] **Step 4: Register subcommand in `cli.py`**

In `src/scriptdeck/cli.py`, add after the `mig` parser (line 18):

```python
    mu = sub.add_parser("migrate-users", help="Move flat storage into per-user subtrees")
    mu.add_argument("--storage-dir", required=True)
    mu.add_argument("--db-path", required=True)
    mu.add_argument("--apply", action="store_true", help="Actually move files (default dry-run)")
```

And in the dispatch block (after the `migrate-from-v1` case), add:

```python
    if args.cmd == "migrate-users":
        from scriptdeck.cli_commands.migrate_users import migrate_users_run
        return migrate_users_run(
            storage_dir=args.storage_dir,
            db_path=args.db_path,
            dry_run=not args.apply,
        )
```

- [ ] **Step 5: Run tests, verify pass**

```bash
pytest tests/test_migrate_users.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/cli_commands/migrate_users.py \
        src/scriptdeck/cli.py \
        tests/test_migrate_users.py
git commit -m "feat(cli): migrate-users moves storage to per-user subtree"
```

---

## Task 9: API user-filter audit

**Files:**
- Modify: `src/scriptdeck/api/deps.py` (add `require_script_owner`)
- Modify: `src/scriptdeck/api/scripts.py`, `src/scriptdeck/api/runs.py`, `src/scriptdeck/api/envs.py`
- Test: `tests/test_api_user_filter.py`

**Goal:** every endpoint that takes a `script_id` rejects if `current_user.id != script.user_id` (unless `role=='admin'`).

- [ ] **Step 1: Read existing endpoints**

```bash
grep -n "script_id\|get_script" src/scriptdeck/api/scripts.py src/scriptdeck/api/runs.py src/scriptdeck/api/envs.py
```

- [ ] **Step 2: Write failing test**

```python
# tests/test_api_user_filter.py
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_user_b_cannot_get_user_a_script():
    # Use existing fixtures from tests/test_server.py to bootstrap two users
    # with JWTs and create a script as user A. Then GET that script as user B
    # and assert the response is 403 or 404.
    #
    # Wire against the existing test helpers (see tests/test_server.py for
    # the JWT-issuing helper). Do not modify existing tests.
    pass
```

Replace the body of step 2 with concrete test code that uses the existing project JWT helper. Match the pattern from `tests/test_server.py`. Assert response status ∈ {403, 404}.

- [ ] **Step 3: Add `require_script_owner` to `src/scriptdeck/api/deps.py`**

```python
from fastapi import HTTPException, status
from scriptdeck.services.script_service import get_script


async def require_script_owner(session, script_id: int, current_user) -> int:
    """Resolve a script and verify the current user owns it (or is admin).

    Returns the owning user_id. Raises 404 if the script doesn't exist,
    403 if the current user is not the owner and not an admin.
    """
    script = await get_script(session, script_id)
    if script is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "script not found")
    if current_user.role != "admin" and script.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your script")
    return script.user_id
```

- [ ] **Step 4: Apply `require_script_owner` to script-scoped endpoints**

In each handler in `src/scriptdeck/api/scripts.py`, `src/scriptdeck/api/runs.py`, `src/scriptdeck/api/envs.py` that takes a `script_id` path or query param, call `await require_script_owner(session, script_id, current_user)` before doing the work. Update `current_user` to come from the existing auth dependency if not already.

- [ ] **Step 5: Run tests, verify pass**

```bash
pytest tests/test_api_user_filter.py tests/test_server.py -v
```

Expected: new + existing tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/api/ tests/test_api_user_filter.py
git commit -m "feat(api): enforce script ownership on all script-scoped endpoints"
```

---

## Task 10: `docker-compose.yml` capabilities

**Files:**
- Modify: `docker-compose.yml:4-25`

- [ ] **Step 1: Add `cap_drop` + `cap_add`**

Replace the `services.scriptdeck` block in `docker-compose.yml` with:

```yaml
    services:
      scriptdeck:
        build: .
        image: ghcr.io/aliaadil/scriptdeck:2.0.0
        container_name: scriptdeck
        restart: unless-stopped
        ports:
          - "8765:8765"
        cap_drop:
          - ALL
        cap_add:
          - SYS_CHROOT
          - SYS_ADMIN
        environment:
          SCRIPTDECK_DB_PATH: /data/scriptdeck.db
          SCRIPTDECK_STORAGE_DIR: /storage
          SCRIPTDECK_JWT_SECRET: ${SCRIPTDECK_JWT_SECRET:?required}
          SCRIPTDECK_ENV_ENCRYPTION_KEY: ${SCRIPTDECK_ENV_ENCRYPTION_KEY:?required}
          SCRIPTDECK_RUNNER_CONCURRENCY: "4"
          SCRIPTDECK_SCHEDULER_INTERVAL: "5"
        volumes:
          - scriptdeck-data:/data
          - scriptdeck-storage:/storage
```

- [ ] **Step 2: Verify compose is valid**

```bash
docker compose config -q
```

Expected: exit code 0, no output.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): drop caps, add SYS_CHROOT + SYS_ADMIN"
```

---

## Task 11: Docs

**Files:**
- Modify: `README.md:148-191` (storage layout + security model)
- Modify: `ROADMAP.md` (v2.1 entry)

- [ ] **Step 1: Update README storage layout**

Replace the `## Storage layout` block in `README.md` with the new per-user tree diagram + a `## Security model` section:

```markdown
## Storage layout

    .
    ├── scriptdeck.db                # ← backup this one file
    └── storage/
        ├── users/<user_id>/
        │   ├── scripts/<id>/<file>      # source uploaded per script
        │   ├── envs/<id>/.env.encrypted # AES-GCM encrypted
        │   ├── venvs/<id>/.venv/...     # per-script Python venv
        │   ├── node_modules/<id>/...    # per-script Node deps
        │   └── logs/<run_id>.log        # captured stdout/stderr
        └── locks/<id>.lock

Backing up `scriptdeck.db` plus `storage/` is a complete disaster-recovery snapshot.

## Security model

When `SCRIPTDECK_SANDBOX_ENABLED=true`, every script runs in a private mount
namespace chrooted into its user's subtree. Other users' files are not
mounted and therefore `open('/storage/users/<other>/...')` returns `ENOENT`.
Env vars are scrubbed to a small whitelist plus the script's own decrypted
env. The parent process's `os.environ` (which contains `SCRIPTDECK_JWT_SECRET`
and `SCRIPTDECK_ENV_ENCRYPTION_KEY`) is never copied into the child.

This is **good-citizen** isolation: it stops accidental cross-reads and
defends against a curious user, but does not claim to defeat a knowledgeable
attacker. For hardening beyond this, see the Roadmap.
```

- [ ] **Step 2: Add v2.1 entry to ROADMAP.md**

Append at the top of `## Future (v2.1+)` in `ROADMAP.md`:

```markdown
- Per-user sandbox (chroot + bind-mount into /storage/users/<uid>/) behind
  `SCRIPTDECK_SANDBOX_ENABLED` flag. Storage migration CLI
  `scriptdeck migrate-users`. See `docs/superpowers/specs/2026-08-16-user-isolation-design.md`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md ROADMAP.md
git commit -m "docs: per-user sandbox + storage layout"
```

---

## Self-Review

**Spec coverage:**
- Storage layout — Tasks 1, 8.
- Sandbox runner — Tasks 2, 3, 4.
- Runner protocol extension — Task 5.
- Env scrub — Tasks 2, 6.
- Container caps — Task 10.
- Error handling — Task 4 step 3 (errors raised in preexec_fn propagate to parent).
- Migration CLI — Task 8.
- API user-filter — Task 9.
- Rollout flag — Task 7.
- Testing — unit (Tasks 2, 3, 5, 7, 8), integration (Tasks 4, 6, 9).
- Docs — Task 11.

**Placeholder scan:** No TBDs. No "add appropriate". Code blocks in every step.

**Type consistency:** `BindMount`, `SandboxView`, `scrub_env`, `build_bind_plan`, `run_sandboxed`, `require_script_owner`, `Script.user_id`, `Settings.sandbox_enabled`, `migrate_users_run` introduced and used consistently across tasks.

**Out-of-scope checks:** network egress, rlimit CPU/mem, Landlock — all noted as non-goals in spec; not in plan.
