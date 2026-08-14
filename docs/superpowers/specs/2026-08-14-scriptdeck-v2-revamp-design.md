---
title: ScriptDeck v2.0 Revamp Design
date: 2026-08-14
status: draft
author: design session
---

# ScriptDeck v2.0 — Revamp Design

## 1. Summary

Full rewrite of ScriptDeck on a FastAPI + React/Vite stack. Single-host
self-hosted scheduled script runner. Ships v2.0 with first-class Python + Node
support, multi-user auth, auto dependency detection, encrypted per-script
environments, full dashboard (scripts, schedules, runs, logs, settings), and a
`LanguageRunner` protocol so future languages slot in cleanly.

Today's stdlib server is replaced end-to-end. The four existing tables
(`scripts`, `schedules`, `runs`, `logs`) and their storage layout carry forward
unchanged; new tables (`users`, `invites`, `script_envs`, `script_deps`,
`audit_log`) ship in migrations `007_from_v1.sql` + `008_indexes.sql`. v1.0.0
users migrate via `scriptdeck migrate-from-v1`.

## 2. Goals

- User-friendly dashboard for script CRUD, schedule CRUD, run history, live
  log tail, dependency editing, and `.env` editing.
- Multi-user with three roles (`admin`, `editor`, `viewer`) and JWT sessions.
- Per-script isolated runtime: `uv venv` for Python, `node_modules/` for
  Node. No global interpreter pollution.
- Auto-detect script dependencies (AST scan Python, regex scan Node) with
  manual override before save.
- Encrypted per-script `.env` files (AES-GCM, key from env).
- Live log streaming via SSE per run with sub-second latency.
- Extensible language support via `LanguageRunner` protocol. Adding Ruby/Go/
  Bun/Deno later = one new class + one registry line.
- Single-host Docker deployment, single process, single SQLite file.

## 3. Non-goals (v2.0)

- Multi-host worker agents (users should use k8s/Argo).
- Workflow DAGs (Temporal/Prefect/Airflow territory).
- Webhook triggers (n8n in front).
- External secret stores beyond env vars (Vault/Infisical follow-up via
  `EnvProvider` protocol).
- Languages beyond Python + Node at v2.0 (protocol ready, impls land in 2.1+).
- SSR/RSC/server actions (React SPA only; FastAPI owns all routing).

## 4. Architecture

Single FastAPI process on uvicorn. One asyncio event loop shared by HTTP,
scheduler tick, and SSE streamer. Subprocess execution via
`asyncio.create_subprocess_exec`. Real-time logs via an in-memory pub/sub
broker (`LogBroker`) that tails run log files and broadcasts lines to SSE
subscribers.

```
Browser (React/Vite SPA)
        │  JSON over HTTP (JWT bearer)   │  SSE /api/runs/<id>/logs/stream
        ▼                                ▼
FastAPI process
  ├── API routers (api/*.py)
  ├── Services (services/*)        pure async, no FastAPI imports
  ├── Repo (db/*)                  SQLAlchemy 2.0 async + aiosqlite
  ├── LanguageRunner registry      PythonRunner, NodeRunner
  ├── Scheduler tick (5s loop)
  ├── Runner (asyncio subprocess, isolation dirs)
  └── LogBroker (in-memory pub/sub for SSE)
                │
   SQLite (scriptdeck.db)       storage/ on volume
```

## 5. Component Contracts

Each component answers: what it does, how to use it, what it depends on.

### API routers (`api/*.py`)
- **What:** FastAPI routers grouped by resource. Convert Pydantic schemas to
  service DTOs. Apply role guards.
- **Use:** Mounted under `/api`. OpenAPI auto-generated at `/api/docs`.
- **Depends on:** services, auth deps.

### Services (`services/*.py`)
- **What:** Async domain logic. `ScriptService`, `ScheduleService`,
  `RunService`, `EnvService`, `DepDetectService`. One responsibility each,
  target ≤200 LOC.
- **Use:** Called from API routers and scheduler. Return DTOs, never ORM
  rows.
- **Depends on:** repo, `LanguageRunner` registry, `LogBroker`.

### Repo (`db/*`)
- **What:** SQLAlchemy 2.0 async models + session factory. Migration files
  in `db/migrations/00N_*.sql` applied in order via a `schema_version` row.
- **Use:** Async session injected per request.
- **Depends on:** aiosqlite driver.

### LanguageRunner protocol (`runner/protocol.py`)
- **What:** Protocol with `detect_deps`, `resolve_artifact_path`, `provision`,
  `build_command`. Two implementations ship: `PythonRunner`, `NodeRunner`.
