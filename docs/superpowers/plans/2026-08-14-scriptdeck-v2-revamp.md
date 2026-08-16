# ScriptDeck v2.0 Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite ScriptDeck on a FastAPI + React/Vite stack with multi-user auth, auto dep detection, encrypted per-script envs, full dashboard, and `LanguageRunner` protocol — single-host Docker, single SQLite file, migration path from v1.0.

**Architecture:** Single FastAPI + uvicorn process. SQLAlchemy 2.0 async + aiosqlite. Asyncio scheduler tick + subprocess runner. In-memory LogBroker for SSE. React/Vite SPA served by FastAPI at `/dashboard/*`. Encryption key + JWT secret from env. Argon2 password hashing. v1.0 tables carry forward; migrations 007 + 008 add users/invites/script_envs/script_deps/audit_log + indexes.

**Tech Stack:** Python 3.12, FastAPI, uvicorn, SQLAlchemy 2.0 (async), aiosqlite, pydantic v2, pydantic-settings, argon2-cffi, PyJWT, croniter, structlog. React 18, Vite 5, TypeScript, Tailwind, shadcn/ui (Radix), TanStack Query, React Router 6, react-hook-form + zod, @monaco-editor/react.

## Global Constraints

- Python 3.11+ runtime; project pins 3.12 in Dockerfile. CI matrix: 3.11, 3.12, 3.13.
- SQLite only; no Postgres. `SCRIPTDECK_DB_PATH` defaults to `scriptdeck.db`.
- `uv` binary required in container (used for Python venv + dep install).
- `node` + `npm` required in container (Node runner).
- Single FastAPI process; no separate worker. Scheduler + SSE share the event loop.
- Default runner concurrency = 4 (`SCRIPTDECK_RUNNER_CONCURRENCY`).
- Default scheduler poll interval = 5s (`SCRIPTDECK_SCHEDULER_INTERVAL`).
- Required env vars on first boot: `SCRIPTDECK_JWT_SECRET` (≥32 bytes), `SCRIPTDECK_ENV_ENCRYPTION_KEY` (32-byte base64). If unset, setup page generates them.
- JWT = HS256, 24h expiry, payload `{sub, role, exp, jti}`.
- Password hashing = argon2 via `argon2-cffi` (defaults).
- Per-script `.env` encrypted at rest with AES-GCM. Never returned by API in plaintext.
- All mutations write an `audit_log` row.
- Backend coverage gate = 85% lines. Frontend = 70%.
- Lint = `ruff`, `mypy --strict`, `eslint`, `tsc --noEmit`.
- Service port: 8765. Host: `127.0.0.1` default, `0.0.0.0` in Docker.
- All `LanguageRunner` implementations must satisfy the protocol (see Task 7).
- Skip-on-overlap behavior: when a script has an active `running` run, the new run is marked `status='error'` with `reason='overlap'` and the cursor advances.
- Logs and runs row paths are stored relative to `storage_dir`.
- Frontend uses TanStack Query for server state; no Redux/Zustand.
- `@monaco-editor/react` lazy-loaded on `ScriptEdit` only.
- Healthcheck endpoint: `GET /api/health` → `{status, db, scheduler}`.
- SSE format: `event: line` per line, `event: end` on terminal status, `: heartbeat` comment every 15s.

---

## Phase 1 — Foundation

### Task 1: Project scaffold + pyproject + uv

**Files:**
- Create: `pyproject.toml`
- Create: `src/scriptdeck/__init__.py`
- Create: `src/scriptdeck/__main__.py`
- Create: `.gitignore` (extend existing)
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `python -m scriptdeck` runs the app (stub for now, real in Task 4). Package importable as `scriptdeck`.

**Steps:**

- [ ] **Step 1.1: Write failing test for package import**

```python
# tests/test_import.py
def test_package_imports():
    import scriptdeck
    assert scriptdeck.__version__ == "2.0.0"
```

- [ ] **Step 1.2: Run test, expect failure**

Run: `pytest tests/test_import.py -v`
Expected: `ModuleNotFoundError: No module named 'scriptdeck'`

- [ ] **Step 1.3: Create pyproject.toml**

```toml
# pyproject.toml
[project]
name = "scriptdeck"
version = "2.0.0"
description = "Self-hosted scheduled script runner"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "sqlalchemy[asyncio]>=2.0",
    "aiosqlite>=0.19",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "argon2-cffi>=23.1",
    "pyjwt>=2.8",
    "croniter>=2.0",
    "structlog>=24.1",
    "httpx>=0.27",
    "python-multipart>=0.0.9",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "ruff>=0.3",
    "mypy>=1.8",
    "coverage>=7.4",
]

[project.scripts]
scriptdeck = "scriptdeck.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/scriptdeck"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--cov=scriptdeck --cov-report=term-missing --cov-fail-under=85"

[[tool.mypy.overrides]]
module = ["scriptdeck.*"]
disallow_untyped_defs = true

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "ASYNC", "S"]
```

- [ ] **Step 1.4: Create package skeleton**

```python
# src/scriptdeck/__init__.py
__version__ = "2.0.0"
```

```python
# src/scriptdeck/__main__.py
"""Entry point for `python -m scriptdeck`."""
from scriptdeck.cli import main

if __name__ == "__main__":
    main()
```

```python
# src/scriptdeck/cli.py
"""CLI entry: `scriptdeck` or `python -m scriptdeck`."""
import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="scriptdeck")
    sub = parser.add_subparsers(dest="cmd", required=False)
    sub.add_parser("serve", help="Run the API server (default)")
    args = parser.parse_args()
    if args.cmd in (None, "serve"):
        from scriptdeck.app import run
        run()
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

```python
# src/scriptdeck/app.py
"""FastAPI app entry — real impl in Task 4."""
def run() -> None:
    raise NotImplementedError("Task 4 wires this up")
```

```python
# tests/__init__.py
```

```python
# tests/conftest.py
"""Shared pytest fixtures."""
import pytest


@pytest.fixture
def tmp_storage(tmp_path):
    """Per-test storage directory."""
    storage = tmp_path / "storage"
    storage.mkdir()
    return storage


@pytest.fixture
def tmp_db(tmp_path):
    """Per-test SQLite path."""
    return tmp_path / "test.db"
```

- [ ] **Step 1.5: Install + run test, expect pass**

```bash
cd /Users/al/orca/workspaces/scriptdeck/feat-initial-launch
uv sync
uv run pytest tests/test_import.py -v
```

Expected: `1 passed`.

- [ ] **Step 1.6: Update .gitignore**

Append (preserving existing entries):

```
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.coverage
htmlcov/
dist/
.venv/
storage/
data/
scriptdeck.db
scriptdeck.db-journal
scriptdeck.db-wal
scriptdeck.db-shm
frontend/dist/
frontend/node_modules/
.DS_Store
```

- [ ] **Step 1.7: Commit**

```bash
git add pyproject.toml src/ tests/ .gitignore
git commit -m "feat(scaffold): pyproject + package skeleton + uv"
```

---

### Task 2: Config + DB engine + migration system

**Files:**
- Create: `src/scriptdeck/config.py`
- Create: `src/scriptdeck/db/__init__.py`
- Create: `src/scriptdeck/db/engine.py`
- Create: `src/scriptdeck/db/migrations.py`
- Create: `src/scriptdeck/db/models.py`
- Create: `src/scriptdeck/migrations/001_init.sql` (carry forward from v1)
- Create: `src/scriptdeck/migrations/002_scripts_v2.sql`
- Create: `src/scriptdeck/migrations/003_schedules.sql`
- Create: `src/scriptdeck/migrations/004_runs.sql`
- Create: `src/scriptdeck/migrations/005_logs_v5.sql` (carry forward from v1)
- Create: `src/scriptdeck/migrations/006_retry.sql`
- Create: `src/scriptdeck/migrations/007_from_v1.sql`
- Create: `src/scriptdeck/migrations/008_indexes.sql`
- Create: `tests/test_db.py`
- Create: `tests/test_migrations.py`

**Interfaces:**
- Consumes: nothing beyond `pyproject.toml`.
- Produces:
  - `scriptdeck.config.Settings` (pydantic-settings).
  - `scriptdeck.db.engine.make_engine(settings)` → `AsyncEngine`.
  - `scriptdeck.db.engine.session_factory(engine)` → `async_sessionmaker[AsyncSession]`.
  - `scriptdeck.db.migrations.run_migrations(engine)` applies pending migrations.

**Steps:**

- [ ] **Step 2.1: Write failing test for Settings + engine**

```python
# tests/test_db.py
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine


def test_settings_defaults():
    s = Settings()
    assert s.host == "127.0.0.1"
    assert s.port == 8765
    assert s.db_path == "scriptdeck.db"
    assert s.storage_dir == "storage"
    assert s.runner_concurrency == 4
    assert s.scheduler_interval == 5


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_PORT", "9000")
    monkeypatch.setenv("SCRIPTDECK_JWT_SECRET", "x" * 32)
    s = Settings()
    assert s.port == 9000
    assert s.jwt_secret == "x" * 32


