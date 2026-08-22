from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import insert, select, update

from kindling.api._params import check_params_argv, check_params_exclusive, check_params_json
from kindling.api.deps import require_run_owner, require_script_owner
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.runner.executor import Script, run_script
from kindling.services import run_service, script_service
from kindling.services.dep_detect import detect_deps_for_language

log = logging.getLogger(__name__)

router = APIRouter(prefix="/runs")


def _runs_table():
    from kindling.db.models import runs
    return runs


def _schedules_table():
    from kindling.db.models import schedules
    return schedules


def _scripts_table():
    from kindling.db.models import scripts
    return scripts


def _deps_table():
    from kindling.db.models import script_deps
    return script_deps


def _envs_table():
    from kindling.db.models import script_envs
    return script_envs


class RunTrigger(BaseModel):
    script_id: int
    params_json: dict[str, Any] | None = None
    params_argv: list[str] | None = None

    @field_validator("params_json")
    @classmethod
    def _check_params(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        # Mirror TriggerCreate.params_json rules so the manual endpoint
        # accepts exactly the same shape schedules and webhooks do.
        return check_params_json(v)

    @field_validator("params_argv")
    @classmethod
    def _check_argv(cls, v: list[Any] | None) -> list[str] | None:
        return check_params_argv(v)

    @field_validator("params_argv", mode="after")
    @classmethod
    def _check_exclusive(cls, v: list[str] | None, info) -> None:
        # mode='after' lets us see the sibling field's value via info.data
        check_params_exclusive(info.data.get("params_json"), v)
        return v


class RunOut(BaseModel):
    id: int
    script_id: int
    script_name: str
    schedule_id: int | None
    schedule_timezone: str | None = None
    # 'manual' / 'cron' / 'interval' / 'webhook' / None (legacy rows).
    trigger_kind: str | None = None
    started_at: str
    ended_at: str | None
    exit_code: int | None
    status: str
    skip_reason: str | None = None
    # Retry-chain identity, so the UI can group a run with its sibling
    # attempts via GET /api/runs?group=<retry_group>. Defaulted because
    # _trigger_run builds RunOut by hand for a fresh (attempt 0) run.
    attempt: int = 0
    retry_group: str | None = None
    # Migration 017: the JSON payload (parsed) the manual run was started
    # with, or null when this run wasn't started from /scripts/{id}/run
    # with a params body (or pre-feature). Holds a dict for the
    # params_json path and a list[str] for the params_argv path — both
    # shapes round-trip through the same TEXT column.
    params_json: dict[str, Any] | list[Any] | None = None

    @field_validator("params_json", mode="before")
    @classmethod
    def _coerce_params_json(cls, v: Any) -> Any:
        # The DB column stores a JSON-encoded payload as TEXT; both the
        # list and detail endpoints construct RunOut directly from a
        # SQLAlchemy RowMapping, so we parse the string back here.
        # Corrupt legacy rows surface as None rather than 500ing the
        # endpoint.
        if v is None or isinstance(v, (dict, list)):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except (ValueError, TypeError):
                return None
            return parsed if isinstance(parsed, (dict, list)) else None
        return None


@router.get("")
async def list_endpoint(
    request: Request,
    script_id: int | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    since: str | None = None,
    group: str | None = None,
    schedule_id: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0, le=10000),
    limit: int = Query(default=50, ge=1, le=100),
    user: User = Depends(current_user),
) -> list[RunOut]:
    sf = request.app.state.session_factory
    t = _runs_table()
    sched_t = _schedules_table()
    scripts_t = _scripts_table()
    # Outer-join scripts so we can populate script_name in one round trip.
    # We use Table.outerjoin directly (no relationship) because runs is
    # defined as a Core table; joining on the explicit FK matches the
    # schema in models.py.
    stmt = (
        select(
            t,
            scripts_t.c.name.label("script_name"),
            sched_t.c.timezone.label("schedule_timezone"),
        )
        .select_from(
            t.outerjoin(scripts_t, t.c.script_id == scripts_t.c.id)
             .outerjoin(sched_t, t.c.schedule_id == sched_t.c.id)
        )
        .limit(limit)
        .offset(offset)
    )
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
    if schedule_id is not None:
        # Resolve schedule → script and owner-check before applying the
        # filter, mirroring the script_id branch above. A non-owner gets
        # 403 (via require_script_owner); an unknown schedule_id gets 404.
        async with sf() as s:
            sched_row = (
                await s.execute(
                    select(sched_t.c.script_id).where(sched_t.c.id == schedule_id)
                )
            ).one_or_none()
            if sched_row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
            await require_script_owner(s, sched_row[0], user)
        stmt = stmt.where(t.c.schedule_id == schedule_id)
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
    return await _trigger_run(request.app, body.script_id, user,
                              params_json=body.params_json)


