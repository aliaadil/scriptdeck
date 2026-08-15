from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services.schedule_service import advance_next_run

router = APIRouter(prefix="/schedules")


def _table():
    from scriptdeck.db.models import schedules
    return schedules


class ScheduleCreate(BaseModel):
    script_id: int
    kind: str = Field(pattern="^(cron|interval)$")
    expression: str = Field(min_length=1)
    enabled: bool = True
    retry_max: int = 0
    retry_backoff: int = 0


class ScheduleOut(BaseModel):
    id: int
    script_id: int
    kind: str
    expression: str
    enabled: bool
    next_run_at: str
    retry_max: int
    retry_backoff: int


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


def _row_to_out(row) -> ScheduleOut:
    return ScheduleOut(
        id=row["id"], script_id=row["script_id"], kind=row["kind"],
        expression=row["expression"], enabled=bool(row["enabled"]),
        next_run_at=row["next_run_at"], retry_max=row["retry_max"],
        retry_backoff=row["retry_backoff"],
    )


@router.get("")
async def list_endpoint(request: Request, script_id: int | None = None,
                       user: User = Depends(current_user)) -> list[ScheduleOut]:
    sf = request.app.state.session_factory
    t = _table()
    stmt = select(t).order_by(t.c.id)
    if script_id is not None:
        stmt = stmt.where(t.c.script_id == script_id)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [_row_to_out(r) for r in rows]


@router.post("", status_code=201)
async def create(body: ScheduleCreate, request: Request,
                 user: User = Depends(current_user)) -> ScheduleOut:
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(UTC).isoformat()
    initial_next = advance_next_run(body.kind, body.expression, now)
    async with sf() as s:
        stmt = (
            insert(t).values(
                script_id=body.script_id, kind=body.kind, expression=body.expression,
                enabled=1 if body.enabled else 0, next_run_at=initial_next,
                retry_max=body.retry_max, retry_backoff=body.retry_backoff,
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
        await s.execute(update(t).where(t.c.id == schedule_id).values(
            kind=body.kind, expression=body.expression,
            enabled=1 if body.enabled else 0, next_run_at=new_next,
            retry_max=body.retry_max, retry_backoff=body.retry_backoff,
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
        await s.execute(delete(t).where(t.c.id == schedule_id))
        await s.commit()
    return None


@router.post("/{schedule_id}/enable")
async def enable(schedule_id: int, request: Request,
                 user: User = Depends(current_user)) -> dict:
    _require(user)
    return await _set_enabled(schedule_id, True, request)


@router.post("/{schedule_id}/disable")
async def disable(schedule_id: int, request: Request,
                  user: User = Depends(current_user)) -> dict:
    _require(user)
    return await _set_enabled(schedule_id, False, request)


async def _set_enabled(schedule_id: int, enabled: bool, request: Request) -> dict:
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        await s.execute(update(t).where(t.c.id == schedule_id).values(
            enabled=1 if enabled else 0,
        ))
        await s.commit()
    return {"ok": True, "enabled": enabled}