def test_engine_creation(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    assert isinstance(engine, AsyncEngine)
```

- [ ] **Step 2.2: Run test, expect failure**

Run: `uv run pytest tests/test_db.py -v`
Expected: `ModuleNotFoundError: No module named 'scriptdeck.config'`

- [ ] **Step 2.3: Implement Settings**

```python
# src/scriptdeck/config.py
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRIPTDECK_",
        env_file=None,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765
    db_path: str = "scriptdeck.db"
    storage_dir: str = "storage"
    runner_concurrency: int = 4
    scheduler_interval: int = 5
    audit_retention_days: int = 90
    log_buffer_lines: int = 200

    # Required on real boot; nullable here so tests can construct Settings()
    jwt_secret: str | None = None
    env_encryption_key: str | None = None  # base64, 32 bytes
```

- [ ] **Step 2.4: Implement engine**

```python
# src/scriptdeck/db/engine.py
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scriptdeck.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{settings.db_path}"
    return create_async_engine(url, echo=False, future=True)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 2.5: Implement migration system**

```python
# src/scriptdeck/db/migrations.py
from __future__ import annotations

import importlib.resources
import logging
import re

from sqlalchemy.ext.asyncio import AsyncEngine

log = logging.getLogger(__name__)

VERSION_RE = re.compile(r"^(\d{3})_.*\.sql$")


def _migration_files() -> list[tuple[int, str]]:
    files: list[tuple[int, str]] = []
    pkg = importlib.resources.files("scriptdeck.migrations")
    for entry in pkg.iterdir():
        name = entry.name
        m = VERSION_RE.match(name)
        if m:
            files.append((int(m.group(1)), str(entry)))
    files.sort()
    return files


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply pending migrations in order, tracked in schema_version table."""
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
            ")"
        )
        result = await conn.exec_driver_sql("SELECT MAX(version) FROM schema_version")
        row = result.first()
        current = row[0] if row and row[0] is not None else 0

    for version, path in _migration_files():
        if version <= current:
            continue
        log.info("applying migration %03d from %s", version, path)
        sql = _read_sql(path)
        async with engine.begin() as conn:
            await conn.exec_driver_sql(sql)
            await conn.exec_driver_sql(
                "INSERT INTO schema_version (version) VALUES (:v)",
                {"v": version},
            )


def _read_sql(path: str) -> str:
    from pathlib import Path
    return Path(path).read_text(encoding="utf-8")
```

```python
# src/scriptdeck/db/__init__.py
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations

__all__ = ["make_engine", "session_factory", "run_migrations"]
```

- [ ] **Step 2.6: Create migration files**

```sql
-- src/scriptdeck/migrations/001_init.sql
CREATE TABLE scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL CHECK (language IN ('python', 'node', 'bash')),
    source_path TEXT NOT NULL,
    requirements_path TEXT,
    interpreter_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_scripts_name ON scripts(name);
```

```sql
-- src/scriptdeck/migrations/002_scripts_v2.sql
-- Adds columns used from v0.4 onward. Carried into v2.0 verbatim.
ALTER TABLE scripts ADD COLUMN description TEXT;
```

```sql
-- src/scriptdeck/migrations/003_schedules.sql
CREATE TABLE schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('cron', 'interval')),
    expression TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run_at TEXT NOT NULL,
    retry_max INTEGER NOT NULL DEFAULT 0,
    retry_backoff INTEGER NOT NULL DEFAULT 0,
    last_status TEXT
);
CREATE INDEX idx_schedules_script ON schedules(script_id);
```

```sql
-- src/scriptdeck/migrations/004_runs.sql
CREATE TABLE runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES schedules(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,
    exit_code INTEGER,
    status TEXT NOT NULL CHECK (status IN (
        'running', 'success', 'failure', 'error', 'cancelled'
    )),
    retry_group TEXT
);
CREATE INDEX idx_runs_script ON runs(script_id);
CREATE INDEX idx_runs_started ON runs(started_at DESC);
```

```sql
-- src/scriptdeck/migrations/005_logs_v5.sql
-- Rebuild runs to allow status='running' and status='cancelled'.
-- (Carried verbatim from v1's v5 migration.)
CREATE TABLE logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    line_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_logs_run ON logs(run_id);
```

```sql
-- src/scriptdeck/migrations/006_retry.sql
-- Adds retry backoff default + last_status to schedules.
ALTER TABLE schedules ADD COLUMN last_error TEXT;
```

```sql
-- src/scriptdeck/migrations/007_from_v1.sql
-- NEW for v2.0. Adds users, invites, script_envs, script_deps, audit_log.
-- The four original tables are inherited from migrations 001-006.

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE TABLE invites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL CHECK (role IN ('admin', 'editor', 'viewer')),
    expires_at TEXT NOT NULL,
    used_at TEXT
);
CREATE INDEX idx_invites_token ON invites(token);

CREATE TABLE script_envs (
    script_id INTEGER PRIMARY KEY REFERENCES scripts(id) ON DELETE CASCADE,
    ciphertext BLOB NOT NULL,
    nonce BLOB NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE script_deps (
    script_id INTEGER PRIMARY KEY REFERENCES scripts(id) ON DELETE CASCADE,
    deps_json TEXT NOT NULL DEFAULT '[]',
    source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('auto', 'manual')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id INTEGER,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    meta_json TEXT NOT NULL DEFAULT '{}'
);
```

```sql
-- src/scriptdeck/migrations/008_indexes.sql
-- NEW for v2.0.
CREATE INDEX idx_runs_script_started ON runs(script_id, started_at DESC);
CREATE INDEX idx_schedules_due ON schedules(enabled, next_run_at);
CREATE INDEX idx_runs_status ON runs(status);
CREATE INDEX idx_audit_user_at ON audit_log(user_id, at DESC);
```

- [ ] **Step 2.7: Add migrations package marker**

```python
# src/scriptdeck/migrations/__init__.py
```

(Empty file — needed so `importlib.resources.files` finds it.)

- [ ] **Step 2.8: Write migration test**

```python
# tests/test_migrations.py
import pytest

from scriptdeck.db.engine import make_engine
from scriptdeck.db.migrations import run_migrations
from scriptdeck.config import Settings


@pytest.mark.asyncio
async def test_run_migrations_creates_tables(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    async with engine.connect() as conn:
        tables = await conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        names = {row[0] for row in tables}
    assert {"scripts", "schedules", "runs", "logs", "users",
            "invites", "script_envs", "script_deps",
            "audit_log", "schema_version"} <= names


@pytest.mark.asyncio
async def test_run_migrations_idempotent(tmp_db):
    s = Settings(db_path=str(tmp_db))
    engine = make_engine(s)
    await run_migrations(engine)
    await run_migrations(engine)  # second call is a no-op
    async with engine.connect() as conn:
        result = await conn.exec_driver_sql(
            "SELECT COUNT(*) FROM schema_version"
        )
        assert result.scalar() == 8
```

- [ ] **Step 2.9: Run tests, expect pass**

```bash
uv run pytest tests/test_db.py tests/test_migrations.py -v
```

Expected: all pass.

- [ ] **Step 2.10: Commit**

```bash
git add src/scriptdeck/config.py src/scriptdeck/db/ src/scriptdeck/migrations/
git add tests/test_db.py tests/test_migrations.py
git commit -m "feat(db): config + async engine + migration system + 001-008"
```

---

### Task 3: FastAPI app skeleton + /api/health

**Files:**
- Modify: `src/scriptdeck/app.py`
- Create: `src/scriptdeck/api/__init__.py`
- Create: `src/scriptdeck/api/health.py`
- Modify: `src/scriptdeck/cli.py`
- Create: `tests/test_app.py`

**Interfaces:**
- Consumes: `Settings`, `make_engine`, `run_migrations`.
- Produces: `scriptdeck.app.create_app(settings)` returns FastAPI app. `GET /api/health` → `{status, db, scheduler}`. `python -m scriptdeck` boots uvicorn on `settings.host:settings.port`.

**Steps:**

- [ ] **Step 3.1: Write failing health test**

```python
# tests/test_app.py
import pytest
from httpx import ASGITransport, AsyncClient

from scriptdeck.app import create_app
from scriptdeck.config import Settings


@pytest.mark.asyncio
async def test_health_endpoint(tmp_db):
    s = Settings(db_path=str(tmp_db), jwt_secret="x" * 32, env_encryption_key="A" * 44)
    app = create_app(s)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert "scheduler" in body
```

- [ ] **Step 3.2: Run test, expect failure**

Run: `uv run pytest tests/test_app.py -v`
Expected: `NotImplementedError` or import failure.

- [ ] **Step 3.3: Implement health endpoint**

```python
# src/scriptdeck/api/health.py
from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    from sqlalchemy import text
    engine = request.app.state.engine
    db_ok = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = "down"
    sched_ok = "ok" if getattr(request.app.state, "scheduler_running", False) else "stopped"
    overall = "ok" if db_ok == "ok" and sched_ok in ("ok", "stopped") else "degraded"
    return {"status": overall, "db": db_ok, "scheduler": sched_ok}
```

```python
# src/scriptdeck/api/__init__.py
```

- [ ] **Step 3.4: Implement app factory**

```python
# src/scriptdeck/app.py
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from scriptdeck.api.health import router as health_router
from scriptdeck.config import Settings
from scriptdeck.db import make_engine, run_migrations


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="ScriptDeck", version="2.0.0")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings)
        await run_migrations(engine)
        app.state.engine = engine
        app.state.settings = settings
        app.state.scheduler_running = False
        try:
            yield
        finally:
            await engine.dispose()

    app.router.lifespan_context = lifespan
    app.include_router(health_router, prefix="/api")
    return app


def run() -> None:
    import uvicorn
    settings = Settings()
    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")
```

- [ ] **Step 3.5: Run test, expect pass**

```bash
uv run pytest tests/test_app.py -v
```

Expected: 1 passed.

- [ ] **Step 3.6: Commit**

```bash
git add src/scriptdeck/app.py src/scriptdeck/api/ tests/test_app.py
git commit -m "feat(api): app factory + /api/health endpoint"
```

---

### Task 4: Auth foundation — users table model + argon2 + JWT

**Files:**
- Create: `src/scriptdeck/auth/__init__.py`
- Create: `src/scriptdeck/auth/passwords.py`
- Create: `src/scriptdeck/auth/jwt.py`
- Create: `src/scriptdeck/auth/users.py`
- Create: `src/scriptdeck/auth/deps.py`
- Create: `tests/test_auth.py`
- Modify: `src/scriptdeck/app.py` (add auth router stub)

**Interfaces:**
- Consumes: `Settings`, async session.
- Produces:
  - `scriptdeck.auth.passwords.hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`.
  - `scriptdeck.auth.jwt.encode_jwt(sub, role) -> tuple[token, jti, exp]`, `decode_jwt(token) -> dict`, `revoke(jti, exp)`.
  - `scriptdeck.auth.users.create_user(session, email, password, role) -> User`.
  - `scriptdeck.auth.users.get_by_email(session, email) -> User | None`.
  - `scriptdeck.auth.deps.current_user(request) -> User` (FastAPI dependency).

**Steps:**

- [ ] **Step 4.1: Write failing auth tests**

```python
# tests/test_auth.py
import pytest
from argon2.exceptions import VerifyMismatchError

from scriptdeck.auth.passwords import hash_password, verify_password
from scriptdeck.auth.jwt import encode_jwt, decode_jwt
from scriptdeck.auth.users import create_user, get_by_email


def test_password_hash_and_verify():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token, jti, exp = encode_jwt(user_id=1, role="admin", secret="x" * 32)
    payload = decode_jwt(token, secret="x" * 32)
    assert payload["sub"] == 1
    assert payload["role"] == "admin"
    assert payload["jti"] == jti
    assert payload["exp"] == exp


def test_jwt_rejects_tampered():
    token, _, _ = encode_jwt(user_id=1, role="admin", secret="x" * 32)
    with pytest.raises(Exception):
        decode_jwt(token + "x", secret="x" * 32)


@pytest.mark.asyncio
async def test_create_and_get_user(tmp_db):
    from scriptdeck.db.engine import make_engine, session_factory
    from scriptdeck.db.migrations import run_migrations
    engine = make_engine(__import__("scriptdeck").config.Settings(db_path=str(tmp_db)))
    await run_migrations(engine)
    Session = session_factory(engine)
    async with Session() as s:
        u = await create_user(s, "a@b.com", "pw", role="admin")
        await s.commit()
        uid = u.id
    async with Session() as s:
        got = await get_by_email(s, "a@b.com")
        assert got is not None
        assert got.id == uid
        assert got.role == "admin"
```

- [ ] **Step 4.2: Run, expect failure**

Run: `uv run pytest tests/test_auth.py -v`
Expected: import errors.

- [ ] **Step 4.3: Implement passwords**

```python
# src/scriptdeck/auth/passwords.py
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False
```

- [ ] **Step 4.4: Implement JWT**

```python
# src/scriptdeck/auth/jwt.py
from __future__ import annotations

import time
import uuid
from threading import Lock

import jwt

_revocation_lock = Lock()
_revoked: dict[str, int] = {}  # jti -> exp epoch seconds


def encode_jwt(user_id: int, role: str, secret: str, ttl: int = 86400) -> tuple[str, str, int]:
    now = int(time.time())
    exp = now + ttl
    jti = uuid.uuid4().hex
    payload = {"sub": user_id, "role": role, "iat": now, "exp": exp, "jti": jti}
    token = jwt.encode(payload, secret, algorithm="HS256")
    return token, jti, exp


def decode_jwt(token: str, secret: str) -> dict:
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    with _revocation_lock:
        if payload.get("jti") in _revoked:
            raise jwt.InvalidTokenError("token revoked")
    return payload


def revoke(jti: str, exp: int) -> None:
    with _revocation_lock:
        _revoked[jti] = exp


def cleanup_revoked(now: int | None = None) -> int:
    """Drop expired entries. Returns count removed."""
    if now is None:
        now = int(time.time())
    with _revocation_lock:
        expired = [k for k, v in _revoked.items() if v <= now]
        for k in expired:
            del _revoked[k]
    return len(expired)
```

- [ ] **Step 4.5: Implement user model + service**

```python
# src/scriptdeck/auth/users.py
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scriptdeck.auth.passwords import hash_password


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    role: str
    created_at: str
    last_login_at: str | None


async def create_user(
    session: AsyncSession, email: str, password: str, role: str
) -> User:
    from sqlalchemy import insert
    pw_hash = hash_password(password)
    stmt = (
        insert(_table())
        .values(email=email, password_hash=pw_hash, role=role)
        .returning(_table().c.id, _table().c.email, _table().c.password_hash,
                   _table().c.role, _table().c.created_at, _table().c.last_login_at)
    )
    result = await session.execute(stmt)
    row = result.mappings().one()
    return User(**row)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(_table()).where(_table().c.email == email)
    row = (await session.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None
    return User(**row)


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    stmt = select(_table()).where(_table().c.id == user_id)
    row = (await session.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None
    return User(**row)


def _table():
    # Defer import to avoid circular deps with db package.
    from scriptdeck.db.models import users
    return users
```

- [ ] **Step 4.6: Implement ORM model**

```python
# src/scriptdeck/db/models.py
from __future__ import annotations

from sqlalchemy import (
    CheckConstraint, Column, ForeignKey, Index, Integer, String, Text, Table,
)
from sqlalchemy.orm import registry

mapper_registry = registry()

users = Table(
    "users",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("last_login_at", Text, nullable=True),
    CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="users_role_check"),
)

invites = Table(
    "invites",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String, nullable=False),
    Column("token", String, nullable=False, unique=True),
    Column("role", String, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("used_at", Text, nullable=True),
    Index("idx_invites_token", "token"),
)

script_envs = Table(
    "script_envs",
    mapper_registry.metadata,
    Column("script_id", Integer, ForeignKey("scripts.id", ondelete="CASCADE"),
           primary_key=True),
    Column("ciphertext", String, nullable=False),  # base64 BLOB stored as TEXT
    Column("nonce", String, nullable=False),
    Column("updated_at", Text, nullable=False),
)

script_deps = Table(
    "script_deps",
    mapper_registry.metadata,
    Column("script_id", Integer, ForeignKey("scripts.id", ondelete="CASCADE"),
           primary_key=True),
    Column("deps_json", Text, nullable=False),
    Column("source", String, nullable=False),
    Column("updated_at", Text, nullable=False),
)

audit_log = Table(
    "audit_log",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="SET NULL")),
    Column("action", String, nullable=False),
    Column("resource_type", String, nullable=False),
    Column("resource_id", Integer),
    Column("at", Text, nullable=False),
    Column("meta_json", Text, nullable=False),
)
```

- [ ] **Step 4.7: Implement FastAPI dep for current user**

```python
# src/scriptdeck/auth/deps.py
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status

from scriptdeck.auth.users import User, get_by_id


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1].strip()
    from scriptdeck.auth.jwt import decode_jwt
    try:
        payload = decode_jwt(token, secret=request.app.state.settings.jwt_secret or "")
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    session_factory = request.app.state.session_factory
    async with session_factory() as s:
        user = await get_by_id(s, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user
```

- [ ] **Step 4.8: Wire session factory into app state + add stub auth router**

```python
# Modify src/scriptdeck/app.py: in lifespan, after creating engine, add:
#     app.state.session_factory = session_factory(engine)
```

```python
# src/scriptdeck/api/auth.py
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/auth")


@router.get("/me")
async def me_stub() -> dict[str, str]:
    """Replaced by full impl in Task 5."""
    return {"stub": "true"}
```

Modify `src/scriptdeck/app.py` to include `from scriptdeck.api.auth import router as auth_router` and `app.include_router(auth_router, prefix="/api")`.

- [ ] **Step 4.9: Update conftest to inject session factory in app**

```python
# Append to src/scriptdeck/app.py lifespan after engine creation:
#     from scriptdeck.db.engine import session_factory as _sf
#     app.state.session_factory = _sf(engine)
```

- [ ] **Step 4.10: Run tests, expect pass**

```bash
uv run pytest tests/test_auth.py -v
```

Expected: 4 passed.

- [ ] **Step 4.11: Commit**

```bash
git add src/scriptdeck/auth/ src/scriptdeck/db/models.py src/scriptdeck/app.py src/scriptdeck/api/auth.py
git add tests/test_auth.py
git commit -m "feat(auth): users model + argon2 + JWT + current_user dep"
```

---

### Task 5: Auth API endpoints (login, me, refresh, logout, setup, invites)

**Files:**
- Modify: `src/scriptdeck/api/auth.py`
- Create: `src/scriptdeck/api/users.py`
- Modify: `src/scriptdeck/auth/users.py` (add update_last_login, count_users)
- Create: `src/scriptdeck/services/audit.py`
- Create: `tests/test_auth_api.py`

**Interfaces:**
- Produces:
  - `POST /api/auth/setup` (only when users empty).
  - `POST /api/auth/login` → `{token, user}`.
  - `POST /api/auth/refresh`.
  - `POST /api/auth/logout`.
  - `GET /api/auth/me` → `{id, email, role}`.
  - `PUT /api/auth/me/password`.
  - `GET /api/users` (admin).
  - `POST /api/users/invites` (admin).
  - `POST /api/users/invites/accept`.
  - `DELETE /api/users/:id` (admin).
  - `PUT /api/users/:id/role` (admin).

**Steps:**

- [ ] **Step 5.1: Implement audit service**

```python
# src/scriptdeck/services/__init__.py
```

```python
# src/scriptdeck/services/audit.py
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession


async def record(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    meta = meta or {}
    stmt = (
        insert(__import__("scriptdeck.db.models", fromlist=["audit_log"]).audit_log)
        .values(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            meta_json=json.dumps(meta),
        )
    )
    await session.execute(stmt)
```

- [ ] **Step 5.2: Add user helpers**

```python
# Append to src/scriptdeck/auth/users.py
from datetime import datetime, timezone
from sqlalchemy import func, update


async def count_users(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(_table())
    return int((await session.execute(stmt)).scalar() or 0)


async def update_last_login(session: AsyncSession, user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    stmt = update(_table()).where(_table().c.id == user_id).values(last_login_at=now)
    await session.execute(stmt)


async def update_password(session: AsyncSession, user_id: int, new_password: str) -> None:
    stmt = update(_table()).where(_table().c.id == user_id).values(
        password_hash=hash_password(new_password)
    )
    await session.execute(stmt)


async def list_users(session: AsyncSession) -> list[User]:
    stmt = select(_table()).order_by(_table().c.id)
    return [User(**r) for r in (await session.execute(stmt)).mappings().all()]


async def delete_user(session: AsyncSession, user_id: int) -> bool:
    from sqlalchemy import delete
    stmt = delete(_table()).where(_table().c.id == user_id)
    result = await session.execute(stmt)
    return result.rowcount > 0  # type: ignore[no-any-return]


async def update_role(session: AsyncSession, user_id: int, role: str) -> bool:
    stmt = update(_table()).where(_table().c.id == user_id).values(role=role)
    result = await session.execute(stmt)
    return result.rowcount > 0  # type: ignore[no-any-return]
```

- [ ] **Step 5.3: Implement invite service**

```python
# src/scriptdeck/auth/invites.py
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Invite:
    id: int
    email: str
    token: str
    role: str
    expires_at: str
    used_at: str | None


def _table():
    from scriptdeck.db.models import invites
    return invites


async def create_invite(
    session: AsyncSession, email: str, role: str, ttl_hours: int = 72
) -> Invite:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
    stmt = (
        insert(_table())
        .values(email=email, token=token, role=role, expires_at=expires)
        .returning(_table().c.id, _table().c.email, _table().c.token,
                   _table().c.role, _table().c.expires_at, _table().c.used_at)
    )
    row = (await session.execute(stmt)).mappings().one()
    return Invite(**row)


async def accept_invite(
    session: AsyncSession, token: str
) -> Invite | None:
    stmt = select(_table()).where(_table().c.token == token)
    row = (await session.execute(stmt)).mappings().one_or_none()
    if row is None or row["used_at"] is not None:
        return None
    inv = Invite(**row)
    if datetime.fromisoformat(inv.expires_at) < datetime.now(timezone.utc):
        return None
    await session.execute(
        update(_table()).where(_table().c.id == inv.id).values(
            used_at=datetime.now(timezone.utc).isoformat()
        )
    )
    return inv
```

- [ ] **Step 5.4: Implement auth API**

```python
# src/scriptdeck/api/auth.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.invites import accept_invite
from scriptdeck.auth.jwt import encode_jwt, decode_jwt, revoke
from scriptdeck.auth.passwords import verify_password
from scriptdeck.auth.users import (
    User, count_users, create_user, get_by_email, update_last_login,
    update_password,
)
from scriptdeck.services.audit import record as audit

router = APIRouter(prefix="/auth")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    token: str
    user: dict


class MeOut(BaseModel):
    id: int
    email: str
    role: str


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8)


class SetupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


@router.post("/setup", status_code=201)
async def setup(request: Request, body: SetupIn) -> dict:
    """First-boot only. Returns 404 once any user exists."""
    sf = request.app.state.session_factory
    async with sf() as s:
        if await count_users(s) > 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="setup disabled")
        u = await create_user(s, body.email, body.password, role="admin")
        await s.commit()
        await audit(s, u.id, "user_created", "user", u.id)
        await s.commit()
    settings = request.app.state.settings
    token, _, _ = encode_jwt(u.id, u.role, settings.jwt_secret or "")
    return {"token": token, "user": {"id": u.id, "email": u.email, "role": u.role}}


@router.post("/login")
async def login(request: Request, body: LoginIn) -> dict:
    sf = request.app.state.session_factory
    async with sf() as s:
        u = await get_by_email(s, body.email)
        if u is None or not verify_password(body.password, u.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad credentials")
        await update_last_login(s, u.id)
        await audit(s, u.id, "login", "user", u.id)
        await s.commit()
    settings = request.app.state.settings
    token, _, _ = encode_jwt(u.id, u.role, settings.jwt_secret or "")
    return {"token": token, "user": {"id": u.id, "email": u.email, "role": u.role}}


@router.post("/refresh")
async def refresh(request: Request, authorization: str | None = None) -> dict:
    # Bearer parsed by dep via header injection (kept inline for refresh).
    from fastapi import Header
    raise NotImplementedError  # wired in full impl below
```

Refactor `refresh` to accept Header (replace stub):

```python
@router.post("/refresh")
async def refresh(
    request: Request,
    authorization: str = Header(...),
) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1]
    settings = request.app.state.settings
    payload = decode_jwt(token, secret=settings.jwt_secret or "")
    new_token, _, _ = encode_jwt(int(payload["sub"]), payload["role"], settings.jwt_secret or "")
    return {"token": new_token}


@router.post("/logout")
async def logout(request: Request, authorization: str = Header(...)) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1]
    settings = request.app.state.settings
    try:
        payload = decode_jwt(token, secret=settings.jwt_secret or "")
    except Exception:
        return {"ok": True}
    revoke(payload["jti"], int(payload["exp"]))
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user)) -> MeOut:
    return MeOut(id=user.id, email=user.email, role=user.role)


@router.put("/me/password")
async def change_password(
    request: Request,
    body: PasswordIn,
    user: User = Depends(current_user),
) -> dict:
    sf = request.app.state.session_factory
    async with sf() as s:
        u = await get_by_email(s, user.email)
        assert u is not None
        if not verify_password(body.current, u.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="wrong current password")
        await update_password(s, u.id, body.new)
        await audit(s, u.id, "password_changed", "user", u.id)
        await s.commit()
    return {"ok": True}
```

- [ ] **Step 5.5: Implement users API**

```python
# src/scriptdeck/api/users.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.invites import create_invite
from scriptdeck.auth.users import (
    User, create_user, delete_user, get_by_email, list_users, update_role,
)
from scriptdeck.services.audit import record as audit

router = APIRouter(prefix="/users")


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|editor|viewer)$")


class InviteOut(BaseModel):
    token: str
    expires_at: str


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


class RoleIn(BaseModel):
    role: str = Field(pattern="^(admin|editor|viewer)$")


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin required")


@router.get("")
async def index(user: User = Depends(current_user)) -> list[dict]:
    require_admin(user)
    sf = user  # placeholder so type checker is happy; replace below
    return []


@router.get("/")
async def list_endpoint(request: Request, user: User = Depends(current_user)) -> list[dict]:
    require_admin(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        users = await list_users(s)
    return [{"id": u.id, "email": u.email, "role": u.role,
             "created_at": u.created_at, "last_login_at": u.last_login_at} for u in users]


@router.post("/invites", status_code=201)
async def invite(
    request: Request, body: InviteIn, user: User = Depends(current_user)
) -> InviteOut:
    require_admin(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        inv = await create_invite(s, body.email, body.role)
        await audit(s, user.id, "invite_created", "invite", inv.id,
                    {"email": body.email, "role": body.role})
        await s.commit()
    return InviteOut(token=inv.token, expires_at=inv.expires_at)


@router.post("/invites/accept", status_code=201)
async def accept(request: Request, body: AcceptInviteIn) -> dict:
    sf = request.app.state.session_factory
    async with sf() as s:
        inv = await accept_invite(s, body.token)
        if inv is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid or expired invite")
        u = await create_user(s, inv.email, body.password, role=inv.role)
        await audit(s, u.id, "user_created", "user", u.id, {"via_invite": True})
        await s.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@router.delete("/{user_id}")
async def remove(user_id: int, request: Request, user: User = Depends(current_user)) -> dict:
    require_admin(user)
    if user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot delete self")
    sf = request.app.state.session_factory
    async with sf() as s:
        ok = await delete_user(s, user_id)
        if ok:
            await audit(s, user.id, "user_deleted", "user", user_id)
            await s.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return {"ok": True}


@router.put("/{user_id}/role")
async def change_role(
    user_id: int, body: RoleIn, request: Request, user: User = Depends(current_user)
) -> dict:
    require_admin(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        ok = await update_role(s, user_id, body.role)
        if ok:
            await audit(s, user.id, "role_changed", "user", user_id, {"role": body.role})
            await s.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return {"ok": True}
```

Remove the duplicate `index` stub above; only the `list_endpoint` version is real.

- [ ] **Step 5.6: Wire routers into app + write tests**

```python
# Modify src/scriptdeck/app.py: add
#     from scriptdeck.api.users import router as users_router
#     app.include_router(users_router, prefix="/api")
```

```python
# tests/test_auth_api.py
import pytest
from httpx import ASGITransport, AsyncClient

from scriptdeck.app import create_app


@pytest.mark.asyncio
async def test_setup_then_login(tmp_db, tmp_storage, monkeypatch):
    monkeypatch.setenv("SCRIPTDECK_STORAGE_DIR", str(tmp_storage))
    s = type("S", (), {})()
    from scriptdeck.config import Settings
    settings = Settings(db_path=str(tmp_db), jwt_secret="x" * 32,
                        env_encryption_key="A" * 44, storage_dir=str(tmp_storage))
    app = create_app(settings)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/auth/setup", json={"email": "a@b.com", "password": "hunter22"})
        assert r.status_code == 201
        token = r.json()["token"]
        r2 = await ac.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
        assert r2.json()["email"] == "a@b.com"
        # Setup is now disabled
        r3 = await ac.post("/api/auth/setup", json={"email": "b@b.com", "password": "hunter22"})
        assert r3.status_code == 404
```

- [ ] **Step 5.7: Run tests, expect pass**

```bash
uv run pytest tests/test_auth_api.py -v
```

Expected: 1 passed.

- [ ] **Step 5.8: Commit**

```bash
git add src/scriptdeck/api/ src/scriptdeck/auth/ src/scriptdeck/services/
git add tests/test_auth_api.py
git commit -m "feat(auth): login/me/refresh/logout/setup + invites + users CRUD"
```

---

## Phase 2 — Backend Domain

### Task 6: LanguageRunner protocol + PythonRunner + NodeRunner

**Files:**
- Create: `src/scriptdeck/runner/__init__.py`
- Create: `src/scriptdeck/runner/protocol.py`
- Create: `src/scriptdeck/runner/registry.py`
- Create: `src/scriptdeck/runner/python_runner.py`
- Create: `src/scriptdeck/runner/node_runner.py`
- Create: `src/scriptdeck/services/dep_detect.py`
- Create: `data/python_stdlib.txt` (bundled list)
- Create: `data/node_stdlib.txt` (bundled list)
- Create: `tests/test_runner_protocol.py`
- Create: `tests/test_dep_detect.py`

**Interfaces:**
- `LanguageRunner` (Protocol): `name: str`, `detect_deps(source) -> list[str]`, `resolve_artifact_path() -> str`, `provision(work_dir, deps) -> Path`, `build_command(interpreter, source_path, env) -> list[str]`.
- `RUNNERS: dict[str, LanguageRunner]` (registry).
- `detect_deps_for_language(language, source) -> list[str]` (convenience).

**Steps:**

- [ ] **Step 6.1: Write failing protocol test**

```python
# tests/test_runner_protocol.py
import pytest

from scriptdeck.runner.protocol import LanguageRunner
from scriptdeck.runner.registry import RUNNERS, get_runner
from scriptdeck.runner.python_runner import PythonRunner
from scriptdeck.runner.node_runner import NodeRunner


def test_registry_has_python_and_node():
    assert "python" in RUNNERS
    assert "node" in RUNNERS
    assert isinstance(RUNNERS["python"], PythonRunner)
    assert isinstance(RUNNERS["node"], NodeRunner)


def test_get_runner_unknown():
    with pytest.raises(KeyError):
        get_runner("ruby")


def test_python_runner_artifact():
    r = PythonRunner()
    assert r.resolve_artifact_path() == "requirements.txt"


def test_node_runner_artifact():
    r = NodeRunner()
    assert r.resolve_artifact_path() == "package.json"
```

- [ ] **Step 6.2: Run, expect failure**

Run: `uv run pytest tests/test_runner_protocol.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 6.3: Implement protocol + registry**

```python
# src/scriptdeck/runner/protocol.py
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class LanguageRunner(Protocol):
    name: str

    async def detect_deps(self, source: str) -> list[str]: ...

    def resolve_artifact_path(self) -> str: ...

    async def provision(self, work_dir: Path, deps: list[str]) -> Path: ...

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]: ...
```

```python
# src/scriptdeck/runner/registry.py
from __future__ import annotations

