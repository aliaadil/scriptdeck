from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import update

from kindling.runner.executor import Script, run_script
from kindling.services.log_broker import LogBroker
from kindling.services.run_service import (
    count_pending,
    create_run,
    finalize_run,
    has_active_run,
    mark_pending_retry,
    pick_due_retries,
    promote_oldest_pending,
)
from kindling.services.schedule_service import (
    ComputeError,
    advance,
    advance_next_run,
    compute_next_run,
    list_due,
)

log = logging.getLogger(__name__)


def _table():
    from kindling.db.models import runs as _runs
    return _runs


def _parse_json_list(raw: str | None) -> list[str] | None:
    """Decode a JSON-or-NULL string column into a list[str] or None."""
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return v if isinstance(v, list) else None


def _parse_json_list_int(raw: str | None) -> list[int] | None:
    """Decode a JSON-or-NULL string column into a list[int] or None."""
    v = _parse_json_list(raw)
    if v is None:
        return None
    return [int(x) for x in v]


async def scheduler_loop(
    *,
    settings,
    session_factory,
    log_broker: LogBroker,
    env_service,
    concurrency: asyncio.Semaphore,
    stop_event: asyncio.Event,
    storage_dir: Path,
    app=None,
) -> None:
    while not stop_event.is_set():
        try:
            await _tick(
                settings=settings,
                session_factory=session_factory,
                log_broker=log_broker,
                env_service=env_service,
                concurrency=concurrency,
                storage_dir=storage_dir,
                app=app,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("scheduler tick failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_interval)
        except TimeoutError:
            pass


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

            # Advance schedule cursor before dispatching, so skipped fires
            # still move the schedule forward. Use the tz-aware compute_next_run
            # for cron schedules so the timezone / blackout_dates / include_days
            # columns are honored; fall back to advance_next_run for interval
            # schedules (which only support time-delta semantics).
            if row["kind"] == "cron":
                try:
                    prev = datetime.fromisoformat(row["next_run_at"])
                    if prev.tzinfo is None:
                        prev = prev.replace(tzinfo=UTC)
                    cur = compute_next_run(
                        cron_expr=row["expression"],
                        tz_name=row.get("timezone") or "UTC",
                        blackout_dates=_parse_json_list(row.get("blackout_dates")),
                        include_days=_parse_json_list_int(row.get("include_days")),
                        after=prev,
                    )
                    new_next = cur.isoformat()
                except ComputeError:
                    # Bad cron / no fire within horizon — leave the schedule
                    # cursor where it is so the next tick can re-evaluate.
                    new_next = row["next_run_at"]
            else:
                new_next = advance_next_run(
                    row["kind"], row["expression"], row["next_run_at"]
                )
            await advance(s, row["id"], new_next)
            await s.commit()

            overlap = await has_active_run(s, sid)
            if overlap and policy == "skip":
                run_id, _, _ = await create_run(
                    s,
                    script_id=sid,
                    schedule_id=row["id"],
                    status="skipped",
                    skip_reason="overlap",
                )
                await finalize_run(s, run_id=run_id, exit_code=-1, status="skipped")
                await s.commit()
                await log_broker.close(run_id, "skipped", -1)
                continue

            if overlap and policy == "queue":
                pending = await count_pending(s, sid)
                if pending >= queue_max:
                    run_id, _, _ = await create_run(
                        s,
                        script_id=sid,
                        schedule_id=row["id"],
                        status="skipped",
                        skip_reason="queue_full",
                    )
                    await finalize_run(s, run_id=run_id, exit_code=-1, status="skipped")
                    schedules_t = _schedules_table()
                    await s.execute(
                        update(schedules_t)
                        .where(schedules_t.c.id == row["id"])
                        .values(queue_dropped=schedules_t.c.queue_dropped + 1)
                    )
                    await s.commit()
                    await log_broker.close(run_id, "skipped", -1)
                    continue
                # Insert as pending — promote_oldest_pending picks it up
                # when the running run finishes (Task 6 hook in executor).
                await create_run(
                    s,
                    script_id=sid,
                    schedule_id=row["id"],
                    status="pending",
                )
                await s.commit()
                continue

            # No overlap OR overlap_policy='parallel' (best-effort dispatch).
            run_id, _, _ = await create_run(s, script_id=sid, schedule_id=row["id"])
            await s.commit()

            # Snapshot the schedule's per-trigger params so the runner can
            # export them as SCRIPTDECK_PARAM_<KEY> + SCRIPTDECK_PARAMS_JSON.
            # Two schedules on the same script can carry different flag sets
            # without mutating the script row.
            from kindling.services.webhook_service import decode_params as _decode_params

            trigger_params = _decode_params(row.get("params_json"))

            script = Script(
                id=sid,
                user_id=row["user_id"],
                name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"],
                entrypoint=row["entrypoint"],
                scripts_dir=storage_dir / "scripts" / str(sid),
                requirements=[],
            )
            _schedule(
                app=app,
                run_id=run_id,
                script=script,
                env_service=env_service,
                log_broker=log_broker,
                concurrency=concurrency,
                storage_dir=storage_dir,
                session_factory=session_factory,
                trigger_params=trigger_params,
            )

        # ---- Phase 2: due retries (pending_retry -> running) ----
        retries = await pick_due_retries(s, now)
        for row in retries:
            sid = row["script_id"]
            # If a non-retry run is already active on this script, defer the
            # retry — leave status='pending_retry' for the next tick.
            if await has_active_run(s, sid):
                continue
            run_id = row["id"]
            await s.execute(
                update(_table()).where(_table().c.id == run_id).values(status="running")
            )
            await s.commit()
            script = Script(
                id=sid,
                user_id=row["user_id"],
                name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"],
                entrypoint=row["entrypoint"],
                scripts_dir=storage_dir / "scripts" / str(sid),
                requirements=[],
            )
            _schedule(
                app=app,
                run_id=run_id,
                script=script,
                env_service=env_service,
                log_broker=log_broker,
                concurrency=concurrency,
                storage_dir=storage_dir,
                session_factory=session_factory,
            )

        # ---- Phase 3: retention GC (idempotent; cheap when nothing to do) ----
        last_gc = getattr(app.state, "last_gc_at", None) if app is not None else None
        gc_due = (
            last_gc is None
            or (now - last_gc).total_seconds() > settings.gc_interval_seconds
        )
        if gc_due:
            from kindling.services.retention import gc_logs
            gc_logs(
                storage_dir=storage_dir,
                retention_days=settings.log_retention_days,
            )
            if app is not None:
                app.state.last_gc_at = now


def _schedules_table():
    from kindling.db.models import schedules as _schedules
    return _schedules


def _schedule(
    *,
    app,
    run_id: int,
    script: Script,
    env_service,
    log_broker: LogBroker,
    concurrency: asyncio.Semaphore,
    storage_dir: Path,
    session_factory,
    trigger_params: dict[str, str] | None = None,
) -> None:
    """Create and register the background run task so its outcome isn't lost."""
    task = asyncio.create_task(
        _execute_and_finalize(
            run_id=run_id,
            script=script,
            env_service=env_service,
            log_broker=log_broker,
            concurrency=concurrency,
            storage_dir=storage_dir,
            session_factory=session_factory,
            active_procs=(app.state.active_procs if app is not None else None),
            trigger_params=trigger_params or {},
        )
    )
    if app is not None:
        app.state.background_tasks.add(task)

        def _on_done(t: asyncio.Task) -> None:
            app.state.background_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.exception("background run task failed: %s", exc)

        task.add_done_callback(_on_done)


async def _execute_and_finalize(
    *,
    run_id,
    script,
    env_service,
    log_broker,
    concurrency,
    storage_dir,
    session_factory,
    active_procs=None,
    trigger_params: dict[str, str] | None = None,
):
    try:
        result = await run_script(
            run_id=run_id,
            script=script,
            env_service=env_service,
            log_broker=log_broker,
            concurrency=concurrency,
            storage_dir=storage_dir,
            active_procs=active_procs,
            trigger_params=trigger_params,
        )
        status = "success" if result.exit_code == 0 else "failure"
    except Exception as exc:
        log.exception("run_script raised for run_id=%s: %s", run_id, exc)
        try:
            await log_broker.close(run_id, "error", -1)
        except Exception:
            pass
        status = "error"
        result = type("R", (), {"exit_code": -1})()
    async with session_factory() as s:
        if status == "failure":
            from sqlalchemy import select as _select

            from kindling.db.models import runs as _runs_t
            from kindling.db.models import schedules as _sched_t
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
        # Drain queued runs waiting on this script (overlap=queue policy).
        try:
            promoted = await promote_oldest_pending(s, script_id=script.id)
            if promoted is not None:
                # Commit the status flip so the background task the
                # scheduler spawns below sees status='running' from its
                # own session.
                await s.commit()
        except Exception:
            promoted = None
        if promoted is not None:
            # `_schedule` is defined in this module; no import needed and a
            # self-import would create a circular reference.
            _schedule(
                app=None,
                run_id=promoted,
                script=script,
                env_service=env_service,
                log_broker=log_broker,
                concurrency=concurrency,
                storage_dir=storage_dir,
                session_factory=session_factory,
            )
