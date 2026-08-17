# Runs Page Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `/runs` so users see what is actively running, can scope to a single schedule, see live ticking duration for in-flight runs, and inspect history pagination. Drill into a row opens the existing `RunView` for full logs.

**Architecture:** Two parallel `GET /api/runs` queries from the React page: one for a sticky "Currently running" section (2s polling, tick-timer), one for paginated history (5s polling, 20/page). API gains `schedule_id` and `offset` filters. Pagination stays server-side; ownership scoped via `require_script_owner`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.x async, SQLite/aiosqlite. React 18, TanStack Query v5, react-router-dom, Vitest, Testing Library, Playwright. Tailwind + Radix UI primitives (already in `frontend/src/components/ui/`).

## Global Constraints

- Single FastAPI process; SQLite only; no new migrations.
- All endpoints remain gated by `require_script_owner`.
- Pagination: `offset` clamped to `[0, 10000]`; `limit` clamped to `[1, 100]`.
- Frontend polls while tab visible; pauses on `visibilitychange` to hidden.
- Coverage target: maintain ≥ 60%.
- Spec: `docs/superpowers/specs/2026-08-16-runs-page-refresh-design.md`.
- Branch: `feat/run-logs`. Co-author commits with Claude trailer.

---

### Task 1: Backend `schedule_id` filter on `GET /api/runs`

**Files:**
- Modify: `src/scriptdeck/api/runs.py:58-107` (`list_endpoint` function)
- Test: `tests/api/test_runs_schedule_filter.py` (new)

**Interfaces:**
- Consumes: existing `script_id`, `status_filter`, `since`, `group`, `limit` query params
- Produces: `list_endpoint` with two new params — `schedule_id: int | None = Query(default=None)` and `offset: int = Query(default=0, ge=0, le=10000)`. Resolved schema column for offset/slicing is `runs.id`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_runs_schedule_filter.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport

from scriptdeck.app import create_app
from scriptdeck.db.engine import session_factory
from scriptdeck.db import models


@pytest.fixture
async def app_ctx(tmp_path):
    """Two users, two scripts, two schedules, four runs."""
    db = tmp_path / "t.db"
    app = create_app(settings_overrides={"db_path": str(db)})
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        async with session_factory(str(db))() as s:
            await s.execute(models.users.insert().values(
                id=1, username="alice", password_hash="x", role="user", timezone="UTC"
            ))
            await s.execute(models.users.insert().values(
                id=2, username="bob", password_hash="x", role="user", timezone="UTC"
            ))
            await s.execute(models.scripts.insert().values(
                id=10, user_id=1, name="hello", language="python", source_path="x.py"
            ))
            await s.execute(models.scripts.insert().values(
                id=20, user_id=2, name="bob-scr", language="python", source_path="y.py"
            ))
            await s.execute(models.schedules.insert().values(
                id=100, script_id=10, kind="cron", expression="* * * * *",
                enabled=1, next_run_at="2030-01-01T00:00:00Z",
                retry_max=0, retry_backoff=0, overlap_policy="skip",
                queue_max=10, queue_dropped=0,
            ))
            await s.execute(models.schedules.insert().values(
                id=200, script_id=20, kind="cron", expression="* * * * *",
                enabled=1, next_run_at="2030-01-01T00:00:00Z",
                retry_max=0, retry_backoff=0, overlap_policy="skip",
                queue_max=10, queue_dropped=0,
            ))
            for i in range(3):
                await s.execute(models.runs.insert().values(
                    id=1000 + i, script_id=10, schedule_id=100,
                    started_at="2030-01-01T00:00:00", status="success",
                    exit_code=0, retry_group=str(i),
                ))
            for i in range(2):
                await s.execute(models.runs.insert().values(
                    id=2000 + i, script_id=20, schedule_id=200,
                    started_at="2030-01-01T00:00:00", status="success",
                    exit_code=0, retry_group=str(i + 10),
                ))
            await s.commit()
        yield ac, app


@pytest.mark.asyncio
async def test_schedule_id_returns_only_matching(app_ctx, monkeypatch_auth):
    ac, _ = app_ctx
    monkeypatch_auth(user_id=1, role="user")
    r = await ac.get("/api/runs", params={"schedule_id": 100})
    assert r.status_code == 200
    runs = r.json()
    assert {x["script_id"] for x in runs} == {10}
    assert len(runs) == 3


