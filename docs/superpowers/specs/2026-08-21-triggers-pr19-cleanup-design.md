# Triggers PR #19 — UI Cleanup Design

Date: 2026-08-21
Status: Draft
Branch: `feat/triggers-per-script-triggers-multi-schedule`
Related PR: <https://github.com/aliaadil/scriptdeck/pull/19>

## Context

PR #19 introduces per-script triggers (multi-schedule + webhook) and the
`KINDLING_PARAM` env. While using the feature, four rough edges showed up
that this design addresses:

1. The global **Schedules** tab/page coexists with the new per-script
   triggers. It is fine for now; we are not removing it.
2. The **Scripts** table row is only navigable via the name link — clicking
   anywhere else on the row does nothing.
3. On the script-edit page, the **Config** and **Logs** tab content sits
   visibly far below the tab buttons. The cumulative padding is
   noticeable.
4. The **Logs** tab only shows logs for the most recent run started from
   this page. Past runs (trigger-fired or earlier manual runs) are not
   reachable from here.

This spec covers the four cleanups. No backend changes. No migration.

## Goals

- Make the Scripts table behave like a navigation affordance.
- Remove the visual gap above Config / Logs content.
- Let users see logs of any past run for a script from the Logs tab.
- Leave the global Schedules tab intact.

## Non-Goals

- Removing or deprecating the Schedules page.
- Refactoring the script-edit page beyond the affected tabs.
- Changing how runs are listed on the Runs page.
- Adding pagination or filtering to the Logs tab runs list.

## Design

### 1. Clickable Scripts table rows (desktop)

File: `frontend/src/pages/Scripts.tsx`

Replace the current `<TableRow>` markup so the whole row navigates to
`/kindling/scripts/{id}`:

- Wrap each row's existing cells in a click handler that calls
  `nav(/kindling/scripts/${s.id})`.
- Add `cursor-pointer` to the `<TableRow>` className so the affordance
  is visible.
- The Run, Edit, and Delete buttons must remain functional. Each calls
  `e.stopPropagation()` before its existing handler so the row-level
  navigation does not fire.

Mobile card list (`isMobile` branch) already wraps the entire row in a
`<Link>` — no change.

### 2. Config / Logs top gap

File: `frontend/src/pages/ScriptEdit.tsx`

Three layered paddings stack above the form / log card:

- `<TabsList className="mx-4 mt-2 self-start">` — 8px top margin.
- `<TabsContent className="overflow-auto p-4">` — 16px all-around
  padding plus the shadcn default `mt-2` on TabsContent.
- `<CardContent className="space-y-4 pt-6">` — 24px top padding.

Combined: ~56px before the first form field. Collapse to a single source
of padding:

- Drop `mt-2` from `<TabsList>` (line 328).
- Drop `pt-6` from `<CardContent>` on Config (line 386) and on Logs
  (line 438).
- Keep `p-4` on `<TabsContent>`.

The Editor tab uses different padding (`mt-2 flex min-h-0 flex-1`) and
is unaffected.

### 3. Logs tab — recent runs list

File: `frontend/src/pages/ScriptEdit.tsx`

The Logs tab currently tracks only one run in `currentRunId` state,
seeded when the user clicks the page-level Run button. Extend it to
show a "Recent runs" panel above the log viewer.

Behavior:

- On Logs tab open (and whenever the script changes), query
  `GET /runs?script_id={id}&limit=20`. Existing API.
- Render a compact list inside its own card: status badge, started_at,
  exit_code, and a small "via schedule" tag when `schedule_id` is
  non-null. (The runs API does not currently expose webhook/manual
  trigger kind on `RunOut`, so we only surface schedule-fired runs.)
- Clicking a row sets `currentRunId` to that run id. The existing
  log-fetch + status-poll effects already key off `currentRunId`, so
  the log viewer reloads automatically.
- A still-running row continues streaming via the existing run-status
  poll + log fallback effect. No SSE work needed for this spec.
- After a freshly-started run finishes, the recent-runs list refreshes
  so the new run shows up at the top.
- Keep current behavior: clicking the header "Run" button still sets
  `currentRunId` to the new run, switches to Logs tab, and (now) the
  new run appears in the list once it completes.

No backend change. `GET /runs` already supports `script_id`, `limit`,
and ownership filtering.

## Components Touched

- `frontend/src/pages/Scripts.tsx` — clickable rows.
- `frontend/src/pages/ScriptEdit.tsx` — gap fix on Config/Logs, recent
  runs panel on Logs.

## Testing

Unit / component tests already cover Scripts and ScriptEdit. Add or
update tests for:

- `Scripts.test.tsx` (or extend an existing one): clicking a non-button
  cell navigates; clicking Run/Edit/Delete does not navigate.
- `ScriptEdit.test.tsx` (or extend): Logs tab renders the recent runs
  panel and selecting a row updates the log viewer.

Run `npm run lint` and `npm test` in `frontend/` before pushing.

## Risks

- Row-level navigation may surprise users who try to select text in a
  cell. Mitigation: keep `user-select: text` allowed (no override).
- Long-running scripts whose logs are large will re-fetch the entire
  log when a row is clicked. Existing behavior already does this on
  Run; not a regression.
- TabsList margin drop is visually subtle but uniform across tabs; we
  apply the same fix to all four tabs implicitly since they share the
  TabsList.
