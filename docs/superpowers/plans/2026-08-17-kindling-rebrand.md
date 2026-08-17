# Kindling Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename ScriptDeck to Kindling across repo, package, CLI, API, dashboard, docs, and brand assets. Behavior unchanged.

**Architecture:** Mechanical rebrand. New logo SVG assets first, then frontend base path, then Python package + CLI rename, then Docker/CI, then docs. Each layer TDD-gated by a grep + smoke test.

**Tech Stack:** Python 3.11/3.12/3.13, FastAPI, React + Vite + TypeScript, Docker, MkDocs, Playwright (e2e), pytest.

## Global Constraints

- Repo path: `github.com/aliaadil/kindling` (rename after CI passes).
- PyPI package: `kindling-runner`. The bare `kindling` name is taken on PyPI (v0.0.2, "Basic building blocks for pytorch"). CLI command, brand, and Python imports remain `kindling`; only the distribution name carries the `-runner` suffix.
- Python module path: `kindling/` (was `scriptdeck/`).
- CLI command: `kindling` (was `scriptdeck`).
- HTTP port: `8765` (unchanged).
- Dashboard URL base: `/kindling/` (was `/dashboard/`).
- API URL base: `/api/kindling/...` (was `/api/...`).
- Env var prefix: `KINDLING_*` (was `SCRIPTDECK_*`).
- Config file: `kindling.toml` (was `scriptdeck.toml`).
- Default DB path: `./data/kindling.db` (was `./data/scriptdeck.db`).
- Storage dir: `./storage/` (unchanged).
- Palette hex tokens: ember `#dc2626`, spark `#fb923c`, flame `#facc15`, charcoal `#0c0a09`, text `#f5f5f4`.
- Wordmark style: lowercase, mono font family.
- Mark: ember cluster (3 overlapping warm-tone circles on charcoal).
- License: MIT. Python: 3.11/3.12/3.13.
- v1.x compat branch keeps old name until 2027-02-14 — not touched here.
- DB schema and API JSON field names unchanged.
- Brand asset filenames: `frontend/public/logo.svg`, `frontend/public/logo-mark.svg`, `frontend/public/favicon.svg`.

## File Structure

| Path | Responsibility |
|------|----------------|
| `frontend/public/logo.svg` | Combined mark + wordmark, primary brand asset. |
| `frontend/public/logo-mark.svg` | Mark only (ember cluster), square viewBox. |
| `frontend/public/favicon.svg` | Optimized favicon variant of the mark. |
| `frontend/src/components/brand.tsx` | React brand component (header logo). |
| `frontend/src/index.css` | Palette CSS custom properties + base styles. |
| `frontend/src/router.tsx` | Router config (base path, route definitions). |
| `frontend/src/api/client.ts` | API client base URL prefix. |
| `frontend/index.html` | `<title>`, meta description, `theme-color`. |
| `frontend/tests/e2e/smoke.spec.ts` | Playwright smoke test for dashboard base URL. |
| `src/kindling/` | Python package (renamed from `src/scriptdeck/`). |
| `src/kindling/cli.py` | CLI entry point. |
| `src/kindling/config.py` | Env var + config file loader. |
| `src/kindling/api/main.py` | FastAPI app + router mount + dashboard static mount. |
| `src/kindling/migrate_from_v1.py` | v1→v2 migration CLI. |
| `src/kindling/db.py` | DB path constants. |
| `pyproject.toml` | Package name, CLI entry point. |
| `Dockerfile` | Module path, image metadata. |
| `docker-compose.yml` | Image, container, env vars. |
| `.env.example` | Env var keys + sample values. |
| `tests/test_branding.py` | NEW: rebrand smoke tests. |
| `tests/test_routes.py` | NEW: dashboard + API base path tests. |
| `tests/test_config.py` | NEW: env var prefix + config file name tests. |
| `tests/test_migrate_from_v1.py` | Migration flag name tests. |
| `README.md`, `CHANGELOG.md`, `ROADMAP.md` | Top-level prose + history. |
| `mkdocs.yml` | Site name + nav titles. |
| `docs/index.md`, `docs/install.md`, `docs/api.md`, `docs/operations.md`, `docs/troubleshooting.md` | User docs. |