async def _trigger_run(
    app, script_id: int, user: User,
    *,
    params_json: dict[str, Any] | None = None,
    params_argv: list[str] | None = None,
) -> RunOut:
    """Shared trigger flow used by /runs and /scripts/{id}/run.

    Exactly one of ``params_json`` (object) or ``params_argv`` (list) may
    be provided:
    - ``params_json``: dict → exported as KINDLING_PARAM_<KEY>=<value> env
      vars (same as the schedule/webhook paths) and converted to
      language-appropriate argv via argv_for() so the runner sees them as
      sys.argv / --flags.
    - ``params_argv``: list of strings → used verbatim as the argv
      appended after the entrypoint. No env-var export. Lets manual
      runners type CLI args the way they'd pass them on a shell.
    """
    from kindling.api.webhooks import trigger_params_env_from_dict
    from kindling.params import argv_for

    sf = app.state.session_factory
    storage = Path(app.state.settings.storage_dir)
    env_ciphertext: str | None = None
    env_nonce: str | None = None
    param_argv: list[str] = []
    # Reflected back on RunOut — list shape for argv path, dict for json path.
    persisted_payload: dict[str, Any] | list[str] | None = None
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
        # Defense-in-depth: model_validators should have caught this, but a
        # future caller path could bypass them.
        if params_json is not None and params_argv is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide either params_json or params_argv, not both.",
            )
        params_json_str: str | None
        if params_argv is not None:
            # User provided raw argv — use verbatim; no language transform.
            param_argv = list(params_argv)
            persisted_payload = param_argv
            params_json_str = json.dumps(param_argv) if param_argv else None
        elif params_json:
            # Compute argv up-front so an invalid language raises 422 here
            # rather than mid-background-task (which would leave the run
            # row stuck in 'running').
            param_argv = argv_for(script.language, params_json)
            persisted_payload = params_json
            params_json_str = json.dumps(params_json)
        else:
            param_argv = []
            params_json_str = None
        run_id, started, retry_group = await run_service.create_run(
            s, script_id=script.id, schedule_id=None, trigger_kind="manual",
            params_json=params_json_str,
        )
        # Always re-detect from source. The script_deps table is updated
        # so /deps reflects what's currently in use.
        source_path = storage / script.source_path
        try:
            source_text = source_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            source_text = ""
        deps = detect_deps_for_language(script.language, source_text)
        now = datetime.now(UTC).isoformat()
        deps_tbl = _deps_table()
        existing_deps = (
            await s.execute(
                select(deps_tbl).where(deps_tbl.c.script_id == script.id)
            )
        ).mappings().one_or_none()
        if existing_deps:
            # Preserve a user-set manual entry; only auto-update rows that
            # were themselves auto-detected previously.
            if existing_deps["source"] != "manual":
                await s.execute(
                    update(deps_tbl)
                    .where(deps_tbl.c.script_id == script.id)
                    .values(deps_json=json.dumps(deps), source="auto", updated_at=now)
                )
        else:
            await s.execute(
                insert(deps_tbl).values(
                    script_id=script.id,
                    deps_json=json.dumps(deps),
                    source="auto",
                    updated_at=now,
                )
            )
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
        entrypoint=script.entrypoint,
        scripts_dir=storage / "scripts" / str(script.id),
        requirements=deps,
    )
    _schedule_execution(
        app,
        run_id=run_id,
        script=runner_script,
        env_ciphertext=env_ciphertext,
        env_nonce=env_nonce,
        # params_argv has no key/value pairs to expose as env vars; env export
        # only makes sense for the params_json path.
        param_env=trigger_params_env_from_dict(params_json) if params_json else None,
        param_argv=param_argv,
    )
    return RunOut(
        id=run_id, script_id=script.id, script_name=script.name,
        schedule_id=None, trigger_kind="manual",
        started_at=started, ended_at=None, exit_code=None, status="running",
        retry_group=retry_group, params_json=persisted_payload,
    )


def _schedule_execution(
    app,
    *,
    run_id: int,
    script: Script,
    env_ciphertext: str | None = None,
    env_nonce: str | None = None,
    param_env: dict[str, str] | None = None,
    param_argv: list[str] | None = None,
) -> None:
    """Create and register the background run task so its outcome isn't lost.

    ``param_env`` exports KINDLING_PARAM_<KEY>=<value> into the run env.
    ``param_argv`` is the language-mapped argv appended after the
    entrypoint (positional for python/bash, --key value for node).
    Both may be set, neither, or either.
    """
    task = asyncio.create_task(
        _execute_and_finalize(
            run_id=run_id,
            script=script,
            app=app,
            env_ciphertext=env_ciphertext,
            env_nonce=env_nonce,
            param_env=param_env,
            param_argv=param_argv,
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
    param_env: dict[str, str] | None = None,
    param_argv: list[str] | None = None,
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
            param_env=param_env,
            param_argv=param_argv,
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
    scripts_t = _scripts_table()
    async with sf() as s:
        await require_run_owner(s, run_id, user)
        row = (await s.execute(
            select(t, scripts_t.c.name.label("script_name"))
            .select_from(t.outerjoin(scripts_t, t.c.script_id == scripts_t.c.id))
            .where(t.c.id == run_id)
        )).mappings().one_or_none()
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
    from fastapi.responses import JSONResponse
    return JSONResponse({"content": log_path.read_text(encoding="utf-8", errors="replace")})


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
        await s.execute(update(t).where(t.c.id == run_id).values(
            status="cancelled",
            ended_at=datetime.now(UTC).isoformat(),
            exit_code=-1,
        ))
        await s.commit()
    await request.app.state.log_broker.close(run_id, "cancelled", -1)
    return {"ok": True, "status": "cancelled"}