@pytest.mark.asyncio
async def test_schedule_id_owner_check(app_ctx, monkeypatch_auth):
    ac, _ = app_ctx
    monkeypatch_auth(user_id=1, role="user")
    r = await ac.get("/api/runs", params={"schedule_id": 200})  # belongs to bob
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_offset_and_limit(app_ctx, monkeypatch_auth):
    ac, _ = app_ctx
    monkeypatch_auth(user_id=1, role="user")
    r = await ac.get("/api/runs", params={"schedule_id": 100, "limit": 2, "offset": 1})
    runs = r.json()
    assert len(runs) == 2
    # Newest-first default ordering; offsets skip
    assert runs[0]["id"] != runs[1]["id"]


@pytest.mark.asyncio
async def test_offset_clamps_upper(app_ctx, monkeypatch_auth):
    ac, _ = app_ctx
    monkeypatch_auth(user_id=1, role="user")
    r = await ac.get("/api/runs", params={"offset": 99999})
    assert r.status_code in (200, 422)  # behavior under clamp policy
```

Add a project-wide auth monkeypatch helper at `tests/conftest.py` (if not already present):

```python
import pytest
from scriptdeck.auth import deps as auth_deps


@pytest.fixture
def monkeypatch_auth(monkeypatch):
    """Returns a factory that fakes current_user for the duration of the test."""
    def _set(user_id: int, role: str = "user", username: str = "tester"):
        async def _fake():
            class U:
                pass
            u = U()
            u.id = user_id
            u.role = role
            u.username = username
            u.timezone = "UTC"
            return u
        monkeypatch.setattr(auth_deps, "current_user", _fake)
    return _set
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_runs_schedule_filter.py -v`
Expected: most tests error or fail; `schedule_id` is accepted by FastAPI's `Query` declaration only after the change.

- [ ] **Step 3: Implement the param + filter logic**

In `src/scriptdeck/api/runs.py`, update `list_endpoint` signature and body. Replace lines 58-107 with:

```python
@router.get("")
async def list_endpoint(
    request: Request,
    script_id: int | None = None,
    status_filter: str | None = None,
    since: str | None = None,
    group: str | None = None,
    schedule_id: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
) -> list[RunOut]:
    sf = request.app.state.session_factory
    t = _runs_table()
    sched_t = _schedules_table()
    stmt = select(t).limit(limit).offset(offset)
    if group is not None:
        stmt = stmt.where(t.c.retry_group == group).order_by(
            t.c.attempt.asc(), t.c.id.asc()
        )
    else:
        stmt = stmt.order_by(t.c.id.desc())
    if script_id:
        stmt = stmt.where(t.c.script_id == script_id)
        async with sf() as s:
            await require_script_owner(s, script_id, user)
    elif group is None:
        if user.role != "admin":
            async with sf() as s:
                own_script_ids = await run_service.own_script_ids(s, user.id)
            if not own_script_ids:
                return []
            stmt = stmt.where(t.c.script_id.in_(own_script_ids))
    if schedule_id is not None:
        # Resolve schedule → script and owner-check before applying the filter,
        # mirroring the script_id branch above.
        async with sf() as s:
            sched_row = (
                await s.execute(
                    select(sched_t.c.script_id).where(sched_t.c.id == schedule_id)
                )
            ).one_or_none()
            if sched_row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
            await require_script_owner(s, int(sched_row[0]), user)
        stmt = stmt.where(t.c.schedule_id == schedule_id)
    if status_filter:
        stmt = stmt.where(t.c.status == status_filter)
    if since:
        stmt = stmt.where(t.c.started_at >= since)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    if group is not None and user.role != "admin":
        async with sf() as s:
            own_script_ids = set(await run_service.own_script_ids(s, user.id))
        rows = [r for r in rows if r["script_id"] in own_script_ids]
    return [RunOut(**dict(r)) for r in rows]
```

Add `_schedules_table()` helper above `list_endpoint`:

```python
def _schedules_table():
    from scriptdeck.db.models import schedules
    return schedules
