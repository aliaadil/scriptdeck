# Runs Timestamp + Log Payload — Design

**Date:** 2026-08-16
**Status:** Draft (pending review)
**Branch:** `feat/run-logs`
**Approach:** A — Migration backfills `runs.started_at` to ISO-8601 UTC; app-side writes both timestamps explicitly; endpoints that serve log/source content return JSON `{content: text}` so the existing `api()` client can decode them.

## Goal

Two pre-existing bugs fixed in one PR:

- `runs.started_at` is stored as a naive `YYYY-MM-DD HH:MM:SS` (SQLite default `datetime('now')`) while `runs.ended_at` is written as a tz-aware ISO-8601 string (`datetime.now(UTC).isoformat()`). `RunView` parses both with `new Date(...)`, which treats the naive string as **local time** and the ISO string as **UTC**. The resulting delta is shifted by the user's UTC offset — observed as `-14399.8s` for an EDT user running a script that actually took ~196ms.
- `GET /api/runs/{id}/log` returns `PlainTextResponse(text)` while `frontend/src/api/client.ts` always parses the body as JSON. For completed runs that finished before the SSE subscriber connected, the fallback `api<string>(...)` throws and the `.catch(() => "")` swallows it, so `RunView` renders "No output." Same contract bug exists on `GET /api/scripts/{id}/source_path`.

## Non-Goals

