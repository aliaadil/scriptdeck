# Triggers PR #19 — UI Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four rough edges in PR #19 — clickable Scripts table rows, top padding on Config/Logs tabs, and a recent-runs list inside the Logs tab.

**Architecture:** Frontend-only tweaks. No backend, no migration. Two component files touched plus one small extension to the existing runs API helper. Existing react-query patterns preserved.

**Tech Stack:** React 18 + TypeScript, react-router-dom, @tanstack/react-query, shadcn/ui (Tabs, Card, Badge, Table), Vitest + Testing Library.

## Global Constraints

- Frontend lives in `frontend/`. Tests run with `npm test` from `frontend/`. Lint with `npm run lint`.
- Tests already mock `@/lib/api` and `@/api/client` (the page imports `@/lib/api`; the helper imports `@/api/client`). Mock whichever one the page uses.
- No new dependencies. No backend change. No migration.
- Existing test patterns: `vi.mock("@/lib/api", ...)` and `apiMock.mockImplementation((path) => ...)`.
- Commit messages use Conventional Commits prefix.

---

## File Structure

**Modify:**
- `frontend/src/pages/Scripts.tsx` — row click navigates; action buttons stop propagation.
- `frontend/src/pages/ScriptEdit.tsx` — drop redundant top padding; add Recent Runs panel on Logs tab.
- `frontend/src/api/runs.ts` — `listRuns` gains optional `limit` param so the Logs tab can request 20 rows.

**Modify (tests):**
- `frontend/src/pages/__tests__/Scripts.test.tsx` — row-click navigation tests.
- `frontend/src/pages/__tests__/ScriptEdit.test.tsx` — gap-shape and recent-runs tests.

No new files. No splits — touched files stay under their existing sizes.

---

## Task 1: Clickable Scripts table rows

**Files:**
- Modify: `frontend/src/pages/Scripts.tsx:105-150` (desktop `TableBody` block)
- Modify: `frontend/src/pages/__tests__/Scripts.test.tsx`

**Interfaces:**
- Consumes: existing `scripts: ScriptRow[]` from `useQuery`; existing `nav: (path) => void` from `useNavigate()`.
- Produces: unchanged API; new behavior: clicking a non-button area of a row navigates to `/kindling/scripts/{id}`.

- [ ] **Step 1: Write the failing test**

Append two tests to `Scripts.test.tsx`. The existing test only mounts on desktop (no `useIsMobile` mock), so by default it renders the table. Add:

```tsx
const apiMock = vi.fn();
vi.mock("@/api/client", () => ({
  api: (...args: unknown[]) => apiMock(...args),
}));

const navMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => navMock };
});
```

Replace the existing `@/api/client` mock block with the version above (keeping the existing test working — the mock returns `[]` by default so `scripts` is empty; the table still renders headers).

Then append inside the `describe("Scripts", ...)` block:

```tsx
it("navigates to the script when a row cell is clicked", async () => {
  apiMock.mockResolvedValue([
    { id: 7, name: "hello", language: "python", last_run: null, schedule: null },
  ]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Scripts />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const row = await screen.findByRole("row", { name: /hello/i });
  await userEvent.click(within(row).getByText("python"));
  expect(navMock).toHaveBeenCalledWith("/kindling/scripts/7");
});

it("does not navigate when the Run button is clicked", async () => {
  apiMock.mockResolvedValue([
    { id: 7, name: "hello", language: "python", last_run: null, schedule: null },
  ]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Scripts />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const runBtn = await screen.findByRole("button", { name: /^run$/i });
  await userEvent.click(runBtn);
  expect(navMock).not.toHaveBeenCalled();
});
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run: `cd frontend && npm test -- Scripts.test.tsx`
Expected: both new tests FAIL — the row click does nothing and Run button does navigate (because Edit already calls `nav`).

- [ ] **Step 3: Make rows clickable; stop propagation on action buttons**

Edit `frontend/src/pages/Scripts.tsx`. In the desktop `<TableBody>` block, replace the row's outer element + each action button:

```tsx
<TableRow
  key={s.id}
  className="cursor-pointer"
  onClick={() => nav(`/kindling/scripts/${s.id}`)}