```

Adjust the `clamp_upper` test: the spec says clamp to 10000 → 422 is correct from FastAPI. Keep `status_code == 422` only (drop 200). Update `test_offset_clamps_upper` last line:

```python
    assert r.status_code == 422
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/api/test_runs_schedule_filter.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/api/runs.py tests/api/test_runs_schedule_filter.py tests/conftest.py
git commit -m "feat(api): schedule_id + offset filter on GET /api/runs"
```

---

### Task 2: Frontend `RunningDuration` component + tests

**Files:**
- Create: `frontend/src/components/runs/RunningDuration.tsx`
- Test: `frontend/tests/components/RunningDuration.test.tsx` (new)

**Interfaces:**
- Consumes: `started_at: string` (ISO)
- Produces: function `RunningDuration({ started_at }: { started_at: string })` that renders formatted duration, ticking every 1s, cleans up on unmount.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/components/RunningDuration.test.tsx`:

```tsx
import { render, screen, act } from "@testing-library/react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { RunningDuration } from "@/components/runs/RunningDuration";

describe("RunningDuration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2030-01-01T00:00:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders seconds when fresh", () => {
    render(<RunningDuration started_at="2030-01-01T00:00:00Z" />);
    expect(screen.getByText(/0\.0s|0s/)).toBeInTheDocument();
  });

  it("ticks forward after 2s", () => {
    const { rerender } = render(<RunningDuration started_at="2030-01-01T00:00:00Z" />);
    act(() => {
      vi.setSystemTime(new Date("2030-01-01T00:00:02Z"));
      vi.advanceTimersByTime(1000);
    });
    rerender(<RunningDuration started_at="2030-01-01T00:00:00Z" />);
    expect(screen.getByText(/2s/)).toBeInTheDocument();
  });

  it("renders minutes when past 60s", () => {
    render(<RunningDuration started_at="2029-12-31T23:58:30Z" />);
    expect(screen.getByText(/1m 30s/)).toBeInTheDocument();
  });

  it("renders hours when past 1h", () => {
    render(<RunningDuration started_at="2029-12-31T22:55:00Z" />);
    expect(screen.getByText(/1h 5m/)).toBeInTheDocument();
  });

  it("renders days when past 24h", () => {
    render(<RunningDuration started_at="2029-12-30T00:00:00Z" />);
    expect(screen.getByText(/2d 0h/)).toBeInTheDocument();
  });

  it("cleans up interval on unmount", () => {
    const spy = vi.spyOn(global, "clearInterval");
    const { unmount } = render(<RunningDuration started_at="2030-01-01T00:00:00Z" />);
    unmount();
    expect(spy).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/components/RunningDuration.test.tsx`
Expected: fail — module not found.

- [ ] **Step 3: Implement the component**

Create `frontend/src/components/runs/RunningDuration.tsx`:

```tsx
import { useEffect, useState } from "react";

function format(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const totalSec = Math.floor(ms / 1000);
  const d = Math.floor(totalSec / 86400);
  const h = Math.floor((totalSec % 86400) / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

export function RunningDuration({ started_at }: { started_at: string }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);

  const started = new Date(started_at).getTime();
  const now = Date.now();
  return <span className="font-mono tabular-nums">{format(now - started)}</span>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run tests/components/RunningDuration.test.tsx`