from scriptdeck.runner.node_runner import NodeRunner
from scriptdeck.runner.protocol import LanguageRunner
from scriptdeck.runner.python_runner import PythonRunner

RUNNERS: dict[str, LanguageRunner] = {
    "python": PythonRunner(),
    "node": NodeRunner(),
}


def get_runner(language: str) -> LanguageRunner:
    return RUNNERS[language]
```

- [ ] **Step 6.4: Implement PythonRunner**

```python
# src/scriptdeck/runner/python_runner.py
from __future__ import annotations

import asyncio
from pathlib import Path

from scriptdeck.runner.protocol import LanguageRunner


class PythonRunner:
    name = "python"

    def resolve_artifact_path(self) -> str:
        return "requirements.txt"

    async def detect_deps(self, source: str) -> list[str]:
        from scriptdeck.services.dep_detect import detect_python_deps
        return detect_python_deps(source)

    async def provision(self, work_dir: Path, deps: list[str]) -> Path:
        req = work_dir / self.resolve_artifact_path()
        req.write_text("\n".join(deps) + ("\n" if deps else ""), encoding="utf-8")
        venv = work_dir / ".venv"
        if not (venv / "bin" / "python").exists():
            await _run(["uv", "venv", str(venv)])
        if deps:
            await _run(["uv", "pip", "install", "--python", str(venv / "bin" / "python"),
                        "-r", str(req)])
        return venv / "bin" / "python"

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]:
        return [str(interpreter), str(source_path)]


async def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}\n{out.decode()}\n{err.decode()}")
```

- [ ] **Step 6.5: Implement NodeRunner**

```python
# src/scriptdeck/runner/node_runner.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from scriptdeck.runner.protocol import LanguageRunner


class NodeRunner:
    name = "node"

    def resolve_artifact_path(self) -> str:
        return "package.json"

    async def detect_deps(self, source: str) -> list[str]:
        from scriptdeck.services.dep_detect import detect_node_deps
        return detect_node_deps(source)

    async def provision(self, work_dir: Path, deps: list[str]) -> Path:
        pkg_path = work_dir / self.resolve_artifact_path()
        if pkg_path.exists():
            data = json.loads(pkg_path.read_text(encoding="utf-8"))
        else:
            data = {"name": "scriptdeck-script", "version": "1.0.0", "private": True}
        data["dependencies"] = {d: "*" for d in deps}
        pkg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        if deps:
            await _run(["npm", "install", "--silent"], cwd=work_dir)
        return Path("node")  # resolved on PATH

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]:
        return [str(interpreter), str(source_path)]


async def _run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {cmd}\n{out.decode()}\n{err.decode()}")
```

- [ ] **Step 6.6: Bundle stdlib lists**

Generate Python stdlib list (requires Python 3.10+):

```bash
python3 -c "import sys; print('\n'.join(sorted(sys.stdlib_module_names)))" \
  > data/python_stdlib.txt
```

If `sys.stdlib_module_names` is unavailable, use the bundled v1 list as fallback.

Node 22 builtin modules (write to `data/node_stdlib.txt`):

```
assert
async_hooks
buffer
child_process
cluster
console
constants
crypto
dgram
diagnostics_channel
dns
domain
events
fs
http
http2
https
inspector
module
net
os
path
perf_hooks
process
punycode
querystring
readline
repl
stream
string_decoder
sys
timers
tls
trace_events
tty
url
util
v8
vm
wasi
worker_threads
zlib
```

- [ ] **Step 6.7: Implement dep_detect**

```python
# src/scriptdeck/services/dep_detect.py
from __future__ import annotations

import ast
import re
from importlib import resources


def _stdlib_set() -> set[str]:
    txt = (resources.files("scriptdeck").joinpath("data/python_stdlib.txt")
           .read_text(encoding="utf-8"))
    return {line.strip() for line in txt.splitlines() if line.strip()}


def _node_builtin_set() -> set[str]:
    txt = (resources.files("scriptdeck").joinpath("data/node_stdlib.txt")
           .read_text(encoding="utf-8"))
    return {line.strip() for line in txt.splitlines() if line.strip()}


def detect_python_deps(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                names.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                names.add(node.module.split(".")[0])
    stdlib = _stdlib_set()
    return sorted(n for n in names if n and n not in stdlib)


_NODE_RE = re.compile(
    r"""(?:require\(\s*['"]([^'"]+)['"]\s*\)|from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)|import\s+['"]([^'"]+)['"])"""
)


def detect_node_deps(source: str) -> list[str]:
    builtins = _node_builtin_set()
    out: set[str] = set()
    for match in _NODE_RE.finditer(source):
        spec = next(g for g in match.groups() if g)
        if spec.startswith((".", "/")):
            continue
        if spec.startswith("node:"):
            spec = spec[5:]
        root = spec.split("/")[0]
        if root.startswith("@"):
            parts = spec.split("/")
            if len(parts) >= 2:
                root = f"{parts[0]}/{parts[1]}"
        if root and root not in builtins:
            out.add(root)
    return sorted(out)


def detect_deps_for_language(language: str, source: str) -> list[str]:
    if language == "python":
        return detect_python_deps(source)
    if language == "node":
        return detect_node_deps(source)
    return []
```

```python
# src/scriptdeck/runner/__init__.py
from scriptdeck.runner.protocol import LanguageRunner
from scriptdeck.runner.registry import RUNNERS, get_runner

__all__ = ["LanguageRunner", "RUNNERS", "get_runner"]
```

- [ ] **Step 6.8: Add dep_detect tests**

```python
# tests/test_dep_detect.py
from scriptdeck.services.dep_detect import detect_python_deps, detect_node_deps


def test_python_basic_imports():
    src = """
import requests
from pandas import DataFrame
import os
from .local import thing
"""
    assert detect_python_deps(src) == ["pandas", "requests"]


def test_python_syntax_error_returns_empty():
    assert detect_python_deps("def broken(:") == []


def test_node_requires_and_imports():
    src = """
const a = require('axios');
import { foo } from 'lodash';
import x from './local';
const path = require('path');
"""
    assert detect_node_deps(src) == ["axios", "lodash"]


def test_node_scoped_packages():
    src = "import { foo } from '@scope/pkg';"
    assert detect_node_deps(src) == ["@scope/pkg"]


def test_node_node_prefix():
    src = "const fs = require('node:fs');"
    assert detect_node_deps(src) == []
```

- [ ] **Step 6.9: Run all tests, expect pass**

```bash
uv run pytest tests/test_runner_protocol.py tests/test_dep_detect.py -v
```

Expected: 9 passed.

- [ ] **Step 6.10: Commit**

```bash
git add src/scriptdeck/runner/ src/scriptdeck/services/dep_detect.py data/
git add tests/test_runner_protocol.py tests/test_dep_detect.py
git commit -m "feat(runner): LanguageRunner protocol + Python + Node + dep_detect"
```

---

### Task 7: EnvService — AES-GCM encrypt/decrypt

**Files:**
- Create: `src/scriptdeck/services/env_service.py`
- Create: `tests/test_env_service.py`

**Steps:**

- [ ] **Step 7.1: Write failing tests**

```python
# tests/test_env_service.py
import base64
import pytest

from scriptdeck.services.env_service import EnvService


@pytest.fixture
def svc():
    key = base64.b64encode(b"k" * 32).decode()
    return EnvService(key)


def test_encrypt_decrypt_roundtrip(svc):
    ct, nonce = svc.encrypt(b"FOO=bar\nBAZ=qux\n")
    assert svc.decrypt(ct, nonce) == b"FOO=bar\nBAZ=qux\n"


def test_decrypt_lines(svc):
    ct, nonce = svc.encrypt(b"FOO=bar\nBAZ=qux\n")
    assert svc.decrypt_lines(ct, nonce) == {"FOO": "bar", "BAZ": "qux"}


def test_wrong_key_fails():
    k1 = base64.b64encode(b"a" * 32).decode()
    k2 = base64.b64encode(b"b" * 32).decode()
    s1 = EnvService(k1)
    s2 = EnvService(k2)
    ct, nonce = s1.encrypt(b"x=1")
    with pytest.raises(Exception):
        s2.decrypt(ct, nonce)


def test_invalid_key_length():
    with pytest.raises(ValueError):
        EnvService(base64.b64encode(b"short").decode())
```

- [ ] **Step 7.2: Run, expect failure**

Run: `uv run pytest tests/test_env_service.py -v`

- [ ] **Step 7.3: Implement EnvService**

```python
# src/scriptdeck/services/env_service.py
from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EnvService:
    """AES-GCM encrypt/decrypt for per-script .env blobs."""

    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.b64decode(key_b64)
        except Exception as exc:
            raise ValueError(f"invalid base64 key: {exc}") from exc
        if len(key) != 32:
            raise ValueError("env_encryption_key must decode to 32 bytes")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> tuple[str, str]:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext, associated_data=None)
        return base64.b64encode(ct).decode(), base64.b64encode(nonce).decode()

    def decrypt(self, ct_b64: str, nonce_b64: str) -> bytes:
        ct = base64.b64decode(ct_b64)
        nonce = base64.b64decode(nonce_b64)
        return self._aes.decrypt(nonce, ct, associated_data=None)

    def decrypt_lines(self, ct_b64: str, nonce_b64: str) -> dict[str, str]:
        raw = self.decrypt(ct_b64, nonce_b64).decode("utf-8")
        out: dict[str, str] = {}
        for line in raw.splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
        return out
```

- [ ] **Step 7.4: Add cryptography dep + run tests**

```toml
# Append to pyproject.toml dependencies:
"cryptography>=42.0",
```

```bash
uv lock
uv run pytest tests/test_env_service.py -v
```

Expected: 4 passed.

- [ ] **Step 7.5: Commit**

```bash
git add src/scriptdeck/services/env_service.py tests/test_env_service.py pyproject.toml uv.lock
git commit -m "feat(env): AES-GCM EnvService for per-script .env encryption"
```

---

### Task 8: LogBroker — in-memory pub/sub for SSE

**Files:**
- Create: `src/scriptdeck/services/log_broker.py`
- Create: `tests/test_log_broker.py`

**Steps:**

- [ ] **Step 8.1: Write failing tests**

```python
# tests/test_log_broker.py
import asyncio

import pytest

from scriptdeck.services.log_broker import LogBroker


@pytest.mark.asyncio
async def test_subscribe_yields_published_lines():
    broker = LogBroker()
    q = await broker.subscribe(run_id=1)
    await broker.publish(1, "hello\n", offset=0)
    await broker.publish(1, "world\n", offset=6)
    await broker.close(1, status="success", exit_code=0)
    events = []
    async for chunk in q:
        events.append(chunk.decode())
        if "event: end" in chunk.decode():
            break
    assert any('"hello"' in e for e in events)
    assert any('"world"' in e for e in events)
    assert any('event: end' in e for e in events)


@pytest.mark.asyncio
async def test_close_is_idempotent():
    broker = LogBroker()
    q = await broker.subscribe(run_id=2)
    await broker.close(2, "success", 0)
    await broker.close(2, "success", 0)
    seen_end = False
    async for chunk in q:
        if "event: end" in chunk.decode():
            seen_end = True
            break
    assert seen_end
```

- [ ] **Step 8.2: Run, expect failure**

Run: `uv run pytest tests/test_log_broker.py -v`

- [ ] **Step 8.3: Implement LogBroker**

```python
# src/scriptdeck/services/log_broker.py
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import AsyncIterator


def encode_sse(data: dict, event: str | None = None) -> bytes:
    parts: list[str] = []
    if event:
        parts.append(f"event: {event}\n")
    parts.append(f"data: {json.dumps(data)}\n\n")
    return "".join(parts).encode("utf-8")


def encode_heartbeat() -> bytes:
    return b": heartbeat\n\n"


@dataclass
class _RunChannel:
    queues: set[asyncio.Queue[bytes]] = field(default_factory=set)
    ended: bool = False
    end_status: str | None = None
    end_exit: int | None = None


class LogBroker:
    """In-memory pub/sub for live run logs."""

    def __init__(self, heartbeat_seconds: float = 15.0) -> None:
        self._channels: dict[int, _RunChannel] = {}
        self._heartbeat = heartbeat_seconds
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: int) -> AsyncIterator[bytes]:
        async with self._lock:
            ch = self._channels.get(run_id)
            if ch is None:
                ch = _RunChannel()
                self._channels[run_id] = ch
            if ch.ended:
                yield encode_sse(
                    {"status": ch.end_status, "exit_code": ch.end_exit}, event="end"
                )
                return
            q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=1024)
            ch.queues.add(q)
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=self._heartbeat)
                    yield chunk
                except asyncio.TimeoutError:
                    yield encode_heartbeat()
        finally:
            async with self._lock:
                ch.queues.discard(q)

    async def publish(self, run_id: int, text: str, offset: int) -> None:
        async with self._lock:
            ch = self._channels.get(run_id)
            if ch is None or ch.ended:
                return
            queues = list(ch.queues)
            payload = encode_sse({"offset": offset, "text": text}, event="line")
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def close(self, run_id: int, status: str, exit_code: int) -> None:
        async with self._lock:
            ch = self._channels.get(run_id)
            if ch is None:
                ch = _RunChannel()
                self._channels[run_id] = ch
            if ch.ended:
                return
            ch.ended = True
            ch.end_status = status
            ch.end_exit = exit_code
            queues = list(ch.queues)
            payload = encode_sse({"status": status, "exit_code": exit_code}, event="end")
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass


_broker: LogBroker | None = None


def get_broker() -> LogBroker:
    global _broker
    if _broker is None:
        _broker = LogBroker()
    return _broker
