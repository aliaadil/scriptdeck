# ScriptDeck Roadmap

The path from "scaffold on a laptop" to "polished self-hosted product." Each milestone is sized to ship as a single Kanban card, with the worker branching off the current `main` and opening a PR per card. As cards land, the merge target moves: v0.7 was developed and merged first on its own branch because the dependency chain (`runs.log_path`, the runner status field) was needed by v0.5; subsequent cards stack on top.

## v0.1 — Scaffold (shipped)

- SQLite schema with four tables and versioned migrations
- Stdlib HTTP/JSON API for `scripts`, `schedules`, `runs`, `logs`
- Environment-variable configuration
- CI on GitHub Actions (pytest + ruff)
- Operator documentation

## v0.2 — The runner (next up)

- Subprocess runner that executes `scripts.source_path` with the right interpreter (`python3`, `node`, `bash`)
- Captures stdout + stderr to `storage/logs/<run_id>.log`
- Writes `runs` row with `started_at`, `ended_at`, `exit_code`, `status` (start with `status='running'`, transition to a terminal status on exit; see v0.5 for the full enum)
- Writes `logs` row with `path` + `size_bytes` on completion
- Idempotent: re-running a failed run does not duplicate state
- Concurrency-safe: at most one runner per script at a time (file-lock per `script_id`)

## v0.3 — The scheduler tick

- Background thread that wakes every 5 s, polls `schedules` where `enabled=1` and `next_run_at <= now()`
- Invokes the runner for due schedules
- Advances `next_run_at` using `croniter` for `kind='cron'` and `expression` for `kind='interval'`
- Skip-on-overlap: if the previous run for the same `script_id` is still active, mark a `status='error'` row with `exit_code=-1` and reason, then advance the cursor
- Self-heals on clock drift: if a tick is missed, the next tick picks up every schedule whose `next_run_at` is now in the past (no backlog explosion due to the skip-on-overlap rule)

## v0.4 — Per-script isolation

- `language='python'` scripts run inside a per-script `uv venv` provisioned on first run
- `language='node'` scripts run with `node_modules/` resolved from a per-script dir
- `language='bash'` runs as a plain subprocess with a clean environment
- Lock file per script dir prevents two runners from racing on the same venv bootstrap
- API surfaces the resolved interpreter path on `GET /api/scripts/<id>`

## v0.5 — Log viewer (shipped)

- Server-sent events over `GET /api/logs/<run_id>/stream` — tails `<storage>/logs/<run_id>.log`, one `data:` event per new line, heartbeat every 15s.
- Closes with a final `event: end` frame when `runs.status` reaches a terminal value (`success`, `failure`, `error`, `cancelled`).
- Static HTML index at `/logs` (last 50 runs) and viewer at `/logs/<run_id>` — vanilla-JS EventSource client, no SPA, no framework.

## v0.6 — Auth

- Single-user HTTP basic auth for v1 (env-var `SCRIPTDECK_BASIC_AUTH=user:hash`)
- Password hashed with `bcrypt` or `argon2` (whichever lands as a stdlib-friendly option; likely a single optional dependency at this point)
- Multi-tenant auth deferred to v0.8+

## v0.7 — Polish

- `scriptdeck doctor` CLI: validates config, checks DB reachable, lists orphaned `runs`
- Structured JSON logs from the runner
- Per-run metrics (duration histogram, exit-code distribution) on `GET /api/runs`
- Retry policy: schedules get `retry_max` + `retry_backoff`
- Alerting webhook: `POST <webhook_url>` on `status='failure'` or `status='error'`

## v1.0 — Public release

- Docs site (mkdocs-material)
- Docker image (`FROM python:3.12-slim`)
- Coolify one-click template
- Migration path for users coming from `bugy/script-server` (read-only importer for scripts + schedules)

## Out of scope (still)

- Multi-host execution (use Kubernetes + Argo Workflows instead)
- Workflow DAGs (use Temporal, Prefect, or Airflow instead — ScriptDeck is intentionally a single cron row per script)
- Webhook triggers (use n8n in front of ScriptDeck's HTTP API instead)
- Secret management beyond environment variables (use HashiCorp Vault or Infisical in front)