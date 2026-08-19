from __future__ import annotations

import json
from datetime import UTC, datetime
from datetime import date as _date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, insert, select, update

from kindling.api.deps import require_script_owner
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.services.schedule_service import (
    ComputeError,
    advance_next_run,
    compute_next_run,
)

router = APIRouter(prefix="/schedules")


def _table():
    from kindling.db.models import schedules
    return schedules


def _scripts_table():
    from kindling.db.models import scripts
    return scripts


def _runs_table():
    from kindling.db.models import runs
    return runs


class ScheduleCreate(BaseModel):
    script_id: int
    kind: str = Field(pattern="^(cron|interval)$")
    expression: str = Field(min_length=1)
    enabled: bool = True
    retry_max: int = Field(default=0, ge=0)
    retry_backoff: int = Field(default=0, ge=0)
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
    run_count: int = 0


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


def _row_to_out(row, run_count: int = 0) -> ScheduleOut:
    bo = json.loads(row["blackout_dates"]) if row["blackout_dates"] else None
    inc = json.loads(row["include_days"]) if row["include_days"] else None
    return ScheduleOut(
        id=row["id"], script_id=row["script_id"], kind=row["kind"],
        expression=row["expression"], enabled=bool(row["enabled"]),
        next_run_at=row["next_run_at"],
        retry_max=row["retry_max"], retry_backoff=row["retry_backoff"],
        timezone=row["timezone"], blackout_dates=bo, include_days=inc,
        overlap_policy=row["overlap_policy"], queue_max=row["queue_max"],
        queue_dropped=row["queue_dropped"],
        run_count=int(run_count),
    )


@router.get("")
async def list_endpoint(request: Request, script_id: int | None = None,
                       user: User = Depends(current_user)) -> list[ScheduleOut]:
    sf = request.app.state.session_factory
    t = _table()
    r = _runs_table()
    # Count runs per schedule via LEFT JOIN + GROUP BY. LEFT JOIN keeps
    # schedules with zero runs in the result set.
    run_count_col = func.count(r.c.id).label("run_count")
    if script_id is not None:
        # Filter narrows to one script — verify caller owns it (admins pass).
        async with sf() as s:
            await require_script_owner(s, script_id, user)
        stmt = (
            select(t, run_count_col)
            .select_from(t.outerjoin(r, r.c.schedule_id == t.c.id))
            .where(t.c.script_id == script_id)
            .group_by(t.c.id)
            .order_by(t.c.id)
        )
    else:
        # No filter — non-admins see only their own scripts' schedules.
        if user.role != "admin":
            async with sf() as s:
                own_script_ids = (
                    await s.execute(
                        select(_scripts_table().c.id).where(_scripts_table().c.user_id == user.id)
                    )
                ).scalars().all()
            if not own_script_ids:
                return []
            stmt = (
                select(t, run_count_col)
                .select_from(t.outerjoin(r, r.c.schedule_id == t.c.id))
                .where(t.c.script_id.in_(own_script_ids))
                .group_by(t.c.id)
                .order_by(t.c.id)
            )
        else:
            stmt = (
                select(t, run_count_col)
                .select_from(t.outerjoin(r, r.c.schedule_id == t.c.id))
                .group_by(t.c.id)
                .order_by(t.c.id)
            )
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [_row_to_out(r, r["run_count"]) for r in rows]


@router.get("/{schedule_id}")
async def get_endpoint(schedule_id: int, request: Request,
                      user: User = Depends(current_user)) -> ScheduleOut:
    """Fetch a single schedule by id, with owner check.

    Mirrors the list endpoint's ownership filtering: non-admin users
    can only read schedules on scripts they own.
    """
    sf = request.app.state.session_factory
    t = _table()
    r = _runs_table()
    run_count_col = func.count(r.c.id).label("run_count")
    async with sf() as s:
        row = (
            await s.execute(
                select(t, run_count_col)
                .select_from(t.outerjoin(r, r.c.schedule_id == t.c.id))
                .where(t.c.id == schedule_id)
                .group_by(t.c.id)
            )
        ).mappings().one_or_none()
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
        # Enforce ownership once the schedule's script_id is known.
        await require_script_owner(s, int(row["script_id"]), user)
    return _row_to_out(row, row["run_count"])


