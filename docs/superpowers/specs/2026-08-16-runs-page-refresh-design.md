# Runs Page Refresh — Design

**Date:** 2026-08-16
**Status:** Draft (pending review)
**Branch:** `feat/run-logs`
**Approach:** A — Status + schedule filters, sticky "Currently running" section, paginated history, live tick for in-flight durations. Click row navigates to existing `/runs/:id` `RunView` for full logs.

## Goal

Users opening `/runs` see, at a glance, what is *currently running*, how long each run has been in flight, recent history for any schedule (or all schedules), and can click into any run to see its live or recorded logs.

## Non-Goals

- URL-driven filter state (deep-linking). Defer to next iteration.
- New schedule detail page (`/schedules/:id`). Deferred — global Runs page owns this UX for now.
- Server-push (SSE / WebSocket) on the list page. Poll-based for simplicity and parity with the rest of the dashboard.
- Retry / Rerun actions from the list. Surface only in `RunView`.
- Cross-user runs. Same ownership scoping as today: non-admins see only their own scripts' runs.

## Constraints

- Existing routes and components are preserved. No new routes.
- `RunView` (`frontend/src/pages/RunView.tsx`) already handles live + recorded logs and cancel; the list page navigates to it.
- Pagination stays server-side so the list scales beyond ~100 runs.
- Ownership scoping (`require_script_owner`) for any new filter must match existing `script_id` / `group` paths.
- SQLite only — no schema changes required.

## API Surface

### `GET /api/runs` — new query params

| Param | Type | Default | Purpose |
|---|---|---|---|
| `schedule_id` | int | None | Filter runs whose `schedule_id` matches. Owner-check resolves via joined schedule+script. |
| `offset` | int | 0 | Number of rows to skip. Used by pagination. Clamped to `[0, 10000]`. |
| `limit` | int | 50 | Already exists; list page requests 20. |

Existing params preserved: `script_id`, `status`, `since`, `group`, `limit`.

**Ownership when `schedule_id` is set:**

1. Resolve schedule row → read `script_id`.
2. Call `require_script_owner(s, script_id, user)`. Non-admin without access → 403.
3. Apply `schedule_id` filter, otherwise no extra scoping (admin sees all; non-admin still filtered to own scripts when `script_id` absent, as today).

**Ordering:** unchanged — `id desc` unless `group` is set. Pagination pairs with `offset + limit`.

**No new endpoint.** Frontend issues two parallel queries against the same endpoint:
- One for the **running section** (`?status=running&schedule_id=<id or absent>&limit=100`).
- One for the **history table** (`?...&status=<...>&schedule_id=<id or absent>&offset=<(page-1)*20>&limit=20`).

## Frontend

### Files touched

- `frontend/src/pages/Runs.tsx` — full rewrite (filters + sticky section + paginated table + tick timer + cancel).
- `frontend/src/components/runs/RunningDuration.tsx` *(new)* — pure component, takes `started_at` ISO string, ticks every 1s, renders `Xs` / `Xm Ys` / `Xh Ym` / `Xd Yh`.
- `frontend/src/api/runs.ts` — no signature change; URL composition lives in `Runs.tsx`.
- `frontend/src/api/schedules.ts` — already exposes `listSchedules()`; reused for the schedule dropdown.

### Layout

```
+---------------------------------------------------------------+
| Runs                                                          |
| [Schedule ▾] [Status ▾]                          page 1/4  ◀ ▶ |
+---------------------------------------------------------------+
| Currently running (3)                            [auto-refresh]|
| ┌──────────────────────────────────────────────────────────┐   |
| │ Run   Script  Status  Started          Duration   Exit   │   |
| │ 8a3..  hello   running 14:02:11         00:42     — [×] │   |
| │ ...                                                       │   |
| └──────────────────────────────────────────────────────────┘   |
+---------------------------------------------------------------+
| History                                                       |
| ┌──────────────────────────────────────────────────────────┐   |
| │ Run   Script   Status    Started   Duration   Exit Sched │   |
| │ 7b1..  hello    success   14:01:11  00:58      0    #3  │   |
| │ ...                                                       │   |
| └──────────────────────────────────────────────────────────┘   |
+---------------------------------------------------------------+
```

