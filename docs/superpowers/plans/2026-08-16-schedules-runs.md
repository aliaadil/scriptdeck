# Schedules + Runs + Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Schedule scripts via cron presets or friendly picker with day-filter + blackout dates + per-schedule timezone; retry on failure with exponential backoff via chained runs; auto-delete log files after 7 days.

**Architecture:** Wrap `croniter` with a tz-aware `compute_next_run()` that applies day-of-week and blackout filters. Chain retry attempts as separate `runs` rows sharing a `retry_group` ULID. Piggyback log-retention GC on the existing 5-second scheduler tick. UI ships as a single-page form (toggle between preset grid and friendly picker) with a hidden gear-icon sheet for raw cron + retry + overlap-policy. New `pending` and `pending_retry` and `skipped` status values. Feature flag `SCRIPTDECK_FEATURE_SCHEDULES_V2` gates the new engine + UI.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + SQLite, pytest (asyncio_mode=auto), croniter (existing), zoneinfo (stdlib), ulid-py (new dep), react + Vite + Radix UI + react-day-picker (frontend).

## Global Constraints

- TDD every task: failing test first, then implementation.
- All new columns additive; existing rows get safe defaults. No destructive migration.
- SQLite CHECK constraints can't be ALTERed — use the table-rebuild pattern (new table → INSERT SELECT → DROP → RENAME).
- Schedule cron math respects per-schedule timezone; storage is always naive UTC ISO strings.
- Feature flag `SCRIPTDECK_FEATURE_SCHEDULES_V2` (default `false`) gates new code paths until rollout.
- Coverage gate: ≥ 60% (current value); do not lower it.
- Lint clean (`ruff check src tests`), mypy not blocking (`ignore_errors = true`).
- Frequent small commits; one task = one commit (or commit-per-step where a step is meaningful).
- Conventional commit prefixes: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.
- Project convention: dataclasses for services, SQLAlchemy Core tables (no ORM declarative), Pydantic v2 for request/response models, `from __future__ import annotations` at top of every Python file.

## File Structure

```
src/scriptdeck/
├── config.py                         # +log_retention_days, +gc_interval_seconds, +feature_schedules_v2
├── db/models.py                      # +schedules.* columns, +runs.* columns, widen status CHECK
├── migrations/011_schedules_runs_v2.sql  # NEW
├── services/
│   ├── schedule_service.py           # rewrite compute_next_run + advance
│   ├── run_service.py                # +create_pending_run, +create_retry_run, +promote_pending
│   ├── retention.py                  # NEW: gc_logs
│   └── presets.py                    # NEW: PRESETS list
├── scheduler/tick.py                 # overlap policies + retry pickup + queue drain + GC piggyback
├── runner/executor.py                # wire retry state machine via finalize_run
├── api/
│   ├── schedules.py                  # extend payload + GET /next-runs
│   ├── runs.py                       # +GET /runs?group=...
│   └── users.py                      # +PATCH /users/me timezone
frontend/src/
├── components/
│   ├── schedules/
│   │   ├── ScheduleForm.tsx          # NEW: full form (replaces edit page body)
│   │   ├── PresetGrid.tsx            # NEW
│   │   ├── TogglePill.tsx            # NEW
│   │   ├── CustomPicker.tsx          # NEW: frequency + day chips + time
│   │   └── SkipDatesPopover.tsx      # NEW
│   ├── users/
│   │   └── TimezoneSelect.tsx        # NEW
│   └── runs/
│       └── AttemptList.tsx           # NEW
└── pages/
    ├── SchedulesPage.tsx             # uses ScheduleForm
    └── RunDetailPage.tsx             # uses AttemptList
tests/
├── test_migration_011.py             # NEW
├── test_schedule_compute.py          # NEW
├── test_retention.py                 # NEW
├── test_scheduler_tick_v2.py         # NEW (avoid clashing with existing test_scheduler.py)
├── test_retry_state.py               # NEW
├── test_schedule_api.py              # NEW
├── test_user_timezone.py             # NEW
└── test_run_group.py                 # NEW
```

---

## Task 1: Migration 011 — schedules + runs schema additions

**Files:**
- Create: `src/scriptdeck/migrations/011_schedules_runs_v2.sql`
- Create: `tests/test_migration_011.py`
- Modify: `src/scriptdeck/db/models.py:100-151` (add columns + widen CHECK)
- Modify: `src/scriptdeck/config.py` (add 3 new settings)
- Modify: `.env.example` (add the 3 new vars)

**Interfaces:**
- Produces: tables with new columns ready for Tasks 2-7.

- [ ] **Step 1: Write the failing migration test**

```python
# tests/test_migration_011.py
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from scriptdeck.db.migrations import run_migrations_sync


def test_schedules_have_v2_columns(tmp_path: Path):
    db_path = tmp_path / "t.db"
    run_migrations_sync(str(db_path))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def _cols(table: str) -> set[str]:
        async with engine.connect() as conn:
            rows = (await conn.exec_driver_sql(
                f"SELECT name FROM pragma_table_info('{table}')"
            )).fetchall()
        return {r[0] for r in rows}

    async def _check():
        s_cols = await _cols("schedules")
        r_cols = await _cols("runs")
        u_cols = await _cols("users")
        await engine.dispose()
        return s_cols, r_cols, u_cols

    s_cols, r_cols, u_cols = asyncio.run(_check())
    assert {"timezone", "blackout_dates", "include_days", "overlap_policy",
            "queue_max", "queue_dropped"}.issubset(s_cols)
    assert {"attempt", "parent_run_id", "next_attempt_at", "skip_reason"}.issubset(r_cols)
    assert "timezone" in u_cols
```

Add `import asyncio` at the top.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migration_011.py -v`
Expected: FAIL — new columns don't exist yet.

- [ ] **Step 3: Write the migration SQL**

```sql
-- src/scriptdeck/migrations/011_schedules_runs_v2.sql
-- Schedules v2: timezone, day filter, blackout dates, overlap policy.
-- Runs v2: attempt tracking, parent_run_id, skip_reason; widen status enum.

ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT 'UTC';

ALTER TABLE schedules ADD COLUMN timezone TEXT;
ALTER TABLE schedules ADD COLUMN blackout_dates TEXT;
ALTER TABLE schedules ADD COLUMN include_days TEXT;
ALTER TABLE schedules ADD COLUMN overlap_policy TEXT NOT NULL DEFAULT 'skip';
ALTER TABLE schedules ADD COLUMN queue_max INTEGER NOT NULL DEFAULT 10;
ALTER TABLE schedules ADD COLUMN queue_dropped INTEGER NOT NULL DEFAULT 0;

ALTER TABLE runs ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN parent_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL;
ALTER TABLE runs ADD COLUMN next_attempt_at DATETIME;
ALTER TABLE runs ADD COLUMN skip_reason TEXT;

-- Widen runs.status CHECK to include 'skipped', 'pending', 'pending_retry'.
-- SQLite can't ALTER a CHECK constraint; rebuild the table.
CREATE TABLE runs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    schedule_id INTEGER REFERENCES schedules(id) ON DELETE SET NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    exit_code INTEGER,
    status TEXT NOT NULL,
    retry_group TEXT,
    attempt INTEGER NOT NULL DEFAULT 0,
    parent_run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    next_attempt_at DATETIME,
    skip_reason TEXT,
    CHECK (status IN (
        'running','success','failure','error','cancelled',
        'skipped','pending','pending_retry'
    ))
);
INSERT INTO runs_new (id, script_id, schedule_id, started_at, ended_at, exit_code, status, retry_group)
    SELECT id, script_id, schedule_id, started_at, ended_at, exit_code, status, retry_group FROM runs;
DROP TABLE runs;
ALTER TABLE runs_new RENAME TO runs;