```

- [ ] **Step 8.4: Run tests, expect pass**

```bash
uv run pytest tests/test_log_broker.py -v
```

Expected: 2 passed.

- [ ] **Step 8.5: Commit**

```bash
git add src/scriptdeck/services/log_broker.py tests/test_log_broker.py
git commit -m "feat(log): LogBroker in-memory pub/sub for SSE streams"
```

---

### Task 9: Runner executor — subprocess + per-script lock + LogBroker hookup

**Files:**
- Create: `src/scriptdeck/runner/lock.py`
- Create: `src/scriptdeck/runner/executor.py`
- Create: `tests/test_executor.py`

**Steps:**

- [ ] **Step 9.1: Write failing executor test**

```python
# tests/test_executor.py
import asyncio
from pathlib import Path

import pytest

from scriptdeck.runner.executor import run_script


@pytest.mark.asyncio
async def test_run_script_success(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    src = work / "hi.py"
    src.write_text("print('hello')\n")
    logs = tmp_path / "logs"
    logs.mkdir()

    class FakeScript:
        id = 1
        name = "hi"
        language = "python"
        source_path = src
        requirements: list[str] = []

    class FakeEnvService:
        def decrypt_lines(self, *args, **kwargs):
            return {}

    from scriptdeck.services.log_broker import LogBroker
    broker = LogBroker()
    sem = asyncio.Semaphore(4)

    result = await run_script(
        run_id=42,
        script=FakeScript(),  # type: ignore[arg-type]
        env_service=FakeEnvService(),  # type: ignore[arg-type]
        log_broker=broker,
        concurrency=sem,
        storage_dir=tmp_path,
    )
    assert result.exit_code == 0
    assert (logs / "42.log").exists()
    assert "hello" in (logs / "42.log").read_text()
```

- [ ] **Step 9.2: Run, expect failure**

Run: `uv run pytest tests/test_executor.py -v`

- [ ] **Step 9.3: Implement lock**

```python
# src/scriptdeck/runner/lock.py
from __future__ import annotations

import asyncio
import fcntl
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

_process_locks: dict[int, asyncio.Lock] = {}
_process_locks_guard = asyncio.Lock()


async def _get_lock(script_id: int) -> asyncio.Lock:
    async with _process_locks_guard:
        lock = _process_locks.get(script_id)
        if lock is None:
            lock = asyncio.Lock()
            _process_locks[script_id] = lock
        return lock


@asynccontextmanager
async def per_script_lock(script_id: int, locks_dir: Path) -> AsyncIterator[None]:
    """Per-script lock combining asyncio.Lock + fcntl.flock sentinel.

    fcntl layer survives crashes; asyncio layer prevents intra-process races.
    """
    locks_dir.mkdir(parents=True, exist_ok=True)
    sentinel = locks_dir / f"{script_id}.lock"
    inner = await _get_lock(script_id)
    async with inner:
        with sentinel.open("a") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
```

- [ ] **Step 9.4: Implement executor**

```python
# src/scriptdeck/runner/executor.py
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scriptdeck.runner.lock import per_script_lock
from scriptdeck.runner.registry import get_runner
from scriptdeck.services.log_broker import LogBroker


@dataclass
class Script:
    id: int
    name: str
    language: str
    source_path: Path
    requirements: list[str]


@dataclass
class RunResult:
    exit_code: int
    log_path: Path


class EnvLike(Protocol):
    def decrypt_lines(self, *args, **kwargs) -> dict[str, str]: ...


async def run_script(
    *,
    run_id: int,
    script: Script,
    env_service: EnvLike,
    log_broker: LogBroker,
    concurrency: asyncio.Semaphore,
    storage_dir: Path,
) -> RunResult:
    logs_dir = storage_dir / "logs"
    scripts_dir = storage_dir / "scripts"
    venvs_dir = storage_dir / "venvs"
    node_modules_dir = storage_dir / "node_modules"
    locks_dir = storage_dir / "locks"
    logs_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    venvs_dir.mkdir(parents=True, exist_ok=True)
    node_modules_dir.mkdir(parents=True, exist_ok=True)

    log_path = logs_dir / f"{run_id}.log"
    script_work = scripts_dir / str(script.id)
    script_work.mkdir(parents=True, exist_ok=True)
    if script.language == "python":
        work_dir = venvs_dir / str(script.id)
    else:
        work_dir = node_modules_dir / str(script.id)
    work_dir.mkdir(parents=True, exist_ok=True)

    async with concurrency:
        async with per_script_lock(script.id, locks_dir):
            runner = get_runner(script.language)
            interpreter = await runner.provision(work_dir, script.requirements)
            merged_env: dict[str, str] = dict(os.environ)
            try:
                env_lines = env_service.decrypt_lines("", "")
                if isinstance(env_lines, dict):
                    merged_env.update(env_lines)
            except Exception:
                pass

            log_fh = log_path.open("wb")
            offset = 0
            try:
                proc = await asyncio.create_subprocess_exec(
                    *runner.build_command(interpreter, script.source_path, merged_env),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(work_dir),
                )
                assert proc.stdout is not None
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
                log_fh.close()
    status = "success" if exit_code == 0 else "failure"
    await log_broker.close(run_id, status=status, exit_code=exit_code)
    return RunResult(exit_code=exit_code, log_path=log_path)
```

- [ ] **Step 9.5: Run tests, expect pass**

```bash
uv run pytest tests/test_executor.py -v
```

Expected: 1 passed. (Requires `uv` + `python` on PATH; CI image provides both.)

- [ ] **Step 9.6: Commit**

```bash
git add src/scriptdeck/runner/lock.py src/scriptdeck/runner/executor.py tests/test_executor.py
git commit -m "feat(runner): executor with per-script lock + LogBroker hookup"
```

---

### Task 10: Scheduler tick

**Files:**
- Create: `src/scriptdeck/scheduler/__init__.py`
- Create: `src/scriptdeck/scheduler/tick.py`
- Create: `src/scriptdeck/services/schedule_service.py`
- Create: `src/scriptdeck/services/run_service.py`
- Create: `tests/test_scheduler.py`

**Steps:**

- [ ] **Step 10.1: Implement schedule service**

```python
# src/scriptdeck/services/schedule_service.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _table():
    from scriptdeck.db.models import schedules as _schedules
    return _schedules


def _scripts():
    from scriptdeck.db.models import scripts as _scripts
    return _scripts


def advance_next_run(kind: str, expression: str, prev_next_run: str) -> str:
    if kind == "cron":
        it = croniter(expression, datetime.fromisoformat(prev_next_run))
        return it.get_next(datetime).isoformat()
    if kind == "interval":
        n = int(expression[:-1])
        unit = expression[-1]
        delta = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        return (datetime.fromisoformat(prev_next_run) + timedelta(seconds=n * delta)).isoformat()
    raise ValueError(f"unknown kind: {kind}")


async def list_due(session: AsyncSession, now: datetime) -> list[dict[str, Any]]:
    t = _table()
    s = _scripts()
    stmt = (
        select(t, s.c.language, s.c.name, s.c.source_path)
        .where(t.c.enabled == 1, t.c.next_run_at <= now.isoformat())
        .join(s, t.c.script_id == s.c.id)
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


async def advance(session: AsyncSession, schedule_id: int, new_next_run: str) -> None:
    t = _table()
    await session.execute(
        update(t).where(t.c.id == schedule_id).values(next_run_at=new_next_run)
    )
```

```python
# src/scriptdeck/services/run_service.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


def _table():
    from scriptdeck.db.models import runs as _runs
    return _runs


async def create_run(
    session: AsyncSession, *, script_id: int, schedule_id: int | None, status: str = "running"
) -> int:
    t = _table()
    stmt = (
        insert(t)
        .values(script_id=script_id, schedule_id=schedule_id, status=status)
        .returning(t.c.id)
    )
    return int((await session.execute(stmt)).scalar_one())


async def has_active_run(session: AsyncSession, script_id: int) -> bool:
    t = _table()
    stmt = select(t.c.id).where(t.c.script_id == script_id, t.c.status == "running")
    return (await session.execute(stmt)).first() is not None


async def finalize_run(
    session: AsyncSession, *, run_id: int, exit_code: int, status: str
) -> None:
    t = _table()
    now = datetime.now(timezone.utc).isoformat()
    await session.execute(
        update(t)
        .where(t.c.id == run_id)
        .values(ended_at=now, exit_code=exit_code, status=status)
    )
```

- [ ] **Step 10.2: Implement scheduler tick**

```python
# src/scriptdeck/scheduler/tick.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from scriptdeck.runner.executor import Script, run_script
from scriptdeck.services.log_broker import LogBroker
from scriptdeck.services.run_service import (
    create_run, finalize_run, has_active_run,
)
from scriptdeck.services.schedule_service import advance, advance_next_run, list_due

log = logging.getLogger(__name__)


async def scheduler_loop(
    *,
    settings,
    session_factory,
    log_broker: LogBroker,
    env_service,
    concurrency: asyncio.Semaphore,
    stop_event: asyncio.Event,
    storage_dir: Path,
) -> None:
    while not stop_event.is_set():
        try:
            await _tick(
                settings=settings,
                session_factory=session_factory,
                log_broker=log_broker,
                env_service=env_service,
                concurrency=concurrency,
                storage_dir=storage_dir,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("scheduler tick failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_interval)
        except asyncio.TimeoutError:
            pass


async def _tick(*, settings, session_factory, log_broker, env_service, concurrency, storage_dir):
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        due = await list_due(s, now)
        for row in due:
            sid = row["script_id"]
            if await has_active_run(s, sid):
                run_id = await create_run(
                    s, script_id=sid, schedule_id=row["id"], status="error"
                )
                new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
                await advance(s, row["id"], new_next)
                await finalize_run(s, run_id=run_id, exit_code=-1, status="error")
                await s.commit()
                await log_broker.close(run_id, "error", -1)
                continue

            new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
            run_id = await create_run(s, script_id=sid, schedule_id=row["id"])
            await advance(s, row["id"], new_next)
            await s.commit()

            script = Script(
                id=sid,
                name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"],
                requirements=[],
            )
            asyncio.create_task(
                _execute_and_finalize(
                    run_id=run_id, script=script, env_service=env_service,
                    log_broker=log_broker, concurrency=concurrency,
                    storage_dir=storage_dir, session_factory=session_factory,
                )
            )


async def _execute_and_finalize(*, run_id, script, env_service, log_broker, concurrency, storage_dir, session_factory):
    result = await run_script(
        run_id=run_id, script=script, env_service=env_service,
        log_broker=log_broker, concurrency=concurrency, storage_dir=storage_dir,
    )
    status = "success" if result.exit_code == 0 else "failure"
    async with session_factory() as s:
        await finalize_run(s, run_id=run_id, exit_code=result.exit_code, status=status)
        await s.commit()
```

- [ ] **Step 10.3: Wire scheduler into app lifespan**

In `src/scriptdeck/app.py` lifespan, after engine ready:

```python
import asyncio
import base64
from pathlib import Path
from scriptdeck.services.env_service import EnvService
from scriptdeck.services.log_broker import get_broker
from scriptdeck.scheduler.tick import scheduler_loop

env_service = EnvService(settings.env_encryption_key or base64.b64encode(b"\0" * 32).decode())
broker = get_broker()
sem = asyncio.Semaphore(settings.runner_concurrency)
stop_event = asyncio.Event()

app.state.env_service = env_service
app.state.log_broker = broker
app.state.runner_sem = sem
app.state.stop_event = stop_event
app.state.scheduler_running = True

task = asyncio.create_task(scheduler_loop(
    settings=settings, session_factory=app.state.session_factory,
    log_broker=broker, env_service=env_service, concurrency=sem,
    stop_event=stop_event, storage_dir=Path(settings.storage_dir),
))
app.state.scheduler_task = task

try:
    yield
finally:
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=5)
    except asyncio.TimeoutError:
        task.cancel()
    await engine.dispose()
```

- [ ] **Step 10.4: Write scheduler test**

```python
# tests/test_scheduler.py
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, update

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations
from scriptdeck.scheduler.tick import _tick
from scriptdeck.services.log_broker import LogBroker


@pytest.mark.asyncio
async def test_tick_due_schedule_dispatches(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"),
                        storage_dir=str(tmp_path / "s"),
                        scheduler_interval=1, runner_concurrency=2)
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    now = datetime.now(timezone.utc).isoformat()

    from scriptdeck.db.models import scripts, schedules
    async with Sf() as s:
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python", source_path="scripts/1/main.py",
        ))
        await s.execute(insert(schedules).values(
            script_id=1, kind="interval", expression="5m", next_run_at=now,
        ))
        await s.commit()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw):
            return {}

    await _tick(
        settings=settings, session_factory=Sf, log_broker=broker,
        env_service=FakeEnv(), concurrency=sem, storage_dir=tmp_path / "s",
    )
    await asyncio.sleep(2)

    async with Sf() as s:
        from sqlalchemy import text
        rows = (await s.execute(text("SELECT status FROM runs"))).all()
    statuses = [r[0] for r in rows]
    assert "success" in statuses
```

- [ ] **Step 10.5: Run, expect pass**

```bash
uv run pytest tests/test_scheduler.py -v
```

- [ ] **Step 10.6: Commit**

```bash
git add src/scriptdeck/scheduler/ src/scriptdeck/services/ tests/test_scheduler.py src/scriptdeck/app.py
git commit -m "feat(scheduler): 5s tick + skip-on-overlap + advance next_run"
```

---

### Task 11: Scripts + Schedules + Runs + Deps + Env API

**Files:**
- Create: `src/scriptdeck/services/script_service.py`
- Create: `src/scriptdeck/api/scripts.py`
- Create: `src/scriptdeck/api/schedules.py`
- Create: `src/scriptdeck/api/runs.py`
- Create: `src/scriptdeck/api/deps.py`
- Create: `src/scriptdeck/api/envs.py`
- Create: `tests/test_scripts_api.py`

**Steps:**

- [ ] **Step 11.1: Implement script service**

```python
# src/scriptdeck/services/script_service.py
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ScriptRow:
    id: int
    name: str
    language: str
    source_path: str
    requirements_path: str | None
    interpreter_path: str | None
    description: str | None


def _table():
    from scriptdeck.db.models import scripts
    return scripts


async def create_script(
    session: AsyncSession,
    *,
    name: str,
    language: str,
    source_path: str,
    description: str | None = None,
) -> ScriptRow:
    t = _table()
    stmt = (
        insert(t)
        .values(name=name, language=language, source_path=source_path, description=description)
        .returning(*t.c)
    )
    return ScriptRow(**(await session.execute(stmt)).mappings().one())


async def get_script(session: AsyncSession, script_id: int) -> ScriptRow | None:
    t = _table()
    row = (await session.execute(select(t).where(t.c.id == script_id))).mappings().one_or_none()
    return ScriptRow(**row) if row else None


async def list_scripts(
    session: AsyncSession,
    language: str | None = None,
    q: str | None = None,
    limit: int = 50,
) -> list[ScriptRow]:
    t = _table()
    stmt = select(t).order_by(t.c.id.desc()).limit(limit)
    if language:
        stmt = stmt.where(t.c.language == language)
    if q:
        stmt = stmt.where(t.c.name.like(f"%{q}%"))
    return [ScriptRow(**r) for r in (await session.execute(stmt)).mappings().all()]


async def update_script(
    session: AsyncSession, script_id: int, *, name: str | None = None,
    description: str | None = None, source_path: str | None = None,
) -> bool:
    values = {k: v for k, v in (
        ("name", name), ("description", description), ("source_path", source_path),
    ) if v is not None}
    if not values:
        return True
    t = _table()
    result = await session.execute(update(t).where(t.c.id == script_id).values(**values))
    return bool(result.rowcount)


async def delete_script(session: AsyncSession, script_id: int) -> bool:
    t = _table()
    result = await session.execute(delete(t).where(t.c.id == script_id))
    return bool(result.rowcount)
```

- [ ] **Step 11.2: Add storage_dir_path helper to Settings**

```python
# Append to src/scriptdeck/config.py:
from pathlib import Path

@property
def storage_dir_path(self) -> Path:
    return Path(self.storage_dir)
```

- [ ] **Step 11.3: Implement scripts API**

```python
# src/scriptdeck/api/scripts.py
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services import script_service

router = APIRouter(prefix="/scripts")


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(pattern="^(python|node)$")
    source: str = Field(min_length=1)
    description: str | None = None


class ScriptOut(BaseModel):
    id: int
    name: str
    language: str
    source_path: str
    description: str | None


class ScriptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: str | None = None


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


@router.get("")
async def list_endpoint(
    request: Request,
    language: str | None = None,
    q: str | None = None,
    limit: int = 50,
    user: User = Depends(current_user),
) -> list[ScriptOut]:
    sf = request.app.state.session_factory
    async with sf() as s:
        rows = await script_service.list_scripts(s, language=language, q=q, limit=limit)
    return [ScriptOut(id=r.id, name=r.name, language=r.language,
                      source_path=r.source_path, description=r.description) for r in rows]


@router.post("", status_code=201)
async def create(
    body: ScriptCreate, request: Request, user: User = Depends(current_user)
) -> ScriptOut:
    _require(user)
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        row = await script_service.create_script(
            s, name=body.name, language=body.language,
            source_path=f"scripts/PLACEHOLDER", description=body.description,
        )
        script_dir = storage / "scripts" / str(row.id)
        script_dir.mkdir(parents=True, exist_ok=True)
        ext = "py" if body.language == "python" else "js"
        path = script_dir / f"main.{ext}"
        path.write_text(body.source, encoding="utf-8")
        await script_service.update_script(s, row.id, source_path=str(path.relative_to(storage)))
        await s.commit()
        new = await script_service.get_script(s, row.id)
    assert new is not None
    return ScriptOut(id=new.id, name=new.name, language=new.language,
                     source_path=new.source_path, description=new.description)


@router.get("/{script_id}")
async def detail(script_id: int, request: Request,
                 user: User = Depends(current_user)) -> ScriptOut:
    sf = request.app.state.session_factory
    async with sf() as s:
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return ScriptOut(id=row.id, name=row.name, language=row.language,
                     source_path=row.source_path, description=row.description)


@router.put("/{script_id}")
async def update(
    script_id: int, body: ScriptUpdate, request: Request, user: User = Depends(current_user)
) -> ScriptOut:
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        await script_service.update_script(
            s, script_id, name=body.name, description=body.description,
        )
        if body.source is not None:
            row = await script_service.get_script(s, script_id)
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
            Path(row.source_path).write_text(body.source, encoding="utf-8")
        await s.commit()
        new = await script_service.get_script(s, script_id)
    if new is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return ScriptOut(id=new.id, name=new.name, language=new.language,
                     source_path=new.source_path, description=new.description)