- **Use:** `REGISTRY = {"python": PythonRunner(), "node": NodeRunner()}`.
  Look up by `script.language`.
- **Depends on:** `uv` binary on PATH for Python; `node` + `npm` for Node.

### Scheduler (`scheduler/tick.py`)
- **What:** Background asyncio task started on FastAPI `startup`. Every 5s,
  queries due schedules, dispatches runs, advances cursors. Skip-on-overlap
  marks new runs `status='error'` with `reason='overlap'`.
- **Use:** No external API. Internal only.
- **Depends on:** `ScheduleService`, `RunService`.

### Runner (`runner/executor.py`)
- **What:** Wraps `asyncio.create_subprocess_exec`. Manages isolation dir,
  per-script file lock (asyncio.Lock + `fcntl.flock`), captures output to
  log file, transitions run status, broadcasts via `LogBroker`.
- **Use:** Called by scheduler and `POST /api/runs` (manual trigger).
- **Depends on:** `LanguageRunner` registry, `EnvService.decrypt`, `LogBroker`.

### LogBroker (`services/log_broker.py`)
- **What:** In-memory `dict[run_id, set[asyncio.Queue]]`. Tail task per
  active run reads file from last offset, fans out new lines to subscribers.
- **Use:** `subscribe(run_id)` returns `AsyncIterator[bytes]`.
- **Depends on:** asyncio primitives only.

## 6. Data Model

### Existing tables (carry forward unchanged)

```sql
scripts        (id, name, language, source_path, requirements_path,
                interpreter_path, created_at, updated_at)
schedules      (id, script_id, kind, expression, enabled,
                next_run_at, retry_max, retry_backoff, last_status)
runs           (id, script_id, schedule_id NULL, started_at, ended_at NULL,
                exit_code NULL, status, retry_group NULL, log_path NULL)
logs           (id, run_id, path, size_bytes, line_count)
```

### New tables

```sql
users          (id, email UNIQUE, password_hash, role, created_at, last_login_at NULL)
                role IN ('admin', 'editor', 'viewer')
invites        (id, email, token UNIQUE, role, expires_at, used_at NULL)
script_envs    (script_id PK, ciphertext BLOB, nonce BLOB, updated_at)
script_deps    (script_id PK, deps_json TEXT, source TEXT, updated_at)
                source IN ('auto', 'manual')
                -- 'auto' = last set via /deps/detect; 'manual' = last set via /deps.
                -- Field is informational only (audit + UI badge); it does
                -- not affect provision() behavior.
audit_log      (id, user_id, action, resource_type, resource_id, at, meta_json)
```

### Indexes

```sql
idx_runs_script_started  ON runs(script_id, started_at DESC)
idx_schedules_due        ON schedules(enabled, next_run_at)
idx_runs_status          ON runs(status)
idx_audit_user_at        ON audit_log(user_id, at DESC)
```

JSON columns (TEXT) used for schedule retry config, run metadata, audit
`meta_json`. No JSON indexes.

## 7. LanguageRunner Protocol

```python
from pathlib import Path

class LanguageRunner(Protocol):
    name: str

    async def detect_deps(self, source: str) -> list[str]: ...
    # Best-effort. Returns PyPI/npm package names without versions.
    # Python: ast.parse -> top-level Import/ImportFrom -> drop stdlib -> top segment.
    # Node: regex over require()/from/import() -> drop relative + builtin.

    async def resolve_artifact_path(self, deps: list[str]) -> str: ...
    # Returns path (relative to work_dir) of the deps file.
    # Python: "requirements.txt". Node: "package.json".

    async def provision(self, work_dir: Path, deps: list[str]) -> Path: ...
    # Creates/updates env under work_dir. Returns interpreter path.
    # Python: `uv venv work_dir/.venv && uv pip install -r requirements.txt`
    # Node:   write package.json + `npm install` in work_dir

    def build_command(
        self, interpreter: Path, source_path: Path, env: dict[str, str]
    ) -> list[str]: ...
    # argv for asyncio.create_subprocess_exec.
    # Python: [str(interpreter), str(source_path)]
    # Node:   ["node", str(source_path)]
```

Registry:

```python
# runner/registry.py
RUNNERS: dict[str, LanguageRunner] = {
    "python": PythonRunner(),
    "node": NodeRunner(),
}
```

Adding a language = new class implementing the protocol + one registry line.

## 8. Runner Execution

