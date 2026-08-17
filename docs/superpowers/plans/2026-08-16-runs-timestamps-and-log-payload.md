# Runs Timestamps + Log Payload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `runs.started_at` tz-aware ISO-8601 (matching `ended_at`) so durations stop displaying negative values, and switch the log/source endpoints from `text/plain` to JSON `{content}` so the frontend's `api()` client can decode them.

**Architecture:** Migration backfills existing naive `started_at` strings to ISO-8601 UTC. `run_service.create_run` writes `started_at` explicitly using `datetime.now(UTC).isoformat()`. Endpoints `/api/runs/{id}/log` and `/api/scripts/{id}/source` return `JSONResponse({"content": text})`. Frontend reads `r.content`. CHECK constraint skipped (SQLite ALTER limitation) — app-side writes pin the format.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, aiosqlite/SQLite, React 18, TanStack Query v5, vitest, pytest.

## Global Constraints

- Single FastAPI process; SQLite only.
- Schema changes only via `src/scriptdeck/migrations/*.sql` (never `models.py`).
- All endpoints remain gated by the same ownership checks.
- Existing tests must still pass; coverage target ≥ 60%.
- Spec: `docs/superpowers/specs/2026-08-16-runs-timestamps-and-log-payload-design.md`.
- Branch: `feat/run-logs`. Co-author Claude.
- Migration runs through `migrations.py`'s `executescript()` — supports multi-statement, but SQLite cannot `ALTER TABLE ADD CHECK`; skip the CHECK.

---

### Task 1: Migration 012 — backfill `runs.started_at` to ISO-8601 UTC

**Files:**
- Create: `src/scriptdeck/migrations/012_runs_timestamps.sql`
- Test: `tests/test_migrations.py` (extend existing module)

**Interfaces:**
- Consumes: existing `runs.started_at` column (String, `DEFAULT (datetime('now'))`).
- Produces: same column with content rewritten to tz-aware ISO-8601.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_migrations.py` a new test function (read the existing file first to match its style and helpers):

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from scriptdeck.db.engine import session_factory
from scriptdeck.db import models


@pytest.mark.asyncio
async def test_migration_012_backfills_naive_started_at_to_iso_utc(tmp_path):
    db = tmp_path / "m.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    # Apply migrations 1..11
    from scriptdeck.db.migrations import run_migrations
    await run_migrations(engine)
    # Insert a naive-row run via raw SQL before migration 012
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO users(id, email, password_hash, role, timezone) "
            "VALUES (1, 'a@b.c', 'x', 'admin', 'UTC')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO scripts(id, user_id, name, language, source_path) "
            "VALUES (1, 1, 's', 'python', 'x.py')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO runs(id, script_id, started_at, status, exit_code) "
            "VALUES (1, 1, '2026-08-17 02:37:01', 'success', 0)"
        )
        await conn.exec_driver_sql(
            "INSERT INTO runs(id, script_id, started_at, status, exit_code) "
            "VALUES (2, 1, '2026-08-17T02:37:01.196009+00:00', 'success', 0)"
        )
    # Migration 012 already applied via run_migrations above; assert contents
    sf = session_factory(str(db))  # not used; read directly
    async with engine.begin() as conn:
        rows = (await conn.exec_driver_sql(
            "SELECT id, started_at FROM runs ORDER BY id"
        )).fetchall()
    assert rows[0][1] == "2026-08-17T02:37:01+00:00"
    assert rows[1][1] == "2026-08-17T02:37:01.196009+00:00"  # unchanged
```

Adapt fixture to whatever test runner style `tests/test_migrations.py` already uses; if it does not have a per-test tmp_path helper, copy the pattern from `tests/api/test_runs_schedule_filter.py`'s `app_ctx`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run python -m pytest tests/test_migrations.py::test_migration_012_backfills_naive_started_at_to_iso_utc --no-cov -v`
Expected: FAIL — migration 012 does not exist yet, so `runs` rows contain the literal naive and tz-aware values as inserted, NOT the rewritten form.

- [ ] **Step 3: Write the migration**

Create `src/scriptdeck/migrations/012_runs_timestamps.sql`:

```sql
-- Backfill existing runs.started_at: convert naive 'YYYY-MM-DD HH:MM:SS' (SQLite
-- datetime('now') default) to tz-aware ISO-8601 UTC. Rows already containing
-- 'T' or '+' or 'Z' (v2 installs, app-side writes) are detected and left alone.
UPDATE runs
SET started_at = substr(started_at, 1, 10) || 'T' || substr(started_at, 12) || '+00:00'
WHERE started_at IS NOT NULL
  AND instr(started_at, 'T') = 0
  AND instr(started_at, '+') = 0
  AND instr(started_at, 'Z') = 0;
```