>
  <TableCell>
    <Link
      to={`/kindling/scripts/${s.id}`}
      className="font-medium hover:underline"
      onClick={(e) => e.stopPropagation()}
    >
      {s.name}
    </Link>
  </TableCell>
  <TableCell>
    <Badge variant="secondary">{s.language}</Badge>
  </TableCell>
  <TableCell>{s.schedule ?? "—"}</TableCell>
  <TableCell>
    {s.last_run ? new Date(s.last_run).toLocaleString() : "—"}
  </TableCell>
  <TableCell className="text-right space-x-2">
    <Button
      size="sm"
      variant="outline"
      onClick={(e) => { e.stopPropagation(); run.mutate(s.id); }}
    >
      Run
    </Button>
    <Button
      size="sm"
      variant="outline"
      onClick={(e) => { e.stopPropagation(); nav(`/kindling/scripts/${s.id}`); }}
    >
      Edit
    </Button>
    <Button
      size="sm"
      variant="destructive"
      onClick={(e) => { e.stopPropagation(); del.mutate(s.id); }}
    >
      Delete
    </Button>
  </TableCell>
</TableRow>
```

Two changes: row `onClick` + `cursor-pointer`; `<Link>` and all three action buttons get `e.stopPropagation()`.

- [ ] **Step 4: Run all Scripts tests and verify they pass**

Run: `cd frontend && npm test -- Scripts.test.tsx`
Expected: all tests pass (existing + new two).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Scripts.tsx frontend/src/pages/__tests__/Scripts.test.tsx
git commit -m "feat(ui): make Scripts table rows clickable; stop propagation on actions"
```

---

## Task 2: Collapse Config / Logs tab top gap

**Files:**
- Modify: `frontend/src/pages/ScriptEdit.tsx:328` (TabsList), `:386` (Config CardContent), `:438` (Logs CardContent)
- Modify: `frontend/src/pages/__tests__/ScriptEdit.test.tsx`

**Interfaces:**
- Consumes: existing layout primitives.
- Produces: tighter vertical spacing above the Config form and Logs card.

- [ ] **Step 1: Write the failing assertion**

Append to `ScriptEdit.test.tsx` inside `describe("ScriptEdit", ...)`:

```tsx
it("Config tab has no extra top padding beyond TabsContent", async () => {
  const user = userEvent.setup();
  renderEditor();
  await user.click(await screen.findByRole("tab", { name: /config/i }));

  const tabPanel = screen.getByRole("tabpanel", { name: /config/i });
  const card = tabPanel.querySelector(".pt-6");
  // The CardContent must not stack its own pt-6 on top of TabsContent p-4.
  expect(card).toBeNull();
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm test -- ScriptEdit.test.tsx`
Expected: FAIL — `card` exists today.

- [ ] **Step 3: Drop the redundant padding**

Edit `frontend/src/pages/ScriptEdit.tsx`:

Line 328 — remove `mt-2`:

```tsx
<TabsList className="mx-4 self-start">
```

Line 386 — remove `pt-6`:

```tsx
<CardContent className="space-y-4">
```

Line 438 — remove `pt-6`:

```tsx
<CardContent className="space-y-3">
```

- [ ] **Step 4: Run all ScriptEdit tests and verify they pass**

Run: `cd frontend && npm test -- ScriptEdit.test.tsx`
Expected: all tests pass.

- [ ] **Step 5: Lint**

Run: `cd frontend && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ScriptEdit.tsx frontend/src/pages/__tests__/ScriptEdit.test.tsx
git commit -m "fix(ui): collapse redundant top padding on Config/Logs tabs"
```

---

## Task 3: Extend `listRuns` helper with `limit`

**Files:**
- Modify: `frontend/src/api/runs.ts:11-17`