### Filters

- **Schedule `<Select>`.** Populated from `GET /api/schedules`. Default item `All schedules`. Labels: `#<id> · <cron expr>` (e.g. `#3 · */1 * * * *`).
- **Status `<Select>`.** `all`, `running`, `success`, `failed` (kept as alias for `failure`), `cancelled`, `error`, `skipped`. Sorted `all → running → success → failure → cancelled → error → skipped`.
- Changing either invalidates both queries and resets `page` to 1.

### Currently running section

- Visible iff at least one returned run in the running query.
- Polled every 2s while running count > 0 via `useQuery({ refetchInterval: (q) => q.state.data ? 2000 : false })`.
- Pauses when `document.visibilityState !== 'visible'`.
- Each row mirrors the history table schema plus an inline `Cancel` icon button (hidden for `viewer`).
- Click row → `nav('/runs/' + id)`.
- Running rows live < 60s after mount use 2s polling; thereafter fall back to 5s to limit background traffic.

### History table

- Columns: Run (`#id-prefix`), Script, StatusBadge, Started, Duration, Exit, Schedule (`#id`, link to `/schedules`).
- Duration column: server returns `ended_at - started_at` when terminal; for `running` rows use `<RunningDuration started_at={...} />`.
- Pagination controls reuse `frontend/src/components/ui/pagination.tsx`. Defaults 20 rows/page. Page resets to 1 when filters change.
- Polled every 5s (no status filter requirement). Pauses while tab hidden.

### Cancel action

- Inline icon button only for `running` rows, hidden when `user.role === 'viewer'`.
- Calls `cancelRun(runId)` (existing in `frontend/src/api/runs.ts`).
- On 2xx: invalidate both queries. On 404: toast `"Already finished"`, still invalidate. On other errors: toast server message.

### Empty states

- No schedules dropdown: fetch has zero entries → "Create a schedule on the Schedules page" hint with link.
- No running + no history under current filter: "No runs match these filters."

## Configuration

None.

## Error Handling

| Case | Behavior |
|---|---|
| 401/403 fetching runs | Existing global toast handler |
| 404 on cancel | Toast "Run already finished" + invalidate |
| Network blip on poll | TanStack Query retries with exponential backoff (default) |
| `started_at` parse fail | Duration renders `—`, row still clickable |
| SSE stream errors | Not handled here — list is poll-based |

## Testing

TDD per project convention. New / extended tests:

| File | Coverage |
|---|---|
| `src/scriptdeck/api/tests/test_runs_schedule_filter.py` | `schedule_id` filter scoping (admin sees all, owner sees theirs, others 403); pagination `offset`+`limit` returns correct slice. |
| `frontend/tests/Runs.test.tsx` *(new)* | Filter changes reset page; running section appears/disappears; running row cancel invalidates both queries; pagination bounds clamp; live tick updates by ≥1s after 2s advance. Use vitest + testing-library. |
| `frontend/tests/components/RunningDuration.test.tsx` *(new)* | Renders `Xs` / `Xm Ys` / `Xh Ym` / `Xd Yh`; advances on tick; cleans up interval on unmount. |

Coverage target: maintain ≥ 60% (current gate).

## Rollout

1. Land backend param additions first. Run targeted pytest. No migration.
2. Land frontend `RunningDuration` + `Runs.tsx` rewrite in same PR.
3. Manual smoke test: open `/runs` with a 1-minute schedule; confirm sticky section ticks; click through to `RunView`; cancel a running row from both pages; flip schedule filter and confirm scope.
4. PR link: `feat/run-logs`.

## Open Questions

- Should the `Failed` status item map to both `failure` and `error` server-side for clarity, or expose them as two distinct dropdown items? **Decision:** keep two items, since the run-history table already shows the actual label via `StatusBadge`. Alias text is fine for callers but server payload is the source of truth.
- Should page size be user-configurable? **Defer.** 20 fixed.
