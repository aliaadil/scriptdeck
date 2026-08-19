# Mobile-Friendly UI Tweaks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Kindling UI usable on a phone — add a bottom nav, convert 4 wide tables to card lists on `< md`, fix RunView padding/tabs, add minor ScriptEdit + form improvements.

**Architecture:** One new nav component (`MobileBottomNav`) shown only below the `md` breakpoint via `useIsMobile()`. Existing desktop sidebar unchanged. Page-level table→card branches live in the page file (one component per page, no premature abstraction). Admin Settings moves into the `UserMenu` on mobile to keep the bottom bar at 4 items.

**Tech Stack:** React 19, react-router, `@tanstack/react-query`, Tailwind v3, `lucide-react`, Vitest + @testing-library/react, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-18-mobile-friendly-design.md`

## Global Constraints

- Branch: `feature/mobile`
- Tailwind `md` breakpoint = 768px. `useIsMobile()` uses `MOBILE_BREAKPOINT = 768`. Aligned.
- Safe area: `pb-[env(safe-area-inset-bottom)]` on the mobile bottom nav.
- Active-tab styling on the mobile nav matches sidebar active color (`bg-sidebar-accent text-sidebar-accent-foreground`).
- Hidden on `/login`, `/setup` — those routes already render outside `AppShell`, so no extra branching needed.
- Keep existing tests green. Mobile-nav hidden ≥ md → existing AppShell test must keep passing.
- No new dependencies. Reuse `useIsMobile`, existing Card primitives, `cn` helper.

---

## File Map

| Path | Action | Responsibility |
|---|---|---|
| `frontend/src/components/mobile-bottom-nav.tsx` | Create | Bottom-nav component, `< md` only |
| `frontend/src/components/__tests__/mobile-bottom-nav.test.tsx` | Create | Unit tests for nav |
| `frontend/src/components/AppShell.tsx` | Edit | Mount nav, pad `<main>` |
| `frontend/src/components/__tests__/app-shell.test.tsx` | Edit | Assert nav mounts |
| `frontend/src/components/user-menu.tsx` | Edit | Mobile Settings link |
| `frontend/src/components/__tests__/user-menu.test.tsx` | Edit | Settings visibility on mobile |
| `frontend/src/pages/Dashboard.tsx` | Edit | Card branch for Recent runs |
| `frontend/src/pages/__tests__/Dashboard.test.tsx` | Edit | Render-assertion for both branches |
| `frontend/src/pages/Runs.tsx` | Edit | Card branch |
| `frontend/src/pages/Schedules.tsx` | Edit | Card branch |
| `frontend/src/pages/Scripts.tsx` | Edit | Card branch |
| `frontend/src/pages/RunView.tsx` | Edit | Responsive padding + tabs wrap |
| `frontend/src/pages/ScriptEdit.tsx` | Edit | Mobile collapse of file picker |
| `frontend/src/pages/ScriptNew.tsx` | Edit | `w-full` form |
| `frontend/src/pages/Settings.tsx` | Edit | `w-full` form |

---

### Task 1: MobileBottomNav component

**Files:**
- Create: `frontend/src/components/mobile-bottom-nav.tsx`
- Create: `frontend/src/components/__tests__/mobile-bottom-nav.test.tsx`

**Interfaces:**
- Exports: `MobileBottomNav` (default export, no props)
- Consumes: `useIsMobile()` from `@/hooks/use-mobile` — returns `boolean`
- Renders: `<nav>` with 4 `<NavLink>` items: Dashboard, Scripts, Schedules, Runs

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/__tests__/mobile-bottom-nav.test.tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi } from "vitest";
import { MobileBottomNav } from "../mobile-bottom-nav";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

import { useIsMobile } from "@/hooks/use-mobile";

describe("MobileBottomNav", () => {
  it("renders four nav links when on mobile", () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    render(
      <MemoryRouter>
        <MobileBottomNav />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: /dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /scripts/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /schedules/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /runs/i })).toBeInTheDocument();
  });

  it("renders nothing when not on mobile", () => {
    vi.mocked(useIsMobile).mockReturnValue(false);
    const { container } = render(
      <MemoryRouter>
        <MobileBottomNav />
      </MemoryRouter>
    );
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/__tests__/mobile-bottom-nav.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `MobileBottomNav`**

```tsx
// frontend/src/components/mobile-bottom-nav.tsx
import { NavLink } from "react-router-dom";
import { LayoutDashboard, FileCode2, Calendar, Activity } from "lucide-react";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