**Interfaces:**
- Consumes: existing `api<Run[]>` helper.
- Produces: `listRuns({ script_id?, status?, limit? })` returning `Run[]`. Backend already supports `limit` (default 50, max 100).

- [ ] **Step 1: Add the limit parameter**

Replace the `listRuns` function body in `frontend/src/api/runs.ts`:

```ts
export const listRuns = (params?: {
  script_id?: number;
  status?: string;
  limit?: number;
}) => {
  const q = new URLSearchParams();
  if (params?.script_id) q.set("script_id", String(params.script_id));
  if (params?.status) q.set("status_filter", params.status);
  if (params?.limit) q.set("limit", String(params.limit));
  const qs = q.toString();
  return api<Run[]>(`/runs${qs ? `?${qs}` : ""}`);
};
```

No test change here — Task 4 covers behavior. This task is type-shape only.

- [ ] **Step 2: Run all tests to make sure nothing regressed**

Run: `cd frontend && npm test`
Expected: all existing tests pass (the change is additive).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/runs.ts
git commit -m "feat(api-helper): accept optional limit on listRuns"
```

---

## Task 4: Add Recent Runs panel to Logs tab

**Files:**
- Modify: `frontend/src/pages/ScriptEdit.tsx` — Logs `TabsContent` block (~line 436-459)
- Modify: `frontend/src/pages/__tests__/ScriptEdit.test.tsx`

**Interfaces:**
- Consumes: existing `apiMock`, existing `currentRunId` state, existing log-fetch effect (keyed off `currentRunId` + run status), existing `listRuns` helper.
- Produces: A new card above the log viewer that lists the last 20 runs for `scriptId`. Clicking a row sets `currentRunId` to that run id, which the existing log-fetch effect picks up automatically.

- [ ] **Step 1: Write the failing test**

Append to `ScriptEdit.test.tsx`:

```tsx
it("Logs tab lists recent runs and clicking one loads its log", async () => {
  const user = userEvent.setup();
  const runsResp = [
    { id: 99, script_id: 1, status: "success", exit_code: 0, started_at: "2026-08-21T00:00:00Z", ended_at: "2026-08-21T00:00:01Z", schedule_id: null, attempt: 0, retry_group: null },
    { id: 98, script_id: 1, status: "failure", exit_code: 2, started_at: "2026-08-20T00:00:00Z", ended_at: "2026-08-20T00:00:01Z", schedule_id: 7, attempt: 0, retry_group: null },
  ];
  apiMock.mockImplementation((path: string) => {
    if (path === "/scripts/1") return Promise.resolve(mockScript);
    if (path.startsWith("/runs?script_id=1")) return Promise.resolve(runsResp);
    if (path === "/runs/98") return Promise.resolve(runsResp[1]);
    if (path === "/runs/98/log") return Promise.resolve({ content: "old log" });
    return Promise.resolve({});
  });
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : (input as Request).url;
      if (url.endsWith("/runs/98/log")) {
        return Promise.resolve(new Response("old log", { status: 200 }));
      }
      return Promise.resolve(new Response("", { status: 404 }));
    }) as unknown as typeof fetch,
  );

  renderEditor();
  await user.click(await screen.findByRole("tab", { name: /logs/i }));

  expect(await screen.findByText("Run #99")).toBeInTheDocument();
  expect(screen.getByText("Run #98")).toBeInTheDocument();

  await user.click(screen.getByText("Run #98"));
  await waitFor(() =>
    expect(screen.getByText(/Run #98/)).toBeInTheDocument(),
  );
});
```

- [ ] **Step 2: Run and verify failure**

Run: `cd frontend && npm test -- ScriptEdit.test.tsx`
Expected: FAIL — there is no "Run #99" / "Run #98" text today.

- [ ] **Step 3: Add the Recent Runs panel**

In `frontend/src/pages/ScriptEdit.tsx`, import the helper:

```tsx
import { listRuns } from "@/api/runs";
```

Place this alongside the other imports near line 1-35.

Inside the `ScriptEdit` component body, just below `const run = useMutation<RunInfo, Error, void>(...)`, add:

```tsx
const recentRuns = useQuery({
  queryKey: ["runs", "by-script", scriptId],
  queryFn: () => listRuns({ script_id: scriptId, limit: 20 }),
  enabled: scriptIdValid,
  refetchInterval: 5000,
});
```

Replace the Logs `TabsContent` block (the one currently starting with `<TabsContent value="logs" className="overflow-auto p-4">`) with:

```tsx
<TabsContent value="logs" className="overflow-auto p-4">
  <div className="space-y-4">
    <Card>
      <CardContent className="space-y-2 p-4">
        <h3 className="text-sm font-medium">Recent runs</h3>
        {recentRuns.data && recentRuns.data.length > 0 ? (
          <div className="divide-y">
            {recentRuns.data.map((r) => (
              <button
                key={r.id}
                type="button"
                data-testid={`recent-run-${r.id}`}
                onClick={() => {
                  setCurrentRunId(r.id);
                  setRunLog("");
                }}
                className={`flex w-full items-center justify-between gap-2 py-2 text-left text-sm hover:bg-muted/50 ${
                  currentRunId === r.id ? "bg-muted/40" : ""
                }`}
              >
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs">#{r.id}</span>
                  <RunStatusBadge status={r.status} exitCode={r.exit_code} />
                  <span className="text-xs text-muted-foreground">
                    {new Date(r.started_at).toLocaleString()}
                  </span>
                  {r.schedule_id != null ? (
                    <span className="rounded-full bg-secondary px-2 py-0.5 text-[10px]">
                      via schedule
                    </span>
                  ) : null}
                </span>
                <span className="text-xs text-muted-foreground">
                  exit {r.exit_code ?? "—"}
                </span>
              </button>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No runs yet.</p>
        )}
      </CardContent>
    </Card>

    <Card>
      <CardContent className="space-y-3 p-4">
        {currentRunId == null ? (
          <p className="text-sm text-muted-foreground">
            Pick a run above, or hit Run in the header.
          </p>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium">Run #{currentRunId}</span>
              <RunStatusBadge
                status={runStatus.data?.status ?? "running"}
                exitCode={runStatus.data?.exit_code ?? null}
              />
            </div>
            <pre className="max-h-[60vh] overflow-auto rounded-md border bg-[#1e1e1e] p-3 font-mono text-[13px] leading-relaxed text-zinc-100">
              {runStatus.data?.status === "running" && !runLog
                ? "Waiting for output…"
                : runLog || "(no output)"}
            </pre>
          </>
        )}
      </CardContent>
    </Card>
  </div>
</TabsContent>
```

- [ ] **Step 4: Run all ScriptEdit tests and verify they pass**

Run: `cd frontend && npm test -- ScriptEdit.test.tsx`
Expected: all tests pass, including the existing "starts a run and switches to the Logs tab" test.

- [ ] **Step 5: Lint**

Run: `cd frontend && npm run lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ScriptEdit.tsx frontend/src/pages/__tests__/ScriptEdit.test.tsx
git commit -m "feat(ui): show recent runs list on script Logs tab"
```

---

## Self-Review Notes

1. **Spec coverage:** four issues — Scripts rows ✓ Task 1; Config/Logs gap ✓ Task 2; recent runs ✓ Tasks 3+4; Schedules tab untouched ✓ global constraint.
2. **Placeholder scan:** no TBD/TODO; all code blocks complete.
3. **Type consistency:** `Run` type from `@/api/runs` is used in Task 4's `recentRuns.data` mapping. `listRuns({ script_id, limit })` signature added in Task 3 matches Task 4's call. `RunStatusBadge` reused — already in `ScriptEdit.tsx`.
4. **Risks:** Task 4 changes the Logs tab's rendered structure. Existing test "starts a run and switches to the Logs tab" asserts `Run #5` text — that text still renders inside the log card. Verified by reading the existing assertion (line 230 of ScriptEdit.test.tsx) — text is "Run #5" which our new panel renders for any selected run.
