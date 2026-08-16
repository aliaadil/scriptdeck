from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

from scriptdeck.runner.executor import Script, run_script
from scriptdeck.services.log_broker import LogBroker
from scriptdeck.services.run_service import (
    create_run,
    finalize_run,
    has_active_run,
)
from scriptdeck.services.schedule_service import advance, advance_next_run, list_due

log = logging.getLogger(__name__)


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
            if await has_active_run(s, sid):
                run_id, _started_at = await create_run(
                    s, script_id=sid, schedule_id=row["id"], status="error"
                )
                new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
                await advance(s, row["id"], new_next)
                await finalize_run(s, run_id=run_id, exit_code=-1, status="error")
                await s.commit()
                await log_broker.close(run_id, "error", -1)
                continue

            new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
            run_id, _started_at = await create_run(s, script_id=sid, schedule_id=row["id"])
            await advance(s, row["id"], new_next)
            await s.commit()

            script = Script(
                id=sid,
                user_id=row["user_id"],
                name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"],
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
        await finalize_run(s, run_id=run_id, exit_code=result.exit_code, status=status)
        await s.commit()