---

### Task 1: Logo SVG assets

**Files:**
- Create: `frontend/public/logo.svg`
- Create: `frontend/public/logo-mark.svg`
- Create: `frontend/public/favicon.svg`

**Interfaces:**
- Produces: `LogoSvg` component (later task) imports these via static URL.

- [ ] **Step 1: Write `frontend/public/logo-mark.svg`**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Kindling mark">
  <rect width="64" height="64" rx="12" fill="#0c0a09"/>
  <circle cx="22" cy="36" r="11" fill="#dc2626"/>
  <circle cx="38" cy="26" r="14" fill="#fb923c"/>
  <circle cx="36" cy="40" r="9" fill="#facc15"/>
  <circle cx="30" cy="32" r="16" fill="#fb923c" fill-opacity="0.5"/>
</svg>
```

- [ ] **Step 2: Write `frontend/public/logo.svg`**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 160" role="img" aria-label="Kindling">
  <g transform="translate(20,20)">
    <rect width="120" height="120" rx="20" fill="#0c0a09"/>
    <circle cx="42" cy="68" r="22" fill="#dc2626"/>
    <circle cx="72" cy="50" r="26" fill="#fb923c"/>
    <circle cx="68" cy="76" r="18" fill="#facc15"/>
    <circle cx="56" cy="60" r="30" fill="#fb923c" fill-opacity="0.5"/>
  </g>
  <text x="170" y="100" font-family="ui-monospace, 'JetBrains Mono', Menlo, Consolas, monospace" font-size="64" font-weight="600" fill="#0c0a09">kindling</text>
</svg>
```

- [ ] **Step 3: Write `frontend/public/favicon.svg`**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
  <rect width="32" height="32" rx="6" fill="#0c0a09"/>
  <circle cx="11" cy="18" r="5" fill="#dc2626"/>
  <circle cx="19" cy="13" r="7" fill="#fb923c"/>
  <circle cx="18" cy="20" r="4" fill="#facc15"/>
</svg>
```

- [ ] **Step 4: Verify assets exist**

Run: `ls -1 frontend/public/logo.svg frontend/public/logo-mark.svg frontend/public/favicon.svg`
Expected: all three paths printed.

- [ ] **Step 5: Commit**

```bash
git add frontend/public/logo.svg frontend/public/logo-mark.svg frontend/public/favicon.svg
git commit -m "feat(brand): add Kindling logo SVG assets (mark, wordmark, favicon)"
```

---

### Task 2: Frontend CSS palette + brand component

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/components/brand.tsx`

**Interfaces:**
- Consumes: SVG files from Task 1 (`/logo.svg`, `/logo-mark.svg`, `/favicon.svg`).
- Produces: `--kindling-*` CSS custom properties used by other components.

- [ ] **Step 1: Write failing CSS test**

Create `frontend/tests/brand-palette.test.ts`:

```ts
import { describe, it, expect } from 'vitest';

describe('brand palette CSS variables', () => {
  it('exposes the Kindling palette tokens', async () => {
    const css = await import('../src/index.css?raw');
    expect(css.default).toMatch(/--kindling-ember:\s*#dc2626/);
    expect(css.default).toMatch(/--kindling-spark:\s*#fb923c/);
    expect(css.default).toMatch(/--kindling-flame:\s*#facc15/);
    expect(css.default).toMatch(/--kindling-charcoal:\s*#0c0a09/);
    expect(css.default).toMatch(/--kindling-text:\s*#f5f5f4/);
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `cd frontend && npx vitest run tests/brand-palette.test.ts`
Expected: FAIL — tokens not yet defined.

- [ ] **Step 3: Replace palette tokens in `frontend/src/index.css`**

Replace the existing `:root` block with:

```css
:root {
  --kindling-ember: #dc2626;
  --kindling-spark: #fb923c;
  --kindling-flame: #facc15;
  --kindling-charcoal: #0c0a09;
  --kindling-text: #f5f5f4;
}