Notes (do NOT add):
- Do NOT add a `ALTER TABLE runs ADD CHECK (...)` — SQLite `ALTER TABLE` cannot add CHECK constraints without a full table rebuild. Skip; tests pin the format instead.
- Do NOT drop the legacy `DEFAULT (datetime('now'))` on `runs.started_at`. The app always supplies `started_at` going forward, but the column default is harmless on new INSERTs that omit the field (none exist post-fix).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_migrations.py --no-cov -v`
Expected: All migration tests pass, including the new one.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/migrations/012_runs_timestamps.sql tests/test_migrations.py
git commit -m "feat(db): migration 012 — backfill runs.started_at to ISO-8601 UTC"
```

---

### Task 2: `run_service.create_run` writes tz-aware `started_at` explicitly

**Files:**
- Modify: `src/scriptdeck/services/run_service.py:39-71`
- Test: `tests/services/test_run_service.py` (extend; create if absent)

**Interfaces:**
- Consumes: same `create_run(session, *, script_id, schedule_id, status, skip_reason, retry_group)`. No signature change.
- Produces: `started_at` in the inserted row is `datetime.now(UTC).isoformat()` (tz-aware ISO-8601).

- [ ] **Step 1: Find or create `tests/services/test_run_service.py`**

Inspect existing tests; if no services-level test for `create_run`, create `tests/services/test_run_service.py` with the existing fixture pattern (look at `tests/api/test_runs_schedule_filter.py:app_ctx` for the shape: spin up engine, run migrations, insert a script + users row).

- [ ] **Step 2: Write the failing test**

```python
from datetime import UTC, datetime

import pytest

from scriptdeck.db import models
from scriptdeck.services.run_service import create_run


@pytest.mark.asyncio
async def test_create_run_writes_tz_aware_started_at(tmp_path):
    from scriptdeck.db.engine import session_factory
    from scriptdeck.db.migrations import run_migrations
    from sqlalchemy.ext.asyncio import create_async_engine

    db = tmp_path / "x.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    await run_migrations(engine)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT INTO users(id, email, password_hash, role, timezone) "
            "VALUES (1, 'a@b.c', 'x', 'admin', 'UTC')"
        )
        await conn.exec_driver_sql(
            "INSERT INTO scripts(id, user_id, name, language, source_path) "
            "VALUES (1, 1, 's', 'python', 'x.py')"
        )
    sf = session_factory(str(db))
    async with sf() as s:
        await s.execute(...)  # ensure schema loaded — may need explicit metadata create
        run_id, started_at, _ = await create_run(s, script_id=1, schedule_id=None)
        parsed = datetime.fromisoformat(started_at)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == __import__("datetime").timedelta(0)
```

If `session_factory(...)` signature differs in this codebase, follow the existing pattern from `tests/api/test_runs_schedule_filter.py:app_ctx`.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run python -m pytest tests/services/test_run_service.py::test_create_run_writes_tz_aware_started_at --no-cov -v`
Expected: FAIL — `started_at` column relies on SQL default, which returns naive string; assertion on `parsed.tzinfo is not None` fails.

- [ ] **Step 4: Update `create_run` to pass `started_at`**

In `src/scriptdeck/services/run_service.py`, modify the `.values(...)` call inside `create_run` (lines 60-67) to include `started_at=datetime.now(UTC).isoformat()`:

```python
async def create_run(
    session: AsyncSession,
    *,
    script_id: int,
    schedule_id: int | None,
    status: str = "running",
    skip_reason: str | None = None,
    retry_group: str | None = None,
) -> tuple[int, str, str]:
    """Insert a new run row and return (run_id, started_at, retry_group). ... """
    t = _table()
    rg = retry_group or _new_ulid()
    started_at = datetime.now(UTC).isoformat()
    stmt = (
        insert(t)
        .values(
            script_id=script_id,
            schedule_id=schedule_id,
            status=status,
            skip_reason=skip_reason,
            retry_group=rg,
            started_at=started_at,
        )
        .returning(t.c.id, t.c.started_at, t.c.retry_group)
    )
    row = (await session.execute(stmt)).one()
    return int(row[0]), row[1], row[2]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run python -m pytest tests/services/test_run_service.py --no-cov -v`
Expected: PASS.

- [ ] **Step 6: Re-run full backend suite**

Run: `uv run python -m pytest --no-cov -q`
Expected: 119+ passed, 3 skipped (one more test than before — the migration 012 test).

- [ ] **Step 7: Commit**

```bash
git add src/scriptdeck/services/run_service.py tests/services/test_run_service.py
git commit -m "feat(services): create_run writes tz-aware started_at"
```

---

### Task 3: `/api/runs/{id}/log` returns JSON `{content}`

**Files:**
- Modify: `src/scriptdeck/api/runs.py:295-299` (`log_text` handler)
- Test: `tests/api/test_runs_log_endpoint.py` (new)

**Interfaces:**
- Consumes: existing path `GET /api/runs/{run_id}/log`, owner-checked.
- Produces: response shape `{"content": str}` JSON, content-type `application/json`. 404 path on missing log file preserved.

- [ ] **Step 1: Write the failing test**

```python
import pytest
from httpx import AsyncClient, ASGITransport