@router.delete("/{script_id}", status_code=204)
async def remove(script_id: int, request: Request,
                 user: User = Depends(current_user)):
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        ok = await script_service.delete_script(s, script_id)
        await s.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return None
```

- [ ] **Step 11.4: Implement deps + envs endpoints**

```python
# src/scriptdeck/api/deps.py
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services import script_service
from scriptdeck.services.dep_detect import detect_deps_for_language

router = APIRouter(prefix="/scripts")


def _table():
    from scriptdeck.db.models import script_deps
    return script_deps


class DepsOut(BaseModel):
    deps: list[str]
    source: str


class DepsIn(BaseModel):
    deps: list[str] = Field(default_factory=list)
    source: str = Field(pattern="^(auto|manual)$")


@router.get("/{script_id}/deps")
async def get_deps(script_id: int, request: Request,
                   user: User = Depends(current_user)) -> DepsOut:
    sf = request.app.state.session_factory
    async with sf() as s:
        t = _table()
        row = (await s.execute(select(t).where(t.c.script_id == script_id))).mappings().one_or_none()
        if row is None:
            return DepsOut(deps=[], source="manual")
        return DepsOut(deps=json.loads(row["deps_json"]), source=row["source"])


@router.post("/{script_id}/deps/detect")
async def detect(script_id: int, request: Request,
                 user: User = Depends(current_user)) -> DepsOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")
    sf = request.app.state.session_factory
    async with sf() as s:
        row = await script_service.get_script(s, script_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        source_text = Path(row.source_path).read_text(encoding="utf-8")  # noqa: F821 (Path imported)
        deps = detect_deps_for_language(row.language, source_text)
    return DepsOut(deps=deps, source="auto")


@router.put("/{script_id}/deps")
async def set_deps(script_id: int, body: DepsIn, request: Request,
                   user: User = Depends(current_user)) -> DepsOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")
    sf = request.app.state.session_factory
    now = datetime.now(timezone.utc).isoformat()
    async with sf() as s:
        t = _table()
        existing = (await s.execute(select(t).where(t.c.script_id == script_id))).first()
        if existing:
            await s.execute(
                update(t).where(t.c.script_id == script_id).values(
                    deps_json=json.dumps(body.deps), source=body.source, updated_at=now,
                )
            )
        else:
            await s.execute(insert(t).values(
                script_id=script_id, deps_json=json.dumps(body.deps),
                source=body.source, updated_at=now,
            ))
        await s.commit()
    return body
```

Add `from pathlib import Path` to the top of `src/scriptdeck/api/deps.py`.

```python
# src/scriptdeck/api/envs.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services.env_service import EnvService

router = APIRouter(prefix="/scripts")


def _table():
    from scriptdeck.db.models import script_envs
    return script_envs


class EnvOut(BaseModel):
    has_env: bool
    line_count: int = 0
    updated_at: str | None = None


class EnvIn(BaseModel):
    content: str = Field(default="")


@router.get("/{script_id}/env")
async def get_env(script_id: int, request: Request,
                  user: User = Depends(current_user)) -> EnvOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot read env metadata")
    sf = request.app.state.session_factory
    async with sf() as s:
        t = _table()
        row = (await s.execute(select(t).where(t.c.script_id == script_id))).mappings().one_or_none()
    if row is None:
        return EnvOut(has_env=False)
    env: EnvService = request.app.state.env_service
    try:
        lines = env.decrypt_lines(row["ciphertext"], row["nonce"])
    except Exception:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="decrypt failed")
    return EnvOut(has_env=True, line_count=len(lines), updated_at=row["updated_at"])


@router.put("/{script_id}/env")
async def set_env(script_id: int, body: EnvIn, request: Request,
                  user: User = Depends(current_user)) -> EnvOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify env")
    sf = request.app.state.session_factory
    env: EnvService = request.app.state.env_service
    cipher, nonce = env.encrypt(body.content.encode("utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    async with sf() as s:
        t = _table()
        existing = (await s.execute(select(t).where(t.c.script_id == script_id))).first()
        if existing:
            await s.execute(
                update(t).where(t.c.script_id == script_id).values(
                    ciphertext=cipher, nonce=nonce, updated_at=now,
                )
            )
        else:
            await s.execute(insert(t).values(
                script_id=script_id, ciphertext=cipher, nonce=nonce, updated_at=now,
            ))
        from scriptdeck.services.audit import record as audit
        await audit(s, user.id, "env_updated", "script", script_id)
        await s.commit()
    return EnvOut(has_env=True, line_count=len(body.content.splitlines()), updated_at=now)


@router.delete("/{script_id}/env")
async def delete_env(script_id: int, request: Request,
                     user: User = Depends(current_user)) -> dict:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify env")
    sf = request.app.state.session_factory
    async with sf() as s:
        t = _table()
        await s.execute(delete(t).where(t.c.script_id == script_id))
        from scriptdeck.services.audit import record as audit
        await audit(s, user.id, "env_deleted", "script", script_id)
        await s.commit()
    return {"ok": True}
```

- [ ] **Step 11.5: Implement schedules + runs API**

```python
# src/scriptdeck/api/schedules.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services.schedule_service import advance_next_run

router = APIRouter(prefix="/schedules")


def _table():
    from scriptdeck.db.models import schedules
    return schedules


class ScheduleCreate(BaseModel):
    script_id: int
    kind: str = Field(pattern="^(cron|interval)$")
    expression: str = Field(min_length=1)
    enabled: bool = True
    retry_max: int = 0
    retry_backoff: int = 0


class ScheduleOut(BaseModel):
    id: int
    script_id: int
    kind: str
    expression: str
    enabled: bool
    next_run_at: str
    retry_max: int
    retry_backoff: int


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


def _row_to_out(row) -> ScheduleOut:
    return ScheduleOut(
        id=row["id"], script_id=row["script_id"], kind=row["kind"],
        expression=row["expression"], enabled=bool(row["enabled"]),
        next_run_at=row["next_run_at"], retry_max=row["retry_max"],
        retry_backoff=row["retry_backoff"],
    )


@router.get("")
async def list_endpoint(request: Request, script_id: int | None = None,
                       user: User = Depends(current_user)) -> list[ScheduleOut]:
    sf = request.app.state.session_factory
    t = _table()
    stmt = select(t).order_by(t.c.id)
    if script_id is not None:
        stmt = stmt.where(t.c.script_id == script_id)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [_row_to_out(r) for r in rows]


@router.post("", status_code=201)
async def create(body: ScheduleCreate, request: Request,
                 user: User = Depends(current_user)) -> ScheduleOut:
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(timezone.utc).isoformat()
    initial_next = advance_next_run(body.kind, body.expression, now)
    async with sf() as s:
        stmt = (
            insert(t).values(
                script_id=body.script_id, kind=body.kind, expression=body.expression,
                enabled=1 if body.enabled else 0, next_run_at=initial_next,
                retry_max=body.retry_max, retry_backoff=body.retry_backoff,
            ).returning(*t.c)
        )
        row = (await s.execute(stmt)).mappings().one()
        await s.commit()
    return _row_to_out(row)


@router.put("/{schedule_id}")
async def update(schedule_id: int, body: ScheduleCreate, request: Request,
                 user: User = Depends(current_user)) -> ScheduleOut:
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(timezone.utc).isoformat()
    new_next = advance_next_run(body.kind, body.expression, now)
    async with sf() as s:
        await s.execute(update(t).where(t.c.id == schedule_id).values(
            kind=body.kind, expression=body.expression,
            enabled=1 if body.enabled else 0, next_run_at=new_next,
            retry_max=body.retry_max, retry_backoff=body.retry_backoff,
        ))
        await s.commit()
        row = (await s.execute(select(t).where(t.c.id == schedule_id))).mappings().one()
    return _row_to_out(row)


@router.delete("/{schedule_id}", status_code=204)
async def remove(schedule_id: int, request: Request, user: User = Depends(current_user)):
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        await s.execute(delete(t).where(t.c.id == schedule_id))
        await s.commit()
    return None


@router.post("/{schedule_id}/enable")
async def enable(schedule_id: int, request: Request,
                 user: User = Depends(current_user)) -> dict:
    _require(user)
    return await _set_enabled(schedule_id, True, request)


@router.post("/{schedule_id}/disable")
async def disable(schedule_id: int, request: Request,
                  user: User = Depends(current_user)) -> dict:
    _require(user)
    return await _set_enabled(schedule_id, False, request)


async def _set_enabled(schedule_id: int, enabled: bool, request: Request) -> dict:
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        await s.execute(update(t).where(t.c.id == schedule_id).values(
            enabled=1 if enabled else 0,
        ))
        await s.commit()
    return {"ok": True, "enabled": enabled}
```

```python
# src/scriptdeck/api/runs.py
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.runner.executor import Script, run_script
from scriptdeck.services import run_service, script_service

router = APIRouter(prefix="/runs")


def _runs_table():
    from scriptdeck.db.models import runs
    return runs


def _deps_table():
    from scriptdeck.db.models import script_deps
    return script_deps


class RunTrigger(BaseModel):
    script_id: int


class RunOut(BaseModel):
    id: int
    script_id: int
    schedule_id: int | None
    started_at: str
    ended_at: str | None
    exit_code: int | None
    status: str


@router.get("")
async def list_endpoint(request: Request, script_id: int | None = None,
                        status_filter: str | None = None, since: str | None = None,
                        limit: int = 50, user: User = Depends(current_user)) -> list[RunOut]:
    sf = request.app.state.session_factory
    t = _runs_table()
    stmt = select(t).order_by(t.c.id.desc()).limit(limit)
    if script_id:
        stmt = stmt.where(t.c.script_id == script_id)
    if status_filter:
        stmt = stmt.where(t.c.status == status_filter)
    if since:
        stmt = stmt.where(t.c.started_at >= since)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [RunOut(**dict(r)) for r in rows]


@router.post("", status_code=201)
async def trigger(body: RunTrigger, request: Request,
                  user: User = Depends(current_user)) -> RunOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot trigger")
    sf = request.app.state.session_factory
    async with sf() as s:
        script = await script_service.get_script(s, body.script_id)
        if script is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="script not found")
        run_id = await run_service.create_run(s, script_id=script.id, schedule_id=None)
        deps_row = (await s.execute(
            select(_deps_table()).where(_deps_table().c.script_id == script.id)
        )).mappings().one_or_none()
        deps = json.loads(deps_row["deps_json"]) if deps_row else []
        started = (
            await s.execute(select(_runs_table().c.started_at).where(_runs_table().c.id == run_id))
        ).scalar_one()
        await s.commit()
    storage = Path(request.app.state.settings.storage_dir)
    runner_script = Script(
        id=script.id, name=script.name, language=script.language,
        source_path=storage / script.source_path, requirements=deps,
    )
    asyncio.create_task(
        _execute_and_finalize(
            run_id=run_id, script=runner_script, app=request.app,
        )
    )
    return RunOut(id=run_id, script_id=script.id, schedule_id=None,
                  started_at=started, ended_at=None, exit_code=None, status="running")


async def _execute_and_finalize(*, run_id, script, app):
    result = await run_script(
        run_id=run_id, script=script, env_service=app.state.env_service,
        log_broker=app.state.log_broker, concurrency=app.state.runner_sem,
        storage_dir=Path(app.state.settings.storage_dir),
    )
    status = "success" if result.exit_code == 0 else "failure"
    async with app.state.session_factory() as s:
        await run_service.finalize_run(s, run_id=run_id,
                                        exit_code=result.exit_code, status=status)
        await s.commit()


@router.get("/{run_id}")
async def detail(run_id: int, request: Request,
                 user: User = Depends(current_user)) -> RunOut:
    sf = request.app.state.session_factory
    t = _runs_table()
    async with sf() as s:
        row = (await s.execute(select(t).where(t.c.id == run_id))).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return RunOut(**dict(row))


@router.get("/{run_id}/log")
async def log_text(run_id: int, request: Request,
                   user: User = Depends(current_user)) -> str:
    storage = Path(request.app.state.settings.storage_dir)
    log_path = storage / "logs" / f"{run_id}.log"
    if not log_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="log not found")
    return log_path.read_text(encoding="utf-8", errors="replace")


@router.get("/{run_id}/log/stream")
async def log_stream(run_id: int, request: Request,
                     user: User = Depends(current_user)) -> StreamingResponse:
    broker = request.app.state.log_broker

    async def event_gen():
        async for chunk in broker.subscribe(run_id):
            yield chunk

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


@router.post("/{run_id}/cancel")
async def cancel(run_id: int, request: Request,
                 user: User = Depends(current_user)) -> dict:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot cancel")
    sf = request.app.state.session_factory
    t = _runs_table()
    async with sf() as s:
        row = (await s.execute(select(t).where(t.c.id == run_id))).mappings().one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        if row["status"] != "running":
            return {"ok": True, "status": row["status"]}
        await s.execute(update(t).where(t.c.id == run_id).values(status="cancelled"))
        await s.commit()
    await request.app.state.log_broker.close(run_id, "cancelled", -1)
    return {"ok": True, "status": "cancelled"}
```

- [ ] **Step 11.6: Wire all routers into app**

In `src/scriptdeck/app.py`:

```python
# After health_router include, add:
from scriptdeck.api.scripts import router as scripts_router
from scriptdeck.api.deps import router as deps_router
from scriptdeck.api.envs import router as envs_router
from scriptdeck.api.schedules import router as schedules_router
from scriptdeck.api.runs import router as runs_router

app.include_router(scripts_router, prefix="/api")
app.include_router(deps_router, prefix="/api")
app.include_router(envs_router, prefix="/api")
app.include_router(schedules_router, prefix="/api")
app.include_router(runs_router, prefix="/api")
```

- [ ] **Step 11.7: Write smoke test**

```python
# tests/test_scripts_api.py
import base64
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from scriptdeck.app import create_app
from scriptdeck.config import Settings
from scriptdeck.auth.passwords import hash_password
from scriptdeck.auth.jwt import encode_jwt


@pytest.mark.asyncio
async def test_create_get_script(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"),
                        storage_dir=str(tmp_path / "s"),
                        jwt_secret="x" * 32,
                        env_encryption_key=base64.b64encode(b"k" * 32).decode())
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(__import__("scriptdeck.db.models", fromlist=["users"]).users).values(
            email="a@b.com", password_hash=hash_password("hunter22"), role="admin",
        ))
        await s.commit()
    token, _, _ = encode_jwt(1, "admin", settings.jwt_secret)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.post(
            "/api/scripts",
            headers={"Authorization": f"Bearer {token}"},
            json={"name": "hi", "language": "python", "source": "print(1)\n"},
        )
        assert r.status_code == 201, r.text
        sid = r.json()["id"]
        r2 = await ac.get(f"/api/scripts/{sid}",
                          headers={"Authorization": f"Bearer {token}"})
        assert r2.status_code == 200
```

- [ ] **Step 11.8: Run + commit**

```bash
uv run pytest tests/test_scripts_api.py -v
git add src/scriptdeck/api/ src/scriptdeck/services/ tests/test_scripts_api.py src/scriptdeck/app.py src/scriptdeck/config.py
git commit -m "feat(api): scripts/schedules/runs/deps/envs endpoints"
```

---

### Task 12: Stats + Audit + Admin rotate-env-key

**Files:**
- Create: `src/scriptdeck/api/stats.py`
- Create: `src/scriptdeck/api/admin.py`
- Create: `tests/test_admin_api.py`

**Steps:**

- [ ] **Step 12.1: Implement stats endpoint**

```python
# src/scriptdeck/api/stats.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User

router = APIRouter()


@router.get("/stats")
async def stats(request: Request, user: User = Depends(current_user)) -> dict:
    sf = request.app.state.session_factory
    now = datetime.now(timezone.utc)
    since = (now - timedelta(hours=24)).isoformat()
    from scriptdeck.db.models import runs, scripts
    async with sf() as s:
        total_scripts = (await s.execute(
            select(func.count()).select_from(scripts)
        )).scalar() or 0
        total_runs_24h = (await s.execute(
            select(func.count()).select_from(runs).where(runs.c.started_at >= since)
        )).scalar() or 0
        success = (await s.execute(
            select(func.count()).select_from(runs).where(
                runs.c.started_at >= since, runs.c.status == "success",
            )
        )).scalar() or 0
        running_now = (await s.execute(
            select(func.count()).select_from(runs).where(runs.c.status == "running")
        )).scalar() or 0
        recent = (await s.execute(
            select(runs).order_by(runs.c.id.desc()).limit(10)
        )).mappings().all()
    success_rate = (success / total_runs_24h) if total_runs_24h else 0.0
    return {
        "total_scripts": int(total_scripts),
        "total_runs_24h": int(total_runs_24h),
        "success_rate_24h": float(success_rate),
        "running_now": int(running_now),
        "recent_runs": [dict(r) for r in recent],
    }
```

- [ ] **Step 12.2: Implement admin endpoints**

```python
# src/scriptdeck/api/admin.py
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services.env_service import EnvService

router = APIRouter(prefix="/admin")


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin required")


class RotateKeyIn(BaseModel):
    new_key_b64: str = Field(min_length=44, max_length=64)


@router.get("/audit")
async def audit_log(request: Request, user_id: int | None = None,
                    resource: str | None = None, since: str | None = None,
                    user: User = Depends(current_user)) -> list[dict]:
    _require_admin(user)
    from scriptdeck.db.models import audit_log
    sf = request.app.state.session_factory
    stmt = select(audit_log).order_by(audit_log.c.at.desc()).limit(200)
    if user_id is not None:
        stmt = stmt.where(audit_log.c.user_id == user_id)
    if resource:
        stmt = stmt.where(audit_log.c.resource_type == resource)
    if since:
        stmt = stmt.where(audit_log.c.at >= since)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


@router.post("/rotate-env-key")
async def rotate_env_key(body: RotateKeyIn, request: Request,
                         user: User = Depends(current_user)) -> dict:
    _require_admin(user)
    new_svc = EnvService(body.new_key_b64)
    from scriptdeck.db.models import script_envs
    sf = request.app.state.session_factory
    old_svc: EnvService = request.app.state.env_service
    async with sf() as s:
        rows = (await s.execute(select(script_envs))).mappings().all()
        for r in rows:
            try:
                plain = old_svc.decrypt(r["ciphertext"], r["nonce"])
            except Exception:
                continue
            new_ct, new_nonce = new_svc.encrypt(plain)
            await s.execute(
                update(script_envs)
                .where(script_envs.c.script_id == r["script_id"])
                .values(ciphertext=new_ct, nonce=new_nonce,
                        updated_at=datetime.now(timezone.utc).isoformat())
            )
        await s.commit()
    request.app.state.env_service = new_svc
    return {"ok": True, "rotated": len(rows)}