- Lex-compare bug in `src/scriptdeck/api/stats.py:25-29` (uses `started_at >= since`). Same root cause but separate spec.
- Generalized content-type negotiation in `api/client.ts` (deferred until a third endpoint needs it).
- Reformatting `ended_at` rows from the migrated v1 install — those are already tz-aware (proven by the user's sqlite dump). No backfill needed.
- Touching any other endpoint's response shape.

## Constraints

- Single migration `012`. Additive only. CHECK constraints enable (don't fail the migration) for existing rows that the backfill cannot recognize.
- Schema changes only via `src/scriptdeck/migrations/*.sql` — never in `models.py` directly.
- One FastAPI process; SQLite only.
- Existing endpoints remain gated by the same ownership checks.
- Coverage target: maintain ≥ 60%.
- Spec location: `docs/superpowers/specs/2026-08-16-runs-timestamps-and-log-payload-design.md`.

## Data Model

### Migration `012_runs_timestamps.sql`

```sql
-- Backfill existing started_at: convert naive 'YYYY-MM-DD HH:MM:SS' to ISO-8601 UTC.
-- Rows already tz-aware are detected by the presence of 'T' or '+' or 'Z' and skipped.
UPDATE runs
SET started_at = substr(started_at, 1, 10) || 'T' || substr(started_at, 12) || '+00:00'
WHERE started_at IS NOT NULL
  AND instr(started_at, 'T') = 0
  AND instr(started_at, '+') = 0
  AND instr(started_at, 'Z')  = 0;

-- Enforce ISO-8601 going forward. App always supplies; CHECK acts as a guardrail
-- against legacy INSERTs that omit started_at and rely on the SQL default.
-- Drop the old default so callers must pass an explicit value.
-- (Re-declaration is blocked on existing installs because the default exists;
-- the migration is gated by an existence probe handled by migrations.py.)
```

The exact DDL for the default-drop step depends on migrations.py's idempotency semantics — see the implementation note under Tasks below. If `migrations.py` rejects re-declaration, leave the default in place; the CHECK constraint still pins the format.

A defensive CHECK constraint to add (best-effort; SQLite ALTER TABLE supports `ADD CONSTRAINT` only with table rebuild — when supported):

```sql
-- Pin row content. SQLite does not allow adding a CHECK to an existing
-- table without rebuild; emit the constraint inside the rebuild block.
```

If rebuild is unsupported by `migrations.py`'s current pattern, skip the CHECK and rely on app-side writes + tests. Note in plan.

## Application-Side Writes

### `src/scriptdeck/services/run_service.py`

In `create_run` (line 39-71), append `started_at` to the `.values(...)` payload using `datetime.now(UTC).isoformat()`:

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

`finalize_run` already writes `ended_at = datetime.now(UTC).isoformat()` (line 150). No change.

## API Surface

### `GET /api/runs/{run_id}/log`

Replace `PlainTextResponse` with `JSONResponse`:

```python
from fastapi.responses import JSONResponse

@router.get("/{run_id}/log")
async def log_text(...):
    ...
    text = log_path.read_text(encoding="utf-8", errors="replace")
    return JSONResponse({"content": text})
```

`Content-Type: application/json`. The 404 path on missing log file is preserved.

### `GET /api/scripts/{script_id}/source_path`

Same shape:

```python
from fastapi.responses import JSONResponse

@router.get("/{script_id}/source_path")
async def get_source(...):
    ...
    return JSONResponse({"content": path.read_text(encoding="utf-8")})
```

Confirm exact path string and consumer before landing (see Tasks).

## Frontend

### `frontend/src/pages/RunView.tsx:50-56`

```ts
const { data: fallbackText } = useQuery({
  queryKey: ["run-log", runId],
  queryFn: async () => {
    const r = await api<{ content: string }>(`/api/runs/${runId}/log`);
    return r.content;
  },
  enabled: Number.isFinite(runId) && liveText === "",
});
```

### `frontend/src/pages/ScriptEdit.tsx` (script source consumer)

Same pattern: read `r.content` instead of casting the JSON body to `string`. Confirm exact consumer code path before landing (see Tasks).

### `frontend/src/pages/Runs.tsx` and `AttemptList.tsx`

No change for the timestamps themselves — `new Date(iso_string).toLocaleString()` accepts ISO-8601. But the `duration` arithmetic in `RunView.tsx:17` (`(ended - started) / 1000`) becomes correct once both columns are tz-aware.

## Error Handling

- Migration's UPDATEs operate on already-failed-safe SQLite syntax: rows with NULL `started_at` excluded by `IS NOT NULL`; rows already tz-aware excluded.
- `create_run` always supplies `started_at`; SQL default becomes redundant but stays in place for replays.
- Endpoint change: 401/403/404 paths unchanged. JSON serialization of large logs (no upper bound) is acceptable; truncate logic deferred.

## Testing

TDD per project convention.

### New / extended tests

| File | Coverage |
|---|---|
| `tests/test_migrations.py` | Extend migration up/down for `012`. Backfill idempotent on re-run. |
| `tests/services/test_run_service.py` | `test_create_run_writes_tz_aware_started_at`: returned `started_at` parses via `datetime.fromisoformat(...)`, has `tzinfo` and `utcoffset() == timedelta(0)`. |
| `tests/api/test_runs_log_endpoint.py` | `test_log_returns_json_content`: log file seeded, response is `application/json`, body is `{"content": "..."}`. `test_log_missing_returns_404`. |
| `tests/api/test_scripts_source_endpoint.py` | `test_source_returns_json_content`: shape parity. |
| `frontend/tests/RunView.test.tsx` (extend; may be new) | mock api client returns `{content: "hello"}`; assert `<pre>` renders it. |

Coverage target ≥ 60% (project gate).

## Rollout

1. Backend (`run_service.create_run`, API endpoints, migration) lands first in one PR.
2. Frontend (`RunView`, `ScriptEdit`) lands in the same PR.
3. Manual smoke: trigger new run, verify duration positive, verify log renders, verify script source page renders source.
4. Old rows display correctly thanks to backfill.

## Open Questions

- Does `ScriptEdit.tsx` actively consume `/api/scripts/{id}/source_path`? Verify in `Tasks`. If not, the JSON wrapper change for the scripts endpoint can be a follow-up PR (still keep the change cohesive to avoid a second text/plain trap).
- SQLite ALTER TABLE for the CHECK constraint: confirm in `migrations.py` whether rebuild is supported. If not, skip CHECK and pin format via tests instead.