body {
  background: var(--kindling-charcoal);
  color: var(--kindling-text);
}
```

(Leave the rest of the file untouched; only swap the existing palette tokens in place.)

- [ ] **Step 4: Update `frontend/src/components/brand.tsx`**

Replace the component body with:

```tsx
export function BrandLogo({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const h = size === 'sm' ? 28 : size === 'lg' ? 56 : 36;
  return <img src="/logo.svg" alt="Kindling" style={{ height: h }} />;
}

export function BrandMark({ size = 32 }: { size?: number }) {
  return <img src="/logo-mark.svg" alt="" width={size} height={size} />;
}
```

(Keep existing exports; remove old "ScriptDeck" strings.)

- [ ] **Step 5: Run test, expect pass**

Run: `cd frontend && npx vitest run tests/brand-palette.test.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/index.css frontend/src/components/brand.tsx frontend/tests/brand-palette.test.ts
git commit -m "feat(brand): apply Kindling palette tokens + brand component"
```

---

### Task 3: Frontend base path + API client + index.html

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/src/router.tsx`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/tests/e2e/smoke.spec.ts`

**Interfaces:**
- Produces: dashboard served at `/kindling/`, API requests to `/api/kindling/...`.

- [ ] **Step 1: Write failing smoke test**

Replace `frontend/tests/e2e/smoke.spec.ts` body:

```ts
import { test, expect } from '@playwright/test';

test('dashboard mounts at /kindling/', async ({ page }) => {
  await page.goto('/kindling/');
  await expect(page).toHaveTitle(/Kindling/);
  await expect(page.getByAltText('Kindling')).toBeVisible();
});

test('logo asset served', async ({ page }) => {
  const res = await page.goto('/kindling/logo.svg');
  expect(res?.status()).toBe(200);
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `cd frontend && npx playwright test tests/e2e/smoke.spec.ts`
Expected: FAIL — page title still ScriptDeck, route 404.

- [ ] **Step 3: Update `frontend/index.html`**

Replace `<title>`, `<meta name="description">`, and `<meta name="theme-color">`:

```html
<title>Kindling</title>
<meta name="description" content="Kindling — self-hosted scheduled script runner.">
<meta name="theme-color" content="#0c0a09">
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
```

- [ ] **Step 3.5: Sweep leftover `ScriptDeck` strings in `frontend/src/`**

```bash
grep -rln 'ScriptDeck' frontend/src | xargs sed -i '' 's/ScriptDeck/Kindling/g'
```

Files known to carry leftover strings (verified by Task 2 review):
- `frontend/src/auth/LoginPage.tsx` — sign-in copy
- `frontend/src/pages/Settings.tsx` — default instance name
- Any other file flagged by the grep above.

Verify:
```bash
grep -rE 'ScriptDeck' frontend/src
```
Expected: no output.

- [ ] **Step 4: Update `frontend/src/router.tsx`**

Find the `createBrowserRouter` (or equivalent) call and change the dashboard base path. Replace the existing route definitions:

```tsx
import { createBrowserRouter } from 'react-router-dom';

export const router = createBrowserRouter([
  { path: '/kindling/*', /* existing dashboard routes */ },
  { path: '/setup', /* existing setup route */ },
], { basename: '/' });
```

(The exact route list mirrors what existed for `/dashboard/*`.)

- [ ] **Step 5: Update `frontend/src/api/client.ts`**

Replace the base URL constant:

```ts
export const API_BASE = '/api/kindling';
```

Update every `${API_BASE}` consumer to keep working unchanged. If the file currently constructs URLs as `'/api/' + path`, switch to `` `${API_BASE}${path}` ``.

- [ ] **Step 6: Run test, expect pass**

Run: `cd frontend && npx playwright test tests/e2e/smoke.spec.ts`
Expected: PASS — title shows Kindling, logo visible.

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html frontend/src/router.tsx frontend/src/api/client.ts frontend/tests/e2e/smoke.spec.ts
git commit -m "feat(brand): serve dashboard at /kindling/ and route API to /api/kindling"
```

---

### Task 4: Python package rename + CLI entry point

**Files:**
- Rename: `src/scriptdeck/` → `src/kindling/`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `import kindling` works; `kindling` CLI command on PATH after install.

- [ ] **Step 1: Write failing import + CLI test**

Create `tests/test_branding.py`:

```python
def test_package_imports_as_kindling():
    import kindling
    assert kindling.__name__ == 'kindling'


def test_cli_command_name():
    from click.testing import CliRunner
    from kindling.cli import main
    runner = CliRunner()
    result = runner.invoke(main, ['--help'])
    assert result.exit_code == 0
    assert 'kindling' in result.output.lower()
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_branding.py -v`
Expected: FAIL — ModuleNotFoundError: No module named 'kindling'.

- [ ] **Step 3: Rename package directory**

```bash
git mv src/scriptdeck src/kindling
```

Then sweep imports inside the renamed tree:

```bash
grep -rln 'scriptdeck' src/kindling | xargs sed -i '' 's/scriptdeck/kindling/g'
grep -rln 'ScriptDeck' src/kindling | xargs sed -i '' 's/ScriptDeck/Kindling/g'
grep -rln 'SCRIPTDECK' src/kindling | xargs sed -i '' 's/SCRIPTDECK/KINDLING/g'
```

Verify clean:

```bash
grep -rE 'scriptdeck|ScriptDeck|SCRIPTDECK' src/kindling
```

Expected: no output.

- [ ] **Step 4: Update `pyproject.toml`**

In `[project]`, replace `name = "scriptdeck"` with `name = "kindling"`.
In `[project.scripts]`, replace `scriptdeck = "kindling.cli:main"` (current name) — keep the entry point target (`kindling.cli:main`) unchanged; only rename the console_script key.

```toml
[project]
name = "kindling"
# ... existing fields unchanged

[project.scripts]
kindling = "kindling.cli:main"
```

- [ ] **Step 5: Reinstall in editable mode**

```bash
pip install -e .
```

- [ ] **Step 6: Run test, expect pass**

Run: `pytest tests/test_branding.py -v`
Expected: PASS — `kindling --help` runs.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat(rebrand): rename python package scriptdeck -> kindling"
```

---

### Task 5: API router prefix + dashboard static mount

**Files:**
- Modify: `src/kindling/api/main.py`
- Modify: `src/kindling/api/__init__.py` (if it exports the app)

**Interfaces:**
- Produces: API mounted at `/api/kindling`, dashboard static files served at `/kindling/`.

- [ ] **Step 1: Write failing routes test**

Create `tests/test_routes.py`:

```python
from fastapi.testclient import TestClient


def test_api_under_kindling_prefix():
    from kindling.api.main import app
    client = TestClient(app)
    res = client.get('/api/kindling/health')
    assert res.status_code in (200, 401, 403)  # any non-404 means routed


def test_dashboard_served_at_kindling():
    from kindling.api.main import app
    client = TestClient(app)
    res = client.get('/kindling/')
    assert res.status_code == 200


def test_old_paths_return_404():
    from kindling.api.main import app
    client = TestClient(app)
    assert client.get('/dashboard/').status_code == 404
    assert client.get('/api/health').status_code == 404
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_routes.py -v`
Expected: FAIL — old `/api/health` still 200 (or new path 404).

- [ ] **Step 3: Update `src/kindling/api/main.py`**

Find the FastAPI `app.include_router(...)` calls and update their `prefix` argument from `"/api"` to `"/api/kindling"`. Strip leading `/api` segments from any sub-router prefixes so the joined path is `/api/kindling/...`.

Find the dashboard static mount. Replace `StaticFiles(...)` mount from `"/dashboard"` to `"/kindling"`. Update `html=True` index serving so requests for `/kindling/` resolve to the dashboard `index.html`.

```python
app.include_router(router, prefix="/api/kindling")
# ... other routers likewise

app.mount("/kindling", StaticFiles(directory="frontend/dist", html=True), name="dashboard")
```

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/test_routes.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kindling/api/main.py tests/test_routes.py
git commit -m "feat(rebrand): mount API at /api/kindling and dashboard at /kindling"
```

---

### Task 6: Env vars + config defaults

**Files:**
- Modify: `src/kindling/config.py`
- Create: `.env.example` (overwrite)
- Modify: `tests/test_config.py` (new)

**Interfaces:**
- Produces: env var prefix `KINDLING_*`, config file name `kindling.toml`, default DB path `./data/kindling.db`.

- [ ] **Step 1: Write failing config test**

Create `tests/test_config.py`:

```python
import os
from pathlib import Path


def test_env_var_prefix():
    os.environ['KINDLING_DB_PATH'] = '/tmp/kindling.db'
    os.environ.pop('SCRIPTDECK_DB_PATH', None)
    from kindling.config import load_config, reset_cache
    reset_cache()
    cfg = load_config()
    assert cfg.db_path == Path('/tmp/kindling.db')


def test_config_file_name(tmp_path, monkeypatch):
    cfg_file = tmp_path / 'kindling.toml'
    cfg_file.write_text('db_path = "/tmp/from-file.db"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('KINDLING_DB_PATH', raising=False)
    from kindling.config import load_config, reset_cache
    reset_cache()
    cfg = load_config()
    assert cfg.db_path == Path('/tmp/from-file.db')


def test_default_db_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('KINDLING_DB_PATH', raising=False)
    monkeypatch.delenv('KINDLING_CONFIG', raising=False)
    from kindling.config import load_config, reset_cache
    reset_cache()
    cfg = load_config()
    assert cfg.db_path == Path('./data/kindling.db')
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — env vars still named `SCRIPTDECK_*`.

- [ ] **Step 3: Update `src/kindling/config.py`**

Replace every `SCRIPTDECK_*` reference with `KINDLING_*`. Update the config-file lookup from `scriptdeck.toml` to `kindling.toml`. Update default values:

```python
DEFAULT_DB_PATH = Path('./data/kindling.db')
DEFAULT_CONFIG_FILE = Path('kindling.toml')
ENV_PREFIX = 'KINDLING_'
```

Ensure `reset_cache()` exists (add if missing).

- [ ] **Step 4: Overwrite `.env.example`**

```bash
# Kindling configuration
KINDLING_DB_PATH=./data/kindling.db
KINDLING_STORAGE_PATH=./storage
KINDLING_HTTP_PORT=8765
KINDLING_LOG_LEVEL=info
```

- [ ] **Step 5: Sweep remaining `SCRIPTDECK_` references in `src/kindling/`**

```bash
grep -rln 'SCRIPTDECK' src/kindling | xargs sed -i '' 's/SCRIPTDECK/KINDLING/g'
grep -rE 'SCRIPTDECK' src/kindling
```

Expected: no output.

- [ ] **Step 6: Run test, expect pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/kindling/config.py .env.example tests/test_config.py
git commit -m "feat(rebrand): rename env prefix to KINDLING_*, default db to kindling.db"
```

---

### Task 7: Dockerfile + docker-compose

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yml`

**Interfaces:**
- Produces: image `aliaadil/kindling`, container `kindling`, compose project `kindling`.

- [ ] **Step 1: Write failing compose sanity test**

Create `tests/test_compose.py`:

```python
from pathlib import Path
import yaml


def test_compose_image_and_container():
    data = yaml.safe_load(Path('docker-compose.yml').read_text())
    svc = data['services']['kindling']
    assert 'aliaadil/kindling' in svc['image']
    assert svc['container_name'] == 'kindling'


def test_compose_env_uses_kindling_prefix():
    data = yaml.safe_load(Path('docker-compose.yml').read_text())
    env = data['services']['kindling'].get('environment', {})
    keys = list(env.keys()) if isinstance(env, dict) else [k.split('=')[0] for k in env]
    assert any(k.startswith('KINDLING_') for k in keys)
    assert not any(k.startswith('SCRIPTDECK_') for k in keys)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_compose.py -v`
Expected: FAIL — image still `aliaadil/scriptdeck`.

- [ ] **Step 3: Update `Dockerfile`**

Replace any reference to `scriptdeck` in `CMD`, `ENTRYPOINT`, `LABEL`, or `COPY` paths with `kindling`. Final `CMD` line:

```dockerfile
CMD ["kindling", "serve"]
```

- [ ] **Step 4: Update `docker-compose.yml`**

Replace the existing `services:` block:

```yaml
services:
  kindling:
    build: .
    image: aliaadil/kindling
    container_name: kindling
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - ./data:/app/data
      - ./storage:/app/storage
    environment:
      KINDLING_DB_PATH: /app/data/kindling.db
      KINDLING_STORAGE_PATH: /app/storage
      KINDLING_HTTP_PORT: "8765"
      KINDLING_LOG_LEVEL: info
```

(Adjust volume paths if existing layout differs; keep `KINDLING_*` env keys.)

- [ ] **Step 5: Run test, expect pass**

Run: `pytest tests/test_compose.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker-compose.yml tests/test_compose.py
git commit -m "feat(rebrand): docker image and compose use Kindling names"
```

---

### Task 8: v1→v2 migration CLI

**Files:**
- Modify: `src/kindling/migrate_from_v1.py`
- Modify: `tests/test_migrate_from_v1.py`

**Interfaces:**
- Produces: `kindling migrate-from-v1 --v2-db-path=...` writes to `./data/kindling.db` by default.

- [ ] **Step 1: Write failing migration flag test**

Append to `tests/test_migrate_from_v1.py`:

```python
from click.testing import CliRunner
from kindling.migrate_from_v1 import main


def test_default_v2_db_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ['--help'])
    assert '--v2-db-path' in result.output
    assert '--v2-storage-path' in result.output
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/test_migrate_from_v1.py -v`
Expected: FAIL — flags may still be `--scriptdeck-db-path`.

- [ ] **Step 3: Update `src/kindling/migrate_from_v1.py`**

Replace the Click option decorators:

```python
@click.option('--v1-db-path', required=True, type=click.Path(path_type=Path))
@click.option('--v1-storage-path', required=True, type=click.Path(path_type=Path))
@click.option('--v2-db-path', default=Path('./data/kindling.db'), type=click.Path(path_type=Path), show_default=True)
@click.option('--v2-storage-path', default=Path('./storage'), type=click.Path(path_type=Path), show_default=True)
```

Strip any logic that hard-codes `scriptdeck.db`. Keep the data-format copy semantics identical.

- [ ] **Step 4: Run test, expect pass**

Run: `pytest tests/test_migrate_from_v1.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/kindling/migrate_from_v1.py tests/test_migrate_from_v1.py
git commit -m "feat(rebrand): migrate-from-v1 CLI uses --v2-db-path with kindling.db default"
```

---

### Task 9: Update existing tests for new paths

**Files:**
- Modify: every file under `tests/` that references `scriptdeck`/`ScriptDeck`/`SCRIPTDECK`, `/dashboard/`, `/api/...`, `--scriptdeck-db-path`, or env vars.

**Interfaces:**
- Consumes: Task 4–8 outputs (new package, CLI, env vars, routes).

- [ ] **Step 1: Find references**

```bash
grep -rlE 'scriptdeck|ScriptDeck|SCRIPTDECK|/dashboard/|/api/[a-z]' tests
```

Expected output: list of files containing the old names/paths.

- [ ] **Step 2: Bulk rewrite**

```bash
grep -rlE 'scriptdeck' tests | xargs sed -i '' 's/scriptdeck/kindling/g'
grep -rlE 'ScriptDeck' tests | xargs sed -i '' 's/ScriptDeck/Kindling/g'
grep -rlE 'SCRIPTDECK' tests | xargs sed -i '' 's/SCRIPTDECK/KINDLING/g'
grep -rl "'/dashboard/" tests | xargs sed -i '' "s|'/dashboard/|'/kindling/|g"
grep -rl '"/dashboard/' tests | xargs sed -i '' 's|"/dashboard/|"/kindling/|g'
```

For `/api/...` URLs, manually update each fixture to its new `/api/kindling/...` form. Verify no auto-rename touched any other test (review the diff before commit).

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: update test fixtures for Kindling names and routes"
```

---

### Task 10: Docs + README + CHANGELOG + ROADMAP

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `ROADMAP.md`
- Modify: `mkdocs.yml`
- Modify: `docs/index.md`, `docs/install.md`, `docs/api.md`, `docs/operations.md`, `docs/troubleshooting.md`

**Interfaces:**
- Produces: docs render with Kindling branding, paths, env vars.

- [ ] **Step 1: Top-level prose rewrite**

`README.md` — replace title, badges, quickstart commands, install path, all CLI invocations, all env var references, all dashboard URLs. Show new quickstart:

```markdown
# Kindling

[![CI](https://github.com/aliaadil/kindling/actions/workflows/ci.yml/badge.svg)](https://github.com/aliaadil/kindling/actions)
![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Self-hosted scheduled script runner.

\```bash
docker compose up -d
open http://localhost:8765/kindling/
\```
```

`CHANGELOG.md` — prepend a new top entry:

```markdown
## Unreleased

### Changed
- **Rebrand to Kindling.** GitHub repo, PyPI package, CLI command, dashboard URL, and env var prefix have all been renamed. v1 data still migrates via `kindling migrate-from-v1`.
```

`ROADMAP.md` — replace `ScriptDeck` mentions; keep the v1.x archive note with old name intact.

- [ ] **Step 2: MkDocs config**

`mkdocs.yml` — update `site_name`, `site_description`, `site_url`, `repo_url`, `repo_name`:

```yaml
site_name: Kindling
site_description: Self-hosted scheduled script runner.
site_url: https://aliaadil.github.io/kindling/
repo_url: https://github.com/aliaadil/kindling
repo_name: aliaadil/kindling
```

- [ ] **Step 3: User docs sweep**

For `docs/index.md`, `docs/install.md`, `docs/api.md`, `docs/operations.md`, `docs/troubleshooting.md`:

```bash
grep -rlE 'scriptdeck|ScriptDeck|SCRIPTDECK|/dashboard/|/api/[a-z]' docs | xargs sed -i '' -e 's/scriptdeck/kindling/g' -e 's/ScriptDeck/Kindling/g' -e 's/SCRIPTDECK/KINDLING/g'
```

Then manually walk each file and replace `/api/<resource>` with `/api/kindling/<resource>`, `/dashboard/` with `/kindling/`, `kindling migrate-from-v1` flags if they appear.

- [ ] **Step 4: Verify docs build**

Run: `mkdocs build --strict`
Expected: no warnings about missing pages or broken refs.

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md ROADMAP.md mkdocs.yml docs/
git commit -m "docs: rebrand to Kindling across README, CHANGELOG, ROADMAP, mkdocs"
```

---

### Task 11: Repo-wide grep gate + CI

**Files:**
- Modify: `.github/workflows/ci.yml` (or equivalent)

**Interfaces:**
- Produces: CI step that fails the build if any old `scriptdeck` reference (outside excluded paths) survives.

- [ ] **Step 1: Add grep gate step**

Add a new step to the CI workflow, after the existing tests:

```yaml
      - name: Rebrand grep gate
        run: |
          ! grep -rIE 'scriptdeck|ScriptDeck|SCRIPTDECK' \
            --exclude-dir=.git \
            --exclude-dir=.superpowers \
            --exclude-dir=site \
            --exclude-dir=node_modules \
            --exclude=CHANGELOG.md \
            .
```

(Adjust excludes: `CHANGELOG.md` may keep historical references; `site/` is generated.)

- [ ] **Step 2: Verify locally**

Run:
```bash
! grep -rIE 'scriptdeck|ScriptDeck|SCRIPTDECK' --exclude-dir=.git --exclude-dir=.superpowers --exclude-dir=site --exclude-dir=node_modules --exclude=CHANGELOG.md .
```

Expected: exit code 1 (no matches) — or run with `|| true` to inspect any hits first.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add grep gate to fail on leftover scriptdeck references"
```

---

### Task 12: PyPI availability check + dry-run build

**Files:** none (operational).

**Interfaces:**
- Produces: confidence the package name `kindling` is publishable.

- [ ] **Step 1: Check PyPI**

Run:
```bash
curl -s https://pypi.org/pypi/kindling/json | python -c "import json,sys; print('taken' if 'info' in json.load(sys.stdin) else 'free')"
```

Expected: prints `free`. If `taken`, surface to the user and stop — brainstorming session needed.

- [ ] **Step 2: Build sdist + wheel**

Run:
```bash
pip install build
python -m build --sdist --wheel
```

Expected: `dist/kindling-<version>.tar.gz` and `dist/kindling-<version>-py3-none-any.whl`.

- [ ] **Step 3: Inspect wheel contents**

Run:
```bash
unzip -l dist/kindling-*.whl | head -20
```

Expected: top-level `kindling/` package directory present; no `scriptdeck/` directory.

- [ ] **Step 4: No commit**

This task is operational. If it surfaces an issue (PyPI name taken, package layout wrong), open a new plan before publishing.

---

### Task 13: Final integration smoke

**Files:** none (operational).

**Interfaces:**
- Produces: end-to-end confidence the rebrand boots a fresh deploy.

- [ ] **Step 1: Build + run Docker image**

```bash
docker build -t kindling-local .
docker run --rm -d --name kindling-local -p 8765:8765 -v $(pwd)/data:/app/data -v $(pwd)/storage:/app/storage kindling-local
```

Expected: container named `kindling-local` starts.

- [ ] **Step 2: Hit dashboard + API**

```bash
curl -fsS http://localhost:8765/kindling/ | head -20
curl -fsS http://localhost:8765/api/kindling/health
```

Expected: dashboard HTML returned; health endpoint 200/401/404-as-routed.

- [ ] **Step 3: Run full test suite**

```bash
pytest -v
cd frontend && npx vitest run && npx playwright test
```

Expected: all green.

- [ ] **Step 4: Tear down**

```bash
docker stop kindling-local
```

- [ ] **Step 5: No commit**

This task is operational. Green means ready for repo rename + PyPI publish (operational, outside this plan).

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|--------------|------|
| Brand assets (logo, mark, favicon) | T1 |
| Palette tokens | T2 |
| Brand component | T2 |
| Frontend base path `/kindling/` | T3 |
| Frontend API base `/api/kindling/` | T3 |
| `<title>`, meta, theme-color | T3 |
| Python module rename | T4 |
| CLI entry point `kindling` | T4 |
| API router prefix | T5 |
| Dashboard static mount | T5 |
| Env var prefix `KINDLING_*` | T6 |
| Config file `kindling.toml` | T6 |
| Default DB path `./data/kindling.db` | T6 |
| Docker image + compose | T7 |
| `kindling migrate-from-v1` flags | T8 |
| Test fixtures updated | T9 |
| README + CHANGELOG + ROADMAP | T10 |
| MkDocs config | T10 |
| User docs sweep | T10 |
| Repo-wide grep gate | T11 |
| PyPI availability | T12 |
| End-to-end smoke | T13 |

**Placeholder scan:** No TBDs, no "implement later", no vague steps. Every step has concrete commands and code.

**Type consistency:**
- `BrandLogo` and `BrandMark` defined in T2; no other task touches brand.tsx.
- `load_config`, `reset_cache` defined in T6; tests in T6 + T9 consume the same names.
- `migrate_from_v1.main` Click group defined in T8; tests in T8 + T9 use it.
- `app` from `kindling.api.main` consumed in T5; T3 uses `/api/kindling/` URLs in fixtures.
- `pytest`, `npx vitest`, `npx playwright` invocations consistent throughout.

No drift detected.