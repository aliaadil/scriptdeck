# Schedules + Runs + Log Retention — Design

**Date:** 2026-08-16
**Status:** Draft (pending review)
**Branch:** `feat/schedules-runs`
**Approach:** A — Lean on what exists. Wrap `croniter`; chain retries via existing `runs.retry_group`; piggyback retention GC on the scheduler tick.

## Goal

Users can schedule scripts to run on a cron cadence expressed three ways (quick start preset, friendly day/time picker, raw cron), skip specific dates, run in their own timezone, retry on failure with exponential backoff, see every run and its log entries in the UI, and have log files automatically cleaned up after 7 days.

## Non-Goals

- Queue-on-overlap and parallel-overlap policies (UI ships dimmed; only `skip` is wired in this spec).
- Cross-user shared schedules (one user, one script, one schedule).
- Alerting / webhook on failure (separate feature; `audit_log` table exists for it later).
- Workflow DAGs (multi-script pipelines). One schedule runs one script.
- Multi-host distributed scheduling. Single-process asyncio tick.
- Log search / full-text indexing. Log viewer streams the file; no index.
- Audit log retention GC (config exists, GC job deferred; only log-file retention ships here).
- Migrating existing logs from old `storage/logs/<run_id>.log` layout — they are read-only artifacts at this point.

## Constraints

- Single FastAPI process owns the event loop, scheduler tick, retry pickup, and GC. No second scheduler, no Celery, no Redis.
- SQLite only (`sqlite+aiosqlite`). All new columns and indexes must be additive.
- Schedule cron math must respect per-schedule timezone (UTC + IANA via stdlib `zoneinfo`).
- Retry attempts must remain visible in the run history (not collapsed into one row).
- Log files are the source of truth for run output; runs rows reference them by `id`. Run rows are not deleted by retention.

## UI Form (locked in via mockup v5)

Single page, two sections.

**Section 1 — When.** Segmented control toggle between *Quick start* (preset grid: Every 15 min, Hourly, Daily @ 9:00, Weekdays @ 17:00, Mondays @ 08:00, First of month) and *Custom* (frequency dropdown + day chips + time input). Selecting a preset fills Custom; editing Custom does not flip back. Footer shows compiled cron + tz.

**Section 2 — Exceptions.** Skip dates via popover calendar (multi-select, red highlight on selected); timezone dropdown defaulted to user profile.

Advanced (raw cron expression, retry controls, overlap policy) lives behind a tiny gear icon at the section title. Hidden by default. Off the main path. Cron expression in Advanced overrides the friendly form.

## Data Model

### Migration `011_schedules_runs_v2.sql` (additive)

```sql
ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC';
ALTER TABLE schedules ADD COLUMN timezone TEXT;
ALTER TABLE schedules ADD COLUMN blackout_dates TEXT;          -- JSON list of 'YYYY-MM-DD'
ALTER TABLE schedules ADD COLUMN include_days TEXT;            -- JSON list of 0..6 (Mon=0)
ALTER TABLE schedules ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'skip';
ALTER TABLE schedules ADD COLUMN queue_max INTEGER NOT NULL DEFAULT 10;
ALTER TABLE schedules ADD COLUMN queue_dropped INTEGER NOT NULL DEFAULT 0;

-- runs already has retry_group (unused). Add the rest:
ALTER TABLE runs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN parent_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE runs ADD COLUMN next_attempt_at DATETIME;
ALTER TABLE runs ADD COLUMN skip_reason TEXT;                  -- 'overlap' | 'queue_full' | 'blackout' | 'day_filter'

-- Widen runs.status enum to include 'skipped' and 'pending_retry'.
-- Existing CHECK constraint must be replaced (SQLite rebuild pattern).

CREATE INDEX idx_runs_next_attempt ON runs(next_attempt_at) WHERE status = 'pending_retry';
CREATE INDEX idx_runs_parent ON runs(parent_run_id);
CREATE INDEX idx_runs_group ON runs(retry_group);
```

Default behavior preserved: existing rows get `attempt=0`, `parent_run_id=NULL`, `overlap_policy='skip'`. No backfill required.

### Status enum

`runs.status ∈ {'running', 'success', 'failure', 'error', 'cancelled', 'skipped', 'pending_retry'}`