```python
# runner/executor.py (shape)
async def run_script(run_id: int, script: Script) -> RunResult:
    log_path = storage_dir() / "logs" / f"{run_id}.log"
    async with open_log(log_path) as log_file:
        async with per_script_lock(script.id):
            runner = REGISTRY[script.language]
            work_dir = work_dir_for(script.id)
            interpreter = await runner.provision(work_dir, script.requirements)
            env = await merge_env(work_dir / ".env", script.env)
            proc = await asyncio.create_subprocess_exec(
                *runner.build_command(interpreter, script.source_path, env),
                stdout=log_file,
                stderr=asyncio.subprocess.STDOUT,
                cwd=work_dir,
            )
            exit_code = await proc.wait()
    return RunResult(exit_code=exit_code, log_path=log_path)
```

- `open_log` registers a broadcast on `LogBroker`.
- `per_script_lock` = `asyncio.Lock` keyed by `script.id` + `fcntl.flock` on a
  sentinel file (crash-safe across process death).
- Concurrency cap: `SCRIPTDECK_RUNNER_CONCURRENCY` (default 4) via semaphore
  around the whole `run_script` invocation.

## 9. Scheduler Tick

- One `asyncio.create_task(scheduler_loop())` started on FastAPI `startup`.
- Poll interval: `SCRIPTDECK_SCHEDULER_INTERVAL` seconds (default 5).
- Query: `schedules WHERE enabled=1 AND next_run_at <= now()`.
- Advance: `croniter` for `kind='cron'`; previous `next_run_at + interval`
  for `kind='interval'` (matches v1 behavior; interval is relative to the
  scheduled time, not to actual run completion).
- Skip-on-overlap: if `script.id` already has a `status='running'` run, mark
  new run `status='error'` with `reason='overlap'` and advance cursor.
- Self-heal on clock drift: every past-due row picked up in one tick;
  skip-on-overlap bounds backlog.

## 10. Authentication & Authorization

### Roles

| Role    | scripts | schedules | runs  | envs/deps | users | audit |
|---------|---------|-----------|-------|-----------|-------|-------|
| admin   | CRUD    | CRUD      | R+retrigger | CRUD | CRUD | R |
| editor  | CRUD    | CRUD      | R+retrigger | CRUD | -    | - |
| viewer  | R       | R         | R     | -         | -     | -     |

### Bootstrap

- First boot: if `users` empty, dashboard redirects to `/setup`. Single-use
  form creates first admin.
- After first user exists: `/setup` returns 404.

### Login flow

- `POST /api/auth/login {email, password}` returns JWT (HS256, 24h) signed
  with `SCRIPTDECK_JWT_SECRET`.
- JWT payload: `{sub: user_id, role, exp}`.
- Bearer in `Authorization` header.
- `POST /api/auth/refresh` rotates.
- `POST /api/auth/logout` adds token JTI to in-memory denylist until `exp`.
- Password hashing: argon2 (`argon2-cffi`).
- Invites: admin creates invite token (`POST /api/users/invites`), recipient
  accepts via `POST /api/users/invites/accept {token, password}`.

### Environment

| Variable | Required | Purpose |
|----------|----------|---------|
| `SCRIPTDECK_JWT_SECRET` | yes | HS256 signing key (≥32 bytes). |
| `SCRIPTDECK_ENV_ENCRYPTION_KEY` | yes | 32-byte base64 key for AES-GCM. |

If either is unset on first boot, the setup page generates them and writes
`data/.env.local`, printing it once to stdout.

## 11. Environment Variable Encryption

- Per-script `.env` edited as key=value list in dashboard.
- Stored encrypted at rest: `script_envs.ciphertext` + `nonce` (AES-GCM).
- Key: `SCRIPTDECK_ENV_ENCRYPTION_KEY` (32 bytes base64, env var).
- `EnvService.decrypt(script_id)` called by `runner.executor` only. Never
  logged. Never returned by API — only `{has_env, line_count, updated_at}`.
- Audit log records `env_updated` with `{script_id, user_id}` — no plaintext.
- Key rotation: `POST /api/admin/rotate-env-key {new_key_b64}` rewraps all
  ciphertexts atomically.

## 12. Auto Dependency Detection

- **Python:** `ast.parse(source)` walks top-level `Import` + `ImportFrom`,
  collects module names, drops stdlib (bundled `stdlib_modules.py` for
  Python 3.12), takes top segment of dotted names.
