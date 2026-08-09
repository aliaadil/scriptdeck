# Changelog

All notable changes to ScriptDeck are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — 2026-08-08

### Added
- Per-script language isolation (v0.4).
- `scripts` table now stores `requirements_path` and `interpreter_path`
  (migration v4).
- `scriptrunner.isolation` module: per-script `uv venv` for python,
  `node_modules/` for node, clean env (`PATH=/usr/bin:/bin`) for bash.
- `provision_lock()` plus a shareable `open_lock()` class for tests, both
  using `fcntl.flock` so the lock survives process crashes.
- `POST /api/scripts` now accepts inline `source` and `requirements` fields
  and persists them under `<storage>/scripts/<id>/`.
- `POST /api/scripts/<id>/run` triggers the runner and returns the run row
  + retry decision.
- `scriptrunner.runner` module: minimal subprocess runner that uses
  isolation, captures stdout+stderr to `<storage>/logs/<run_id>.log`, and
  hands off to `scheduler.record_run_result` for retry/alert policy.
- 10 new tests in `tests/test_isolation.py` (67 total now passing).

## [0.5.0] — 2026-08-08

### Added
- Server-Sent Events log stream at `GET /api/logs/<run_id>/stream`. Tails
  `<storage>/logs/<run_id>.log` and emits one `data:` event per new line,
  with the v0.5 SLA of "<1 second from line written to event sent".
- Final `event: end` SSE frame plus socket close when `runs.status` reaches
  a terminal state (`success`, `failure`, `error`, `cancelled`). The page
  badge updates accordingly via the EventSource `addEventListener('end')`
  hook.
- Static HTML index at `GET /logs` (no auth — auth is v0.6). Lists the
  newest 50 runs (id, script name, status badge, duration, started_at) and
  links each row to its viewer.
- Static HTML viewer at `GET /logs/<run_id>` that embeds a vanilla-JS
  EventSource client (28 lines of inline JS, no framework, no build step).
- Heartbeat SSE comment every 15s so idle connections survive proxies.
- Migration v5: rebuild `runs` table to allow `status='running'` (in-flight
  placeholder for the live viewer) and `status='cancelled'`. Existing data
  and the v2 retry-group index are preserved.
- New repository constants: `RUN_STATUSES` (now includes `running`) and
  `TERMINAL_RUN_STATUSES` (the four end-states that close the SSE stream).
- New helper: `list_recent_runs_with_script(conn, limit=50)` for the index
  page, joining `scripts` to `runs` so each row can render the script label
  in one query.
- New module `scriptrunner.log_stream` containing the testable pure logic:
  `read_new_lines(path, offset)` and `encode_sse(data, event=None)`.
- 12 new tests (test_log_stream.py + migration coverage) for SSE framing,
  active-file tailing, terminal-status closing, 404 handling, static-page
  rendering, and the v5 migration.

### Changed
- `RequestHandler.protocol_version` bumped to `HTTP/1.1` so the SSE endpoint
  can stream via chunked transfer encoding (no Content-Length).
- `TCP_NODELAY` is enabled on the underlying socket at the start of an SSE
  response so events flush to the client immediately.

## [0.1.0] — 2026-08-08

### Added
- Initial scaffold.
- SQLite-backed persistence with four tables (`scripts`, `schedules`, `runs`, `logs`) and versioned migrations.
- Stdlib HTTP/JSON API for managing scripts, schedules, runs, and reading log metadata.
- Environment-variable configuration (`SCRIPTDECK_DB_PATH`, `SCRIPTDECK_STORAGE_DIR`, `SCRIPTDECK_HOST`, `SCRIPTDECK_PORT`).
- Test suite (22 tests): migrations, repository CRUD invariants, end-to-end HTTP contract.
- GitHub Actions CI: pytest on Python 3.11 / 3.12 / 3.13, ruff lint.
- Operator runbook in Obsidian vault (`Projects/ScriptRunner/Operator Runbook.md`).
- Research report at `script-runner-research/report.html` (off-repo) — every cited source preserved.

### Known gaps (tracked under [ROADMAP.md](ROADMAP.md))
- Subprocess runner not yet implemented (rows in `runs` are not auto-populated).
- Scheduler tick not yet implemented (rows in `schedules` are not auto-fired).
- Per-script isolation (`uv venv`, `node_modules/`) not yet implemented.
- Live log viewer not yet implemented.
- Authentication not yet implemented (the service currently binds to `127.0.0.1` only and has no auth on `/api/*`).
