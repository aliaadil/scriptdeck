# Kindling

[![CI](https://github.com/aliaadil/kindling/actions/workflows/ci.yml/badge.svg)](https://github.com/aliaadil/kindling/actions)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Self-hosted scheduled script runner.

```bash
docker compose up -d
open http://localhost:8765/kindling/
```

First boot redirects to `/setup` to create the first admin.

## Migrate from v1

```bash
kindling migrate-from-v1 \
  --v1-db-path=./old/scriptdeck.db \
  --v1-storage-path=./old/storage \
  --v2-db-path=./data/kindling.db \
  --v2-storage-path=./storage
```

v1.x receives security fixes until 2027-02-14, then archived.

## Why

Cron + logrotate + ad-hoc shell wrappers work — until you have a dozen jobs that need conflicting Python versions, structured run history, and a record of *what actually ran and when*. Kindling gives you that without dragging in Postgres, Redis, or a workflow engine.

## What ships in v2.0

- FastAPI + React/Vite SPA in a single Docker image.
- Multi-user with JWT auth, role-based access (admin/editor/viewer), invite flow.
- Per-script isolated runtimes: Python via `uv venv`, Node via `node_modules`.
- Encrypted per-script `.env` files (AES-GCM).
- Auto dependency detection for Python + Node.
- Live log streaming via SSE.
- Cron + interval scheduling with retries.
- CLI subcommands: `serve`, `doctor`, `backup`, `restore`, `migrate-from-v1`.
- Full audit log of every mutating action.

## What's tracked but not yet built

These are the next Kanban tasks the steward will pick up. None are shipped yet:

- [ ] Subprocess runner (execute `source_path` against the right interpreter, capture stdout/stderr to `storage/`)
- [ ] Scheduler tick (poll `schedules.next_run_at`, fire the runner, advance the cursor)
- [ ] Per-script isolation (`uv venv` for Python, `node_modules/` for Node)
- [ ] Authentication (single-user basic auth for v1, multi-tenant later)
- [ ] Retry policy + alerting webhooks on `status='failure'`

## Live log viewer (v0.5)

The runner still doesn't exist, but the viewer is shipped ahead of it so the
interface is in place. Once a runner writes lines to
`storage/logs/<run_id>.log` and transitions the row's `status` to a terminal
value (`success`, `failure`, `error`, `cancelled`), you can tail it in a
browser:

- `GET /kindling/logs` — last 50 runs (id, script, status badge, duration, started).
- `GET /kindling/logs/<run_id>` — vanilla-JS EventSource viewer that streams lines in
  real time and updates a status badge when the run ends.
- `GET /api/kindling/logs/<run_id>/stream` — the raw SSE endpoint, also usable from
  `curl -N` or any EventSource client.

See [`ROADMAP.md`](ROADMAP.md) and the [Operator Runbook](https://github.com/aliaadil/kindling/wiki) for detail.

## Install & run

```bash
git clone https://github.com/aliaadil/kindling
cd kindling
pip install -e .

kindling                      # boots on http://127.0.0.1:8765
# or
python -m kindling
```

### Quickstart

```bash
# 1. Health check
curl -s http://127.0.0.1:8765/api/kindling/health
# -> {"status": "ok"}

# 2. Register a script
curl -s -X POST http://127.0.0.1:8765/api/kindling/scripts \
  -H 'Content-Type: application/json' \
  -d '{"name":"hello","language":"python","source_path":"./storage/scripts/hello.py"}'

# 3. Attach a schedule
curl -s -X POST http://127.0.0.1:8765/api/kindling/schedules \
  -H 'Content-Type: application/json' \
  -d '{"script_id":1,"kind":"interval","expression":"15m","enabled":true}'

# 4. Inspect
curl -s http://127.0.0.1:8765/api/kindling/scripts
curl -s http://127.0.0.1:8765/api/kindling/schedules
```

> **Note:** the runner is not built yet, so no `runs` rows will appear on their own until the scheduler-tick Kanban task lands. Until then, you can manually insert a run row via `POST /api/kindling/runs` for testing.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `KINDLING_DB_PATH` | `./data/kindling.db` | SQLite file path. Backup this one file. |
| `KINDLING_STORAGE_DIR` | `storage` | Per-script source + per-run logs live here. |
| `KINDLING_HOST` | `127.0.0.1` | Bind address. Set to `0.0.0.0` if fronted by a reverse proxy. |
| `KINDLING_PORT` | `8765` | TCP port. |
| `KINDLING_JWT_SECRET` | unset | Required. Random secret for JWT signing. |
| `KINDLING_ENV_ENCRYPTION_KEY` | unset | Required. Base64 32-byte key for AES-GCM .env encryption. |
| `KINDLING_BASIC_AUTH` | unset | Optional single-user Basic auth in `username:bcrypt_hash` format. |

### HTTP Basic auth

Authentication is disabled when `KINDLING_BASIC_AUTH` is unset. When it is
set, `/api/kindling/health`, `/`, `/kindling/logs`, and every `/api/kindling/*` route require HTTP Basic auth.
The configured password must be a bcrypt hash; plaintext passwords are not
accepted. Install the optional dependency with:

```bash
pip install -e '.[auth]'
```

Generate a bcrypt hash locally (the command below uses Apache's `htpasswd`):

```bash
htpasswd -nbBC 12 "" "password" | tr -d ':\n' | sed 's/\$2y\$/\$2a\$/'
```

Set the resulting value in Coolify as an environment variable. For example,
if the generated hash is `$2a$12$...`, set:

```text
KINDLING_BASIC_AUTH=kindling:$2a$12$...
```

Keep the value in Coolify's secret/environment-variable store and do not put
it in the repository. Restart or redeploy the service after changing it.

## Storage layout

```
.
├── data/kindling.db            # ← backup this one file
└── storage/
    ├── users/<user_id>/
    │   ├── scripts/<id>/<file>      # source uploaded per script
    │   ├── envs/<id>/.env.encrypted # AES-GCM encrypted
    │   ├── venvs/<id>/.venv/...     # per-script Python venv
    │   ├── node_modules/<id>/...    # per-script Node deps
    │   └── logs/<run_id>.log        # captured stdout/stderr
    └── locks/<id>.lock
```

Backing up `data/kindling.db` plus `storage/` is a complete disaster-recovery snapshot.

## Security model

When `KINDLING_SANDBOX_ENABLED=true`, every script runs in a private mount
namespace chrooted into its user's subtree. Other users' files are not
mounted and therefore `open('/storage/users/<other>/...')` returns `ENOENT`.
Env vars are scrubbed to a small whitelist plus the script's own decrypted
env. The parent process's `os.environ` (which contains `KINDLING_JWT_SECRET`
and `KINDLING_ENV_ENCRYPTION_KEY`) is never copied into the child.

This is **good-citizen** isolation: it stops accidental cross-reads and
defends against a curious user, but does not claim to defeat a knowledgeable
attacker. For hardening beyond this, see the Roadmap.

## Development

```bash
git clone https://github.com/aliaadil/kindling
cd kindling
pip install -e ".[dev]"          # if/when dev extras exist; for now: pip install pytest ruff
pytest                          # runs the migration + repository test suite
ruff check src/ tests/          # lint
```

## Project layout

```
kindling/
├── src/kindling/                # the package
│   ├── api/                     # FastAPI routers (auth, scripts, runs, ...)
│   ├── auth/                    # JWT + bcrypt helpers
│   ├── cli_commands/            # subcommand implementations
│   ├── db/                      # engine + SQLAlchemy models
│   ├── migrations/              # versioned SQL migrations
│   ├── runner/                  # subprocess execution + sandboxing
│   ├── scheduler/               # cron/interval tick loop
│   ├── services/                # EnvService, log broker, retention, ...
│   ├── app.py                   # FastAPI factory + lifespan
│   ├── cli.py                   # argparse entry
│   ├── config.py                # Settings dataclass + env-var loader
│   └── dashboard_static/        # Vite build output (mounted at /kindling)
├── tests/
│   ├── api/                     # HTTP contract tests
│   ├── services/                # service-layer tests
│   ├── test_app.py
│   ├── test_auth.py / test_auth_api.py
│   ├── test_branding.py
│   ├── test_compose.py
│   ├── test_config.py
│   ├── test_db.py / test_migrations.py
│   ├── test_env_service.py
│   ├── test_executor.py / test_executor_sandbox_wiring.py
│   ├── test_kindling_spa_fallback.py
│   ├── test_log_broker.py
│   ├── test_migrate_from_v1.py
│   ├── test_migrate_users.py
│   ├── test_retention.py
│   ├── test_routes.py
│   ├── test_runner_protocol.py / test_runner_sandbox_view.py
│   ├── test_sandbox.py / test_sandbox_view.py
│   ├── test_schedule_api.py / test_schedule_compute.py
│   ├── test_scheduler.py / test_scheduler_tick_v2.py
│   └── test_*.py                # many more focused suites
├── frontend/                    # Vite + React SPA
│   ├── src/api / src/auth / src/components / src/pages
│   └── index.html
├── docs/                        # install, operations, troubleshooting
├── pyproject.toml
├── docker-compose.yml / Dockerfile
├── README.md / ROADMAP.md / CHANGELOG.md / LICENSE
└── .github/workflows/ci.yml
```

## License

MIT — see [`LICENSE`](LICENSE).