- **Node:** regex over `require("...")`, `from "..."`, `import("...")`.
  Drops relative paths (`./`, `../`) and builtin modules (Node 22 stdlib
  list bundled).
- Always return editable list to UI. UI shows "Detected: X, Y, Z (edit
  before save)".
- On save: deps written to `requirements.txt` (Python) or `package.json`
  `dependencies` (Node), then `provision()` runs.

## 13. REST API

Prefix `/api`. JSON. Pydantic v2 schemas in `api/schemas.py`. OpenAPI at
`/api/docs`.

Error shape: `{detail: string, code: string}` with proper HTTP codes (`400`
validation, `401` auth, `403` role, `404` not-found, `409` conflict, `422`
business rule, `500` internal).

Pagination: `?limit=50&cursor=<base64 of (created_at, id)>`.
Filtering: `?status=running&script_id=5&since=2026-08-01`.

### Endpoints

```
AUTH
POST   /api/auth/setup
POST   /api/auth/login
POST   /api/auth/refresh
POST   /api/auth/logout
GET    /api/auth/me
PUT    /api/auth/me/password

USERS (admin only except /me)
GET    /api/users
POST   /api/users/invites
POST   /api/users/invites/accept
DELETE /api/users/:id
PUT    /api/users/:id/role

SCRIPTS
GET    /api/scripts
POST   /api/scripts
GET    /api/scripts/:id
PUT    /api/scripts/:id
DELETE /api/scripts/:id
POST   /api/scripts/:id/source
GET    /api/scripts/:id/source
POST   /api/scripts/:id/deps/detect
PUT    /api/scripts/:id/deps
GET    /api/scripts/:id/env
PUT    /api/scripts/:id/env
DELETE /api/scripts/:id/env

SCHEDULES
GET    /api/schedules
POST   /api/schedules
PUT    /api/schedules/:id
DELETE /api/schedules/:id
POST   /api/schedules/:id/enable
POST   /api/schedules/:id/disable

RUNS
GET    /api/runs
GET    /api/runs/:id
POST   /api/runs
GET    /api/runs/:id/log
GET    /api/runs/:id/log/stream          SSE
POST   /api/runs/:id/cancel

DASHBOARD STATS
GET    /api/stats

ADMIN
GET    /api/admin/audit
POST   /api/admin/rotate-env-key

HEALTH
GET    /api/health                       -> {status, db, scheduler}
```

### SSE Framing

```
event: line
data: {"offset": 0, "text": "starting...\n"}

event: line
data: {"offset": 11, "text": "done\n"}

: heartbeat   <- every 15s (comment)

event: end
data: {"status": "success", "exit_code": 0}
```

## 14. Frontend Structure (React + Vite + TypeScript)

```
frontend/
├── package.json
├── vite.config.ts            # proxy /api -> :8000 in dev
├── index.html
└── src/
    ├── main.tsx
    ├── router.tsx            # React Router, 9 routes + role guards (Login, Setup, Dashboard, Scripts, ScriptEdit, Schedules, Runs, RunView, Settings)
    ├── api/                  # typed fetchers per resource
    ├── auth/
    │   ├── AuthProvider.tsx
    │   ├── ProtectedRoute.tsx
    │   └── LoginPage.tsx
    ├── pages/
    │   ├── Dashboard.tsx
    │   ├── Scripts.tsx
    │   ├── ScriptEdit.tsx    # tabs: Source | Deps | Env | Schedules | History
    │   ├── Schedules.tsx
    │   ├── Runs.tsx
    │   ├── RunView.tsx       # live log + status badge + cancel
    │   ├── Settings.tsx      # users (admin), audit (admin), system
    │   └── Setup.tsx         # first admin form
    ├── components/           # shared UI
    └── hooks/
        ├── useLiveLogs.ts    # EventSource wrapper, reconnect, teardown
        ├── useDebounce.ts
        └── useToast.ts
```

### State

- Server state: TanStack Query.
- Auth: React Context + localStorage for JWT.
- Forms: react-hook-form + zod schemas matching backend Pydantic.
- Live logs: dedicated hook over EventSource (not TanStack).
- No global state lib (Context + Query sufficient).

### Styling

Tailwind + shadcn/ui (Radix primitives).

### Real-time UX

- `RunView` opens: fetch full log, open EventSource, append on `event: line`,
  close on `event: end`, update badge.
- `Runs` list `refetchInterval: 5s` while any run is `running`.
- `Dashboard` `running_now` counter polls every 5s.

### Code editor

`@monaco-editor/react` lazy-loaded on `ScriptEdit` only.