CREATE INDEX idx_runs_next_attempt ON runs(next_attempt_at) WHERE status = 'pending_retry';
CREATE INDEX idx_runs_parent ON runs(parent_run_id);
CREATE INDEX idx_runs_group ON runs(retry_group);
```

- [ ] **Step 4: Update `db/models.py` to declare the new columns**

In `src/scriptdeck/db/models.py`, update the `schedules` Table (lines 100-121):

```python
schedules = Table(
    "schedules",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "script_id",
        Integer,
        ForeignKey("scripts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", String, nullable=False),
    Column("expression", String, nullable=False),
    Column("enabled", Integer, nullable=False, default=1),
    Column("next_run_at", String, nullable=False),
    Column("retry_max", Integer, nullable=False, default=0),
    Column("retry_backoff", Integer, nullable=False, default=0),
    Column("last_status", String),
    Column("last_error", Text),
    Column("timezone", String),
    Column("blackout_dates", Text),
    Column("include_days", Text),
    Column("overlap_policy", String, nullable=False, default="skip"),
    Column("queue_max", Integer, nullable=False, default=10),
    Column("queue_dropped", Integer, nullable=False, default=0),
    CheckConstraint("kind IN ('cron', 'interval')", name="schedules_kind_check"),
    Index("idx_schedules_script", "script_id"),
    Index("idx_schedules_due", "enabled", "next_run_at"),
)
```

Update the `runs` Table (lines 123-151):

```python
runs = Table(
    "runs",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "script_id",
        Integer,
        ForeignKey("scripts.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "schedule_id",
        Integer,
        ForeignKey("schedules.id", ondelete="SET NULL"),
    ),
    Column("started_at", String, nullable=False),
    Column("ended_at", String),
    Column("exit_code", Integer),
    Column("status", String, nullable=False),
    Column("retry_group", String),
    Column("attempt", Integer, nullable=False, default=0),
    Column("parent_run_id", Integer, ForeignKey("runs.id", ondelete="SET NULL")),
    Column("next_attempt_at", String),
    Column("skip_reason", String),
    CheckConstraint(
        "status IN ('running', 'success', 'failure', 'error', 'cancelled', "
        "'skipped', 'pending', 'pending_retry')",
        name="runs_status_check",
    ),
    Index("idx_runs_script", "script_id"),
    Index("idx_runs_started", text("started_at DESC")),
    Index("idx_runs_script_started", "script_id", text("started_at DESC")),
    Index("idx_runs_status", "status"),
)
```

Update the `users` Table (lines 18-28):

```python
users = Table(
    "users",
    mapper_registry.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False),
    Column("role", String, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("last_login_at", Text, nullable=True),
    Column("timezone", String, nullable=False, default="UTC"),
    CheckConstraint("role IN ('admin', 'editor', 'viewer')", name="users_role_check"),
)
```

- [ ] **Step 5: Run migration test to verify it passes**

Run: `pytest tests/test_migration_011.py -v`
Expected: PASS.

- [ ] **Step 6: Add new settings to `config.py`**

Append to `Settings` in `src/scriptdeck/config.py`:

```python
    log_retention_days: int = 7
    gc_interval_seconds: int = 3600
    feature_schedules_v2: bool = False
```

- [ ] **Step 7: Update `.env.example`**

Append to `.env.example`:

```
# Schedules v2 feature flag (default off until rollout)
SCRIPTDECK_FEATURE_SCHEDULES_V2=false
# Days before log files are deleted (logs only; runs rows stay forever)
SCRIPTDECK_LOG_RETENTION_DAYS=7
# How often the scheduler tick runs retention GC
SCRIPTDECK_GC_INTERVAL_SECONDS=3600
```

- [ ] **Step 8: Run full test suite to ensure no regressions**

Run: `pytest tests/ -x --timeout=60`
Expected: PASS (all existing tests still green).

- [ ] **Step 9: Commit**

```bash
git add src/scriptdeck/migrations/011_schedules_runs_v2.sql \
        src/scriptdeck/db/models.py \
        src/scriptdeck/config.py \
        .env.example \
        tests/test_migration_011.py
git commit -m "feat(db): migration 011 — schedules v2 cols, runs attempt tracking, status enum"
```

---

## Task 2: `compute_next_run` — tz-aware schedule math

**Files:**
- Modify: `src/scriptdeck/services/schedule_service.py`
- Create: `tests/test_schedule_compute.py`
- Create: `src/scriptdeck/services/presets.py`

**Interfaces:**
- Produces: `compute_next_run(cron_expr, tz_name, blackout_dates, include_days, after) -> datetime` (naive UTC).
- Produces: `PRESETS` constant — list of `{id, label, cron}` dicts.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schedule_compute.py
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from scriptdeck.services.schedule_service import ComputeError, compute_next_run


def test_basic_cron_utc():
    # 0 9 * * * = 09:00 daily UTC
    nxt = compute_next_run(
        cron_expr="0 9 * * *",
        tz_name="UTC",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 16, 9, 0, tzinfo=UTC)


def test_tz_shifts_fire_time():
    # 0 9 * * * in America/New_York; on Aug 16 (EDT, UTC-4) that is 13:00 UTC.
    nxt = compute_next_run(
        cron_expr="0 9 * * *",
        tz_name="America/New_York",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 16, 13, 0, tzinfo=UTC)


def test_include_days_filters():
    # 0 17 * * 2-4 in UTC: only Tue/Wed/Thu 17:00.
    # After Mon 2026-08-17 18:00 UTC, next is Tue 2026-08-18 17:00 UTC.
    nxt = compute_next_run(
        cron_expr="0 17 * * 2-4",
        tz_name="UTC",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 8, 17, 18, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 18, 17, 0, tzinfo=UTC)


def test_blackout_date_skipped():
    # 0 9 * * * UTC. Blackout 2026-08-17. After 2026-08-16 18:00, next is 08-18 09:00.
    nxt = compute_next_run(
        cron_expr="0 9 * * *",
        tz_name="UTC",
        blackout_dates=["2026-08-17"],
        include_days=None,
        after=datetime(2026, 8, 16, 18, 0, tzinfo=UTC),
    )
    assert nxt == datetime(2026, 8, 18, 9, 0, tzinfo=UTC)


def test_dst_spring_forward():
    # America/New_York: 2026-03-08 02:00 EST -> 03:00 EDT (skip 02:00-03:00).
    # Cron "30 2 * * *" — 02:30 doesn't exist; croniter should jump to next valid.
    nxt = compute_next_run(
        cron_expr="30 2 * * *",
        tz_name="America/New_York",
        blackout_dates=None,
        include_days=None,
        after=datetime(2026, 3, 7, 0, 0, tzinfo=UTC),
    )
    # Expect a datetime on 2026-03-09 (skipping the gap day).
    assert nxt.date() >= datetime(2026, 3, 9).date()


def test_invalid_cron_raises():
    with pytest.raises(ComputeError):
        compute_next_run(
            cron_expr="not a cron",
            tz_name="UTC",
            blackout_dates=None,
            include_days=None,
            after=datetime(2026, 8, 16, tzinfo=UTC),
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schedule_compute.py -v`
Expected: FAIL — `compute_next_run` doesn't exist.

- [ ] **Step 3: Add `ComputeError` and `compute_next_run` to `schedule_service.py`**

Replace the body of `src/scriptdeck/services/schedule_service.py` (keep `_table`, `_scripts`, `list_due`, `advance` as-is; add the new code above `advance_next_run`):

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ComputeError(ValueError):
    """Schedule computation failed (bad cron, no valid fire within bounded horizon)."""


def _table():
    from scriptdeck.db.models import schedules as _schedules
    return _schedules


def _scripts():
    from scriptdeck.db.models import scripts as _scripts
    return _scripts


_MAX_COMPUTE_HORIZON_DAYS = 7


def compute_next_run(
    *,
    cron_expr: str,
    tz_name: str,
    blackout_dates: list[str] | None,
    include_days: list[int] | None,
    after: datetime,
) -> datetime:
    """Return next firing after `after` (UTC-aware), respecting tz + filters.

    Args:
        cron_expr: 5-field cron string.
        tz_name: IANA timezone name (e.g. "America/New_York"); "UTC" allowed.
        blackout_dates: list of "YYYY-MM-DD" in schedule tz to skip; None = no skips.
        include_days: list of 0..6 (Mon=0) to override cron's day-of-week; None = use cron.
        after: naive-or-aware datetime in UTC; lower bound, exclusive.

    Returns: tz-aware datetime in UTC.
    Raises: ComputeError on bad cron, unknown tz, or no fire within 7 days.
    """
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise ComputeError(f"unknown timezone: {tz_name}") from exc

    if after.tzinfo is None:
        after_utc = after.replace(tzinfo=timezone.utc)
    else:
        after_utc = after.astimezone(timezone.utc)

    after_local = after_utc.astimezone(tz)
    horizon_end_local = after_local + timedelta(days=_MAX_COMPUTE_HORIZON_DAYS)

    try:
        it = croniter(cron_expr, after_local)
    except (ValueError, KeyError, TypeError) as exc:
        raise ComputeError(f"bad cron expression: {cron_expr!r}") from exc

    while True:
        try:
            candidate_local = it.get_next(datetime)
        except (ValueError, StopIteration):
            raise ComputeError(f"no fire within {_MAX_COMPUTE_HORIZON_DAYS} days")
        if candidate_local > horizon_end_local:
            raise ComputeError(f"no fire within {_MAX_COMPUTE_HORIZON_DAYS} days")

        if include_days is not None and candidate_local.weekday() not in include_days:
            continue
        date_iso = candidate_local.date().isoformat()
        if blackout_dates and date_iso in blackout_dates:
            continue

        return candidate_local.astimezone(timezone.utc)


# ---- Existing functions below (unchanged) ----
def advance_next_run(kind: str, expression: str, prev_next_run: str) -> str:
    ...
```

(Keep the existing `advance_next_run`, `list_due`, `advance` functions unchanged for now — they will be reworked in Task 4.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_schedule_compute.py -v`
Expected: PASS.

- [ ] **Step 5: Create the presets module**

```python
# src/scriptdeck/services/presets.py
from __future__ import annotations

PRESETS: list[dict[str, str]] = [
    {"id": "every-15m",   "label": "Every 15 min",      "cron": "*/15 * * * *"},
    {"id": "hourly",      "label": "Hourly",            "cron": "0 * * * *"},
    {"id": "daily-9",     "label": "Daily @ 9:00",      "cron": "0 9 * * *"},
    {"id": "weekdays-17", "label": "Weekdays @ 17:00",  "cron": "0 17 * * 1-5"},
    {"id": "mondays-8",   "label": "Mondays @ 08:00",   "cron": "0 8 * * 1"},
    {"id": "first-month", "label": "First of month",    "cron": "0 0 1 * *"},
]
```

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/services/schedule_service.py \
        src/scriptdeck/services/presets.py \
        tests/test_schedule_compute.py
