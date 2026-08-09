# ScriptDeck

> **Single-host scheduled script runner.** Upload a script, give it a cron or interval, watch runs and their logs land in one SQLite file plus a `storage/` tree. Stdlib only. No runtime dependencies. No Docker required.

[![CI](https://github.com/aliaadil/scriptdeck/actions/workflows/ci.yml/badge.svg)](https://github.com/aliaadil/scriptdeck/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Why

Cron + logrotate + ad-hoc shell wrappers work — until you have a dozen jobs that need conflicting Python versions, structured run history, and a record of *what actually ran and when*. ScriptDeck gives you that without dragging in Postgres, Redis, or a workflow engine.

## What ships today

- **SQLite-backed persistence** — one file, four tables (`scripts`, `schedules`, `runs`, `logs`), versioned migrations.
- **Stdlib HTTP JSON API** — manage scripts, schedules, runs, and read log metadata over a single port.
- **Zero runtime dependencies** — `pip install scriptdeck` and you're done. No FastAPI, no Pydantic, no SQLAlchemy.
- **Environment-variable config** — `SCRIPTDECK_DB_PATH`, `SCRIPTDECK_STORAGE_DIR`, `SCRIPTDECK_HOST`, `SCRIPTDECK_PORT`. Coolify, systemd, plain shell — all the same.

## What's tracked but not yet built

These ship in v0.7 (already merged on `main`):

- [x] Subprocess runner — `scriptrunner.scheduler.run_script_now()`
- [x] Scheduler tick — `scriptrunner.scheduler.Scheduler` background thread
- [x] Retry policy — `retry_max`, `retry_backoff_seconds`, `retry_attempt`, `retry_group_id`
- [x] Alerting webhook — `SCRIPTDECK_BASIC_AUTH` env var + `POST` to `alert_webhook_url` on exhaustion

Still on the roadmap:

- [ ] Per-script isolation (`uv venv` for Python, `node_modules/` for Node)
- [ ] Live log viewer (server-sent events over `/api/logs/<run_id>/stream`)
- [ ] Multi-user / multi-tenant auth (deferred past v1.0)

## Install & run

The quickest path is Docker — see [Install](#install) below. For local dev:

```bash
git clone https://github.com/aliaadil/scriptdeck
cd scriptdeck
pip install -e .

scriptdeck                 # boots on http://127.0.0.1:8765
# or
python -m scriptrunner
```

### Quickstart

```bash
# 1. Health check
curl -s http://127.0.0.1:8765/health
# -> {"status": "ok"}

# 2. Register a script
curl -s -X POST http://127.0.0.1:8765/api/scripts \
  -H 'Content-Type: application/json' \
  -d '{"name":"hello","language":"python","source_path":"./storage/scripts/hello.py"}'

# 3. Attach a schedule
curl -s -X POST http://127.0.0.1:8765/api/schedules \
  -H 'Content-Type: application/json' \
  -d '{"script_id":1,"kind":"interval","expression":"15m","enabled":true}'

# 4. Inspect
curl -s http://127.0.0.1:8765/api/scripts
curl -s http://127.0.0.1:8765/api/schedules
```

> **Note:** the runner ships in v0.7 — schedules fire automatically and
> `runs` rows appear with `stdout`/`stderr` captured to `<SCRIPTDECK_STORAGE_DIR>/logs/<run_id>.log`.
> Try `scriptdeck-doctor` to validate a fresh install.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SCRIPTDECK_DB_PATH` | `scriptdeck.db` | SQLite file path. Backup this one file. |
| `SCRIPTDECK_STORAGE_DIR` | `storage` | Per-script source + per-run logs live here. |
| `SCRIPTDECK_HOST` | `127.0.0.1` | Bind address. Set to `0.0.0.0` if fronted by a reverse proxy. |
| `SCRIPTDECK_PORT` | `8765` | TCP port. |
| `SCRIPTDECK_BASIC_AUTH` | _(unset)_ | Optional. `user:bcrypt-hash` enables HTTP basic auth on every endpoint. Leave unset for local-only. Generate with: `htpasswd -nbBC 12 "" "your-password" \| tr -d ':\n' \| sed 's/\$2y\$/\$2a\$/'`. (v0.6+) |

> **Legacy names:** the v0.1-era code shipped with `SCRIPTRUNNER_*` env-var
> names; both names are still accepted (`SCRIPTDECK_*` wins when both are
> set). New deployments should use `SCRIPTDECK_*`.

## Install

### Docker (recommended)

The image is published to `ghcr.io/aliaadil/scriptdeck`. Two ways to run:

**Quick start (just run it):**
```bash
docker run -d --name scriptdeck --restart unless-stopped \
  -p 8765:8765 \
  -v scriptdeck-data:/data \
  -v scriptdeck-storage:/storage \
  ghcr.io/aliaadil/scriptdeck:latest
```

**Production (persistent, env-var driven):** use the included compose file.
```bash
curl -O https://raw.githubusercontent.com/aliaadil/scriptdeck/main/docker-compose.yml
# Optional: set SCRIPTDECK_BASIC_AUTH=user:bcrypt-hash in your shell or .env
docker compose up -d
docker compose logs -f
docker compose exec scriptdeck scriptdeck-doctor   # validate the install
```

The named volumes (`scriptdeck-data`, `scriptdeck-storage`) survive container
restarts and `docker compose down`. Backup `scriptdeck-data/scriptdeck.db`
+ `scriptdeck-storage/` for a full disaster-recovery snapshot.

### Coolify

Add a new resource of type **Docker Compose** in Coolify, point it at this
repo, and select `coolify/docker-compose.yml` as the compose file. Coolify
will prompt for `SCRIPTDECK_BASIC_AUTH` (leave blank to disable auth) and
`SCRIPTDECK_PORT` (default `8765`).

### systemd (bare-metal / VM)

```bash
# 1. Install
sudo useradd --system --home /opt/scriptdeck scriptdeck
sudo mkdir -p /opt/scriptdeck /var/lib/scriptdeck
sudo chown -R scriptdeck:scriptdeck /opt/scriptdeck /var/lib/scriptdeck
sudo -u scriptdeck git clone https://github.com/aliaadil/scriptdeck /opt/scriptdeck/src
cd /opt/scriptdeck/src && sudo -u scriptdeck uv venv .venv && sudo -u scriptdeck uv pip install -e .

# 2. Configure
sudo cp packaging/systemd/scriptdeck.env.example /etc/scriptdeck/scriptdeck.env
sudoedit /etc/scriptdeck/scriptdeck.env         # set SCRIPTDECK_BASIC_AUTH, SCRIPTDECK_PORT, etc.
sudo chmod 600 /etc/scriptdeck/scriptdeck.env
sudo cp packaging/systemd/scriptdeck.service /etc/systemd/system/scriptdeck.service

# 3. Activate
sudo systemctl daemon-reload
sudo systemctl enable --now scriptdeck
sudo systemctl status scriptdeck
sudo journalctl -u scriptdeck -f
```

## Storage layout

```
.
├── scriptdeck.db                # ← backup this one file
├── storage/
│   ├── scripts/<id>/<file>      # source uploaded per script
│   ├── envs/<id>/               # per-script venv (when runner ships)
│   └── logs/<run_id>.log        # captured stdout/stderr per run
```

Backing up `scriptdeck.db` plus `storage/` is a complete disaster-recovery snapshot.

## Development

```bash
git clone https://github.com/aliaadil/scriptdeck
cd scriptdeck
pip install -e ".[dev]"          # if/when dev extras exist; for now: pip install pytest ruff
pytest                          # runs the migration + repository test suite
ruff check src/ tests/          # lint
```

## Project layout

```
scriptdeck/
├── src/scriptrunner/            # the package (kept as `scriptrunner` for the console script)
│   ├── __init__.py
│   ├── __main__.py              # `python -m scriptrunner` entry
│   ├── alerting.py              # v0.7 webhook delivery
│   ├── config.py                # Settings dataclass + env-var loader (SCRIPTDECK_* + legacy SCRIPTRUNNER_*)
│   ├── db.py                    # SQLite connect + versioned migrations
│   ├── doctor.py                # v0.7 `scriptdeck-doctor` CLI
│   ├── repository.py            # typed CRUD over the schema
│   ├── scheduler.py             # v0.7 background scheduler tick
│   └── server.py                # stdlib HTTP/JSON API
├── tests/
│   ├── test_config_env.py       # env-var precedence: SCRIPTDECK_* vs SCRIPTRUNNER_*
│   ├── test_db.py               # migrations + smoke
│   ├── test_repository.py       # CRUD invariants
│   ├── test_server.py           # end-to-end HTTP contract
│   ├── test_alerting.py         # v0.7 webhook + retry policy
│   ├── test_doctor.py           # v0.7 install validator
│   ├── test_scheduler.py        # v0.7 scheduler tick
│   └── test_migrations_v2_v3.py # v0.7 schema bumps
├── packaging/
│   └── systemd/                 # `scriptdeck.service` + `scriptdeck.env.example`
├── coolify/
│   └── docker-compose.yml       # Coolify one-click resource definition
├── docker-compose.yml           # local + production compose
├── Dockerfile                   # multi-stage, non-root, python:3.12-slim
├── pyproject.toml
├── README.md
├── ROADMAP.md
├── LICENSE
└── .github/workflows/
    ├── ci.yml                   # pytest + ruff on PRs
    └── docker.yml               # builds + publishes ghcr.io image
```

## License

MIT — see [`LICENSE`](LICENSE).