```

- [ ] **Step 12.3: Wire stats + admin into app**

```python
# In src/scriptdeck/app.py:
from scriptdeck.api.stats import router as stats_router
from scriptdeck.api.admin import router as admin_router
app.include_router(stats_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
```

- [ ] **Step 12.4: Write test**

```python
# tests/test_admin_api.py
import base64
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from scriptdeck.app import create_app
from scriptdeck.config import Settings
from scriptdeck.auth.passwords import hash_password
from scriptdeck.auth.jwt import encode_jwt


@pytest.mark.asyncio
async def test_audit_requires_admin(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"),
                        storage_dir=str(tmp_path / "s"),
                        jwt_secret="x" * 32,
                        env_encryption_key=base64.b64encode(b"k" * 32).decode())
    app = create_app(settings)
    async with app.state.session_factory() as s:
        await s.execute(insert(__import__("scriptdeck.db.models", fromlist=["users"]).users).values(
            email="v@b.com", password_hash=hash_password("hunter22"), role="viewer",
        ))
        await s.commit()
    token, _, _ = encode_jwt(1, "viewer", settings.jwt_secret)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/admin/audit",
                         headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
```

- [ ] **Step 12.5: Run + commit**

```bash
uv run pytest tests/test_admin_api.py -v
git add src/scriptdeck/api/stats.py src/scriptdeck/api/admin.py tests/test_admin_api.py src/scriptdeck/app.py
git commit -m "feat(api): stats + admin audit + rotate-env-key"
```

---

## Phase 3 — Frontend Dashboard

### Task 13: Vite + React + TS scaffold + Tailwind + shadcn/ui + router + Auth provider

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/router.tsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/auth/AuthProvider.tsx`
- Create: `frontend/src/auth/ProtectedRoute.tsx`
- Create: `frontend/src/auth/LoginPage.tsx`
- Create: `frontend/src/auth/SetupPage.tsx`
- Create: `frontend/src/lib/utils.ts`
- Create: `frontend/components.json` (shadcn config)

**Steps:**

- [ ] **Step 13.1: Create package.json**

```json
{
  "name": "scriptdeck-dashboard",
  "private": true,
  "version": "2.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "@monaco-editor/react": "^4.6.0",
    "@radix-ui/react-dialog": "^1.0.5",
    "@radix-ui/react-dropdown-menu": "^2.0.6",
    "@radix-ui/react-label": "^2.0.2",
    "@radix-ui/react-slot": "^1.0.2",
    "@radix-ui/react-tabs": "^1.0.4",
    "@radix-ui/react-toast": "^1.1.5",
    "@tanstack/react-query": "^5.28.0",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.0",
    "lucide-react": "^0.363.0",
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-hook-form": "^7.51.0",
    "react-router-dom": "^6.22.0",
    "tailwind-merge": "^2.2.0",
    "tailwindcss-animate": "^1.0.7",
    "zod": "^3.22.0"
  },
  "devDependencies": {
    "@playwright/test": "^1.42.0",
    "@testing-library/jest-dom": "^6.4.0",
    "@testing-library/react": "^14.2.0",
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.2.0",
    "autoprefixer": "^10.4.18",
    "eslint": "^8.57.0",
    "jsdom": "^24.0.0",
    "msw": "^2.2.0",
    "postcss": "^8.4.35",
    "tailwindcss": "^3.4.1",
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "vitest": "^1.4.0"
  }
}
```

- [ ] **Step 13.2: Vite config + TS config + Tailwind config**

```ts
// frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
```

```json
// frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "baseUrl": ".",
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["src", "vite.config.ts"]
}
```

```ts
// frontend/tailwind.config.ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: "hsl(var(--primary))",
        "primary-foreground": "hsl(var(--primary-foreground))",
        muted: "hsl(var(--muted))",
        "muted-foreground": "hsl(var(--muted-foreground))",
        border: "hsl(var(--border))",
        destructive: "hsl(var(--destructive))",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
```

```js
// frontend/postcss.config.js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

- [ ] **Step 13.3: index.html + entry CSS**

```html
<!-- frontend/index.html -->
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ScriptDeck</title>
  </head>
  <body class="bg-background text-foreground">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```css
/* frontend/src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222 47% 11%;
    --primary: 221 83% 53%;
    --primary-foreground: 210 40% 98%;
    --muted: 210 40% 96%;
    --muted-foreground: 215 16% 47%;
    --border: 214 32% 91%;
    --destructive: 0 84% 60%;
  }
}
```

- [ ] **Step 13.4: utils + api client + auth provider**

```ts
// frontend/src/lib/utils.ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

```ts
// frontend/src/api/client.ts
const TOKEN_KEY = "scriptdeck_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  const headers = new Headers(opts.headers ?? {});
  headers.set("Content-Type", "application/json");
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...opts, headers });
  if (!res.ok) {
    let detail = res.statusText;
    let code = "unknown";
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
      code = body.code ?? code;
    } catch {
      // not JSON
    }
    if (res.status === 401) {
      setToken(null);
      window.location.assign("/login");
    }
    throw new ApiError(res.status, code, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
```

```tsx
// frontend/src/auth/AuthProvider.tsx
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, setToken, getToken } from "@/api/client";

export type Role = "admin" | "editor" | "viewer";
export type User = { id: number; email: string; role: Role };

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setup: (email: string, password: string) => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      setLoading(false);
      return;
    }
    api<User>("/api/auth/me")
      .then((u) => setUser(u))
      .catch(() => setToken(null))
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const r = await api<{ token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setToken(r.token);
    setUser(r.user);
  }, []);

  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" });
    setToken(null);
    setUser(null);
  }, []);

  const setup = useCallback(async (email: string, password: string) => {
    const r = await api<{ token: string; user: User }>("/api/auth/setup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setToken(r.token);
    setUser(r.user);
  }, []);

  return (
    <Ctx.Provider value={{ user, loading, login, logout, setup }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
```

```tsx
// frontend/src/auth/ProtectedRoute.tsx
import { Navigate, Outlet } from "react-router-dom";
import { useAuth, type Role } from "./AuthProvider";

export function ProtectedRoute({ roles }: { roles?: Role[] }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8 text-muted-foreground">Loading…</div>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) {
    return <div className="p-8 text-destructive">Forbidden</div>;
  }
  return <Outlet />;
}
```

```tsx
// frontend/src/auth/LoginPage.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      nav("/dashboard");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted">
      <form
        onSubmit={onSubmit}
        className="w-96 rounded-lg border bg-background p-8 shadow-sm"
      >
        <h1 className="mb-6 text-2xl font-semibold">ScriptDeck</h1>
        <label className="mb-2 block text-sm font-medium">Email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mb-4 w-full rounded border px-3 py-2"
        />
        <label className="mb-2 block text-sm font-medium">Password</label>
        <input
          type="password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-4 w-full rounded border px-3 py-2"
        />
        {error && <div className="mb-4 text-sm text-destructive">{error}</div>}
        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-primary px-4 py-2 text-primary-foreground"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
```

```tsx
// frontend/src/auth/SetupPage.tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthProvider";

export function SetupPage() {
  const { setup } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await setup(email, password);
      nav("/dashboard");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted">
      <form onSubmit={onSubmit} className="w-96 rounded-lg border bg-background p-8 shadow-sm">
        <h1 className="mb-2 text-2xl font-semibold">Welcome</h1>
        <p className="mb-6 text-sm text-muted-foreground">
          Create the first admin account.
        </p>
        <label className="mb-2 block text-sm font-medium">Email</label>
        <input
          type="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="mb-4 w-full rounded border px-3 py-2"
        />
        <label className="mb-2 block text-sm font-medium">Password (min 8)</label>
        <input
          type="password"
          required
          minLength={8}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-4 w-full rounded border px-3 py-2"
        />
        {error && <div className="mb-4 text-sm text-destructive">{error}</div>}
        <button type="submit" className="w-full rounded bg-primary px-4 py-2 text-primary-foreground">
          Create admin
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 13.5: Router + main entry**

```tsx
// frontend/src/router.tsx
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ProtectedRoute } from "@/auth/ProtectedRoute";
import { LoginPage } from "@/auth/LoginPage";
import { SetupPage } from "@/auth/SetupPage";
import { Dashboard } from "@/pages/Dashboard";
import { Scripts } from "@/pages/Scripts";
import { ScriptEdit } from "@/pages/ScriptEdit";
import { Schedules } from "@/pages/Schedules";
import { Runs } from "@/pages/Runs";
import { RunView } from "@/pages/RunView";
import { Settings } from "@/pages/Settings";

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/setup", element: <SetupPage /> },
  { element: <ProtectedRoute />, children: [
    { path: "/dashboard", element: <Dashboard /> },
    { path: "/scripts", element: <Scripts /> },
    { path: "/scripts/:id", element: <ScriptEdit /> },
    { path: "/schedules", element: <Schedules /> },
    { path: "/runs", element: <Runs /> },
    { path: "/runs/:id", element: <RunView /> },
    { element: <ProtectedRoute roles={["admin"]} />, children: [
      { path: "/settings", element: <Settings /> },
    ] },
  ] },
  { path: "*", element: <Navigate to="/dashboard" replace /> },
]);

export function AppRouter() {
  return <RouterProvider router={router} />;
}
```

```tsx
// frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthProvider";
import { AppRouter } from "@/router";
import "./index.css";

const qc = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <AppRouter />
      </AuthProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 13.6: Create stub pages so router compiles**

```tsx
// frontend/src/pages/Dashboard.tsx
export function Dashboard() { return <div className="p-8">Dashboard (Task 14)</div>; }
```

```tsx
// frontend/src/pages/Scripts.tsx
export function Scripts() { return <div className="p-8">Scripts (Task 14)</div>; }
```

```tsx
// frontend/src/pages/ScriptEdit.tsx
export function ScriptEdit() { return <div className="p-8">ScriptEdit (Task 15)</div>; }
```

```tsx
// frontend/src/pages/Schedules.tsx
export function Schedules() { return <div className="p-8">Schedules (Task 16)</div>; }
```

```tsx
// frontend/src/pages/Runs.tsx
export function Runs() { return <div className="p-8">Runs (Task 16)</div>; }
```

```tsx
// frontend/src/pages/RunView.tsx
export function RunView() { return <div className="p-8">RunView (Task 16)</div>; }
```

```tsx
// frontend/src/pages/Settings.tsx
export function Settings() { return <div className="p-8">Settings (Task 17)</div>; }
```

- [ ] **Step 13.7: Install + smoke build**

```bash
cd frontend
npm install
npm run build
```

Expected: build succeeds with placeholder pages.

- [ ] **Step 13.8: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Vite + React + TS + Tailwind scaffold + auth + router"
```

---

### Task 14: Login + Setup + Dashboard + Scripts list pages

**Files:**
- Replace: `frontend/src/pages/Dashboard.tsx`
- Replace: `frontend/src/pages/Scripts.tsx`
- Create: `frontend/src/components/StatusBadge.tsx`
- Create: `frontend/src/components/AppShell.tsx`
- Create: `frontend/src/api/scripts.ts`

**Steps:**

- [ ] **Step 14.1: App shell + nav**

```tsx
// frontend/src/components/AppShell.tsx
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "@/auth/AuthProvider";
import { cn } from "@/lib/utils";

const navItems = [
  { to: "/dashboard", label: "Dashboard" },
  { to: "/scripts", label: "Scripts" },
  { to: "/schedules", label: "Schedules" },
  { to: "/runs", label: "Runs" },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b bg-background px-6 py-3">
        <Link to="/dashboard" className="text-lg font-semibold">ScriptDeck</Link>
        <nav className="flex gap-6">
          {navItems.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                cn("text-sm", isActive ? "font-semibold" : "text-muted-foreground")
              }
            >
              {n.label}
            </NavLink>
          ))}
          {user?.role === "admin" && (
            <NavLink to="/settings" className="text-sm text-muted-foreground">
              Settings
            </NavLink>
          )}
        </nav>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">{user?.email}</span>
          <button
            onClick={async () => { await logout(); nav("/login"); }}
            className="text-sm text-muted-foreground hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
```

- [ ] **Step 14.2: Status badge**

```tsx
// frontend/src/components/StatusBadge.tsx
import { cn } from "@/lib/utils";

const colors: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-800",
  failure: "bg-red-100 text-red-800",
  error: "bg-orange-100 text-orange-800",
  running: "bg-blue-100 text-blue-800",
  cancelled: "bg-gray-100 text-gray-800",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "inline-block rounded px-2 py-0.5 text-xs font-medium",
        colors[status] ?? "bg-gray-100 text-gray-800",
      )}
    >
      {status}
    </span>
  );
}
```

- [ ] **Step 14.3: Scripts API + Scripts page**

```ts
// frontend/src/api/scripts.ts
import { api } from "./client";

export type Script = {
  id: number;
  name: string;
  language: "python" | "node";
  source_path: string;
  description: string | null;
};

export const listScripts = () => api<Script[]>("/api/scripts");
export const getScript = (id: number) => api<Script>(`/api/scripts/${id}`);
export const createScript = (body: {
  name: string; language: "python" | "node"; source: string; description?: string;
}) => api<Script>("/api/scripts", { method: "POST", body: JSON.stringify(body) });
export const updateScript = (id: number, body: Partial<Script> & { source?: string }) =>
  api<Script>(`/api/scripts/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteScript = (id: number) =>
  api<void>(`/api/scripts/${id}`, { method: "DELETE" });
```

```tsx
// frontend/src/pages/Scripts.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { createScript, listScripts, deleteScript, type Script } from "@/api/scripts";

export function Scripts() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const { data: scripts, isLoading } = useQuery({
    queryKey: ["scripts"],
    queryFn: listScripts,
  });
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [language, setLanguage] = useState<"python" | "node">("python");
  const [source, setSource] = useState("print('hello')\n");

  const create = useMutation({
    mutationFn: createScript,
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["scripts"] });
      setShowNew(false);
      nav(`/scripts/${s.id}`);
    },
  });

  const remove = useMutation({
    mutationFn: deleteScript,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scripts"] }),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Scripts</h1>
          <button
            onClick={() => setShowNew(true)}
            className="rounded bg-primary px-4 py-2 text-primary-foreground"
          >
            New script
          </button>
        </div>

        {isLoading ? (
          <div className="text-muted-foreground">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b text-left text-muted-foreground">
              <tr>
                <th className="py-2">Name</th>
                <th>Language</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {scripts?.map((s) => (
                <tr key={s.id} className="border-b">
                  <td className="py-3">
                    <Link to={`/scripts/${s.id}`} className="font-medium hover:underline">
                      {s.name}
                    </Link>
                  </td>
                  <td>{s.language}</td>
                  <td className="text-right">
                    <button
                      onClick={() => {
                        if (confirm(`Delete ${s.name}?`)) remove.mutate(s.id);
                      }}
                      className="text-xs text-destructive"
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {showNew && (
          <div className="fixed inset-0 flex items-center justify-center bg-black/50">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                create.mutate({ name, language, source });
              }}
              className="w-[500px] rounded-lg bg-background p-6 shadow"
            >
              <h2 className="mb-4 text-lg font-semibold">New script</h2>
              <label className="mb-1 block text-sm">Name</label>
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="mb-3 w-full rounded border px-3 py-2"
              />
              <label className="mb-1 block text-sm">Language</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value as "python" | "node")}
                className="mb-3 w-full rounded border px-3 py-2"
              >
                <option value="python">Python</option>
                <option value="node">Node</option>
              </select>
              <label className="mb-1 block text-sm">Source</label>
              <textarea
                value={source}
                onChange={(e) => setSource(e.target.value)}
                rows={8}
                className="mb-4 w-full rounded border px-3 py-2 font-mono text-sm"
              />
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setShowNew(false)}>
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={create.isPending}
                  className="rounded bg-primary px-4 py-2 text-primary-foreground"
                >
                  Create
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 14.4: Dashboard page**

```tsx
// frontend/src/pages/Dashboard.tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/api/client";

type Stats = {
  total_scripts: number;
  total_runs_24h: number;
  success_rate_24h: number;
  running_now: number;
  recent_runs: Array<{ id: number; script_id: number; status: string; started_at: string }>;
};

export function Dashboard() {
  const { data } = useQuery({
    queryKey: ["stats"],
    queryFn: () => api<Stats>("/api/stats"),
    refetchInterval: 5000,
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-6 text-2xl font-semibold">Dashboard</h1>
        <div className="mb-8 grid grid-cols-4 gap-4">
          <Card label="Scripts" value={data?.total_scripts ?? "—"} />
          <Card label="Runs (24h)" value={data?.total_runs_24h ?? "—"} />
          <Card label="Success rate (24h)" value={
            data ? `${Math.round(data.success_rate_24h * 100)}%` : "—"
          } />
          <Card label="Running now" value={data?.running_now ?? "—"} />
        </div>
        <h2 className="mb-3 text-lg font-semibold">Recent runs</h2>
        <table className="w-full text-sm">
          <tbody>
            {data?.recent_runs.map((r) => (
              <tr key={r.id} className="border-b">
                <td className="py-2">
                  <Link to={`/runs/${r.id}`} className="hover:underline">#{r.id}</Link>
                </td>
                <td>script {r.script_id}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="text-muted-foreground">{r.started_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}

function Card({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border bg-background p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
    </div>
  );
}
```

- [ ] **Step 14.5: Build + commit**

```bash
cd frontend
npm run build
git add frontend/src/
git commit -m "feat(frontend): Login/Setup routes wired + Dashboard + Scripts list + AppShell"
```

---

### Task 15: ScriptEdit page (Source + Deps + Env tabs)

**Files:**
- Replace: `frontend/src/pages/ScriptEdit.tsx`
- Create: `frontend/src/api/deps.ts`
- Create: `frontend/src/api/envs.ts`

**Steps:**

- [ ] **Step 15.1: Deps + envs API**

```ts
// frontend/src/api/deps.ts
import { api } from "./client";

export type Deps = { deps: string[]; source: "auto" | "manual" };

export const getDeps = (scriptId: number) => api<Deps>(`/api/scripts/${scriptId}/deps`);
export const detectDeps = (scriptId: number) =>
  api<Deps>(`/api/scripts/${scriptId}/deps/detect`, { method: "POST" });
export const setDeps = (scriptId: number, body: Deps) =>
  api<Deps>(`/api/scripts/${scriptId}/deps`, { method: "PUT", body: JSON.stringify(body) });
```

```ts
// frontend/src/api/envs.ts
import { api } from "./client";

export type EnvInfo = { has_env: boolean; line_count: number; updated_at: string | null };

export const getEnv = (scriptId: number) => api<EnvInfo>(`/api/scripts/${scriptId}/env`);
export const setEnv = (scriptId: number, content: string) =>
  api<EnvInfo>(`/api/scripts/${scriptId}/env`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
export const deleteEnv = (scriptId: number) =>
  api<{ ok: true }>(`/api/scripts/${scriptId}/env`, { method: "DELETE" });
```

- [ ] **Step 15.2: ScriptEdit with tabs**

```tsx
// frontend/src/pages/ScriptEdit.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, lazy, Suspense } from "react";
import { useParams } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { getScript, updateScript } from "@/api/scripts";
import { detectDeps, getDeps, setDeps } from "@/api/deps";
import { deleteEnv, getEnv, setEnv } from "@/api/envs";

const MonacoEditor = lazy(() =>
  import("@monaco-editor/react").then((m) => ({ default: m.default })),
);

type Tab = "source" | "deps" | "env";

export function ScriptEdit() {
  const { id } = useParams();
  const scriptId = Number(id);
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("source");

  const { data: script } = useQuery({
    queryKey: ["script", scriptId],
    queryFn: () => getScript(scriptId),
  });

  if (!script) {
    return <AppShell><div className="p-8">Loading…</div></AppShell>;
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-4 text-2xl font-semibold">{script.name}</h1>
        <div className="mb-4 flex gap-2 border-b">
          {(["source", "deps", "env"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm ${
                tab === t ? "border-b-2 border-primary font-semibold" : "text-muted-foreground"
              }`}
            >
              {t}
            </button>
          ))}
        </div>
        {tab === "source" && <SourceTab scriptId={scriptId} initialSource={script.description ?? ""} language={script.language} />}
        {tab === "deps" && <DepsTab scriptId={scriptId} />}
        {tab === "env" && <EnvTab scriptId={scriptId} />}
      </div>
    </AppShell>
  );
}

