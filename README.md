# ScriptDeck

> **Single-host scheduled script runner.** Upload a script, give it a cron or interval, watch runs and their logs land in one SQLite file plus a `storage/` tree. The core service uses the standard library; bcrypt is an optional dependency for HTTP Basic auth. No Docker required.

[![CI](https://github.com/aliaadil/scriptdeck/actions/workflows/ci.yml/badge.svg)](https://github.com/aliaadil/scriptdeck/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## Why

Cron + logrotate + ad-hoc shell wrappers work — until you have a dozen jobs that need conflicting Python versions, structured run history, and a record of *what actually ran and when*. ScriptDeck gives you that without dragging in Postgres, Redis, or a workflow engine.

## What ships today

- **SQLite-backed persistence** — one file, four tables (`scripts`, `triggers`, `runs`, `logs`), versioned migrations.
- **Stdlib HTTP JSON API** — manage scripts, schedules, runs, and read log metadata over a single port.
- **Small dependency surface** — `pip install scriptdeck` and you're done. No FastAPI, no Pydantic, no SQLAlchemy. Install the optional `auth` extra when enabling Basic auth.
- **Environment-variable config** — `SCRIPTDECK_DB_PATH`, `SCRIPTDECK_STORAGE_DIR`, `SCRIPTDECK_HOST`, `SCRIPTDECK_PORT`. Coolify, systemd, plain shell — all the same.

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

- `GET /logs` — last 50 runs (id, script, status badge, duration, started).
- `GET /logs/<run_id>` — vanilla-JS EventSource viewer that streams lines in
  real time and updates a status badge when the run ends.
- `GET /api/logs/<run_id>/stream` — the raw SSE endpoint, also usable from
  `curl -N` or any EventSource client.

See [`ROADMAP.md`](ROADMAP.md) and the [Operator Runbook](https://github.com/aliaadil/scriptdeck/wiki) for detail.

## Triggers (v0.8)

A script can have 0..N *triggers*. Each trigger is either:

- **schedule** — a cron/interval expression that fires the runner on a cadence.
  Carries the legacy retry policy (`retry_max`, `retry_backoff_seconds`) and
  an optional `alert_webhook_url` that fires once when retries are exhausted.
- **webhook** — a unique URL `http://host/webhooks/<token>` plus a 64-char
  secret token. POSTing to that URL enqueues a run for the script. No Basic
  auth — the token in the path is the only credential.

Both kinds carry an optional `params` map (JSON object of stringy keys/values).
At run time, every entry is exported as `SCRIPTDECK_PARAM_<KEY>` plus the full
blob as `SCRIPTDECK_PARAMS_JSON`, so two triggers on the same script can pass
different flags without mutating the script row.

API surface:

```bash
# Create a script
curl -X POST http://127.0.0.1:8765/api/scripts \
  -H 'Content-Type: application/json' \
  -d '{"name":"nightly","language":"python","source":"print(\"hi\")\n"}'

# Attach a schedule trigger with per-trigger params
curl -X POST http://127.0.0.1:8765/api/scripts/1/triggers/schedule \
  -H 'Content-Type: application/json' \
  -d '{"schedule_kind":"cron","expression":"0 3 * * *","params":{"env":"prod"}}'

# Attach a webhook trigger
curl -X POST http://127.0.0.1:8765/api/scripts/1/triggers/webhook \
  -H 'Content-Type: application/json' \
  -d '{"params":{"region":"us-east-1"}}'
# -> {"id":3,"kind":"webhook","webhook_url":"http://.../webhooks/<token>", ...}

# Hit the webhook to fire the script (no Basic auth required)
curl -X POST http://127.0.0.1:8765/webhooks/<token> -d '{}'
# -> 202 {"run_id":42,"status":"success"}
```

The HTML view at `GET /scripts/<id>` lists every trigger with add / run-now /
delete buttons; the page is plain HTML + a few lines of vanilla JS so it works
without a build step.

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
| `SCRIPTDECK_BASIC_AUTH` | unset | Optional single-user Basic auth in `username:bcrypt_hash` format. |

### HTTP Basic auth

Authentication is disabled when `SCRIPTDECK_BASIC_AUTH` is unset. When it is
set, `/health`, `/`, `/logs`, and every `/api/*` route require HTTP Basic auth.
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
SCRIPTDECK_BASIC_AUTH=scriptdeck:$2a$12$...
```

Keep the value in Coolify's secret/environment-variable store and do not put
it in the repository. Restart or redeploy the service after changing it.

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