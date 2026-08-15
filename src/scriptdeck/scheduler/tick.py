from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
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
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("scheduler tick failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.scheduler_interval)
        except asyncio.TimeoutError:
            pass


async def _tick(*, settings, session_factory, log_broker, env_service, concurrency, storage_dir):
    now = datetime.now(timezone.utc)
    async with session_factory() as s:
        due = await list_due(s, now)
        for row in due:
            sid = row["script_id"]
            if await has_active_run(s, sid):
                run_id = await create_run(
                    s, script_id=sid, schedule_id=row["id"], status="error"
                )
                new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
                await advance(s, row["id"], new_next)
                await finalize_run(s, run_id=run_id, exit_code=-1, status="error")
                await s.commit()
                await log_broker.close(run_id, "error", -1)
                continue

            new_next = advance_next_run(row["kind"], row["expression"], row["next_run_at"])
            run_id = await create_run(s, script_id=sid, schedule_id=row["id"])
            await advance(s, row["id"], new_next)
            await s.commit()

            script = Script(
                id=sid,
                name=row["name"],
                language=row["language"],
                source_path=storage_dir / row["source_path"],
                requirements=[],
            )
            asyncio.create_task(
                _execute_and_finalize(
                    run_id=run_id,
                    script=script,
                    env_service=env_service,
                    log_broker=log_broker,
                    concurrency=concurrency,
                    storage_dir=storage_dir,
                    session_factory=session_factory,
                )
            )


async def _execute_and_finalize(
    *,
    run_id,
    script,
    env_service,
    log_broker,
    concurrency,
    storage_dir,
    session_factory,
):
    result = await run_script(
        run_id=run_id,
        script=script,
        env_service=env_service,
        log_broker=log_broker,
        concurrency=concurrency,
        storage_dir=storage_dir,
    )
    status = "success" if result.exit_code == 0 else "failure"
    async with session_factory() as s:
        await finalize_run(s, run_id=run_id, exit_code=result.exit_code, status=status)
        await s.commit()
