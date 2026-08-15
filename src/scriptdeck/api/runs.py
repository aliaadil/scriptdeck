from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.runner.executor import Script, run_script
from scriptdeck.services import run_service, script_service

router = APIRouter(prefix="/runs")


def _runs_table():
    from scriptdeck.db.models import runs
    return runs


def _deps_table():
    from scriptdeck.db.models import script_deps
    return script_deps


class RunTrigger(BaseModel):
    script_id: int


class RunOut(BaseModel):
    id: int
    script_id: int
    schedule_id: int | None
    started_at: str
    ended_at: str | None
    exit_code: int | None
    status: str


@router.get("")
async def list_endpoint(request: Request, script_id: int | None = None,
                        status_filter: str | None = None, since: str | None = None,
                        limit: int = 50, user: User = Depends(current_user)) -> list[RunOut]:
    sf = request.app.state.session_factory
    t = _runs_table()
    stmt = select(t).order_by(t.c.id.desc()).limit(limit)
    if script_id:
        stmt = stmt.where(t.c.script_id == script_id)
    if status_filter:
        stmt = stmt.where(t.c.status == status_filter)
    if since:
        stmt = stmt.where(t.c.started_at >= since)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [RunOut(**dict(r)) for r in rows]


@router.post("", status_code=201)
async def trigger(body: RunTrigger, request: Request,
                  user: User = Depends(current_user)) -> RunOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot trigger")
    sf = request.app.state.session_factory
    storage = Path(request.app.state.settings.storage_dir)
    async with sf() as s:
        script = await script_service.get_script(s, body.script_id)
        if script is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="script not found")
        run_id, started = await run_service.create_run(
            s, script_id=script.id, schedule_id=None
        )
        deps_row = (await s.execute(
            select(_deps_table()).where(_deps_table().c.script_id == script.id)
        )).mappings().one_or_none()
        deps = json.loads(deps_row["deps_json"]) if deps_row else []
        await s.commit()
    runner_script = Script(
        id=script.id, name=script.name, language=script.language,
        source_path=storage / script.source_path, requirements=deps,
    )
    asyncio.create_task(
        _execute_and_finalize(
            run_id=run_id, script=runner_script, app=request.app,
        )
    )
    return RunOut(id=run_id, script_id=script.id, schedule_id=None,
                  started_at=started, ended_at=None, exit_code=None, status="running")


async def _execute_and_finalize(*, run_id, script, app):
    result = await run_script(
        run_id=run_id, script=script, env_service=app.state.env_service,
        log_broker=app.state.log_broker, concurrency=app.state.runner_sem,
        storage_dir=Path(app.state.settings.storage_dir),
    )
    status = "success" if result.exit_code == 0 else "failure"
    async with app.state.session_factory() as s:
        await run_service.finalize_run(s, run_id=run_id,
                                        exit_code=result.exit_code, status=status)
        await s.commit()


@router.get("/{run_id}")
async def detail(run_id: int, request: Request,
                 user: User = Depends(current_user)) -> RunOut:
    sf = request.app.state.session_factory
    t = _runs_table()
    async with sf() as s:
        row = (await s.execute(select(t).where(t.c.id == run_id))).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return RunOut(**dict(row))


@router.get("/{run_id}/log")
async def log_text(run_id: int, request: Request,
                   user: User = Depends(current_user)) -> str:
    storage = Path(request.app.state.settings.storage_dir)
    log_path = storage / "logs" / f"{run_id}.log"
    if not log_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="log not found")
    return log_path.read_text(encoding="utf-8", errors="replace")


@router.get("/{run_id}/log/stream")
async def log_stream(
    run_id: int,
    request: Request,
    token: str | None = Query(default=None),
    user: User = Depends(current_user),
) -> StreamingResponse:
    broker = request.app.state.log_broker

    async def event_gen():
        async for chunk in broker.subscribe(run_id):
            yield chunk

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                              headers={"Cache-Control": "no-cache",
                                       "X-Accel-Buffering": "no"})


@router.post("/{run_id}/cancel")
async def cancel(run_id: int, request: Request,
                 user: User = Depends(current_user)) -> dict:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot cancel")
    sf = request.app.state.session_factory
    t = _runs_table()
    async with sf() as s:
        row = (await s.execute(select(t).where(t.c.id == run_id))).mappings().one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        if row["status"] != "running":
            return {"ok": True, "status": row["status"]}
        await s.execute(update(t).where(t.c.id == run_id).values(status="cancelled"))
        await s.commit()
    await request.app.state.log_broker.close(run_id, "cancelled", -1)
    return {"ok": True, "status": "cancelled"}