@router.post("", status_code=201)
async def create(body: ScheduleCreate, request: Request,
                 user: User = Depends(current_user)) -> ScheduleOut:
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(UTC).isoformat()
    initial_next = advance_next_run(body.kind, body.expression, now)
    async with sf() as s:
        await require_script_owner(s, body.script_id, user)
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
        row = (await s.execute(stmt)).mappings().one()
        await s.commit()
    return _row_to_out(row)


@router.put("/{schedule_id}")
async def update_schedule(schedule_id: int, body: ScheduleCreate, request: Request,
                          user: User = Depends(current_user)) -> ScheduleOut:
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(UTC).isoformat()
    new_next = advance_next_run(body.kind, body.expression, now)
    async with sf() as s:
        # Load the existing schedule to find its script_id before mutating;
        # verify ownership before we change any data.
        existing = (
            await s.execute(
                select(t.c.script_id).where(t.c.id == schedule_id)
            )
        ).mappings().one_or_none()
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
        await require_script_owner(s, int(existing["script_id"]), user)
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
        await s.commit()
        row = (await s.execute(select(t).where(t.c.id == schedule_id))).mappings().one()
    return _row_to_out(row)


@router.delete("/{schedule_id}", status_code=204)
async def remove(schedule_id: int, request: Request, user: User = Depends(current_user)):
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        existing = (
            await s.execute(
                select(t.c.script_id).where(t.c.id == schedule_id)
            )
        ).mappings().one_or_none()
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
        await require_script_owner(s, int(existing["script_id"]), user)
        await s.execute(delete(t).where(t.c.id == schedule_id))
        await s.commit()
    return None


@router.post("/{schedule_id}/enable")
async def enable(schedule_id: int, request: Request,
                 user: User = Depends(current_user)) -> dict:
    _require(user)
    return await _set_enabled(schedule_id, True, request, user)


@router.post("/{schedule_id}/disable")
async def disable(schedule_id: int, request: Request,
                  user: User = Depends(current_user)) -> dict:
    _require(user)
    return await _set_enabled(schedule_id, False, request, user)


async def _set_enabled(schedule_id: int, enabled: bool, request: Request, user: User) -> dict:
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        existing = (
            await s.execute(
                select(t.c.script_id).where(t.c.id == schedule_id)
            )
        ).mappings().one_or_none()
        if existing is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
        await require_script_owner(s, int(existing["script_id"]), user)
        await s.execute(update(t).where(t.c.id == schedule_id).values(
            enabled=1 if enabled else 0,
        ))
        await s.commit()
    return {"ok": True, "enabled": enabled}


@router.get("/{schedule_id}/next-runs")
async def next_runs(
    schedule_id: int,
    request: Request,
    limit: int = Query(default=5, ge=1, le=100),
    user: User = Depends(current_user),
) -> list[str]:
    """Compute the next `limit` fire times for the given schedule.

    Owner-checked via the schedule's script. Returns ISO 8601 timestamps in
    UTC, suitable for direct rendering in the UI.
    """
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        sched = (
            await s.execute(
                select(
                    t.c.expression, t.c.timezone, t.c.blackout_dates,
                    t.c.include_days, t.c.script_id,
                ).where(t.c.id == schedule_id)
            )
        ).mappings().one_or_none()
    if sched is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="schedule not found")
    async with sf() as s:
        await require_script_owner(s, int(sched["script_id"]), user)

    tz_name = sched["timezone"] or "UTC"
    bo = json.loads(sched["blackout_dates"]) if sched["blackout_dates"] else None
    inc = json.loads(sched["include_days"]) if sched["include_days"] else None

    fires: list[str] = []
    cursor = datetime.now(UTC)
    for _ in range(limit):
        try:
            cursor = compute_next_run(
                cron_expr=sched["expression"],
                tz_name=tz_name,
                blackout_dates=bo,
                include_days=inc,
                after=cursor,
            )
        except ComputeError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        fires.append(cursor.isoformat())
    return fires