from scriptdeck.app import create_app


@pytest.mark.asyncio
async def test_log_returns_json_with_content(tmp_path, monkeypatch_auth):
    db = tmp_path / "log.db"
    storage = tmp_path / "storage"
    storage.mkdir()
    (storage / "logs").mkdir()
    app = create_app(settings_overrides={"db_path": str(db), "storage_dir": str(storage)})
    # ... seed users / scripts / runs row using the existing app_ctx style
    log_file = storage / "logs" / "1.log"
    log_file.write_text("hello\nworld\n", encoding="utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        monkeypatch_auth(user_id=1, role="admin", app=app)  # adapt to real helper
        r = await ac.get("/api/runs/1/log")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        body = r.json()
        assert body == {"content": "hello\nworld\n"}


@pytest.mark.asyncio
async def test_log_missing_returns_404(tmp_path, monkeypatch_auth):
    # Same setup, but no log file → 404.
    ...
    assert r.status_code == 404
```

Adapt fixtures (`monkeypatch_auth` signature, `Settings(...)` shape) to whatever Task 1 of the runs-page-refresh PR established. Use `tests/api/test_runs_schedule_filter.py:14-90` as the canonical setup template.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/api/test_runs_log_endpoint.py --no-cov -v`
Expected: FAIL — endpoint returns `text/plain`; `r.headers["content-type"]` does not start with `application/json`.

- [ ] **Step 3: Update the handler**

Modify `src/scriptdeck/api/runs.py`:

```python
from fastapi.responses import JSONResponse

@router.get("/{run_id}/log")
async def log_text(run_id: int, request: Request,
                   user: User = Depends(current_user)):
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_run_owner(s, run_id, user)
    storage = Path(request.app.state.settings.storage_dir)
    log_path = storage / "logs" / f"{run_id}.log"
    if not log_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="log not found")
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return JSONResponse({"content": text})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/api/test_runs_log_endpoint.py --no-cov -v`
Expected: 2 PASS.

- [ ] **Step 5: Run full backend suite**

Run: `uv run python -m pytest --no-cov -q`
Expected: 121+ passed.

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/api/runs.py tests/api/test_runs_log_endpoint.py
git commit -m "feat(api): /api/runs/{id}/log returns JSON {content}"
```

---

### Task 4: `/api/scripts/{id}/source` returns JSON `{content}`

**Files:**
- Modify: `src/scriptdeck/api/scripts.py:141-153` (`get_source` handler)
- Modify: `frontend/src/pages/ScriptEdit.tsx:62-70` (switch from manual `fetch` to `api`)
- Test: `tests/api/test_scripts_source_endpoint.py` (new)

**Interfaces:**
- Backend: same path, owner-checked; returns `{"content": <source_text>}` JSON.
- Frontend: drop the manual `fetch + res.text()`, use `api<{content: string}>(...)`.

- [ ] **Step 1: Write the failing tests (backend + frontend)**

Backend `tests/api/test_scripts_source_endpoint.py`:

```python
@pytest.mark.asyncio
async def test_source_returns_json_content(tmp_path, monkeypatch_auth):
    # Seed user/script/source file. Same setup as Task 3.
    ...
    r = await ac.get("/api/scripts/1/source")
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"content": "print('hi')\n"}
```

Frontend `frontend/src/pages/__tests__/ScriptEdit.test.tsx` (extend existing):

```tsx
it("loads source via api JSON wrapper", async () => {
  apiMock.mockResolvedValueOnce({ id: 1, name: "s", language: "python", source_path: "x.py" }); // script meta
  // remove the manual fetch stub; ensure the second api call returns {content}
  ...
  expect(await screen.findByText(/print\('hi'\)/)).toBeInTheDocument();
});
```

Adapt to existing test scaffolding.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/api/test_scripts_source_endpoint.py --no-cov -v` and `cd frontend && npx vitest run tests/pages/__tests__/ScriptEdit.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Backend — switch handler to JSON**

In `src/scriptdeck/api/scripts.py`:

```python
from fastapi.responses import JSONResponse

