# Changelog

All notable changes to ScriptDeck are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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