from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, update

from scriptdeck.api.deps import require_run_owner, require_script_owner
from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.runner.executor import Script, run_script
from scriptdeck.services import run_service, script_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/runs")


def _runs_table():
    from scriptdeck.db.models import runs
    return runs


def _deps_table():
    from scriptdeck.db.models import script_deps
    return script_deps


def _envs_table():
    from scriptdeck.db.models import script_envs
    return script_envs


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
    # Retry-chain identity, so the UI can group a run with its sibling
    # attempts via GET /api/runs?group=<retry_group>. Defaulted because
    # _trigger_run builds RunOut by hand for a fresh (attempt 0) run.
    attempt: int = 0
    retry_group: str | None = None


@router.get("")
async def list_endpoint(
    request: Request,
    script_id: int | None = None,
    status_filter: str | None = None,
    since: str | None = None,
    group: str | None = None,
    limit: int = 50,
    user: User = Depends(current_user),
) -> list[RunOut]:
    sf = request.app.state.session_factory
    t = _runs_table()
    stmt = select(t).limit(limit)
    # Retry-group lookup — order attempts ascending so callers see the chain
    # in order (0, 1, 2, ...) rather than newest-first. All other filters
    # and ownership scoping still apply.
    if group is not None:
        stmt = stmt.where(t.c.retry_group == group).order_by(
            t.c.attempt.asc(), t.c.id.asc()
        )
    else:
        stmt = stmt.order_by(t.c.id.desc())
    if script_id:
        stmt = stmt.where(t.c.script_id == script_id)
        # Enforce ownership when filtering by a specific script_id.
        async with sf() as s:
            await require_script_owner(s, script_id, user)
    elif group is None:
        # No script_id filter and no retry_group — non-admins see only
        # their own scripts' runs.
        if user.role != "admin":
            async with sf() as s:
                own_script_ids = await run_service.own_script_ids(s, user.id)
            if not own_script_ids:
                return []
            stmt = stmt.where(t.c.script_id.in_(own_script_ids))
    if status_filter:
        stmt = stmt.where(t.c.status == status_filter)
    if since:
        stmt = stmt.where(t.c.started_at >= since)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    if group is not None and user.role != "admin":
        # Per-run ownership re-check for group queries — a non-admin could
        # guess another user's retry_group, so filter the response to rows
        # whose script the caller actually owns.
        async with sf() as s:
            own_script_ids = set(await run_service.own_script_ids(s, user.id))
        rows = [r for r in rows if r["script_id"] in own_script_ids]
    return [RunOut(**dict(r)) for r in rows]


@router.post("", status_code=201)
async def trigger(body: RunTrigger, request: Request,
                  user: User = Depends(current_user)) -> RunOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot trigger")
    return await _trigger_run(request.app, body.script_id, user)


async def _trigger_run(app, script_id: int, user: User) -> RunOut:
    """Shared trigger flow used by /runs and /scripts/{id}/run."""
    sf = app.state.session_factory
    storage = Path(app.state.settings.storage_dir)
    env_ciphertext: str | None = None
    env_nonce: str | None = None
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        script = await script_service.get_script(s, script_id)
        if script is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="script not found")
        # I1: guard against concurrent trigger
        if await run_service.has_active_run(s, script.id):
            raise HTTPException(
                status.HTTP_409_CONFLICT, detail="another run is in progress"
            )
        run_id, started, retry_group = await run_service.create_run(
            s, script_id=script.id, schedule_id=None
        )
        deps_row = (await s.execute(
            select(_deps_table()).where(_deps_table().c.script_id == script.id)
        )).mappings().one_or_none()
        deps = json.loads(deps_row["deps_json"]) if deps_row else []
        env_row = (await s.execute(
            select(_envs_table()).where(_envs_table().c.script_id == script.id)
        )).mappings().one_or_none()
        if env_row:
            env_ciphertext = env_row["ciphertext"]
            env_nonce = env_row["nonce"]
        await s.commit()
    runner_script = Script(
        id=script.id, user_id=script.user_id, name=script.name, language=script.language,
        source_path=(storage / script.source_path).resolve(),
        requirements=deps,
    )
    _schedule_execution(
        app,
        run_id=run_id,
        script=runner_script,
        env_ciphertext=env_ciphertext,
        env_nonce=env_nonce,
    )
    return RunOut(id=run_id, script_id=script.id, schedule_id=None,
                  started_at=started, ended_at=None, exit_code=None, status="running",
                  retry_group=retry_group)


def _schedule_execution(
    app,
    *,
    run_id: int,
    script: Script,
    env_ciphertext: str | None = None,
    env_nonce: str | None = None,
) -> None:
    """Create and register the background run task so its outcome isn't lost."""
    task = asyncio.create_task(
        _execute_and_finalize(
            run_id=run_id,
            script=script,
            app=app,
            env_ciphertext=env_ciphertext,
            env_nonce=env_nonce,
        )
    )
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
    app,
    env_ciphertext: str | None = None,
    env_nonce: str | None = None,
):
    try:
        result = await run_script(
            run_id=run_id,
            script=script,
            env_service=app.state.env_service,
            log_broker=app.state.log_broker,
            concurrency=app.state.runner_sem,
            storage_dir=Path(app.state.settings.storage_dir),
            env_ciphertext=env_ciphertext,
            env_nonce=env_nonce,
            active_procs=app.state.active_procs,
        )
        status = "success" if result.exit_code == 0 else "failure"
    except Exception as exc:
        log.exception("run_script raised for run_id=%s: %s", run_id, exc)
        try:
            await app.state.log_broker.close(run_id, "error", -1)
        except Exception:
            pass
        status = "error"
        result = type("R", (), {"exit_code": -1})()
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
        await require_run_owner(s, run_id, user)
        row = (await s.execute(select(t).where(t.c.id == run_id))).mappings().one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return RunOut(**dict(row))


@router.get("/{run_id}/log")
async def log_text(run_id: int, request: Request,
                   user: User = Depends(current_user)):
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_run_owner(s, run_id, user)
    storage = Path(request.app.state.settings.storage_dir)
    log_path = storage / "logs" / f"{run_id}.log"
    if not log_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="log not found")
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(log_path.read_text(encoding="utf-8", errors="replace"))


@router.get("/{run_id}/log/stream")
async def log_stream(
    run_id: int,
    request: Request,
    token: str | None = Query(default=None),
    user: User = Depends(current_user),
) -> StreamingResponse:
    # Authorize before opening the stream so unauthorized callers never
    # receive a single chunk of another user's logs.
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_run_owner(s, run_id, user)
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
    # I4: terminate the live subprocess, if any, so cancel actually kills work
    procs: dict[int, asyncio.subprocess.Process] = request.app.state.active_procs
    # Authorize ownership before killing anything or mutating DB rows.
    async with sf() as s:
        await require_run_owner(s, run_id, user)
        row = (await s.execute(select(t).where(t.c.id == run_id))).mappings().one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    proc = procs.get(run_id)
    if proc is not None and proc.returncode is None:
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
    async with sf() as s:
        if row["status"] != "running":
            return {"ok": True, "status": row["status"]}
        await s.execute(update(t).where(t.c.id == run_id).values(status="cancelled"))
        await s.commit()
    await request.app.state.log_broker.close(run_id, "cancelled", -1)
    return {"ok": True, "status": "cancelled"}
