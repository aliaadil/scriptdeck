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

These are the next Kanban tasks the steward will pick up. None are shipped in this scaffold:

- [ ] Subprocess runner (execute `source_path` against the right interpreter, capture stdout/stderr to `storage/`)
- [ ] Scheduler tick (poll `schedules.next_run_at`, fire the runner, advance the cursor)
- [ ] Per-script isolation (`uv venv` for Python, `node_modules/` for Node)
- [ ] Live log viewer (server-sent events over `/api/logs/<run_id>/stream`)
- [ ] Authentication (single-user basic auth for v1, multi-tenant later)
- [ ] Retry policy + alerting webhooks on `status='failure'`

See [`ROADMAP.md`](ROADMAP.md) and the [Operator Runbook](https://github.com/aliaadil/scriptdeck/wiki) for detail.

## Install & run

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

> **Note:** the runner is not built yet, so no `runs` rows will appear on their own until the scheduler-tick Kanban task lands. Until then, you can manually insert a run row via `POST /api/runs` for testing.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `SCRIPTDECK_DB_PATH` | `scriptdeck.db` | SQLite file path. Backup this one file. |
| `SCRIPTDECK_STORAGE_DIR` | `storage` | Per-script source + per-run logs live here. |
| `SCRIPTDECK_HOST` | `127.0.0.1` | Bind address. Set to `0.0.0.0` if fronted by a reverse proxy. |
| `SCRIPTDECK_PORT` | `8765` | TCP port. |

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
│   ├── config.py                # Settings dataclass + env-var loader
│   ├── db.py                    # SQLite connect + versioned migrations
│   ├── repository.py            # typed CRUD over the schema
│   └── server.py                # stdlib HTTP/JSON API
├── tests/
│   ├── test_db.py               # migrations + smoke
│   ├── test_repository.py       # CRUD invariants
│   └── test_server.py           # end-to-end HTTP contract
├── pyproject.toml
├── README.md
├── ROADMAP.md
├── LICENSE
└── .github/workflows/ci.yml
```

## License

MIT — see [`LICENSE`](LICENSE).