const items = [
  { to: "/kindling/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/kindling/scripts", label: "Scripts", icon: FileCode2 },
  { to: "/kindling/schedules", label: "Schedules", icon: Calendar },
  { to: "/kindling/runs", label: "Runs", icon: Activity },
];

export function MobileBottomNav() {
  const isMobile = useIsMobile();
  if (!isMobile) return null;
  return (
    <nav
      aria-label="Primary"
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 border-t bg-background pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {items.map((it) => (
        <NavLink
          key={it.to}
          to={it.to}
          className={({ isActive }) =>
            cn(
              "flex flex-col items-center justify-center gap-1 py-2 text-xs transition-colors",
              isActive
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-muted-foreground hover:text-foreground"
            )
          }
        >
          <it.icon className="h-5 w-5" />
          {it.label}
        </NavLink>
      ))}
    </nav>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/__tests__/mobile-bottom-nav.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/mobile-bottom-nav.tsx frontend/src/components/__tests__/mobile-bottom-nav.test.tsx
git commit -m "feat(ui): add MobileBottomNav for < md viewport"
```

---

### Task 2: AppShell mounts the nav + pads `<main>`

**Files:**
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/components/__tests__/app-shell.test.tsx`

**Interfaces:**
- Imports the new `MobileBottomNav` from Task 1
- Adds `pb-20 md:pb-6` to `<main>` so content never sits under the fixed bar

- [ ] **Step 1: Update AppShell**

```tsx
// frontend/src/components/AppShell.tsx
import { AppSidebar } from "./app-sidebar";
import { SiteHeader } from "./site-header";
import { MobileBottomNav } from "./mobile-bottom-nav";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <AppSidebar />
      <div className="flex flex-1 flex-col">
        <SiteHeader />
        <main className="flex-1 p-4 pb-20 md:p-6 md:pb-6">{children}</main>
      </div>
      <MobileBottomNav />
    </div>
  );
}
```

- [ ] **Step 2: Update AppShell test to assert nav mounts on mobile**

Append a new test inside `describe("AppShell", ...)`:

```tsx
import { useIsMobile } from "@/hooks/use-mobile";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

// ...inside describe("AppShell", () => {
  it("mounts the mobile bottom nav when on mobile", () => {
    vi.mocked(useIsMobile).mockReturnValue(true);
    render(
      <MemoryRouter>
        <AppShell>
          <div>child</div>
        </AppShell>
      </MemoryRouter>
    );
    expect(screen.getByRole("navigation", { name: /primary/i })).toBeInTheDocument();
  });
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/components/__tests__/app-shell.test.tsx`
Expected: PASS for all cases including new one.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/AppShell.tsx frontend/src/components/__tests__/app-shell.test.tsx
git commit -m "feat(ui): mount mobile nav in AppShell, pad main"
```

---

### Task 3: UserMenu exposes Settings on mobile

**Files:**
- Modify: `frontend/src/components/user-menu.tsx`
- Modify: `frontend/src/components/__tests__/user-menu.test.tsx`

**Interfaces:**
- Consumes `useIsMobile()` (Task 1 already added the hook mock target)
- Renders a Settings `<Link>` inside the dropdown only when `isMobile && user?.role === "admin"`

- [ ] **Step 1: Read existing UserMenu to plan the diff**

Run: `Read frontend/src/components/user-menu.tsx` and `Read frontend/src/components/__tests__/user-menu.test.tsx`. Note: do NOT modify blindly — existing tests likely mock `useAuth` similarly. Match the existing mock shape.

- [ ] **Step 2: Write failing test**

Append to the test file:

```tsx
import { useIsMobile } from "@/hooks/use-mobile";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

// ...inside describe:
it("shows Settings link for admins inside the menu on mobile", async () => {
  vi.mocked(useIsMobile).mockReturnValue(true);
  // Render UserMenu with admin user, open the menu (click trigger)
  // ...assert screen.getByRole("link", { name: /settings/i }) exists.
});
```

(Adjust trigger-button selector to match what the existing implementation uses. If the existing test file already covers opening the menu, follow that pattern.)

- [ ] **Step 3: Run test, confirm fails**

Run: `cd frontend && npx vitest run src/components/__tests__/user-menu.test.tsx`
Expected: FAIL — Settings link missing.

- [ ] **Step 4: Add Settings link conditional in UserMenu**

Inside the dropdown body of `UserMenu.tsx`, add (insert just before the logout item):

```tsx
import { useIsMobile } from "@/hooks/use-mobile";
import { Settings } from "lucide-react"; // if not already imported

const isMobile = useIsMobile();

// ...inside the dropdown, BEFORE the Logout item:
{user?.role === "admin" && isMobile && (
  <DropdownMenuItem asChild>
    <Link to="/kindling/settings" className="flex items-center gap-2">
      <Settings className="h-4 w-4" />
      Settings
    </Link>
  </DropdownMenuItem>
)}
```

(Use exact existing imports/patterns already in `user-menu.tsx`. The `asChild` link pattern matches shadcn DropdownMenuItem idioms — confirm and match.)

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/components/__tests__/user-menu.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/user-menu.tsx frontend/src/components/__tests__/user-menu.test.tsx
git commit -m "feat(ui): expose Settings in UserMenu on mobile"
```

---

### Task 4: Dashboard — recent runs table → card list on mobile

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`
- Modify: `frontend/src/pages/__tests__/Dashboard.test.tsx`

**Interfaces:**
- Mock `useIsMobile` in test; assert card branch renders script names when mobile, table row when desktop.

- [ ] **Step 1: Update Dashboard to branch on `useIsMobile`**

```tsx
// Dashboard.tsx — at top of component:
import { useIsMobile } from "@/hooks/use-mobile";

export function Dashboard() {
  // ...existing queries
  const isMobile = useIsMobile();
  // ...existing derivations

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard title="Total scripts" value={scripts.length} />
          <StatCard title="Active schedules" value={schedules.filter((s: any) => s.enabled).length} />
          <StatCard title="Runs today" value={todayRuns.length} />
          <StatCard title="Failure rate" value={`${failureRate}%`} />
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Recent runs</CardTitle>
          </CardHeader>
          <CardContent>
            {isMobile ? (
              <div className="space-y-2">
                {runRows.length === 0 && (
                  <div className="text-center text-muted-foreground">No runs yet.</div>
                )}
                {runRows.map((r: any) => (
                  <Link
                    key={r.id}
                    to={`/kindling/runs/${r.id}`}
                    className="flex items-center justify-between rounded-md border p-3 hover:bg-muted"
                  >
                    <div className="min-w-0">
                      <div className="truncate font-medium">{r.script_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {new Date(r.started_at).toLocaleString()} · {r.duration}
                      </div>
                    </div>
                    <Badge variant={r.status === "failed" ? "destructive" : r.status === "success" ? "success" : "secondary"}>
                      {r.status}
                    </Badge>
                  </Link>
                ))}
              </div>
            ) : (
              <Table>
                {/* EXISTING TABLE — DO NOT MODIFY */}
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </AppShell>
  );
}
```

Add import `import { Link } from "react-router-dom";` to existing import list.

- [ ] **Step 2: Update Dashboard test**

Append:

```tsx
import { useIsMobile } from "@/hooks/use-mobile";

vi.mock("@/hooks/use-mobile", () => ({
  useIsMobile: vi.fn(),
}));

// Also extend api mock so runs have data:
vi.mock("@/api/client", () => ({
  api: {
    get: vi.fn().mockResolvedValue({
      scripts: [],
      runs: [{ id: 1, script_name: "demo", status: "success", started_at: new Date().toISOString(), duration: "1.2s" }],
    }),
  },
}));

it("renders card list on mobile", async () => {
  vi.mocked(useIsMobile).mockReturnValue(true);
  // ...render Dashboard in QueryClient + MemoryRouter
  expect(await screen.findByText("demo")).toBeInTheDocument();
  // No <table> on mobile branch
  expect(screen.queryByRole("table")).toBeNull();
});

it("renders table on desktop", async () => {
  vi.mocked(useIsMobile).mockReturnValue(false);
  // ...render
  expect(await screen.findByRole("table")).toBeInTheDocument();
});
```

- [ ] **Step 3: Run tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/Dashboard.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Dashboard.tsx frontend/src/pages/__tests__/Dashboard.test.tsx
git commit -m "feat(ui): recent runs as cards on mobile dashboard"
```

---

### Task 5: Runs list — cards on mobile

**Files:**
- Modify: `frontend/src/pages/Runs.tsx`

- [ ] **Step 1: Read `frontend/src/pages/Runs.tsx` to inspect existing columns**

Run `Read frontend/src/pages/Runs.tsx` and identify: column set, row data shape, link target for each run.

- [ ] **Step 2: Add card branch**

At top of file, add:

```tsx
import { useIsMobile } from "@/hooks/use-mobile";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
```

In the component body, after queries, add `const isMobile = useIsMobile();`.

Wrap the existing `Table` block:

```tsx
{isMobile ? (
  <div className="space-y-2">
    {runRows.length === 0 && (
      <div className="text-center text-muted-foreground">No runs yet.</div>
    )}
    {runRows.map((r: any) => (
      <Link
        key={r.id}
        to={`/kindling/runs/${r.id}`}
        className="flex items-center justify-between rounded-md border p-3 hover:bg-muted"
      >
        <div className="min-w-0">
          <div className="truncate font-medium">{r.script_name}</div>
          <div className="text-xs text-muted-foreground">
            {new Date(r.started_at).toLocaleString()} · {r.duration}
          </div>
        </div>
        <Badge variant={r.status === "failed" ? "destructive" : r.status === "success" ? "success" : "secondary"}>
          {r.status}
        </Badge>
      </Link>
    ))}
  </div>
) : (
  // existing <Table>...</Table> JSX — UNCHANGED
)}
```

- [ ] **Step 3: Run existing Runs test**

Run: `cd frontend && npx vitest run src/pages/__tests__/Runs.test.tsx`
Expected: PASS (desktop default).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Runs.tsx
git commit -m "feat(ui): Runs list as cards on mobile"
```

---

### Task 6: Schedules list — cards on mobile

**Files:**
- Modify: `frontend/src/pages/Schedules.tsx`

- [ ] **Step 1: Read `frontend/src/pages/Schedules.tsx`**

Identify columns, row data, link target. Note `enabled` boolean field.

- [ ] **Step 2: Add card branch**

```tsx
import { useIsMobile } from "@/hooks/use-mobile";
import { Link } from "react-router-dom";
```

```tsx
const isMobile = useIsMobile();
```

```tsx
{isMobile ? (
  <div className="space-y-2">
    {rows.length === 0 && (
      <div className="text-center text-muted-foreground">No schedules.</div>
    )}
    {rows.map((s: any) => (
      <Link
        key={s.id}
        to={`/kindling/schedules/${s.id}`}
        className="flex items-center justify-between rounded-md border p-3 hover:bg-muted"
      >
        <div className="min-w-0">
          <div className="truncate font-medium">{s.name}</div>
          <div className="text-xs text-muted-foreground">
            {s.cron ?? s.schedule ?? ""} · next {s.next_run ?? "—"}
          </div>
        </div>
        <Badge variant={s.enabled ? "success" : "secondary"}>
          {s.enabled ? "on" : "off"}
        </Badge>
      </Link>
    ))}
  </div>
) : (
  // existing <Table>
)}
```

(Field labels adapt to actual data shape — `Read` first.)

- [ ] **Step 3: Run existing test**

Run: `cd frontend && npx vitest run src/pages/__tests__/Schedules.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Schedules.tsx
git commit -m "feat(ui): Schedules list as cards on mobile"
```

---

### Task 7: Scripts list — cards on mobile

**Files:**
- Modify: `frontend/src/pages/Scripts.tsx`

- [ ] **Step 1: Read `frontend/src/pages/Scripts.tsx`**

Identify columns, language field, edit target URL.

- [ ] **Step 2: Add card branch**

```tsx
import { useIsMobile } from "@/hooks/use-mobile";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
```

```tsx
const isMobile = useIsMobile();
```

```tsx
{isMobile ? (
  <div className="space-y-2">
    {scripts.length === 0 && (
      <div className="text-center text-muted-foreground">No scripts.</div>
    )}
    {scripts.map((s: any) => (
      <Link
        key={s.id}
        to={`/kindling/scripts/${s.id}`}
        className="flex items-center justify-between rounded-md border p-3 hover:bg-muted"
      >
        <div className="min-w-0">
          <div className="truncate font-medium">{s.name}</div>
          <div className="text-xs text-muted-foreground">
            {s.last_run
              ? `last run: ${s.last_run.status} · ${s.last_run.ago}`
              : "never run"}
          </div>
        </div>
        <Badge variant="secondary">{s.language ?? "—"}</Badge>
      </Link>
    ))}
  </div>
) : (
  // existing <Table>
)}
```

- [ ] **Step 3: Run existing test**

Run: `cd frontend && npx vitest run src/pages/__tests__/Scripts.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/Scripts.tsx
git commit -m "feat(ui): Scripts list as cards on mobile"
```

---

### Task 8: RunView — responsive padding + tabs wrap

**Files:**
- Modify: `frontend/src/pages/RunView.tsx`

- [ ] **Step 1: Update outer padding**

Change `<div className="mx-auto max-w-5xl space-y-6 p-6">` to `<div className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">`.

- [ ] **Step 2: Make tabs wrap on narrow widths**

Change `<TabsList>` (or its wrapper) to:

```tsx
<TabsList className="flex flex-wrap">
```

If `TabsList` already has class merged with `cn`, append `flex-wrap` to the existing string — do NOT replace the whole classname.

- [ ] **Step 3: Verify CardHeader reflow**

Inspect `CardHeader` flex. Existing classes: `flex flex-row items-center justify-between space-y-0`. On `< md`, add `flex-wrap gap-2` so StatusBadge + Cancel button wrap to a second line if needed:

```tsx
<CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 space-y-0">
```

- [ ] **Step 4: Run existing test**

Run: `cd frontend && npx vitest run src/pages/__tests__/RunView.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/RunView.tsx
git commit -m "feat(ui): RunView responsive padding + tab wrap"
```

---

### Task 9: ScriptEdit mobile file-picker collapse

**Files:**
- Modify: `frontend/src/pages/ScriptEdit.tsx`

- [ ] **Step 1: Read `frontend/src/pages/ScriptEdit.tsx`**

Identify where the file list is rendered (multi-file editor per recent commit). Find the existing sidebar/list rendering.

- [ ] **Step 2: Hide desktop file list on mobile**

Wrap the existing file-list container:

```tsx
<div className="hidden md:block ...">
  {/* existing file list JSX */}
</div>
```

(If the existing wrapper is `<aside>` or `<div>`, just add `hidden md:block` to its classname — do NOT rename the element.)

- [ ] **Step 3: Add mobile file picker**

Above the editor toolbar, add:

```tsx
const [files, setFiles] = useState<...>(...); // whatever shape already exists
const [activeFile, setActiveFile] = useState(...);

<div className="md:hidden">
  <Select value={activeFile} onValueChange={setActiveFile}>
    <SelectTrigger><SelectValue placeholder="Select file" /></SelectTrigger>
    <SelectContent>
      {files.map((f) => (
        <SelectItem key={f.path} value={f.path}>{f.path}</SelectItem>
      ))}
    </SelectContent>
  </Select>
</div>
```

Use existing `Select` primitive already in the project (`@/components/ui/select`). Match variable names already in the file.

- [ ] **Step 4: Touch targets**

Locate action buttons (Save, Run, etc.). Add `min-h-10` to each. If existing classes use `Button size="sm"`, wrap or change to `size="default"` on mobile via `className`:

```tsx
<Button className="min-h-10 md:size-sm">Save</Button>
```

If size is a prop and not overridable per-breakpoint, skip this tweak — don't break existing API.

- [ ] **Step 5: Run existing test**

Run: `cd frontend && npx vitest run src/pages/__tests__/ScriptEdit.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ScriptEdit.tsx
git commit -m "feat(ui): ScriptEdit collapse file picker on mobile"
```

---

### Task 10: ScriptNew + Settings — full-width forms

**Files:**
- Modify: `frontend/src/pages/ScriptNew.tsx`
- Modify: `frontend/src/pages/Settings.tsx`

- [ ] **Step 1: Read `frontend/src/pages/ScriptNew.tsx`**

- [ ] **Step 2: Apply `w-full` and stack action row on mobile**

For each `<Input>` / `<Textarea>` / `<Select>`, add `className="w-full"` (extend, don't replace).

For the submit/actions row:

```tsx
<div className="flex w-full flex-col-reverse gap-2 md:w-auto md:flex-row md:justify-end">
  {/* existing buttons */}
</div>
```

- [ ] **Step 3: Read `frontend/src/pages/Settings.tsx`**

- [ ] **Step 4: Same `w-full` treatment**

Inputs go `w-full`. If Settings uses a grid (`grid grid-cols-...`), keep desktop layout but allow it to reflow:

```tsx
<div className="grid w-full gap-4 md:grid-cols-2">
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run src/pages/__tests__/ScriptNew.test.tsx src/pages/__tests__/Settings.test.tsx`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ScriptNew.tsx frontend/src/pages/Settings.tsx
git commit -m "feat(ui): full-width forms on mobile (ScriptNew, Settings)"
```

---

### Task 11: Full suite + manual smoke

- [ ] **Step 1: Run all frontend tests**

Run: `cd frontend && npx vitest run`
Expected: ALL PASS.

- [ ] **Step 2: Run lint + typecheck (whichever the repo uses)**

Run: `cd frontend && npx tsc --noEmit` (if a `package.json` script exists, prefer that).

- [ ] **Step 3: Manual smoke in dev**

1. Start dev server (`cd frontend && npm run dev`).
2. Open Chrome DevTools, toggle device toolbar. Pick iPhone 12 (390×844) and Pixel 5 (393×851).
3. Walk through:
   - Bottom nav appears with 4 tabs.
   - Each tab navigates and shows active state.
   - Admin Settings reachable from UserMenu dropdown on mobile.
   - Dashboard renders Recent runs as cards.
   - Runs/Schedules/Scripts lists render as cards.
   - Open a run — log area scrolls cleanly, tabs wrap onto two rows if needed.
   - Open script editor — file picker is a Select on mobile.
4. Resize to > 768px. Confirm desktop sidebar appears and bottom nav disappears. Existing layout unchanged.

- [ ] **Step 4: Final commit if any tweaks landed**

```bash
git status
# if clean, skip. Otherwise:
git add -A
git commit -m "chore(ui): mobile smoke fixes"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Mobile nav with 4 tabs | T1, T2 |
| Settings inside UserMenu on mobile | T3 |
| Dashboard card list | T4 |
| Runs list card list | T5 |
| Schedules list card list | T6 |
| Scripts list card list | T7 |
| RunView padding + tabs wrap | T8 |
| ScriptEdit collapse + touch targets | T9 |
| ScriptNew + Settings full-width forms | T10 |
| Testing | T11 |

**Placeholders:** No TBDs. `Badge` variant usage, table fields, and `RunView` classes use placeholders the implementer must reconcile against the actual file (`Read` step covers this).

**Type consistency:** `useIsMobile()` is the single source. `MobileBottomNav` consumed in T2 matches T1's export. No name drift.

**Gaps:** None — main spec requires are mapped.

---

## Execution Handoff

Pick execution mode after this plan is reviewed.