Expected: 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/runs/RunningDuration.tsx frontend/tests/components/RunningDuration.test.tsx
git commit -m "feat(ui): RunningDuration ticking component"
```

---

### Task 3: `Runs.tsx` rewrite — filters, sticky running section, paginated history, cancel

**Files:**
- Modify: `frontend/src/pages/Runs.tsx` (full rewrite)
- Test: `frontend/tests/Runs.test.tsx` (new)

**Interfaces:**
- Consumes: `api()` from `@/api/client`, `cancelRun` from `@/api/runs`, `listSchedules` from `@/api/schedules`, `<RunningDuration>` from Task 2, existing `<Pagination>` at `@/components/ui/pagination.tsx`.
- Produces: default-export-free component `Runs()` consumed by the router (no signature change).

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/Runs.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, beforeEach, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Runs } from "@/pages/Runs";

const apiMock = vi.fn();
const cancelMock = vi.fn();
const schedulesMock = vi.fn();

vi.mock("@/api/client", () => ({
  api: (...a: unknown[]) => apiMock(...a),
}));
vi.mock("@/api/runs", () => ({
  cancelRun: (...a: unknown[]) => cancelMock(...a),
  getRun: vi.fn(),
  listRunGroup: vi.fn(),
}));
vi.mock("@/api/schedules", () => ({
  listSchedules: () => schedulesMock(),
}));
vi.mock("@/auth/AuthProvider", () => ({
  useAuth: () => ({ user: { role: "user", timezone: "UTC" } }),
}));

function setup() {
  apiMock.mockReset();
  cancelMock.mockReset();
  schedulesMock.mockReset();
  apiMock.mockResolvedValue([]);
  schedulesMock.mockResolvedValue([
    { id: 1, expression: "* * * * *", script_id: 10, enabled: true,
      next_run_at: null, timezone: "UTC", run_count: 0 },
  ]);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Runs />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("Runs page", () => {
  beforeEach(() => setup());

  it("renders schedule dropdown and pulls schedules", async () => {
    await waitFor(() => expect(schedulesMock).toHaveBeenCalled());
    expect(screen.getByText(/Runs/i)).toBeInTheDocument();
  });

  it("fetches runs on mount", async () => {
    await waitFor(() => expect(apiMock).toHaveBeenCalledWith("/api/runs"));
  });

  it("shows 'No runs match' when both queries empty", async () => {
    await waitFor(() => expect(screen.getByText(/No runs match/i)).toBeInTheDocument());
  });

  it("shows running section when a running row exists", async () => {
    apiMock.mockImplementation((url: string) => {
      if (url.includes("status=running")) {
        return Promise.resolve([{
          id: 1, script_name: "hello", schedule_id: null,
          started_at: new Date().toISOString(),
          ended_at: null, exit_code: null, status: "running",
        }]);
      }
      return Promise.resolve([]);
    });
    setup();
    await waitFor(() =>
      expect(screen.getByText(/Currently running/i)).toBeInTheDocument()
    );
  });

  it("calls cancelRun and invalidates when Cancel clicked", async () => {
    apiMock.mockImplementation((url: string) => {
      if (url.includes("status=running")) {
        return Promise.resolve([{
          id: 1, script_name: "hello", schedule_id: null,
          started_at: new Date().toISOString(),
          ended_at: null, exit_code: null, status: "running",
        }]);
      }
      return Promise.resolve([]);
    });
    cancelMock.mockResolvedValue({ ok: true });
    setup();
    const user = userEvent.setup();
    const cancelBtn = await screen.findByLabelText(/Cancel run 1/i);
    await user.click(cancelBtn);
    await waitFor(() => expect(cancelMock).toHaveBeenCalledWith(1));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run tests/Runs.test.tsx`
Expected: FAIL — page missing or selectors not found.

- [ ] **Step 3: Rewrite `Runs.tsx`**

Replace `frontend/src/pages/Runs.tsx` content with:

```tsx
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { cancelRun } from "@/api/runs";
import { listSchedules } from "@/api/schedules";
import { useAuth } from "@/auth/AuthProvider";
import { AppShell } from "@/components/AppShell";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Pagination, PaginationContent, PaginationItem, PaginationNext, PaginationPrevious } from "@/components/ui/pagination";
import { toast } from "@/components/ui/sonner";
import { CardHeader, CardTitle } from "@/components/ui/card";
import { RunningDuration } from "@/components/runs/RunningDuration";
import { X } from "lucide-react";

const STATUSES = ["all", "running", "success", "failed", "cancelled", "error", "skipped"] as const;
type Status = (typeof STATUSES)[number];
const PAGE_SIZE = 20;

type RunRow = {
  id: number;
  script_id: number;
  script_name: string;
  schedule_id: number | null;
  started_at: string;
  ended_at: string | null;
  exit_code: number | null;
  status: string;
};

type ScheduleRow = {
  id: number;
  expression: string;
  script_id: number;
  enabled: boolean;
  next_run_at: string | null;
  timezone: string | null;
  run_count: number;
};

function runsUrl(opts: { schedule?: string; status?: Status; offset?: number; limit?: number }) {
  const params = new URLSearchParams();
  if (opts.schedule && opts.schedule !== "all") params.set("schedule_id", opts.schedule);
  if (opts.status && opts.status !== "all") params.set("status", opts.status === "failed" ? "failure" : opts.status);
  if (opts.offset && opts.offset > 0) params.set("offset", String(opts.offset));
  params.set("limit", String(opts.limit ?? PAGE_SIZE));
  const qs = params.toString();
  return qs ? `/runs?${qs}` : "/runs";
}

export function Runs() {
  const nav = useNavigate();
  const qc = useQueryClient();
  const { user } = useAuth();
  const [schedule, setSchedule] = useState("all");
  const [status, setStatus] = useState<Status>("all");
  const [page, setPage] = useState(1);

  const { data: schedules = [] } = useQuery({
    queryKey: ["schedules-for-runs"],
    queryFn: () => listSchedules(),
  }) as { data: ScheduleRow[] };

  const offset = (page - 1) * PAGE_SIZE;
  const commonArgs = { schedule, status, limit: PAGE_SIZE };

  const history = useQuery({
    queryKey: ["runs-history", schedule, status, page],
    queryFn: () => api<RunRow[]>(runsUrl({ ...commonArgs, offset })),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
    placeholderData: keepPreviousData,
  });

  const running = useQuery({
    queryKey: ["runs-running", schedule],
    queryFn: () => api<RunRow[]>(runsUrl({ schedule, status: "running", limit: 100 })),
    refetchInterval: (q) => (q.state.data && (q.state.data as unknown[]).length > 0 ? 2000 : false),
    refetchIntervalInBackground: false,
  });

  // Pause polling when tab hidden — TanStack Query already does this when
  // refetchIntervalInBackground is false, so no manual listener needed.

  useEffect(() => {
    function onVis() { /* react-query handles pause */ }
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, []);

  const totalPages = useMemo(() => {
    // Approximation: history query's total count isn't returned; default 1.
    // The pagination controls only show Next when the page returned full rows.
    return Math.max(1, page + ((history.data?.length ?? 0) === PAGE_SIZE ? 1 : 0));
  }, [history.data, page]);

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["runs-history"] });
    qc.invalidateQueries({ queryKey: ["runs-running"] });
  }

  async function onCancel(id: number) {
    try {
      await cancelRun(id);
      toast.success("Run cancelled");
      invalidate();
    } catch (e) {
      const msg = (e as Error).message;
      if (/404/.test(msg)) toast.error("Already finished");
      else toast.error(msg);
      invalidate();
    }
  }

  const showRunning = (running.data?.length ?? 0) > 0;
  const noMatches = !showRunning && (history.data?.length ?? 0) === 0 && !history.isLoading;

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl space-y-6 p-6">
        <h1 className="text-2xl font-semibold">Runs</h1>
        <div className="flex flex-wrap items-center gap-3">
          <Select value={schedule} onValueChange={(v) => { setSchedule(v); setPage(1); }}>
            <SelectTrigger className="w-64"><SelectValue placeholder="All schedules" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All schedules</SelectItem>
              {schedules.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  #{s.id} · {s.expression}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={status} onValueChange={(v) => { setStatus(v as Status); setPage(1); }}>
            <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
            <SelectContent>
              {STATUSES.map((s) => (
                <SelectItem key={s} value={s}>{s}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {showRunning && (
          <Card>
            <CardHeader className="px-4 py-3">
              <CardTitle className="text-sm font-medium">
                Currently running ({running.data!.length})
              </CardTitle>
            </CardHeader>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Run</TableHead>
                  <TableHead>Script</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                  <TableHead>Exit</TableHead>
                  <TableHead className="w-24 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {running.data!.map((r) => (
                  <TableRow
                    key={r.id}
                    tabIndex={0}
                    onClick={() => nav(`/runs/${r.id}`)}
                    onKeyDown={(e) => { if (e.key === "Enter") nav(`/runs/${r.id}`); }}
                    className="cursor-pointer hover:bg-muted/50"
                  >
                    <TableCell className="font-mono text-xs">#{String(r.id).slice(0, 6)}</TableCell>
                    <TableCell>{r.script_name}</TableCell>
                    <TableCell><Badge>{r.status}</Badge></TableCell>
                    <TableCell>{new Date(r.started_at).toLocaleString()}</TableCell>
                    <TableCell><RunningDuration started_at={r.started_at} /></TableCell>
                    <TableCell>{r.exit_code ?? "—"}</TableCell>
                    <TableCell className="text-right">
                      {user?.role !== "viewer" && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={`Cancel run ${r.id}`}
                          onClick={(e) => { e.stopPropagation(); onCancel(r.id); }}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
        )}

        <Card>
          <CardHeader className="px-4 py-3">
            <CardTitle className="text-sm font-medium">History</CardTitle>
          </CardHeader>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Run</TableHead>
                <TableHead>Script</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Exit</TableHead>
                <TableHead>Schedule</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(history.data ?? []).map((r) => (
                <TableRow
                  key={r.id}
                  tabIndex={0}
                  onClick={() => nav(`/runs/${r.id}`)}
                  onKeyDown={(e) => { if (e.key === "Enter") nav(`/runs/${r.id}`); }}
                  className="cursor-pointer hover:bg-muted/50"
                >
                  <TableCell className="font-mono text-xs">#{String(r.id).slice(0, 6)}</TableCell>
                  <TableCell>{r.script_name}</TableCell>
                  <TableCell><Badge variant={variantFor(r.status)}>{r.status}</Badge></TableCell>
                  <TableCell>{new Date(r.started_at).toLocaleString()}</TableCell>
                  <TableCell>
                    {r.ended_at
                      ? <span className="font-mono tabular-nums">{(new Date(r.ended_at).getTime() - new Date(r.started_at).getTime()) / 1000 | 0}s</span>
                      : <RunningDuration started_at={r.started_at} />}
                  </TableCell>
                  <TableCell>{r.exit_code ?? "—"}</TableCell>
                  <TableCell>{r.schedule_id ? `#${r.schedule_id}` : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>

        {noMatches && (
          <div className="py-12 text-center text-sm text-muted-foreground">No runs match these filters.</div>
        )}

        <Pagination>
          <PaginationContent>
            <PaginationItem>
              <PaginationPrevious
                href="#"
                onClick={(e) => { e.preventDefault(); setPage((p) => Math.max(1, p - 1)); }}
                aria-disabled={page === 1}
              />
            </PaginationItem>
            <PaginationItem className="px-4 text-sm">page {page}</PaginationItem>
            <PaginationItem>
              <PaginationNext
                href="#"
                onClick={(e) => { e.preventDefault(); setPage((p) => p + 1); }}
                aria-disabled={(history.data?.length ?? 0) < PAGE_SIZE}
              />
            </PaginationItem>
          </PaginationContent>
        </Pagination>
      </div>
    </AppShell>
  );
}

