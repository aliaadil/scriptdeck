# Kindling rebrand — design

**Date:** 2026-08-17
**Status:** Approved (brainstorming → spec)
**Branch:** `feat/rebranding`

## Context

`ScriptDeck` collides with other products in the scripting/macro-pad space
(notably [scriptdeck.org](https://scriptdeck.org), a Stream Deck scripting
companion, and the broader Elgato Stream Deck ecosystem). The project needs a
distinctive name and a refreshed identity before v2.0 ships.

## Decision

Rebrand to **Kindling**.

- Maker/workshop metaphor: small fires, lighting scripts on a schedule.
- Friendly, dev-tool-adjacent tone.
- Reads cleanly as a wordmark, a CLI, and an API namespace.

## Brand

### Name

`Kindling`. Lowercase in product/code, sentence case in prose.

### Wordmark

Lowercase mono: `kindling`. Dev-tool energy, quiet, technical.
Final asset: `frontend/public/logo-wordmark.svg` and
`frontend/public/logo.svg` (combined mark + wordmark).

### Mark

Ember cluster: three overlapping warm-tone circles (saturated red, orange,
gold) on near-black. Abstract, modern, scales to favicon. Implementation:
`frontend/public/favicon.svg`.

### Palette ("Spark modern")

| Token       | Hex       | Use                                |
|-------------|-----------|------------------------------------|
| `ember`     | `#dc2626` | deepest red — accent, error states |
| `spark`     | `#fb923c` | orange — primary accent            |
| `flame`     | `#facc15` | yellow — highlights, success       |
| `charcoal`  | `#0c0a09` | background                         |
| `text`      | `#f5f5f4` | foreground text                    |

Exposed as CSS custom properties in `frontend/src/index.css`.

## Identity changes (repo-wide)

| Layer            | Old                       | New                          |
|------------------|---------------------------|------------------------------|
| GitHub repo      | `aliaadil/scriptdeck`     | `aliaadil/kindling`          |
| PyPI package     | `scriptdeck`              | `kindling-runner` (name `kindling` taken on PyPI by an unrelated project; CLI command, brand, and Python imports remain `kindling`) |
| Python module    | `scriptdeck/`             | `kindling/`                  |
| CLI binary       | `scriptdeck`              | `kindling`                   |
| CLI subcommands  | `serve`, `doctor`, `backup`, `restore`, `migrate-from-v1` | unchanged |
| Docker image     | `aliaadil/scriptdeck`     | `aliaadil/kindling`          |
| Compose project  | `scriptdeck`              | `kindling`                   |
| Container name   | `scriptdeck`              | `kindling`                   |
| Default DB path  | `./data/scriptdeck.db`    | `./data/kindling.db`         |
| Storage dir      | `./storage/`              | unchanged                    |
| HTTP port        | `8765`                    | unchanged                    |
| Dashboard URL    | `/dashboard/`             | `/kindling/`                 |
| API base         | `/api/...`                | `/api/kindling/...`          |
| Config file      | `scriptdeck.toml`         | `kindling.toml`              |
| Env var prefix   | `SCRIPTDECK_*`            | `KINDLING_*`                 |
| Brand title      | `ScriptDeck`              | `Kindling`                   |

## What stays unchanged

- DB schema (tables, columns, indexes).
- API JSON field names (`script_id`, `run_id`, `status`, etc.).
- Cron expression syntax, retry policy semantics.
- Storage layout (`/storage/scripts/`, `/storage/logs/`, `/storage/env/`).
- v1 → v2 migration data format.
- License (MIT), Python version support (3.11/3.12/3.13).
- HTTP port (8765) — fewer surprises for existing deploys.

## Files to touch

### Code

- `src/scriptdeck/` → rename to `src/kindling/`; update internal imports.
- `pyproject.toml` — `[project] name`, `[project.scripts]` entry point.
- `Dockerfile` — module path (`scriptdeck.cli` → `kindling.cli`).
- `docker-compose.yml` — image name, container name, volume mounts,
  `KINDLING_*` env.
- `.env.example` — `KINDLING_*` keys.
- `src/kindling/migrate_from_v1.py` — CLI flag names updated
  (`--v2-db-path` default `./data/kindling.db`).

### Frontend

- `frontend/index.html` — `<title>Kindling</title>`, `theme-color`,
  description meta.
- `frontend/src/components/brand.tsx` — render new mark + wordmark.
- `frontend/src/index.css` — palette CSS vars.
- `frontend/public/logo.svg`, `frontend/public/favicon.svg` — new assets.
- All hardcoded strings: `ScriptDeck` → `Kindling`,
  `/dashboard/` → `/kindling/`, `/api/...` → `/api/kindling/...`.
- Router (`frontend/src/router.tsx`) — base path.

### Backend API

- `src/kindling/api/` — FastAPI router prefix updated to `/api/kindling`.
- Static mount for dashboard: served at `/kindling/` (was `/dashboard/`).

### Tests

- All `tests/**/*.py` referencing module path, CLI command, URLs, env vars.
- `frontend/tests/e2e/smoke.spec.ts` — base URL `/kindling/`.

### Docs

- `README.md` — new name + logo, quickstart path.
- `CHANGELOG.md` — top entry: rebrand to Kindling.
- `ROADMAP.md` — any references to "ScriptDeck".
- `docs/index.md`, `docs/install.md`, `docs/api.md`, `docs/operations.md`,
  `docs/troubleshooting.md` — replace names, paths, env vars.
- `mkdocs.yml` — `site_name: Kindling`, `site_description`.

## Logo assets

Two SVG files plus a favicon variant:

- `frontend/public/logo.svg` — combined icon + wordmark, ~480×160 viewBox,
  ember cluster left, `kindling` mono wordmark right.
- `frontend/public/logo-mark.svg` — icon only, ember cluster, square viewBox.
- `frontend/public/favicon.svg` — same as mark, optimized for 16/32/48 px.

Source palette baked into the files (no external font dependency for SVG
mark — wordmark uses system mono fallback).

## Order of operations

1. Spec approved.
2. Implementation plan via writing-plans skill.
3. Code, in this order:
   1. Brand assets (SVG logo files).
   2. Frontend strings, router, base path.
   3. CSS palette + brand component.
   4. Python package + module rename + CLI entry.
   5. Dockerfile + docker-compose.
   6. Env vars + `.env.example`.
   7. API router prefix.
   8. Docs + README + CHANGELOG + ROADMAP.
   9. Tests (unit + e2e).
   10. Migration test against v1 sample DB.
4. CI green on all targets.
5. Repo rename on GitHub.
6. PyPI publish as `kindling`.

## Out of scope

- DB column/table renames.
- API JSON payload field renames.
- v1.x compat branch — keeps the old name and CLI until 2027-02-14, then
  archived. The compat branch is not touched by this rebrand.
- Marketing site (`/site/`) — generated from `docs/` by MkDocs; updates flow
  through after docs are written.

## Success criteria

- `grep -rE 'scriptdeck' --exclude-dir=.git --exclude-dir=.superpowers`
  returns no source-code hits (only intentional references in CHANGELOG and
  v1-compat migration docs).
- `pip install kindling && kindling serve` boots successfully.
- `docker compose up -d` brings up the container named `kindling`, dashboard
  reachable at `http://localhost:8765/kindling/`.
- All existing tests pass with new names.
- README quickstart matches a fresh clone → boot → first-script-run flow.

## Risks

| Risk                                                  | Mitigation                         |
|-------------------------------------------------------|------------------------------------|
| Missed string in deep path (HTML, test fixture, doc)   | Grep gate in CI                    |
| Docker pull-cache carries old name                    | Bump image tag, doc note in CHANGELOG |
| PyPI name `kindling` taken                            | Verify on PyPI before final publish |
| Existing v2 deploys break on URL base path change     | Note in CHANGELOG; `/dashboard/` 301 → `/kindling/` for one cycle |
| Wordmark font fallback differs across OS               | Embed Inter Mono / JetBrains Mono as `@font-face` if visual drift shows |

## Open questions

None — all brainstorming questions resolved:
- Vibe: friendly/approachable
- Direction: maker/workshop metaphor
- Logo: icon + wordmark
- Name: Kindling
- Palette: Spark modern
- Wordmark: lowercase mono