@router.get("/{script_id}/source")
async def get_source(script_id: int, request: Request, user: User = Depends(current_user)):
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    storage: Path = request.app.state.settings.storage_dir_path
    path = storage / row.source_path
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="source missing")
    return JSONResponse({"content": path.read_text(encoding="utf-8")})
```

- [ ] **Step 4: Frontend — switch to `api` helper**

In `frontend/src/pages/ScriptEdit.tsx:62-70`, replace the manual fetch with:

```tsx
const meta = await api<Omit<Script, "source">>(`/api/scripts/${id}`);
const sourceRes = await api<{ content: string }>(`/api/scripts/${id}/source`);
return { ...meta, source: sourceRes.content } as Script;
```

Drop the `token`/`Authorization` header plumbing (the `api()` helper already attaches it via `client.ts:24-25`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run python -m pytest tests/api/test_scripts_source_endpoint.py --no-cov -v` and `cd frontend && npx vitest run tests/pages/__tests__/ScriptEdit.test.tsx`
Expected: PASS.

- [ ] **Step 6: Re-run frontend suite**

Run: `cd frontend && npx vitest run`
Expected: 30+ passed (29 + at least one new ScriptEdit assertion).

- [ ] **Step 7: Commit**

```bash
git add src/scriptdeck/api/scripts.py frontend/src/pages/ScriptEdit.tsx frontend/src/pages/__tests__/ScriptEdit.test.tsx tests/api/test_scripts_source_endpoint.py
git commit -m "feat: /api/scripts/{id}/source returns JSON {content}; ScriptEdit uses api()"
```

---

### Task 5: Frontend `RunView.tsx` reads `r.content`

**Files:**
- Modify: `frontend/src/pages/RunView.tsx:50-56`
- Test: extend `frontend/tests/Runs.test.tsx` or add `frontend/tests/RunView.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/RunView.test.tsx` (Vitest + Testing Library + MemoryRouter). The page route is `/runs/:id`; tests must mock `getRun`, `listRunGroup`, and the new `api` for the log endpoint. Assert `<pre>` contains the seeded `content`.

Snippet:

```tsx
it("renders fetched log content when SSE replayed nothing", async () => {
  apiMock.mockImplementation((path: string) => {
    if (path === "/api/runs/1/log") return Promise.resolve({ content: "hello\nworld\n" });
    return Promise.reject(new Error("unexpected " + path));
  });
  // mock getRun: ...
  // render <RunView /> via MemoryRouter with route /runs/1
  expect(await screen.findByText(/hello/)).toBeInTheDocument();
});
```

Adapt to existing test infrastructure.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/RunView.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Update `RunView.tsx`**

```tsx
const { data: fallbackText } = useQuery({
  queryKey: ["run-log", runId],
  queryFn: async () => {
    const r = await api<{ content: string }>(`/api/runs/${runId}/log`);
    return r.content;
  },
  enabled: Number.isFinite(runId) && liveText === "",
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/RunView.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: 30+ passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/RunView.tsx frontend/tests/RunView.test.tsx
git commit -m "feat(ui): RunView reads log content from JSON wrapper"
```

---

### Task 6: End-to-end gate + push + open PR

**Files:** no edits; verification + push only.

- [ ] **Step 1: Run full backend suite**

Run: `uv run python -m pytest --no-cov -q`
Expected: 121+ passed, 3 skipped.

- [ ] **Step 2: Run full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: 30+ passed.

- [ ] **Step 3: Lint**

Run: `ruff check src tests` and `cd frontend && npm run lint`
Expected: clean.

- [ ] **Step 4: Manual smoke**

1. Start `cd frontend && npm run dev`.
2. Open `/runs`. Trigger a new run (or wait for one). Observe `Duration` field is **positive**.
3. Open `/runs/<id>` for a **completed** run. Confirm log content renders (no longer "No output").

- [ ] **Step 5: Push branch and open PR**

```bash
git push -u origin feat/run-logs
gh pr edit 13 --add-label bug --add-label db
# OR open a new PR for this branch series if main has progressed; follow whatever
# the user prefers.
```

Pick one:
- Reuse the open PR #13 (it already has the runs-page refresh work) and push the bug-fix commits on top of it.
- Open a new PR titled "fix: canonical ISO-8601 started_at + JSON log/script endpoints" against `main`.

Decide with the user before pushing. Document in the PR body that this is a follow-up to PR #13.

- [ ] **Step 6: Confirm CI / watch for failures**

Watch PR CI. If green, hand off for review.