| Status | Meaning |
|---|---|
| `running` | Subprocess active |
| `success` | Exit 0, terminal |
| `failure` | Exit ≠ 0, terminal (after retries exhausted) |
| `error` | Runner error (couldn't spawn, lock fail), terminal |
| `cancelled` | User-initiated stop, terminal |
| `skipped` | Tick fired but overlap/blackout/queue_full — terminal, no subprocess ran |
| `pending` | Queued (overlap_policy=`queue`); waiting for current `running` run on same script to finish — non-terminal |
| `pending_retry` | Failed, waiting for `next_attempt_at` to fire — non-terminal |

## Schedule Computation Engine

New pure function in `src/scriptdeck/services/schedule_service.py`:

```python
def compute_next_run(
    *,
    cron_expr: str,
    tz: zoneinfo.ZoneInfo,
    blackout_dates: list[str] | None,
    include_days: list[int] | None,
    after: datetime,         # naive UTC, inclusive lower bound
) -> datetime: ...           # naive UTC
```

Algorithm:

1. Convert `after` from UTC into `tz`, then build a `croniter(cron_expr, after_local)`.
2. Iterate `next()` until a candidate `c` passes all filters (loop bounded to 7 days; raises `ComputeError` if not).
3. Apply `include_days` filter (if set): if `c.weekday()` not in set, advance one minute via a fresh `croniter` start at `c` and retry.
4. Apply `blackout_dates` filter: if `c.date().isoformat()` ∈ set, advance and retry.
5. Convert `c` back to UTC and return as naive datetime.

Used by:

- Tick loop (`scheduler/tick.py::tick`) when advancing cursor.
- `GET /api/schedules/{id}/next-runs` preview endpoint.
- Schedule form preview (frontend calls the endpoint, not local cron math).

Existing `croniter`-only path is replaced; no direct croniter calls remain outside `compute_next_run`.

## Tick Loop

`scheduler/tick.py::tick` runs every `SCRIPTDECK_SCHEDULER_INTERVAL` seconds (default 5s). On each tick:

1. **Due-schedule query.** `SELECT … FROM schedules WHERE enabled=1 AND next_run_at <= now` joined with `scripts` (existing `idx_schedules_due`). For each due schedule:
   1. Compute `next_run_at = compute_next_run(...)` for the cursor advance (always — even if skipped — keeps the schedule moving).
   2. Check overlap: `SELECT 1 FROM runs WHERE script_id=? AND status='running' LIMIT 1`.
      - If overlap and `overlap_policy='skip'`: INSERT run row with `status='skipped'`, `skip_reason='overlap'`, no dispatch.
      - If overlap and `overlap_policy='queue'`: count pending (`status='pending'`) runs for this schedule. If `<queue_max`: INSERT run row with `status='pending'`, no dispatch yet (queue worker picks up when current `running` finishes). Else: INSERT `status='skipped'`, `skip_reason='queue_full'`, increment `schedules.queue_dropped`.
      - If overlap and `overlap_policy='parallel'`: proceed to dispatch (note: violates `runner_concurrency` semaphore if set; documented limitation in this spec).
      - If no overlap: INSERT run row with `status='running'`, dispatch.
   3. UPDATE `schedules.next_run_at = computed`.
2. **Due-retry query.** `SELECT … FROM runs WHERE status='pending_retry' AND next_attempt_at <= now`. For each: UPDATE `status='running'`, dispatch.
3. **Pending-queue drain.** If any `status='pending'` run exists for a script whose current `running` run has just finished (handled in `_execute_and_finalize`): promote oldest pending to `running`, dispatch.
4. **Retention GC.** If `now - last_gc_at > SCRIPTDECK_GC_INTERVAL_SECONDS` (default 3600): call `retention.gc_logs(days=SCRIPTDECK_LOG_RETENTION_DAYS)`; update `last_gc_at`.

Tick body must remain transactional at the SQL level but non-blocking at the asyncio level (existing pattern preserved).

## Retry State Machine

`_execute_and_finalize` in `runner/executor.py` runs after subprocess exit. New branch:

```
status = determine(exit_code)
if status == 'failure' and schedule.retry_max > run.attempt:
    run.status = 'pending_retry'
    run.next_attempt_at = now + timedelta(seconds=schedule.retry_backoff * (2 ** run.attempt))
    # 1st retry: backoff * 1; 2nd: backoff * 2; 3rd: backoff * 4
elif status == 'failure':
    run.status = 'failure'   # exhausted
else:
    run.status = status       # success / error / cancelled
```

`retry_group` is a ULID generated when the parent run row is inserted. All chained attempts share it. First attempt: `attempt=0`, `parent_run_id=NULL`, `retry_group=GROUP_ID`. Retries: `attempt=1..N`, `parent_run_id=parent.id`, `retry_group=GROUP_ID`.

UI: when a run has `attempt > 0`, the run detail page shows "Attempt 2 of 3" badge + a collapsible list of sibling attempts ordered by `attempt`.

## Retention GC

New module `src/scriptdeck/services/retention.py`:

```python
def gc_logs(*, retention_days: int) -> GcResult: ...
```

Walks `storage/users/<uid>/logs/*.log` (and legacy `storage/logs/*.log`), removes files whose `mtime` is older than `now() - timedelta(days=retention_days)`. Returns `{deleted: int, errors: list[Path]}`. Idempotent. Synchronous; safe to call inside the tick coroutine (small file counts in self-host scenarios; documented limitation).

Settings (new in `config.py`):

- `log_retention_days: int = 7`
- `gc_interval_seconds: int = 3600`

Run rows are **not** touched. The 7-day GC removes log files only. Users see run rows indefinitely in history; clicking a row older than retention shows the log view as empty with a banner *"Log file cleaned up after retention period."*

## API Surface

### New endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/schedule-presets` | List of `{id, label, cron}` for frontend rendering |
| GET | `/api/schedules/{id}/next-runs?limit=5` | Preview using `compute_next_run` |
| PATCH | `/api/users/me` | Update `timezone` (and other profile fields) |
| GET | `/api/runs?group=<retry_group>` | Fetch attempt chain for a run |

### Extended

- `POST /api/scripts/{id}/schedules` and `PUT /api/schedules/{id}` payloads gain: `timezone`, `blackout_dates`, `include_days`, `overlap_policy`, `queue_max`, `retry_max`, `retry_backoff`. Existing fields preserved.
- `GET /api/schedules/{id}` response includes `next_runs: list[datetime]` (top 5) and `queue_dropped: int`.
- Validation: `blackout_dates` is `list[str]` of `YYYY-MM-DD`; `include_days` is `list[int]` subset of `[0..6]`; `overlap_policy ∈ {'skip','queue','parallel'}`; `queue_max ∈ [1..100]`.

All endpoints remain gated by `require_script_owner` (existing helper in `api/deps.py`).

## UI Components

- `frontend/src/components/ScheduleForm.tsx` (new) — replaces existing edit form. Radix `Popover` + `react-day-picker` for the calendar; native `<input type="time">` for time; `Select` for timezone.
- `frontend/src/components/schedules/PresetGrid.tsx` (new)
- `frontend/src/components/schedules/TogglePill.tsx` (new)
- `frontend/src/components/runs/AttemptList.tsx` (new) — collapsible list of sibling attempts
- `frontend/src/components/users/TimezoneSelect.tsx` (new)

Existing components reused: `StatusBadge`, `AppShell`, `Sidebar`.

## Configuration

New env vars (prefix `SCRIPTDECK_`):

| Var | Default | Purpose |
|---|---|---|
| `SCRIPTDECK_LOG_RETENTION_DAYS` | `7` | Days before log files are deleted |
| `SCRIPTDECK_GC_INTERVAL_SECONDS` | `3600` | How often the tick loop runs GC |

`.env.example` updated.

## Testing

TDD per project convention. New tests:

| File | Coverage |
|---|---|
| `tests/test_schedule_compute.py` | tz, include_days, blackouts, DST boundaries (America/New_York spring-forward), Feb 29, day-of-month 31 skipping short months, malformed cron → ComputeError |
| `tests/test_scheduler_tick.py` | due-row pickup, overlap=skip/queue/parallel, queue overflow + `queue_dropped` bump, retry pickup at `next_attempt_at` |
| `tests/test_retry_state.py` | retry_max=0 → no retry; retry_max>attempt → chains; backoff math (`base * 2^attempt`); exhausted → terminal `failure`; `retry_group` shared across attempts |
| `tests/test_retention.py` | deletes old logs, leaves recent, idempotent, run rows untouched, handles missing dir |
| `tests/test_schedule_api.py` | `/schedule-presets` shape, `/next-runs` correctness, payload validation rejects bad `blackout_dates`/`include_days`/`overlap_policy` |
| `tests/test_user_timezone.py` | `PATCH /users/me` round-trips tz; defaults to UTC for new users |
| Migration: extend `tests/test_migrations.py` with up/down for `011_schedules_runs_v2.sql` |

Coverage target: maintain ≥ 60% (current gate).

## Rollout

1. Merge migration `011` first; ship behind feature flags `SCRIPTDECK_FEATURE_SCHEDULES_V2=true` (gates new UI + engine paths). Old paths untouched.
2. Frontend ships new `ScheduleForm` behind same flag.
3. Enable flag in dev. Smoke-test quick-start presets, custom picker, skip dates, timezone preview, retry on a failing script.
4. Enable retention GC in dev. Wait one GC interval. Verify old logs deleted.
5. Flip flag for production. Watch `schedules.queue_dropped` and run success rate for one week.
6. Remove flag (always-on) once stable.

## Open Questions (none blocking)

- Should `audit_log` retention GC also ship in this PR? **Defer** — separate, low-risk change.
- Queue-worker promotion: when the running run finishes, should the pending run fire immediately or wait one tick? **Immediate** — promote inside `_execute_and_finalize`.
- DST gaps: a schedule set to "2:30 AM daily" in `America/New_York` on the spring-forward day has no such time. `croniter` returns the next valid instant; document this in the UI tooltip.