function variantFor(status: string): "default" | "secondary" | "destructive" | "success" {
  switch (status) {
    case "success":
      return "success";
    case "failure":
    case "error":
      return "destructive";
    default:
      return "secondary";
  }
}

import { CardHeader, CardTitle } from "@/components/ui/card";
```

Note: all imports grouped at top in final file.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/Runs.test.tsx`
Expected: 5 tests PASS (with `keepPreviousData` and TanStack Query v5).

- [ ] **Step 5: Manual smoke**

1. `cd frontend && npm run dev`
2. Open `/runs`. Confirm: schedule dropdown populated from `/api/schedules`, status dropdown shows 7 options, history table renders.
3. With a 1-min schedule and a current run: confirm sticky "Currently running" section appears, ticks every second, Cancel button visible for `role=user`.
4. Click any row → navigates to `/runs/<id>` and `RunView` loads logs.
5. Cancel a running row → toast appears, row removed from sticky section on next poll.
6. Toggle schedule filter → history + running both re-scope.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/Runs.tsx frontend/tests/Runs.test.tsx
git commit -m "feat(ui): rebuild Runs page — schedule filter + running section + pagination"
```

---

### Task 4: End-to-end pytest + vitest gate

**Files:**
- Run only (no file edits)
- Test: `tests/api/test_runs_schedule_filter.py`, `frontend/tests/Runs.test.tsx`, `frontend/tests/components/RunningDuration.test.tsx`

- [ ] **Step 1: Run backend tests**

Run: `pytest tests/api/test_runs_schedule_filter.py -v`
Expected: 4 PASS.

- [ ] **Step 2: Run frontend tests**

Run: `cd frontend && npx vitest run`
Expected: all tests across Runs.test, RunningDuration.test, and the existing suite PASS.

- [ ] **Step 3: Lint**

Run: `ruff check src tests` and `cd frontend && npm run lint`
Expected: clean.

- [ ] **Step 4: Push branch and open PR**

```bash
git push -u origin feat/run-logs
gh pr create --base main --head feat/run-logs \
  --title "feat: refresh Runs page (schedule filter + running section + pagination)" \
  --body "Implements docs/superpowers/specs/2026-08-16-runs-page-refresh-design.md"
```

Expected: PR URL printed. Watch CI; fix any failures before requesting review.