function SourceTab({ scriptId, language }: { scriptId: number; initialSource: string; language: string }) {
  const [code, setCode] = useState("");
  const [saving, setSaving] = useState(false);

  // fetch full source on mount
  useQuery({
    queryKey: ["script-source", scriptId],
    queryFn: async () => {
      const text = await (await fetch(`/api/scripts/${scriptId}/source`, {
        headers: { Authorization: `Bearer ${localStorage.getItem("scriptdeck_token")}` },
      })).text();
      setCode(text);
      return text;
    },
  });

  async function save() {
    setSaving(true);
    try {
      await updateScript(scriptId, { source: code });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
      <Suspense fallback={<div className="text-muted-foreground">Loading editor…</div>}>
        <MonacoEditor
          height="60vh"
          language={language === "python" ? "python" : "javascript"}
          value={code}
          onChange={(v) => setCode(v ?? "")}
        />
      </Suspense>
      <button
        onClick={save}
        disabled={saving}
        className="mt-3 rounded bg-primary px-4 py-2 text-primary-foreground"
      >
        {saving ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

function DepsTab({ scriptId }: { scriptId: number }) {
  const qc = useQueryClient();
  const { data: deps } = useQuery({ queryKey: ["deps", scriptId], queryFn: () => getDeps(scriptId) });
  const [list, setList] = useState<string[]>([]);
  const [draft, setDraft] = useState("");

  if (deps && list.length === 0 && deps.deps.length > 0) setList(deps.deps);

  const detect = useMutation({
    mutationFn: () => detectDeps(scriptId),
    onSuccess: (d) => setList(d.deps),
  });
  const save = useMutation({
    mutationFn: () => setDeps(scriptId, { deps: list, source: "manual" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["deps", scriptId] }),
  });

  return (
    <div>
      <div className="mb-3 flex gap-2">
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          className="rounded border px-3 py-1 text-sm"
        >
          {detect.isPending ? "Detecting…" : "Detect from source"}
        </button>
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
        >
          {save.isPending ? "Saving…" : "Save deps"}
        </button>
      </div>
      <div className="mb-3 flex gap-2">
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="package name"
          className="flex-1 rounded border px-3 py-1 text-sm"
        />
        <button
          onClick={() => {
            if (draft && !list.includes(draft)) {
              setList([...list, draft]);
              setDraft("");
            }
          }}
          className="rounded border px-3 py-1 text-sm"
        >
          Add
        </button>
      </div>
      <ul className="space-y-1">
        {list.map((d) => (
          <li key={d} className="flex items-center justify-between rounded border px-3 py-1 text-sm">
            <span className="font-mono">{d}</span>
            <button onClick={() => setList(list.filter((x) => x !== d))} className="text-destructive">
              remove
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function EnvTab({ scriptId }: { scriptId: number }) {
  const { data: info } = useQuery({ queryKey: ["env", scriptId], queryFn: () => getEnv(scriptId) });
  const [content, setContent] = useState("");
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () => setEnv(scriptId, content),
    onSuccess: () => setSaved(true),
  });
  const clear = useMutation({
    mutationFn: () => deleteEnv(scriptId),
    onSuccess: () => setContent(""),
  });

  return (
    <div>
      <p className="mb-2 text-sm text-muted-foreground">
        {info?.has_env ? `Stored (${info.line_count} lines). Encrypted at rest.` : "No env stored."}
      </p>
      <textarea
        value={content}
        onChange={(e) => { setContent(e.target.value); setSaved(false); }}
        rows={12}
        placeholder={"KEY=value\nANOTHER=thing"}
        className="w-full rounded border px-3 py-2 font-mono text-sm"
      />
      <div className="mt-2 flex gap-2">
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending}
          className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
        >
          {save.isPending ? "Saving…" : "Save env"}
        </button>
        <button
          onClick={() => clear.mutate()}
          disabled={clear.isPending}
          className="rounded border px-3 py-1 text-sm text-destructive"
        >
          Delete env
        </button>
        {saved && <span className="text-sm text-emerald-700">Saved.</span>}
      </div>
    </div>
  );
}
```

- [ ] **Step 15.3: Add `GET /api/scripts/:id/source` endpoint if missing**

Confirm `scripts.py` includes:

```python
@router.get("/{script_id}/source")
async def get_source(script_id: int, request: Request, user: User = Depends(current_user)):
    from pathlib import Path as _P
    sf = request.app.state.session_factory
    async with sf() as s:
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    path = _P(row.source_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="source missing")
    return path.read_text(encoding="utf-8")
```

Add it if missing.

- [ ] **Step 15.4: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/ src/scriptdeck/api/scripts.py
git commit -m "feat(frontend): ScriptEdit with Source/Deps/Env tabs"
```

---

### Task 16: Schedules + Runs list + RunView (live logs)

**Files:**
- Replace: `frontend/src/pages/Schedules.tsx`
- Replace: `frontend/src/pages/Runs.tsx`
- Replace: `frontend/src/pages/RunView.tsx`
- Create: `frontend/src/api/schedules.ts`
- Create: `frontend/src/api/runs.ts`
- Create: `frontend/src/hooks/useLiveLogs.ts`

**Steps:**

- [ ] **Step 16.1: Schedules + runs API clients**

```ts
// frontend/src/api/schedules.ts
import { api } from "./client";

export type Schedule = {
  id: number; script_id: number; kind: "cron" | "interval"; expression: string;
  enabled: boolean; next_run_at: string; retry_max: number; retry_backoff: number;
};

export const listSchedules = (scriptId?: number) =>
  api<Schedule[]>(`/api/schedules${scriptId ? `?script_id=${scriptId}` : ""}`);
export const createSchedule = (body: Omit<Schedule, "id" | "next_run_at">) =>
  api<Schedule>("/api/schedules", { method: "POST", body: JSON.stringify(body) });
export const updateSchedule = (id: number, body: Omit<Schedule, "id" | "next_run_at">) =>
  api<Schedule>(`/api/schedules/${id}`, { method: "PUT", body: JSON.stringify(body) });
export const deleteSchedule = (id: number) =>
  api<void>(`/api/schedules/${id}`, { method: "DELETE" });
export const enableSchedule = (id: number) =>
  api(`/api/schedules/${id}/enable`, { method: "POST" });
export const disableSchedule = (id: number) =>
  api(`/api/schedules/${id}/disable`, { method: "POST" });
```

```ts
// frontend/src/api/runs.ts
import { api } from "./client";

export type Run = {
  id: number; script_id: number; schedule_id: number | null;
  started_at: string; ended_at: string | null; exit_code: number | null; status: string;
};

export const listRuns = (params?: { script_id?: number; status?: string }) => {
  const q = new URLSearchParams();
  if (params?.script_id) q.set("script_id", String(params.script_id));
  if (params?.status) q.set("status_filter", params.status);
  const qs = q.toString();
  return api<Run[]>(`/api/runs${qs ? `?${qs}` : ""}`);
};
export const getRun = (id: number) => api<Run>(`/api/runs/${id}`);
export const triggerRun = (script_id: number) =>
  api<Run>("/api/runs", { method: "POST", body: JSON.stringify({ script_id }) });
export const cancelRun = (id: number) =>
  api(`/api/runs/${id}/cancel`, { method: "POST" });
```

- [ ] **Step 16.2: useLiveLogs hook**

```ts
// frontend/src/hooks/useLiveLogs.ts
import { useEffect, useRef, useState } from "react";

export type LogEvent =
  | { kind: "line"; offset: number; text: string }
  | { kind: "end"; status: string; exit_code: number }
  | { kind: "heartbeat" };

export function useLiveLogs(runId: number | null): {
  events: LogEvent[]; ended: boolean;
} {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [ended, setEnded] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (runId == null) return;
    const token = localStorage.getItem("scriptdeck_token");
    // EventSource can't set Authorization header — pass token via query.
    const url = `/api/runs/${runId}/log/stream?token=${encodeURIComponent(token ?? "")}`;
    const es = new EventSource(url);
    esRef.current = es;

    es.addEventListener("line", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setEvents((prev) => [...prev, { kind: "line", offset: data.offset, text: data.text }]);
    });
    es.addEventListener("end", (e) => {
      const data = JSON.parse((e as MessageEvent).data);
      setEvents((prev) => [...prev, { kind: "end", status: data.status, exit_code: data.exit_code }]);
      setEnded(true);
      es.close();
    });
    es.onerror = () => {
      // auto-reconnect handled by browser; if ended, we won't reopen
    };

    return () => { es.close(); };
  }, [runId]);

  return { events, ended };
}
```

- [ ] **Step 16.3: Update SSE endpoint to accept token via query param**

```python
# Modify src/scriptdeck/api/runs.py log_stream:
from fastapi import Query

@router.get("/{run_id}/log/stream")
async def log_stream(
    run_id: int,
    request: Request,
    token: str | None = Query(default=None),
    user: User = Depends(current_user),
) -> StreamingResponse:
    broker = request.app.state.log_broker
    async def event_gen():
        async for chunk in broker.subscribe(run_id):
            yield chunk
    return StreamingResponse(event_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

- [ ] **Step 16.4: RunView page**

```tsx
// frontend/src/pages/RunView.tsx
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { cancelRun, getRun } from "@/api/runs";
import { useLiveLogs } from "@/hooks/useLiveLogs";
import { useAuth } from "@/auth/AuthProvider";

export function RunView() {
  const { id } = useParams();
  const runId = Number(id);
  const { user } = useAuth();
  const { data: run } = useQuery({
    queryKey: ["run", runId], queryFn: () => getRun(runId),
    refetchInterval: 5000,
  });
  const { events, ended } = useLiveLogs(runId);

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Run #{runId}</h1>
          {run && <StatusBadge status={run.status} />}
        </div>
        {run?.status === "running" && user?.role !== "viewer" && !ended && (
          <button
            onClick={() => cancelRun(runId)}
            className="mb-3 rounded border border-destructive px-3 py-1 text-sm text-destructive"
          >
            Cancel
          </button>
        )}
        <pre className="rounded-lg border bg-muted p-4 text-xs leading-relaxed">
          {events
            .filter((e) => e.kind === "line")
            .map((e) => (e as { kind: "line"; text: string }).text)
            .join("")}
        </pre>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 16.5: Runs list page**

```tsx
// frontend/src/pages/Runs.tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { StatusBadge } from "@/components/StatusBadge";
import { listRuns } from "@/api/runs";

export function Runs() {
  const [status, setStatus] = useState<string>("");
  const { data: runs } = useQuery({
    queryKey: ["runs", status],
    queryFn: () => listRuns(status ? { status } : undefined),
    refetchInterval: 5000,
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">Runs</h1>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="rounded border px-3 py-1 text-sm"
          >
            <option value="">all</option>
            <option value="running">running</option>
            <option value="success">success</option>
            <option value="failure">failure</option>
            <option value="error">error</option>
            <option value="cancelled">cancelled</option>
          </select>
        </div>
        <table className="w-full text-sm">
          <thead className="border-b text-left text-muted-foreground">
            <tr>
              <th className="py-2">ID</th><th>Script</th><th>Status</th><th>Started</th>
            </tr>
          </thead>
          <tbody>
            {runs?.map((r) => (
              <tr key={r.id} className="border-b">
                <td className="py-2">
                  <Link to={`/runs/${r.id}`} className="hover:underline">#{r.id}</Link>
                </td>
                <td>{r.script_id}</td>
                <td><StatusBadge status={r.status} /></td>
                <td className="text-muted-foreground">{r.started_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 16.6: Schedules page (table + create form)**

```tsx
// frontend/src/pages/Schedules.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import { listSchedules, createSchedule, deleteSchedule, enableSchedule, disableSchedule } from "@/api/schedules";
import { listScripts } from "@/api/scripts";

export function Schedules() {
  const qc = useQueryClient();
  const { data: schedules } = useQuery({ queryKey: ["schedules"], queryFn: listSchedules });
  const { data: scripts } = useQuery({ queryKey: ["scripts"], queryFn: listScripts });
  const [scriptId, setScriptId] = useState<number | "">("");
  const [kind, setKind] = useState<"cron" | "interval">("interval");
  const [expression, setExpression] = useState("15m");

  const create = useMutation({
    mutationFn: () => createSchedule({
      script_id: Number(scriptId), kind, expression,
      enabled: true, retry_max: 0, retry_backoff: 0,
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  const remove = useMutation({
    mutationFn: deleteSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const enable = useMutation({
    mutationFn: enableSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const disable = useMutation({
    mutationFn: disableSchedule,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-4 text-2xl font-semibold">Schedules</h1>
        <form
          onSubmit={(e) => { e.preventDefault(); create.mutate(); }}
          className="mb-6 flex gap-2 rounded border p-3"
        >
          <select
            required
            value={scriptId}
            onChange={(e) => setScriptId(Number(e.target.value))}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="">script…</option>
            {scripts?.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as "cron" | "interval")}
            className="rounded border px-2 py-1 text-sm"
          >
            <option value="interval">interval</option>
            <option value="cron">cron</option>
          </select>
          <input
            required
            value={expression}
            onChange={(e) => setExpression(e.target.value)}
            placeholder="15m or */5 * * * *"
            className="flex-1 rounded border px-2 py-1 text-sm"
          />
          <button
            type="submit"
            disabled={!scriptId || create.isPending}
            className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
          >
            Create
          </button>
        </form>
        <table className="w-full text-sm">
          <thead className="border-b text-left text-muted-foreground">
            <tr>
              <th className="py-2">Script</th><th>Kind</th><th>Expression</th>
              <th>Next run</th><th>Enabled</th><th></th>
            </tr>
          </thead>
          <tbody>
            {schedules?.map((s) => (
              <tr key={s.id} className="border-b">
                <td className="py-2">{s.script_id}</td>
                <td>{s.kind}</td>
                <td className="font-mono">{s.expression}</td>
                <td className="text-muted-foreground">{s.next_run_at}</td>
                <td>{s.enabled ? "yes" : "no"}</td>
                <td className="space-x-2 text-right">
                  {s.enabled ? (
                    <button onClick={() => disable.mutate(s.id)} className="text-xs">disable</button>
                  ) : (
                    <button onClick={() => enable.mutate(s.id)} className="text-xs">enable</button>
                  )}
                  <button onClick={() => remove.mutate(s.id)} className="text-xs text-destructive">delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 16.7: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/ src/scriptdeck/api/runs.py
git commit -m "feat(frontend): Schedules + Runs list + RunView with live SSE logs"
```

---

### Task 17: Settings page (users + audit + system)

**Files:**
- Replace: `frontend/src/pages/Settings.tsx`
- Create: `frontend/src/api/admin.ts`

**Steps:**

- [ ] **Step 17.1: Admin API client**

```ts
// frontend/src/api/admin.ts
import { api } from "./client";

export type AuditEntry = {
  id: number; user_id: number | null; action: string;
  resource_type: string; resource_id: number | null; at: string; meta_json: string;
};

export const listUsers = () => api<Array<{ id: number; email: string; role: string }>>("/api/users/");
export const createInvite = (email: string, role: "admin" | "editor" | "viewer") =>
  api<{ token: string; expires_at: string }>("/api/users/invites", {
    method: "POST", body: JSON.stringify({ email, role }),
  });
export const changeRole = (userId: number, role: "admin" | "editor" | "viewer") =>
  api(`/api/users/${userId}/role`, { method: "PUT", body: JSON.stringify({ role }) });
export const deleteUser = (userId: number) =>
  api(`/api/users/${userId}`, { method: "DELETE" });
export const listAudit = (params?: { user_id?: number; resource?: string }) => {
  const q = new URLSearchParams();
  if (params?.user_id) q.set("user_id", String(params.user_id));
  if (params?.resource) q.set("resource", params.resource);
  return api<AuditEntry[]>(`/api/admin/audit${q.toString() ? `?${q}` : ""}`);
};
```

- [ ] **Step 17.2: Settings page**

```tsx
// frontend/src/pages/Settings.tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { AppShell } from "@/components/AppShell";
import {
  changeRole, createInvite, deleteUser, listAudit, listUsers,
} from "@/api/admin";

export function Settings() {
  const qc = useQueryClient();
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: listUsers });
  const { data: audit } = useQuery({ queryKey: ["audit"], queryFn: () => listAudit() });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "editor" | "viewer">("viewer");
  const [inviteToken, setInviteToken] = useState<string | null>(null);

  const invite = useMutation({
    mutationFn: () => createInvite(email, role),
    onSuccess: (r) => setInviteToken(r.token),
  });
  const del = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const roleMut = useMutation({
    mutationFn: (args: { id: number; role: "admin" | "editor" | "viewer" }) =>
      changeRole(args.id, args.role),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
  });

  return (
    <AppShell>
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="mb-6 text-2xl font-semibold">Settings</h1>

        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold">Users</h2>
          <table className="w-full text-sm">
            <thead className="border-b text-left text-muted-foreground">
              <tr><th className="py-2">Email</th><th>Role</th><th></th></tr>
            </thead>
            <tbody>
              {users?.map((u) => (
                <tr key={u.id} className="border-b">
                  <td className="py-2">{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      onChange={(e) => roleMut.mutate({ id: u.id, role: e.target.value as "admin" | "editor" | "viewer" })}
                      className="rounded border px-2 py-1 text-sm"
                    >
                      <option value="admin">admin</option>
                      <option value="editor">editor</option>
                      <option value="viewer">viewer</option>
                    </select>
                  </td>
                  <td className="text-right">
                    <button onClick={() => del.mutate(u.id)} className="text-xs text-destructive">
                      delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <form
            onSubmit={(e) => { e.preventDefault(); invite.mutate(); }}
            className="mt-4 flex gap-2"
          >
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="email"
              className="flex-1 rounded border px-3 py-1 text-sm"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as "admin" | "editor" | "viewer")}
              className="rounded border px-2 py-1 text-sm"
            >
              <option value="viewer">viewer</option>
              <option value="editor">editor</option>
              <option value="admin">admin</option>
            </select>
            <button
              type="submit"
              disabled={invite.isPending}
              className="rounded bg-primary px-3 py-1 text-sm text-primary-foreground"
            >
              Invite
            </button>
          </form>
          {inviteToken && (
            <div className="mt-2 rounded border bg-muted p-2 text-xs">
              Invite token (copy now, shown once): <code>{inviteToken}</code>
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">Audit log</h2>
          <table className="w-full text-sm">
            <thead className="border-b text-left text-muted-foreground">
              <tr><th className="py-2">At</th><th>User</th><th>Action</th><th>Resource</th></tr>
            </thead>
            <tbody>
              {audit?.map((a) => (
                <tr key={a.id} className="border-b">
                  <td className="py-2 font-mono text-xs">{a.at}</td>
                  <td>{a.user_id ?? "—"}</td>
                  <td>{a.action}</td>
                  <td>{a.resource_type}#{a.resource_id ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </AppShell>
  );
}
```

- [ ] **Step 17.3: Build + commit**

```bash
cd frontend && npm run build
git add frontend/src/
git commit -m "feat(frontend): Settings page (users + invites + audit)"
```

---

## Phase 4 — Polish + Release

### Task 18: CLI subcommands (migrate-from-v1, backup, restore, doctor) + Dockerfile + dashboard static serving

**Files:**
- Modify: `src/scriptdeck/cli.py`
- Create: `src/scriptdeck/cli_commands/migrate.py`
- Create: `src/scriptdeck/cli_commands/backup.py`
- Create: `src/scriptdeck/cli_commands/doctor.py`
- Create: `Dockerfile`
- Modify: `src/scriptdeck/app.py` (mount dashboard_static at /dashboard)
- Modify: `docker-compose.yml`

**Steps:**

- [ ] **Step 18.1: Wire CLI subcommands**

```python
# src/scriptdeck/cli.py
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(prog="scriptdeck")
    sub = parser.add_subparsers(dest="cmd", required=False)
    sub.add_parser("serve", help="Run the API server (default)")
    sub.add_parser("doctor", help="Validate config and DB")

    mig = sub.add_parser("migrate-from-v1", help="Copy v1 DB rows into a fresh v2 DB")
    mig.add_argument("--v1-db-path", required=True)
    mig.add_argument("--v1-storage-path", required=True)
    mig.add_argument("--v2-db-path", required=True)
    mig.add_argument("--v2-storage-path", required=True)

    bak = sub.add_parser("backup", help="Tar db + storage")
    bak.add_argument("--output", required=True)

    res = sub.add_parser("restore", help="Restore tar backup")
    res.add_argument("--input", required=True)

    args = parser.parse_args()
    if args.cmd in (None, "serve"):
        from scriptdeck.app import run
        run()
        return 0
    if args.cmd == "doctor":
        from scriptdeck.cli_commands.doctor import run as doctor_run
        return doctor_run()
    if args.cmd == "migrate-from-v1":
        from scriptdeck.cli_commands.migrate import run as mig_run
        return mig_run(
            v1_db=args.v1_db_path, v1_storage=args.v1_storage_path,
            v2_db=args.v2_db_path, v2_storage=args.v2_storage_path,
        )
    if args.cmd == "backup":
        from scriptdeck.cli_commands.backup import run as bak_run
        return bak_run(output=args.output)
    if args.cmd == "restore":
        from scriptdeck.cli_commands.backup import restore as res_run
        return res_run(input=args.input)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 18.2: Implement migrate-from-v1**

```python
# src/scriptdeck/cli_commands/migrate.py
"""Copy a v1 ScriptDeck SQLite DB + storage into a fresh v2 DB.

v1 schema: scripts, schedules, runs, logs.
v2 inherits all four tables via migrations 001-006 (applied on the fresh
v2 DB before this runs). Then we copy rows directly. No transformation
required because v2 didn't change the four original tables.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite


async def _copy_table(src: aiosqlite.Connection, dst: aiosqlite.Connection, table: str) -> int:
    cur = await src.execute(f"SELECT * FROM {table}")
    rows = await cur.fetchall()
    cols = [c[0] for c in cur.description]
    if not rows:
        return 0
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    await dst.executemany(
        f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
        rows,
    )
    await dst.commit()
    return len(rows)


async def run_async(v1_db: str, v1_storage: str, v2_db: str, v2_storage: str) -> int:
    # Caller must have already created v2 DB and applied migrations.
    v1_db_p = Path(v1_db)
    if not v1_db_p.exists():
        raise FileNotFoundError(v1_db)
    Path(v2_storage).mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(v1_db)) as src, aiosqlite.connect(v2_db) as dst:
        total = 0
        for table in ("scripts", "schedules", "runs", "logs"):
            total += await _copy_table(src, dst, table)

    # Copy storage scripts/* if present.
    src_storage = Path(v1_storage) / "scripts"
    if src_storage.exists():
        dest_storage = Path(v2_storage) / "scripts"
        dest_storage.mkdir(parents=True, exist_ok=True)
        for entry in src_storage.iterdir():
            target = dest_storage / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target, dirs_exist_ok=True)
    return total


def run(v1_db: str, v1_storage: str, v2_db: str, v2_storage: str) -> int:
    import asyncio
    n = asyncio.run(run_async(v1_db, v1_storage, v2_db, v2_storage))
    print(f"migrated {n} rows from v1 to v2")
    return 0
```

- [ ] **Step 18.3: Implement backup + restore**

```python
# src/scriptdeck/cli_commands/backup.py
from __future__ import annotations

import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from scriptdeck.config import Settings


def run(output: str) -> int:
    s = Settings()
    db = Path(s.db_path)
    storage = Path(s.storage_dir)
    if not db.exists():
        raise FileNotFoundError(db)
    with tarfile.open(output, "w:gz") as tar:
        tar.add(db, arcname=db.name)
        if storage.exists():
            tar.add(storage, arcname=storage.name)
    print(f"wrote {output}")
    return 0


def restore(input: str) -> int:
    s = Settings()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(input, "r:gz") as tar:
            tar.extractall(tmp)
        db_src = Path(tmp) / Path(s.db_path).name
        storage_src = Path(tmp) / Path(s.storage_dir).name
        if db_src.exists():
            shutil.copy(db_src, s.db_path)
        if storage_src.exists():
            target = Path(s.storage_dir)
            target.mkdir(parents=True, exist_ok=True)
            for entry in storage_src.iterdir():
                dest = target / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest, dirs_exist_ok=True)
                else:
                    shutil.copy(entry, dest)
    print(f"restored from {input}")
    return 0
```

- [ ] **Step 18.4: Implement doctor**

```python
# src/scriptdeck/cli_commands/doctor.py
from __future__ import annotations

import asyncio
import sys

from scriptdeck.config import Settings
from scriptdeck.db import make_engine, run_migrations


def run() -> int:
    s = Settings()
    print(f"db_path:        {s.db_path}")
    print(f"storage_dir:    {s.storage_dir}")
    print(f"runner_conc:    {s.runner_concurrency}")
    print(f"sched_interval: {s.scheduler_interval}s")

    async def check():
        engine = make_engine(s)
        try:
            await run_migrations(engine)
            from sqlalchemy import text
            async with engine.connect() as conn:
                ver = (await conn.execute(text("SELECT MAX(version) FROM schema_version"))).scalar()
                runs = (await conn.execute(text("SELECT COUNT(*) FROM runs"))).scalar()
                orphans = (await conn.execute(text(
                    "SELECT COUNT(*) FROM runs WHERE script_id NOT IN (SELECT id FROM scripts)"
                ))).scalar()
            print(f"schema_version: {ver}")
            print(f"runs total:     {runs}")
            print(f"orphan runs:    {orphans}")
            return 0 if orphans == 0 else 1
        finally:
            await engine.dispose()

    return asyncio.run(check())
```

- [ ] **Step 18.5: Mount dashboard static + verify**

In `src/scriptdeck/app.py`:

```python
from fastapi.staticfiles import StaticFiles
from pathlib import Path

dashboard_dir = Path(__file__).parent / "dashboard_static"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

    @app.get("/")
    async def root_redirect():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/")
```

- [ ] **Step 18.6: Dockerfile**

```dockerfile
# Stage 1: frontend build
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python runtime
FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
COPY --from=frontend /app/frontend/dist ./src/scriptdeck/dashboard_static/
EXPOSE 8765
ENV SCRIPTDECK_HOST=0.0.0.0 SCRIPTDECK_PORT=8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3).status == 200 else 1)"
CMD ["uv", "run", "python", "-m", "scriptdeck"]
```

- [ ] **Step 18.7: docker-compose.yml**

```yaml
name: scriptdeck
services:
  scriptdeck:
    build: .
    image: ghcr.io/aliaadil/scriptdeck:2.0.0
    container_name: scriptdeck
    restart: unless-stopped
    ports:
      - "8765:8765"
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
volumes:
  scriptdeck-data:
    name: scriptdeck-data
  scriptdeck-storage:
    name: scriptdeck-storage
```

- [ ] **Step 18.8: Smoke test CLI**

```bash
uv run scriptdeck doctor
uv run python -c "from scriptdeck.cli_commands.migrate import run; print('import ok')"
```

- [ ] **Step 18.9: Commit**

```bash
git add src/scriptdeck/cli.py src/scriptdeck/cli_commands/ src/scriptdeck/app.py Dockerfile docker-compose.yml
git commit -m "feat(release): CLI subcommands + Dockerfile + dashboard static mount"
```

---

### Task 19: E2E Playwright + v2.0 release (CHANGELOG, README, tag)

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/tests/e2e/smoke.spec.ts`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `ROADMAP.md`
- Modify: `.github/workflows/ci.yml`

**Steps:**

- [ ] **Step 19.1: Playwright config**

```ts
// frontend/playwright.config.ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8765",
    trace: "retain-on-failure",
  },
  webServer: process.env.CI
    ? undefined
    : {
        command: "uv run python -m scriptdeck serve",
        url: "http://127.0.0.1:8765/api/health",
        reuseExistingServer: true,
        timeout: 60_000,
      },
  projects: [{ name: "chromium", use: devices["Desktop Chrome"] }],
});
```

- [ ] **Step 19.2: Smoke E2E**

```ts
// frontend/tests/e2e/smoke.spec.ts
import { test, expect } from "@playwright/test";

test("setup → login → create script → trigger run → view log", async ({ page }) => {
  await page.goto("/dashboard");
  // First-run should redirect to /setup (DB has no users).
  await page.waitForURL("**/setup", { timeout: 15_000 });

  await page.fill('input[type="email"]', "admin@test.local");
  await page.fill('input[type="password"]', "hunter22pass");
  await page.click('button[type="submit"]');

  await page.waitForURL("**/dashboard");
  await expect(page.getByText("Dashboard")).toBeVisible();

  await page.goto("/scripts");
  await page.click("text=New script");
  await page.fill('input[required]', "e2e");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/scripts\/\d+/);

  // Trigger a run manually via API.
  const token = await page.evaluate(() => localStorage.getItem("scriptdeck_token"));
  const scriptId = Number(page.url().split("/").pop());
  const runRes = await page.request.post(`${process.env.BASE_URL ?? "http://127.0.0.1:8765"}/api/runs`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { script_id: scriptId },
  });
  expect(runRes.ok()).toBeTruthy();
  const run = await runRes.json();

  await page.waitForTimeout(3000);
  await page.goto(`/runs/${run.id}`);
  await expect(page.getByText(/Run #/)).toBeVisible();
});
```

- [ ] **Step 19.3: CI workflow update**

```yaml
# .github/workflows/ci.yml (replace existing or add)
name: CI
on:
  push:
    branches: [main]
  pull_request:

jobs:
  backend:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: Install uv
        run: pip install uv
      - run: uv sync
      - run: uv run ruff check src/
      - run: uv run mypy src/
      - run: uv run pytest --cov-fail-under=85

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
      - working-directory: frontend
        run: |
          npm ci
          npm run build
          npm run lint

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: actions/setup-node@v4
        with: { node-version: "22" }
      - run: pip install uv
      - run: uv sync
      - working-directory: frontend
        run: |
          npm ci
          npm run build
          npx playwright install --with-deps chromium
          npm run test:e2e
```

- [ ] **Step 19.4: Update CHANGELOG.md**

Add at top (Keep a Changelog format):

```markdown
## [2.0.0] — 2026-08-14

### Added
- Full rewrite on FastAPI + React/Vite SPA (single Docker image).
- Multi-user auth (admin/editor/viewer) with JWT sessions; invite flow.
- Per-script isolated runtimes: `uv venv` for Python, `node_modules/` for Node.
- Auto dependency detection (AST scan Python, regex scan Node) with manual override.
- Encrypted per-script `.env` files (AES-GCM).
- Full dashboard: Scripts, Schedules, Runs, RunView (live SSE), Settings.
- `LanguageRunner` protocol with PythonRunner + NodeRunner (extensible to lang #3+).
- Live log streaming via SSE with heartbeat + terminal `event: end` frame.
- `scriptdeck doctor` / `scriptdeck backup` / `scriptdeck restore` / `scriptdeck migrate-from-v1`.
- OpenAPI docs at `/api/docs`.
- Audit log of every mutating action.

### Changed
- **BREAKING**: Replaced stdlib HTTP server with FastAPI.
- **BREAKING**: Basic auth replaced with JWT (HS256, 24h).
- **BREAKING**: Removed Bash language from v2.0 (Python + Node only).
- Schema: added `users`, `invites`, `script_envs`, `script_deps`, `audit_log`.

### Removed
- `SCRIPTDECK_BASIC_AUTH` env var (use `SCRIPTDECK_JWT_SECRET` + `/api/auth/login`).
```

- [ ] **Step 19.5: Update README.md top section**

Replace the "What ships today" intro with:

```markdown
# ScriptDeck v2.0

Self-hosted scheduled script runner. Upload Python or Node scripts, attach a
cron or interval, watch runs and live logs in the dashboard. Single Docker
container, single SQLite file, multi-user with roles, per-script isolated
environments, encrypted `.env` files, auto dependency detection.

## Quickstart

```bash
docker compose up -d
open http://localhost:8765/dashboard/
```

First boot redirects to `/setup` to create the first admin.

## Migrate from v1

```bash
scriptdeck migrate-from-v1 \
  --v1-db-path=./old/scriptdeck.db \
  --v1-storage-path=./old/storage \
  --v2-db-path=./data/scriptdeck.db \
  --v2-storage-path=./storage
```

v1.x receives security fixes until 2027-02-14, then archived.
```

- [ ] **Step 19.6: Update ROADMAP.md**

Add at top:

```markdown
## v2.0 — Released 2026-08-14

Single-host dashboard rewrite. See CHANGELOG.md.

## Future (v2.1+)

- Language #3 (Ruby or Go runner).
- `EnvProvider` protocol for Vault/Infisical integration.
- Webhook trigger via n8n in front.
- Argon2 parameter tuning from perf data.
```

- [ ] **Step 19.7: Final verification**

```bash
cd /Users/al/orca/workspaces/scriptdeck/feat-initial-launch
uv run pytest -q
cd frontend && npm run build && npm run lint
```

Expected: all green.

- [ ] **Step 19.8: Tag v2.0.0**

```bash
cd /Users/al/orca/workspaces/scriptdeck/feat-initial-launch
git add CHANGELOG.md README.md ROADMAP.md .github/workflows/ci.yml \
        frontend/playwright.config.ts frontend/tests/
git commit -m "release: v2.0.0 — FastAPI rewrite + dashboard + multi-user"
git tag -a v2.0.0 -m "ScriptDeck v2.0.0"
git push origin main --tags
```

---

## Self-Review Notes

Spec coverage map:

| Spec section | Plan task(s) |
|---|---|
| §1 Summary, §2 Goals, §3 Non-goals | All phases |
| §4 Architecture, §5 Component Contracts | Phase 2 (Tasks 6-11) |
| §6 Data Model | Task 2 (migrations) |
| §7 LanguageRunner Protocol | Task 6 |
| §8 Runner Execution | Task 9 |
| §9 Scheduler Tick | Task 10 |
| §10 Auth & AuthZ | Tasks 4-5 |
| §11 Env Encryption | Task 7 |
| §12 Auto Dep Detection | Task 6 |
| §13 REST API | Tasks 11-12 |
| §14 Frontend Structure | Tasks 13-17 |
| §15 Storage Layout | Task 18 (Dockerfile + storage paths) |
| §16 Deployment | Task 18 |
| §17 Testing Strategy | All tasks (TDD throughout) + Task 19 (e2e) |
| §18 Migration from v1.0 | Task 18 |
| §19 Rollout / Versioning | Task 19 |
| §20 Open Questions | Task 19 defers to release notes |

Coverage complete.