## 15. Storage Layout

```
data/
├── scriptdeck.db
└── .env.local                 # generated on first boot
storage/
├── scripts/<id>/<file>        # source per script
├── envs/<id>/.env             # plaintext decrypted at run time, never stored
├── venvs/<id>/.venv/          # Python (uv)
├── node_modules/<id>/         # Node
└── logs/<run_id>.log
```

Backup = `scriptdeck.db` + `storage/`. Companion CLIs:

```bash
scriptdeck backup --output backup.tgz
scriptdeck restore --input backup.tgz
```

## 16. Deployment

### Dockerfile (multi-stage)

```dockerfile
FROM node:22-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY src/ ./src/
COPY --from=frontend /app/frontend/dist ./src/scriptdeck/dashboard_static/
EXPOSE 8765
ENV SCRIPTDECK_HOST=0.0.0.0 SCRIPTDECK_PORT=8765
CMD ["uv", "run", "python", "-m", "scriptdeck"]
```

### docker-compose.yml

```yaml
name: scriptdeck
services:
  scriptdeck:
    build: .
    image: ghcr.io/aliaadil/scriptdeck:2.0.0
    restart: unless-stopped
    ports: ["8765:8765"]
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
  scriptdeck-storage:
```

### Healthcheck

`GET /api/health` returns `{"status":"ok","db":"ok","scheduler":"ok"}`.

### Logging

stdout JSON via `structlog`. Fields: `ts`, `level`, `event`, `run_id`,
`script_id`, `user_id`, `request_id`.

## 17. Testing Strategy

- **Unit:** services, runner protocol impls, dep_detect, env encrypt/
  decrypt, jwt, cron math.
- **Integration:** FastAPI `TestClient` (async) hitting real SQLite + temp
  storage. One test per endpoint contract.
- **Runner:** real subprocess against tiny scripts in temp dirs. Verify exit
  codes, log capture, lock contention.
- **SSE:** in-memory broker, simulate file appends, assert event payloads.
- **Scheduler:** fake clock + injected `asyncio.sleep`, assert cursor
  advances correctly across overlap/skip cases.
- **Frontend:** Vitest + Testing Library for components, MSW for API mocking,
  Playwright for 3-5 e2e smoke (login, create script, trigger run, view log).
- **Coverage:** backend 85% lines, frontend 70%.
- **CI:** GitHub Actions matrix (Python 3.11/3.12/3.13 + Node 20/22). Lint:
  ruff + mypy + eslint + tsc --noEmit.

## 18. Migration from v1.0.0

New migration files in v2.0:

```
db/migrations/
├── 001_init.sql              (existing v1)
├── ...                       (existing v1)
├── 005_logs_v5.sql           (existing v1; carried into v2.0 verbatim)
├── 007_from_v1.sql           NEW -- adds ONLY the five new tables (users,
│                              invites, script_envs, script_deps, audit_log).
│                              The four original tables (scripts, schedules,
│                              runs, logs) are inherited from v1 migrations
│                              001-006 unchanged. No row copy needed.
└── 008_indexes.sql           NEW -- adds idx_runs_script_started, idx_schedules_due, idx_runs_status, idx_audit_user_at
```

CLI:

```bash
scriptdeck migrate-from-v1 \
  --v1-db-path=old.db \
  --v1-storage-path=old-storage \
  --v2-db-path=scriptdeck.db \
  --v2-storage-path=storage
```

Validates compat (schema version present, no v1-only columns), copies rows,
carries `scripts.source_path` references unchanged. Leaves v1 untouched.

v1.x branch receives critical/security fixes for 6 months after v2.0 ships,
then archived.

## 19. Rollout / Versioning

- v2.0.0 = breaking (FastAPI rewrite, new auth, Basic auth removed).
- Semver: v2.x ships dashboard improvements; v3.0 when first non-Python/Node
  runner lands.
- CHANGELOG entry format: Keep a Changelog.
- Tagging: `v2.0.0`, `v2.0.1`, `v2.1.0`, ...

## 20. Open Questions

- Exact shadcn/ui component list (locked during frontend bootstrap).
- Argon2 params (use `argon2-cffi` defaults unless perf data says otherwise).
- Default audit retention: 90 days, env-overridable.

## 21. References

- Today's project: `/Users/al/orca/workspaces/scriptdeck/feat-initial-launch`
- Today's README, ROADMAP, CHANGELOG in repo root.
- Existing modules: `src/scriptrunner/{db,repository,runner,scheduler,...}.py`.