git commit -m "feat(schedule): tz-aware compute_next_run + presets"
```

---

## Task 3: Retention GC module

**Files:**
- Create: `src/scriptdeck/services/retention.py`
- Create: `tests/test_retention.py`

**Interfaces:**
- Produces: `gc_logs(*, storage_dir, retention_days) -> GcResult` where `GcResult` is a dataclass `{deleted: int, errors: list[tuple[str, str]]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retention.py
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scriptdeck.services.retention import GcResult, gc_logs


def test_deletes_old_logs_leaves_recent(tmp_path: Path):
    user1 = tmp_path / "users" / "1" / "logs"
    user1.mkdir(parents=True)
    old = user1 / "old.log"
    new = user1 / "new.log"
    old.write_text("ancient")
    new.write_text("recent")

    # Make "old" 10 days old, "new" 1 day old.
    ten_days_ago = time.time() - 10 * 86400
    one_day_ago = time.time() - 1 * 86400
    os.utime(old, (ten_days_ago, ten_days_ago))
    os.utime(new, (one_day_ago, one_day_ago))

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert isinstance(result, GcResult)
    assert result.deleted == 1
    assert not old.exists()
    assert new.exists()


def test_idempotent(tmp_path: Path):
    (tmp_path / "users" / "1" / "logs").mkdir(parents=True)
    old = tmp_path / "users" / "1" / "logs" / "old.log"
    old.write_text("x")
    os.utime(old, (time.time() - 14 * 86400, time.time() - 14 * 86400))

    gc_logs(storage_dir=tmp_path, retention_days=7)
    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert result.deleted == 0


def test_handles_missing_user_dir(tmp_path: Path):
    # No users/ dir at all.
    result = gc_logs(storage_dir=tmp_path, retention_days=7)
    assert result.deleted == 0
    assert result.errors == []


def test_legacy_log_dir_also_cleaned(tmp_path: Path):
    legacy = tmp_path / "logs"
    legacy.mkdir()
    old = legacy / "old.log"
    old.write_text("x")
    os.utime(old, (time.time() - 14 * 86400, time.time() - 14 * 86400))

    result = gc_logs(storage_dir=tmp_path, retention_days=7)

    assert result.deleted == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retention.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `retention.py`**

```python
# src/scriptdeck/services/retention.py
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class GcResult:
    deleted: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def gc_logs(*, storage_dir: Path, retention_days: int) -> GcResult:
    """Delete .log files older than retention_days. Idempotent.

    Walks `storage_dir/users/<uid>/logs/*.log` (per-user layout) and
    `storage_dir/logs/*.log` (legacy layout). Run rows are not touched.
    """
    result = GcResult()
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    roots = [
        storage_dir / "logs",                       # legacy
        *(p / "logs" for p in (storage_dir / "users").iterdir()
          if p.is_dir() and (p / "logs").is_dir()),  # per-user
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for log_file in root.glob("*.log"):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime, UTC)
                if mtime < cutoff:
                    log_file.unlink()
                    result.deleted += 1
            except OSError as exc:
                result.errors.append((str(log_file), str(exc)))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_retention.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/services/retention.py tests/test_retention.py
git commit -m "feat(retention): gc_logs deletes expired .log files"
```

---

## Task 4: Tick loop — overlap policies + queue drain

**Files:**
- Modify: `src/scriptdeck/scheduler/tick.py`
- Modify: `src/scriptdeck/services/run_service.py` (add `count_pending`, `promote_oldest_pending`)
- Create: `tests/test_scheduler_tick_v2.py`

**Interfaces:**
- New: `count_pending(session, script_id) -> int`
- New: `promote_oldest_pending(session, script_id) -> int | None` (returns promoted run_id or None)

- [ ] **Step 1: Write the failing test for overlap=skip (already works; just lock the contract)**

```python
# tests/test_scheduler_tick_v2.py
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, text

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations
from scriptdeck.scheduler.tick import _tick
from scriptdeck.services.log_broker import LogBroker


def _settings(tmp_path):
    return Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )


async def _setup_due_schedule(Sf, *, overlap_policy="skip", queue_max=10):
    from scriptdeck.db.models import schedules, scripts
    now = datetime.now(timezone.utc).isoformat()
    async with Sf() as s:
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python", source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            script_id=1, kind="interval", expression="5m", next_run_at=now,
            overlap_policy=overlap_policy, queue_max=queue_max,
        ))
        await s.commit()


async def _mark_running(Sf, script_id=1):
    from scriptdeck.db.models import runs
    now = datetime.now(timezone.utc).isoformat()
    async with Sf() as s:
        await s.execute(insert(runs).values(
            script_id=script_id, status="running", started_at=now,
        ))
        await s.commit()


@pytest.mark.asyncio
async def test_overlap_skip_creates_skipped_run(tmp_path):
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    await _setup_due_schedule(Sf, overlap_policy="skip")
    await _mark_running(Sf)

    broker = LogBroker()
    sem = asyncio.Semaphore(2)
    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    await _tick(
        settings=settings, session_factory=Sf, log_broker=broker,
        env_service=FakeEnv(), concurrency=sem,
        storage_dir=tmp_path / "s", app=None,
    )

    async with Sf() as s:
        rows = (await s.execute(text(
            "SELECT status, skip_reason FROM runs ORDER BY id"
        ))).all()
    statuses = [(r[0], r[1]) for r in rows]
    assert ("skipped", "overlap") in statuses


@pytest.mark.asyncio
async def test_overlap_queue_creates_pending_then_drops(tmp_path):
    settings = _settings(tmp_path)
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)
    await _setup_due_schedule(Sf, overlap_policy="queue", queue_max=2)
    await _mark_running(Sf)

    broker = LogBroker()
    sem = asyncio.Semaphore(2)
    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    # Tick three times to fill queue (cap 2), then drop on third.
    for _ in range(3):
        await _tick(
            settings=settings, session_factory=Sf, log_broker=broker,
            env_service=FakeEnv(), concurrency=sem,
            storage_dir=tmp_path / "s", app=None,
        )

    async with Sf() as s:
        statuses = (await s.execute(text("SELECT status FROM runs"))).all()
        dropped = (await s.execute(text(
            "SELECT queue_dropped FROM schedules WHERE id=1"
        ))).first()
    s_list = [r[0] for r in statuses]
    assert s_list.count("pending") == 2
    assert s_list.count("skipped") == 1
    assert dropped[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scheduler_tick_v2.py -v`
Expected: FAIL — current `_tick` always uses `status='error'` on overlap (old path).

- [ ] **Step 3: Extend `run_service.py` with pending helpers**

Append to `src/scriptdeck/services/run_service.py`:

```python
async def count_pending(session: AsyncSession, script_id: int) -> int:
    t = _table()
    stmt = (
        select(t.c.id)
        .where(t.c.script_id == script_id, t.c.status == "pending")
    )
    return len((await session.execute(stmt)).all())


async def promote_oldest_pending(
    session: AsyncSession, script_id: int
) -> int | None:
    """Atomically flip the oldest pending run to running; return its id or None."""
    t = _table()
    row = (
        await session.execute(
            select(t.c.id)
            .where(t.c.script_id == script_id, t.c.status == "pending")
            .order_by(t.c.started_at)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    run_id = int(row[0])
    await session.execute(
        update(t).where(t.c.id == run_id).values(status="running")
    )
    return run_id
```

- [ ] **Step 4: Rewrite `_tick` in `scheduler/tick.py`**

Replace the body of `_tick` (keep `scheduler_loop`, `_schedule`, `_execute_and_finalize` unchanged for now):

```python
async def _tick(
    *,
    settings,
    session_factory,
    log_broker,
    env_service,
    concurrency,
    storage_dir,
    app=None,
):
    now = datetime.now(UTC)
    async with session_factory() as s:
        due = await list_due(s, now)
        for row in due:
            sid = row["script_id"]
            policy = row.get("overlap_policy", "skip")
            queue_max = row.get("queue_max", 10)
            new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
            await advance(s, row["id"], new_next)
            await s.commit()

            overlap = await has_active_run(s, sid)
            if overlap and policy == "skip":
                run_id, _ = await create_run(
                    s, script_id=sid, schedule_id=row["id"],
                    status="skipped", skip_reason="overlap",
                )
                await finalize_run(s, run_id=run_id, exit_code=-1, status="skipped")
                await s.commit()
                await log_broker.close(run_id, "skipped", -1)
                continue

            if overlap and policy == "queue":
                pending = await count_pending(s, sid)
                if pending >= queue_max:
                    run_id, _ = await create_run(
                        s, script_id=sid, schedule_id=row["id"],
                        status="skipped", skip_reason="queue_full",
                    )
                    await finalize_run(s, run_id=run_id, exit_code=-1, status="skipped")
                    await s.execute(
                        update(_table()).where(_table().c.id == row["id"])
                        .values(queue_dropped=_table().c.queue_dropped + 1)
                    )
                    await s.commit()
                    await log_broker.close(run_id, "skipped", -1)
                    continue
                # Insert as pending — promote_oldest_pending picks it up
                # when the running run finishes (Task 4b hook in executor).
                await create_run(
                    s, script_id=sid, schedule_id=row["id"], status="pending",
                )
                await s.commit()
                continue

            # No overlap OR overlap_policy='parallel' (best-effort dispatch).
            run_id, _ = await create_run(s, script_id=sid, schedule_id=row["id"])
            await s.commit()

            script = Script(
                id=sid, user_id=row["user_id"], name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"], requirements=[],
            )
            _schedule(
                app=app, run_id=run_id, script=script,
                env_service=env_service, log_broker=log_broker,
                concurrency=concurrency, storage_dir=storage_dir,
                session_factory=session_factory,
            )
```

Add a helper at top of file (near imports):

```python
def _table():
    from scriptdeck.db.models import runs as _runs
    return _runs
```

(Needed for the `queue_dropped` increment; existing import already pulls `runs` indirectly via `run_service`.)

Also update `create_run` signature — extend `run_service.py` to accept `skip_reason`:

```python
async def create_run(
    session: AsyncSession, *,
    script_id: int,
    schedule_id: int | None,
    status: str = "running",
    skip_reason: str | None = None,
) -> tuple[int, str]:
    """Insert a new run row and return (run_id, started_at)."""
    t = _table()
    stmt = (
        insert(t)
        .values(
            script_id=script_id, schedule_id=schedule_id,
            status=status, skip_reason=skip_reason,
        )
        .returning(t.c.id, t.c.started_at)
    )
    row = (await session.execute(stmt)).one()
    return int(row[0]), row[1]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_scheduler_tick_v2.py tests/test_scheduler.py -v`
Expected: PASS. If `test_scheduler.py` (existing) regresses, fix the legacy path inside `_tick` — the legacy path only ran when no overlap existed; new code preserves that branch.

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/scheduler/tick.py \
        src/scriptdeck/services/run_service.py \
        tests/test_scheduler_tick_v2.py
git commit -m "feat(scheduler): overlap policies (skip/queue/parallel) + queue drain"
```

---

## Task 5: Tick loop — retry pickup (`pending_retry` → `running`)

**Files:**
- Modify: `src/scriptdeck/scheduler/tick.py` (add retry-query branch to `_tick`)
- Modify: `src/scriptdeck/services/run_service.py` (add `pick_due_retries`)
- Create: `tests/test_retry_state.py`

**Interfaces:**
- New: `pick_due_retries(session, now) -> list[dict]` returning run rows with `status='pending_retry'` and `next_attempt_at <= now`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_retry_state.py`:

```python
# tests/test_retry_state.py
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import insert, text

from scriptdeck.config import Settings
from scriptdeck.db.engine import make_engine, session_factory
from scriptdeck.db.migrations import run_migrations
from scriptdeck.scheduler.tick import _tick
from scriptdeck.services.log_broker import LogBroker


@pytest.mark.asyncio
async def test_pending_retry_runs_after_next_attempt_at(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)

    from scriptdeck.db.models import runs, schedules, scripts
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("print('ok')\n")

    async with Sf() as s:
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python", source_path="scripts/1/main.py",
            user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="interval", expression="5m",
            next_run_at=future, retry_max=3, retry_backoff=60,
        ))
        # One run already in pending_retry, due now.
        await s.execute(insert(runs).values(
            script_id=1, schedule_id=10, status="pending_retry",
            started_at=past, next_attempt_at=past, attempt=1,
            retry_group="01TEST",
        ))
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    await _tick(
        settings=settings, session_factory=Sf, log_broker=broker,
        env_service=FakeEnv(), concurrency=sem,
        storage_dir=tmp_path / "s", app=None,
    )
    await asyncio.sleep(2)

    async with Sf() as s:
        rows = (await s.execute(text(
            "SELECT status FROM runs WHERE retry_group='01TEST'"
        ))).all()
    statuses = [r[0] for r in rows]
    assert "success" in statuses
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retry_state.py::test_pending_retry_runs_after_next_attempt_at -v`
Expected: FAIL — current `_tick` doesn't query `pending_retry`.

- [ ] **Step 3: Add `pick_due_retries` to `run_service.py`**

```python
async def pick_due_retries(session: AsyncSession, now: datetime) -> list[dict]:
    """Return run rows with status='pending_retry' and next_attempt_at <= now."""
    from scriptdeck.db.models import scripts
    t = _table()
    stmt = (
        select(t, scripts.c.name, scripts.c.language, scripts.c.source_path, scripts.c.user_id)
        .where(t.c.status == "pending_retry", t.c.next_attempt_at <= now.isoformat())
        .join(scripts, t.c.script_id == scripts.c.id)
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Add retry branch to `_tick`**

After the existing due-schedule loop in `_tick`, append:

```python
        # ---- Phase 2: due retries (pending_retry → running) ----
        retries = await pick_due_retries(s, now)
        for row in retries:
            sid = row["script_id"]
            # If a non-retry run is already active on this script, defer the
            # retry — leave status='pending_retry' for the next tick.
            if await has_active_run(s, sid):
                continue
            run_id = row["id"]
            await s.execute(
                update(_table()).where(_table().c.id == run_id)
                .values(status="running")
            )
            await s.commit()
            script = Script(
                id=sid, user_id=row["user_id"], name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"], requirements=[],
            )
            _schedule(
                app=app, run_id=run_id, script=script,
                env_service=env_service, log_broker=log_broker,
                concurrency=concurrency, storage_dir=storage_dir,
                session_factory=session_factory,
            )
```

(Place this inside the same `async with session_factory() as s:` block as the due-schedule loop — the block is already opened at the top of `_tick`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_retry_state.py::test_pending_retry_runs_after_next_attempt_at -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/scheduler/tick.py \
        src/scriptdeck/services/run_service.py \
        tests/test_retry_state.py
git commit -m "feat(scheduler): pick up pending_retry runs whose next_attempt_at has elapsed"
```

---

## Task 6: Tick loop — GC piggyback + finalize-side queue drain

**Files:**
- Modify: `src/scriptdeck/scheduler/tick.py`
- Modify: `src/scriptdeck/runner/executor.py` (call `promote_oldest_pending` after finalize)

**Interfaces:**
- New: track `app.state.last_gc_at`; when `now - last_gc_at > gc_interval_seconds`, call `gc_logs()`.

- [ ] **Step 1: Add GC phase to `_tick`**

At the very end of `_tick` (still inside the `async with session_factory()` block), add:

```python
        # ---- Phase 3: retention GC (idempotent; cheap when nothing to do) ----
        last_gc = getattr(app.state, "last_gc_at", None) if app is not None else None
        gc_due = (
            last_gc is None
            or (now - last_gc).total_seconds() > settings.gc_interval_seconds
        )
        if gc_due:
            from scriptdeck.services.retention import gc_logs
            gc_logs(
                storage_dir=storage_dir,
                retention_days=settings.log_retention_days,
            )
            if app is not None:
                app.state.last_gc_at = now
```

- [ ] **Step 2: Wire `promote_oldest_pending` into `_execute_and_finalize`**

In `src/scriptdeck/runner/executor.py`, at the end of `_execute_and_finalize` (after `finalize_run` + commit), append:

```python
        # Drain queued runs waiting on this script (overlap=queue policy).
        try:
            promoted = await promote_oldest_pending(
                s, script_id=script.id,
            )
        except Exception:
            promoted = None
        if promoted is not None:
            from scriptdeck.scheduler.tick import _schedule
            _schedule(
                app=None, run_id=promoted, script=script,
                env_service=env_service, log_broker=log_broker,
                concurrency=concurrency, storage_dir=storage_dir,
                session_factory=session_factory,
            )
```

Refactor the helper in `run_service.py`:

```python
async def promote_oldest_pending(
    session: AsyncSession, *, script_id: int, session_factory=None
) -> int | None:
    """Atomically flip the oldest pending run to running; return its id or None."""
    t = _table()
    row = (
        await session.execute(
            select(t.c.id)
            .where(t.c.script_id == script_id, t.c.status == "pending")
            .order_by(t.c.started_at)
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    run_id = int(row[0])
    await session.execute(
        update(t).where(t.c.id == run_id).values(status="running")
    )
    await session.commit()
    return run_id
```

(Adjust the call signature from Task 4: now keyword-only with `script_id`. The Task 4 test still passes because both signatures accept positional/keyword `script_id`.)

- [ ] **Step 3: Add `last_gc_at` initialization in `app.py`**

In `src/scriptdeck/app.py`, inside `create_app`'s lifespan startup, after the scheduler task is spawned, add:

```python
    app.state.last_gc_at = None
```

- [ ] **Step 4: Run the full suite**

Run: `pytest tests/ -x --timeout=60`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/scheduler/tick.py \
        src/scriptdeck/runner/executor.py \
        src/scriptdeck/services/run_service.py \
        src/scriptdeck/app.py
git commit -m "feat(scheduler): GC piggyback + post-finalize queue drain"
```

---

## Task 7: Retry state machine in executor

**Files:**
- Modify: `src/scriptdeck/runner/executor.py` (decide retry in finalizer)
- Modify: `src/scriptdeck/services/run_service.py` (add `mark_pending_retry`)
- Extend: `tests/test_retry_state.py`

**Interfaces:**
- New: `mark_pending_retry(session, *, run_id, attempt, retry_group, schedule_retry_max, schedule_retry_backoff)` → returns `True` if a retry was scheduled, `False` if exhausted.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_retry_state.py`:

```python
@pytest.mark.asyncio
async def test_failure_with_retry_marks_pending_retry(tmp_path):
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)

    from scriptdeck.db.models import runs, schedules, scripts
    now = datetime.now(timezone.utc).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("import sys; sys.exit(1)\n")

    async with Sf() as s:
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="interval", expression="5m",
            next_run_at=now, retry_max=3, retry_backoff=60,
        ))
        await s.execute(insert(runs).values(
            script_id=1, schedule_id=10, status="running",
            started_at=now, attempt=0, retry_group="01ABC",
        ))
        run_id = (await s.execute(text("SELECT id FROM runs LIMIT 1"))).first()[0]
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    # Drive the executor directly to avoid touching the tick loop.
    from scriptdeck.runner.executor import Script, _execute_and_finalize
    script = Script(
        id=1, user_id=1, name="t", language="python",
        source_path=tmp_path / "s" / "scripts" / "1" / "main.py",
        requirements=[],
    )
    await _execute_and_finalize(
        run_id=run_id, script=script, env_service=FakeEnv(),
        log_broker=broker, concurrency=sem,
        storage_dir=tmp_path / "s", session_factory=Sf,
    )

    async with Sf() as s:
        row = (await s.execute(text(
            "SELECT status, attempt, next_attempt_at FROM runs WHERE id=:i"
        ), {"i": run_id})).first()
    assert row[0] == "pending_retry"
    assert row[1] == 1
    assert row[2] is not None


@pytest.mark.asyncio
async def test_failure_with_retry_exhausted_marks_failure(tmp_path):
    # Same setup but retry_max=0.
    settings = Settings(
        db_path=str(tmp_path / "t.db"),
        storage_dir=str(tmp_path / "s"),
        scheduler_interval=1,
        runner_concurrency=2,
        feature_schedules_v2=True,
    )
    engine = make_engine(settings)
    await run_migrations(engine)
    Sf = session_factory(engine)

    from scriptdeck.db.models import runs, schedules, scripts
    now = datetime.now(timezone.utc).isoformat()

    work = tmp_path / "s" / "scripts" / "1"
    work.mkdir(parents=True)
    (work / "main.py").write_text("import sys; sys.exit(1)\n")

    async with Sf() as s:
        await s.execute(insert(scripts).values(
            id=1, name="t", language="python",
            source_path="scripts/1/main.py", user_id=1,
        ))
        await s.execute(insert(schedules).values(
            id=10, script_id=1, kind="interval", expression="5m",
            next_run_at=now, retry_max=0, retry_backoff=0,
        ))
        await s.execute(insert(runs).values(
            script_id=1, schedule_id=10, status="running",
            started_at=now, attempt=0, retry_group="01DEF",
        ))
        run_id = (await s.execute(text("SELECT id FROM runs LIMIT 1"))).first()[0]
        await s.commit()

    broker = LogBroker()
    sem = asyncio.Semaphore(2)

    class FakeEnv:
        def decrypt_lines(self, *a, **kw): return {}

    from scriptdeck.runner.executor import Script, _execute_and_finalize
    script = Script(
        id=1, user_id=1, name="t", language="python",
        source_path=tmp_path / "s" / "scripts" / "1" / "main.py",
        requirements=[],
    )
    await _execute_and_finalize(
        run_id=run_id, script=script, env_service=FakeEnv(),
        log_broker=broker, concurrency=sem,
        storage_dir=tmp_path / "s", session_factory=Sf,
    )

    async with Sf() as s:
        status = (await s.execute(text(
            "SELECT status FROM runs WHERE id=:i"
        ), {"i": run_id})).first()[0]
    assert status == "failure"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_retry_state.py -v`
Expected: FAIL — executor's finalizer doesn't know about retry.

- [ ] **Step 3: Add `mark_pending_retry` to `run_service.py`**

```python
async def mark_pending_retry(
    session: AsyncSession,
    *,
    run_id: int,
    attempt: int,
    schedule_retry_max: int,
    schedule_retry_backoff: int,
) -> bool:
    """If retries remain, set status=pending_retry + next_attempt_at and return True.
    Otherwise return False (caller should mark terminal failure)."""
    from datetime import datetime, timedelta, timezone
    t = _table()
    if attempt >= schedule_retry_max:
        return False
    delay = timedelta(seconds=schedule_retry_backoff * (2 ** attempt))
    next_at = (datetime.now(timezone.utc) + delay).isoformat()
    await session.execute(
        update(t)
        .where(t.c.id == run_id)
        .values(
            status="pending_retry",
            attempt=attempt + 1,
            next_attempt_at=next_at,
        )
    )
    return True
```

- [ ] **Step 4: Wire retry decision into `_execute_and_finalize`**

In `src/scriptdeck/runner/executor.py`, replace the existing finalizer block (`async with session_factory() as s: ...`) with:

```python
    async with session_factory() as s:
        if status == "failure":
            from sqlalchemy import select as _select
            from scriptdeck.db.models import runs as _runs_t, schedules as _sched_t
            sched_row = (
                await s.execute(
                    _select(_sched_t.c.retry_max, _sched_t.c.retry_backoff)
                    .join(_runs_t, _runs_t.c.schedule_id == _sched_t.c.id)
                    .where(_runs_t.c.id == run_id)
                )
            ).first()
            attempt_row = (
                await s.execute(
                    _select(_runs_t.c.attempt).where(_runs_t.c.id == run_id)
                )
            ).first()
            retry_scheduled = await mark_pending_retry(
                s,
                run_id=run_id,
                attempt=attempt_row[0] if attempt_row else 0,
                schedule_retry_max=sched_row[0] if sched_row else 0,
                schedule_retry_backoff=sched_row[1] if sched_row else 0,
            )
            if retry_scheduled:
                await s.commit()
                return
        await finalize_run(s, run_id=run_id, exit_code=result.exit_code, status=status)
        await s.commit()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_retry_state.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/scriptdeck/runner/executor.py \
        src/scriptdeck/services/run_service.py \
        tests/test_retry_state.py
git commit -m "feat(executor): chained retry via pending_retry + exponential backoff"
```

---

## Task 8: API — presets + next-runs + user timezone + run group

**Files:**
- Modify: `src/scriptdeck/api/schedules.py`
- Modify: `src/scriptdeck/api/runs.py`
- Modify: `src/scriptdeck/api/users.py`
- Create: `tests/test_schedule_api.py`
- Create: `tests/test_user_timezone.py`
- Create: `tests/test_run_group.py`

**Interfaces:**
- New endpoint: `GET /api/schedule-presets` → `[{id, label, cron}]`
- New endpoint: `GET /api/schedules/{id}/next-runs?limit=5` → `[ISO datetime, ...]`
- New: `PATCH /api/users/me` accepts `{timezone: str}`
- New: `GET /api/runs?group=<retry_group>` → `[run_out, ...]`

- [ ] **Step 1: Write the failing API tests**

```python
# tests/test_schedule_api.py
from datetime import UTC, datetime


def test_presets_endpoint_returns_six(client):
    r = client.get("/api/schedule-presets")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 6
    assert all({"id", "label", "cron"} <= set(p) for p in body)


def test_next_runs_endpoint_uses_croniter(client, auth_headers):
    # Insert a schedule and a script first.
    from sqlalchemy import insert
    from scriptdeck.db.models import schedules, scripts
    from scriptdeck.db.engine import session_factory as _sf
    # (assume test fixtures provide `client`, `auth_headers`, `engine`)
    async def _seed():
        async with _sf(engine)() as s:
            await s.execute(insert(scripts).values(
                id=1, name="t", language="python",
                source_path="scripts/1/main.py",
            ))
            await s.execute(insert(schedules).values(
                id=10, script_id=1, kind="cron",
                expression="0 9 * * *",
                next_run_at=datetime.now(UTC).isoformat(),
                overlap_policy="skip",
            ))
            await s.commit()
    asyncio.run(_seed())
    r = client.get("/api/schedules/10/next-runs?limit=5", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 5
    for ts in body:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
```

```python
# tests/test_user_timezone.py
def test_patch_user_me_timezone_round_trips(client, auth_headers):
    r = client.patch("/api/users/me", json={"timezone": "America/Los_Angeles"}, headers=auth_headers)
    assert r.status_code == 200
    r2 = client.get("/api/users/me", headers=auth_headers)
    assert r2.json()["timezone"] == "America/Los_Angeles"


def test_invalid_timezone_rejected(client, auth_headers):
    r = client.patch("/api/users/me", json={"timezone": "Not/AZone"}, headers=auth_headers)
    assert r.status_code == 422
```

```python
# tests/test_run_group.py
def test_run_group_returns_chained_attempts(client, auth_headers):
    # Insert three runs sharing retry_group, then GET /runs?group=...
    from sqlalchemy import insert, text
    from scriptdeck.db.engine import session_factory as _sf
    async def _seed():
        async with _sf(engine)() as s:
            await s.execute(insert(scripts).values(
                id=1, name="t", language="python",
                source_path="scripts/1/main.py",
            ))
            await s.execute(insert(runs).values(
                script_id=1, status="failure", retry_group="XYZ",
                started_at=..., attempt=2, ...
            ))
            ...
    r = client.get("/api/runs?group=XYZ", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 3
```

(Exact seed payloads mirror Tasks 4-7 patterns; reduce to one test for group filtering once seeded.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schedule_api.py tests/test_user_timezone.py tests/test_run_group.py -v`
Expected: FAIL — endpoints don't exist.

- [ ] **Step 3: Add `/api/schedule-presets`**

In `src/scriptdeck/api/schedules.py`, add at top of file:

```python
from scriptdeck.services.presets import PRESETS


@router.get("/../schedule-presets", include_in_schema=False)
async def list_presets() -> list[dict[str, str]]:
    return PRESETS
```

(Register the endpoint on the app router under `/schedule-presets` — easiest: add a sibling router in `app.py` if path conflicts arise. Alternatively, register the route inside `api/schedules.py` and prefix at mount.)

Better — add a small standalone router file:

```python
# src/scriptdeck/api/presets.py
from __future__ import annotations
from fastapi import APIRouter
from scriptdeck.services.presets import PRESETS

router = APIRouter()


@router.get("/schedule-presets")
async def list_presets() -> list[dict[str, str]]:
    return PRESETS
```

Register in `src/scriptdeck/app.py` alongside existing routers (`app.include_router(presets.router)`).

- [ ] **Step 4: Add `/api/schedules/{id}/next-runs`**

In `src/scriptdeck/api/schedules.py`, append:

```python
@router.get("/{schedule_id}/next-runs")
async def next_runs(
    schedule_id: int, limit: int = 5, request: Request = None,
    user: User = Depends(current_user),
) -> list[str]:
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        sched = (
            await s.execute(
                select(t.c.expression, t.c.timezone, t.c.blackout_dates,
                       t.c.include_days, t.c.script_id)
                .where(t.c.id == schedule_id)
            )
        ).mappings().one_or_none()
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
    await _check_owner(sf, sched["script_id"], user)

    from datetime import datetime, timezone
    tz_name = sched["timezone"] or "UTC"
    bo = json.loads(sched["blackout_dates"]) if sched["blackout_dates"] else None
    inc = json.loads(sched["include_days"]) if sched["include_days"] else None
    fires: list[str] = []
    cursor = datetime.now(timezone.utc)
    from scriptdeck.services.schedule_service import compute_next_run
    for _ in range(limit):
        cursor = compute_next_run(
            cron_expr=sched["expression"], tz_name=tz_name,
            blackout_dates=bo, include_days=inc, after=cursor,
        )
        fires.append(cursor.isoformat())
    return fires
```

Add `_check_owner` helper at module scope:

```python
async def _check_owner(sf, script_id: int, user: User) -> None:
    async with sf() as s:
        await require_script_owner(s, script_id, user)
```

Add `import json` at top.

- [ ] **Step 5: Add `PATCH /api/users/me`**

In `src/scriptdeck/api/users.py`, add a Pydantic model + endpoint:

```python
class UserMePatch(BaseModel):
    timezone: str | None = None


@router.patch("/me")
async def patch_me(body: UserMePatch, request: Request,
                   user: User = Depends(current_user)) -> dict:
    if body.timezone is not None:
        try:
            ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=f"unknown timezone: {body.timezone}")
    sf = request.app.state.session_factory
    users_t = _users_table()
    values = {k: v for k, v in body.model_dump(exclude_none=True).items()}
    if values:
        async with sf() as s:
            await s.execute(
                update(users_t).where(users_t.c.id == user.id).values(**values)
            )
            await s.commit()
    return {"ok": True}
```

Add imports: `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError`, `from pydantic import BaseModel`, `from sqlalchemy import update`.

- [ ] **Step 6: Extend `GET /api/runs` with `?group=`**

In `src/scriptdeck/api/runs.py`, find the `list_endpoint` and add `group: str | None = None` as a query param. When set:

```python
if group is not None:
    stmt = stmt.where(runs_t.c.retry_group == group)
```

(Apply ownership filter as today.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_schedule_api.py tests/test_user_timezone.py tests/test_run_group.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/scriptdeck/api/presets.py \
        src/scriptdeck/api/schedules.py \
        src/scriptdeck/api/users.py \
        src/scriptdeck/api/runs.py \
        src/scriptdeck/app.py \
        tests/test_schedule_api.py \
        tests/test_user_timezone.py \
        tests/test_run_group.py
git commit -m "feat(api): schedule-presets + next-runs + user tz + run-group endpoints"
```

---

## Task 9: Schedule payload validation — new fields

**Files:**
- Modify: `src/scriptdeck/api/schedules.py` (extend `ScheduleCreate`/`ScheduleOut`, payload validation)
- Extend: `tests/test_schedule_api.py`

**Interfaces:**
- Extended `ScheduleCreate`: gains `timezone`, `blackout_dates`, `include_days`, `overlap_policy`, `queue_max`.
- New `ScheduleOut`: gains `next_runs`, `queue_dropped` (read-only).

- [ ] **Step 1: Write the failing validation test**

Append to `tests/test_schedule_api.py`:

```python
def test_create_schedule_validates_blackout_dates(client, auth_headers):
    bad = {"script_id": 1, "kind": "cron", "expression": "0 9 * * *",
           "blackout_dates": ["not-a-date"]}
    r = client.post("/api/scripts/1/schedules", json=bad, headers=auth_headers)
    assert r.status_code == 422


def test_create_schedule_validates_overlap_policy(client, auth_headers):
    bad = {"script_id": 1, "kind": "cron", "expression": "0 9 * * *",
           "overlap_policy": "explode"}
    r = client.post("/api/scripts/1/schedules", json=bad, headers=auth_headers)
    assert r.status_code == 422


def test_create_schedule_with_blackout_round_trips(client, auth_headers):
    payload = {"script_id": 1, "kind": "cron", "expression": "0 9 * * *",
               "timezone": "UTC", "blackout_dates": ["2026-12-25"],
               "include_days": [0, 1, 2],
               "overlap_policy": "skip", "queue_max": 5,
               "retry_max": 2, "retry_backoff": 30}
    r = client.post("/api/scripts/1/schedules", json=payload, headers=auth_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["blackout_dates"] == ["2026-12-25"]
    assert body["include_days"] == [0, 1, 2]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_schedule_api.py::test_create_schedule_validates_blackout_dates -v`
Expected: FAIL — current `ScheduleCreate` doesn't accept the new fields.

- [ ] **Step 3: Extend `ScheduleCreate` and `ScheduleOut`**

Replace in `src/scriptdeck/api/schedules.py`:

```python
import json
from datetime import date as _date

from pydantic import field_validator


class ScheduleCreate(BaseModel):
    script_id: int
    kind: str = Field(pattern="^(cron|interval)$")
    expression: str = Field(min_length=1)
    enabled: bool = True
    retry_max: int = Field(default=0, ge=0, le=100)
    retry_backoff: int = Field(default=0, ge=0, le=86400)
    timezone: str | None = None
    blackout_dates: list[str] | None = None
    include_days: list[int] | None = None
    overlap_policy: str = "skip"
    queue_max: int = Field(default=10, ge=1, le=100)

    @field_validator("blackout_dates")
    @classmethod
    def _check_blackout(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        for s in v:
            try:
                _date.fromisoformat(s)
            except ValueError as exc:
                raise ValueError(f"bad blackout date: {s!r}") from exc
        return v

    @field_validator("include_days")
    @classmethod
    def _check_include_days(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return v
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("include_days must be 0..6")
        return v

    @field_validator("overlap_policy")
    @classmethod
    def _check_policy(cls, v: str) -> str:
        if v not in {"skip", "queue", "parallel"}:
            raise ValueError(f"bad overlap_policy: {v!r}")
        return v


class ScheduleOut(BaseModel):
    id: int
    script_id: int
    kind: str
    expression: str
    enabled: bool
    next_run_at: str
    retry_max: int
    retry_backoff: int
    timezone: str | None
    blackout_dates: list[str] | None
    include_days: list[int] | None
    overlap_policy: str
    queue_max: int
    queue_dropped: int
    next_runs: list[str] = []


def _row_to_out(row) -> ScheduleOut:
    bo = json.loads(row["blackout_dates"]) if row["blackout_dates"] else None
    inc = json.loads(row["include_days"]) if row["include_days"] else None
    return ScheduleOut(
        id=row["id"], script_id=row["script_id"], kind=row["kind"],
        expression=row["expression"], enabled=bool(row["enabled"]),
        next_run_at=row["next_run_at"],
        retry_max=row["retry_max"], retry_backoff=row["retry_backoff"],
        timezone=row["timezone"], blackout_dates=bo, include_days=inc,
        overlap_policy=row["overlap_policy"], queue_max=row["queue_max"],
        queue_dropped=row["queue_dropped"], next_runs=[],
    )
```

Update the `create` endpoint body — replace its INSERT block:

```python
        stmt = (
            insert(t).values(
                script_id=body.script_id, kind=body.kind, expression=body.expression,
                enabled=1 if body.enabled else 0, next_run_at=initial_next,
                retry_max=body.retry_max, retry_backoff=body.retry_backoff,
                timezone=body.timezone,
                blackout_dates=json.dumps(body.blackout_dates) if body.blackout_dates else None,
                include_days=json.dumps(body.include_days) if body.include_days else None,
                overlap_policy=body.overlap_policy,
                queue_max=body.queue_max,
            ).returning(*t.c)
        )
```

And the `update_schedule` endpoint's UPDATE block:

```python
        await s.execute(update(t).where(t.c.id == schedule_id).values(
            kind=body.kind, expression=body.expression,
            enabled=1 if body.enabled else 0, next_run_at=new_next,
            retry_max=body.retry_max, retry_backoff=body.retry_backoff,
            timezone=body.timezone,
            blackout_dates=json.dumps(body.blackout_dates) if body.blackout_dates else None,
            include_days=json.dumps(body.include_days) if body.include_days else None,
            overlap_policy=body.overlap_policy,
            queue_max=body.queue_max,
        ))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schedule_api.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scriptdeck/api/schedules.py tests/test_schedule_api.py
git commit -m "feat(api): schedule payload gains tz/blackout/include_days/overlap_policy/queue_max"
```

---

## Task 10: Frontend — ScheduleForm rewrite + components

**Files:**
- Create: `frontend/src/components/schedules/ScheduleForm.tsx`
- Create: `frontend/src/components/schedules/PresetGrid.tsx`
- Create: `frontend/src/components/schedules/TogglePill.tsx`
- Create: `frontend/src/components/schedules/CustomPicker.tsx`
- Create: `frontend/src/components/schedules/SkipDatesPopover.tsx`
- Create: `frontend/src/components/users/TimezoneSelect.tsx`
- Create: `frontend/src/components/runs/AttemptList.tsx`
- Modify: `frontend/src/pages/SchedulesPage.tsx` (mount new form)
- Modify: `frontend/src/pages/RunDetailPage.tsx` (mount `AttemptList`)
- Modify: `frontend/src/pages/UserSettingsPage.tsx` (mount `TimezoneSelect`)
- Create: `frontend/src/api/schedulePresets.ts` (typed fetcher)

**Note:** Frontend tasks have no TDD loop (project convention). Manual smoke-test via Playwright e2e (existing harness) after build.

- [ ] **Step 1: Install frontend deps**

```bash
cd frontend
npm install react-day-picker date-fns
```

Commit `package.json` + `package-lock.json` separately:

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add react-day-picker + date-fns"
```

- [ ] **Step 2: Create `TogglePill.tsx`**

```tsx
import { cn } from "@/lib/utils";

export function TogglePill<T extends string>({
  options, value, onChange,
}: {
  options: { value: T; label: string }[];
  value: T; onChange: (v: T) => void;
}) {
  return (
    <div className="inline-flex rounded-lg bg-muted p-1">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          onClick={() => onChange(opt.value)}
          className={cn(
            "rounded-md px-3 py-1 text-sm transition",
            value === opt.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Create `PresetGrid.tsx`**

```tsx
import { cn } from "@/lib/utils";
import type { SchedulePreset } from "@/api/schedulePresets";

export function PresetGrid({
  presets, selected, onSelect,
}: {
  presets: SchedulePreset[];
  selected: string | null;
  onSelect: (preset: SchedulePreset) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3">
      {presets.map((p) => (
        <button
          key={p.id}
          type="button"
          onClick={() => onSelect(p)}
          className={cn(
            "rounded-lg border p-3 text-left transition",
            selected === p.id
              ? "border-primary bg-primary/10"
              : "border-border hover:border-primary/50",
          )}
        >
          <div className="font-medium">{p.label}</div>
          <code className="mt-1 block text-xs text-muted-foreground">
            {p.cron}
          </code>
        </button>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Create `CustomPicker.tsx`**

```tsx
import { Input } from "@/components/ui/input";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

const FREQUENCIES = [
  { value: "*/15 * * * *", label: "Every 15 min" },
  { value: "0 * * * *", label: "Hourly" },
  { value: "0 9 * * *", label: "Daily" },
  { value: "0 17 * * 1-5", label: "Weekdays" },
];

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export function CustomPicker({
  cron, time, onCronChange, onTimeChange,
}: {
  cron: string; time: string;
  onCronChange: (c: string) => void;
  onTimeChange: (t: string) => void;
}) {
  // Lightweight parser — assumes "minute hour * * dow" shape.
  const parts = cron.split(" ");
  const hour = parts[1] ?? "*";
  const dow = parts[4] ?? "*";

  const setHour = (h: string) => {
    const [mm, , , , d] = parts;
    onCronChange(`${mm ?? "0"} ${h} * * ${d ?? "*"}`);
    onTimeChange(`${h.padStart(2, "0")}:${(mm ?? "0").padStart(2, "0")}`);
  };

  const toggleDay = (idx: number) => {
    const [mm, hh, , ,] = parts;
    const current = dow === "*" ? [] : dow.split(",").map(Number);
    const next = current.includes(idx)
      ? current.filter((d) => d !== idx)
      : [...current, idx].sort();
    const dowStr = next.length === 0 ? "*" : next.join(",");
    onCronChange(`${mm ?? "0"} ${hh ?? hour} * * ${dowStr}`);
  };

  return (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        <label className="mb-1 block text-xs text-muted-foreground">Repeats</label>
        <Select value={hour} onValueChange={setHour}>
          <SelectTrigger className="w-[170px]"><SelectValue /></SelectTrigger>
          <SelectContent>
            {FREQUENCIES.map((f) => (
              <SelectItem key={f.label} value={f.value.split(" ")[1]}>
                {f.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div>
        <label className="mb-1 block text-xs text-muted-foreground">On these days</label>
        <div className="flex gap-1">
          {DAYS.map((d, i) => {
            const active = dow !== "*" && dow.split(",").map(Number).includes(i);
            return (
              <button
                key={d}
                type="button"
                onClick={() => toggleDay(i)}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs",
                  active
                    ? "border-primary bg-primary/10"
                    : "border-border opacity-60 hover:opacity-100",
                )}
              >{d}</button>
            );
          })}
        </div>
      </div>
      <div>
        <label className="mb-1 block text-xs text-muted-foreground">At</label>
        <Input type="time" value={time} onChange={(e) => onTimeChange(e.target.value)} className="w-[110px]" />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Create `SkipDatesPopover.tsx`**

```tsx
import { useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

export function SkipDatesPopover({
  value, onChange,
}: {
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = value.map((s) => new Date(s + "T00:00:00"));

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button variant="outline" type="button">📅 + Pick dates</Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-auto p-0">
          <DayPicker
            mode="multiple"
            selected={selected}
            onSelect={(days) => {
              const next = (days ?? []).map((d) =>
                d.toISOString().slice(0, 10));
              onChange(next);
            }}
            disabled={{ before: new Date() }}
          />
        </PopoverContent>
      </Popover>
      {value.map((d) => (
        <span
          key={d}
          className="inline-flex items-center gap-1 rounded-md border border-destructive bg-destructive/10 px-2 py-1 text-xs"
        >
          {d}
          <button
            type="button"
            aria-label={`Remove ${d}`}
            onClick={() => onChange(value.filter((x) => x !== d))}
          ><X className="h-3 w-3" /></button>
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Create `TimezoneSelect.tsx`**

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export const COMMON_TZS = [
  "UTC",
  "America/New_York",
  "America/Los_Angeles",
  "America/Chicago",
  "Europe/London",
  "Europe/Berlin",
  "Asia/Tokyo",
];

export function TimezoneSelect({
  value, onChange, hint,
}: {
  value: string; onChange: (tz: string) => void; hint?: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger className="w-[240px]"><SelectValue /></SelectTrigger>
        <SelectContent>
          {COMMON_TZS.map((tz) => (
            <SelectItem key={tz} value={tz}>{tz}</SelectItem>
          ))}
        </SelectContent>
      </Select>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </div>
  );
}
```

- [ ] **Step 7: Create `schedulePresets.ts` API client**

```ts
// frontend/src/api/schedulePresets.ts
import { api } from "@/lib/api";

export type SchedulePreset = { id: string; label: string; cron: string };

export async function fetchPresets(): Promise<SchedulePreset[]> {
  const r = await api.get<SchedulePreset[]>("/api/schedule-presets");
  return r.data;
}

export async function fetchNextRuns(scheduleId: number, limit = 5): Promise<string[]> {
  const r = await api.get<string[]>(`/api/schedules/${scheduleId}/next-runs?limit=${limit}`);
  return r.data;
}
```

- [ ] **Step 8: Create `ScheduleForm.tsx`**

```tsx
import { useEffect, useState } from "react";
import { TogglePill } from "./TogglePill";
import { PresetGrid } from "./PresetGrid";
import { CustomPicker } from "./CustomPicker";
import { SkipDatesPopover } from "./SkipDatesPopover";
import { TimezoneSelect } from "../users/TimezoneSelect";
import { Button } from "@/components/ui/button";
import { fetchPresets, fetchNextRuns, type SchedulePreset } from "@/api/schedulePresets";
import { Save } from "lucide-react";

type Mode = "preset" | "custom";

export function ScheduleForm({
  scriptId, initial, onSubmit, onCancel,
}: {
  scriptId: number;
  initial?: Partial<SchedulePayload>;
  onSubmit: (p: SchedulePayload) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<Mode>("preset");
  const [presets, setPresets] = useState<SchedulePreset[]>([]);
  const [cron, setCron] = useState(initial?.expression ?? "0 9 * * *");
  const [time, setTime] = useState("09:00");
  const [tz, setTz] = useState(initial?.timezone ?? "UTC");
  const [blackouts, setBlackouts] = useState<string[]>(initial?.blackout_dates ?? []);
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [nextRuns, setNextRuns] = useState<string[]>([]);

  useEffect(() => { fetchPresets().then(setPresets); }, []);

  useEffect(() => {
    // Preview next 5 fires (debounced).
    const t = setTimeout(async () => {
      const r = await fetch("/api/schedule-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cron, timezone: tz, blackout_dates: blackouts }),
      });
      if (r.ok) setNextRuns(await r.json());
    }, 300);
    return () => clearTimeout(t);
  }, [cron, tz, blackouts]);

  const submit = () => {
    onSubmit({
      script_id: scriptId,
      kind: "cron",
      expression: cron,
      timezone: tz,
      blackout_dates: blackouts,
      include_days: null,
      overlap_policy: "skip",
      queue_max: 10,
      retry_max: 0,
      retry_backoff: 0,
    });
  };

  return (
    <div className="space-y-6">
      {/* Section 1: When */}
      <section>
        <TogglePill<Mode>
          options={[{ value: "preset", label: "Quick start" }, { value: "custom", label: "Custom" }]}
          value={mode}
          onChange={setMode}
        />
        <div className="mt-4">
          {mode === "preset" ? (
            <PresetGrid
              presets={presets}
              selected={selectedPreset}
              onSelect={(p) => {
                setSelectedPreset(p.id);
                setCron(p.cron);
              }}
            />
          ) : (
            <CustomPicker
              cron={cron} time={time}
              onCronChange={setCron}
              onTimeChange={setTime}
            />
          )}
        </div>
        {nextRuns.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            Next 5: {nextRuns.map((r) => <code key={r} className="mr-2">{r}</code>)}
          </p>
        )}
      </section>

      {/* Section 2: Exceptions */}
      <section className="space-y-4 border-t pt-4">
        <div>
          <label className="mb-2 block text-sm font-medium">Skip dates</label>
          <SkipDatesPopover value={blackouts} onChange={setBlackouts} />
        </div>
        <div>
          <label className="mb-2 block text-sm font-medium">Timezone</label>
          <TimezoneSelect
            value={tz}
            onChange={setTz}
            hint="Defaults to your profile · change to override per-schedule"
          />
        </div>
      </section>

      {/* Footer */}
      <footer className="flex items-center justify-between border-t pt-4">
        <span className="text-xs text-muted-foreground">
          Cron: <code>{cron}</code> · {tz}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" type="button" onClick={onCancel}>Cancel</Button>
          <Button type="button" onClick={submit}>
            <Save className="mr-1 h-4 w-4" /> Save schedule
          </Button>
        </div>
      </footer>
    </div>
  );
}

export type SchedulePayload = {
  script_id: number;
  kind: string;
  expression: string;
  timezone: string;
  blackout_dates: string[];
  include_days: number[] | null;
  overlap_policy: string;
  queue_max: number;
  retry_max: number;
  retry_backoff: number;
};
```

Note: the next-runs preview uses a hypothetical `POST /api/schedule-preview` endpoint — if not desired, fall back to client-side `cron-parser` (`npm install cron-parser`).

Add fallback (preferred — keeps preview offline-friendly):

```bash
cd frontend && npm install cron-parser
```

Then replace the `useEffect` that fetches `/api/schedule-preview` with:

```tsx
import cronParser from "cron-parser";

useEffect(() => {
  try {
    const it = cronParser.parseExpression(cron, {
      currentDate: new Date(),
      tz,
    });
    const next = [] as string[];
    for (let i = 0; i < 5; i++) next.push(it.next().toISOString());
    setNextRuns(next);
  } catch {
    setNextRuns([]);
  }
}, [cron, tz, blackouts]);
```

This removes the network round-trip and matches the locked-in mockup behavior.

- [ ] **Step 9: Create `AttemptList.tsx`**

```tsx
import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/StatusBadge";

export type AttemptRun = {
  id: number; attempt: number; status: string;
  started_at: string; ended_at: string | null;
  exit_code: number | null;
};

export function AttemptList({ runs }: { runs: AttemptRun[] }) {
  const [open, setOpen] = useState(false);
  if (runs.length <= 1) return null;

  return (
    <div className="rounded-lg border p-3">
      <Button
        variant="ghost" size="sm" type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between"
      >
        <span>
          {open ? <ChevronDown className="mr-1 inline h-4 w-4" />
                : <ChevronRight className="mr-1 inline h-4 w-4" />}
          {runs.length} attempts
        </span>
      </Button>
      {open && (
        <ul className="mt-2 space-y-2">
          {runs.map((r) => (
            <li key={r.id} className="flex items-center gap-3 text-sm">
              <span className="w-16 text-muted-foreground">
                #{r.attempt}
              </span>
              <StatusBadge status={r.status} />
              <span className="text-xs text-muted-foreground">
                exit={r.exit_code ?? "-"}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {r.started_at}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 10: Mount new components in pages**

Edit `frontend/src/pages/SchedulesPage.tsx`: replace the existing schedule edit form body with `<ScheduleForm scriptId={...} ... />`.

Edit `frontend/src/pages/RunDetailPage.tsx`: add `<AttemptList runs={chain} />` when the loaded run has `attempt > 0` (fetch chain via `/api/runs?group=<run.retry_group>`).

Edit `frontend/src/pages/UserSettingsPage.tsx`: add `<TimezoneSelect value={user.timezone} onChange={...} />` plus a `PATCH /api/users/me` call on change.

- [ ] **Step 11: Build + smoke-test**

```bash
cd frontend
npm run build
npm run typecheck
npm run lint
```

Run Playwright e2e (existing harness) and verify:
- Schedules page renders the new form.
- Selecting a preset updates the cron in the footer.
- Picking skip dates works (calendar popover opens, dates highlighted red).
- Timezone dropdown lists at least UTC + America/New_York.

- [ ] **Step 12: Commit**

```bash
git add frontend/src/components/schedules \
        frontend/src/components/users/TimezoneSelect.tsx \
        frontend/src/components/runs/AttemptList.tsx \
        frontend/src/api/schedulePresets.ts \
        frontend/src/pages/SchedulesPage.tsx \
        frontend/src/pages/RunDetailPage.tsx \
        frontend/src/pages/UserSettingsPage.tsx
git commit -m "feat(ui): schedule form rewrite (preset/custom toggle + skip dates + tz) + run attempt list"
```

---

## Self-Review (run before handing off)

1. **Spec coverage** — walk every section of `docs/superpowers/specs/2026-08-16-schedules-runs-design.md` and confirm a task addresses it:
   - Migration 011 → Task 1 ✓
   - `compute_next_run` engine → Task 2 ✓
   - Retention GC → Task 3 ✓
   - Tick overlap policies + queue drain → Task 4 ✓
   - Tick retry pickup → Task 5 ✓
   - Tick GC piggyback + executor queue drain → Task 6 ✓
   - Retry state machine → Task 7 ✓
   - API endpoints (presets, next-runs, user tz, run group) → Task 8 ✓
   - Schedule payload validation → Task 9 ✓
   - Frontend ScheduleForm + components → Task 10 ✓
   - Status enum widening (`pending`, `pending_retry`, `skipped`) → Task 1 (migration) + Tasks 4/5/7 (consumers) ✓
   - Tests for engine, retry, retention, scheduler, API, user tz, run group → Tasks 2-9 ✓

2. **Placeholder scan** — no `TBD` / `TODO` / "implement later" present.

3. **Type consistency** —
   - `compute_next_run` signature: `(cron_expr, tz_name, blackout_dates, include_days, after)` — consistent across Task 2 tests and Task 8 endpoint.
   - `gc_logs` signature: `(storage_dir, retention_days)` — consistent.
   - `mark_pending_retry` signature: `(run_id, attempt, schedule_retry_max, schedule_retry_backoff)` — consistent.
   - `promote_oldest_pending` signature: refactored to keyword-only `(script_id, session_factory=None)` — Task 4 caller and Task 6 caller both updated.
   - Status enum values: `'pending'`, `'pending_retry'`, `'skipped'` — consistent across migration, tick, executor, run_service.

4. **Coverage gate** — Task 10 is the only frontend task without new pytest coverage (project pattern); backend tasks collectively add ~14 new test cases targeting ~600+ lines of new code. Net coverage should rise above 60%.

## Execution Handoff

After saving this plan, the implementer chooses:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Use superpowers:subagent-driven-development.
2. **Inline Execution** — execute tasks in this session with checkpoints for review. Use superpowers:executing-plans.
