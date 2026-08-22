"""Per-script triggers management API.

A single Kindling script can have multiple triggers: any mix of cron schedules,
interval schedules, and webhook triggers. This module exposes a CRUD API
under ``/api/kindling/scripts/<script_id>/triggers`` so the SPA can list,
create, edit, and delete them.

Webhook trigger creation generates a random URL-safe token; the token is
returned ONCE in the POST response (the DB only ever stores the SHA-256 hash).
To rotate a webhook token, PUT the trigger with ``rotate_token=True``; the
fresh token is returned in that PUT response.

The legacy ``/api/kindling/schedules`` endpoints remain unchanged for
backward compatibility — they expose the same data model with the old
field names and omit the webhook token-rotation affordance.
"""
from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, insert, select, update

from kindling.api.deps import require_script_owner
from kindling.api.webhooks import hash_token
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.services.schedule_service import advance_next_run

router = APIRouter(prefix="/scripts")


def _table():
    from kindling.db.models import schedules
    return schedules


def _runs_table():
    from kindling.db.models import runs
    return runs


# --- Schemas -----------------------------------------------------------------


class TriggerCreate(BaseModel):
    """Body for POST /scripts/<id>/triggers."""
    kind: str = Field(pattern="^(cron|interval|webhook)$")
    expression: str | None = None
    enabled: bool = True
    timezone: str | None = None
    overlap_policy: str = "skip"
    retry_max: int = Field(default=0, ge=0)
    retry_backoff: int = Field(default=0, ge=0)
    queue_max: int = Field(default=10, ge=1, le=100)
    params_json: dict[str, Any] | None = None

    @field_validator("overlap_policy")
    @classmethod
    def _check_policy(cls, v: str) -> str:
        if v not in {"skip", "queue", "parallel"}:
            raise ValueError(f"bad overlap_policy: {v!r}")
        return v

    @field_validator("params_json")
    @classmethod
    def _check_params(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is None:
            return v
        for k, val in v.items():
            if not isinstance(k, str) or not k:
                raise ValueError("params_json keys must be non-empty strings")
            if not isinstance(val, (str, int, float, bool)):
                raise ValueError(
                    f"params_json[{k!r}] must be a primitive"
                )
        return v

    @model_validator(mode="after")
    def _kind_appropriate(self) -> TriggerCreate:
        if self.kind == "webhook":
            if self.timezone is not None:
                raise ValueError("timezone not allowed for kind='webhook'")
            self.expression = None
        else:
            if self.params_json is not None:
                raise ValueError("params_json only allowed for kind='webhook'")
            if not self.expression:
                raise ValueError(f"expression required for kind='{self.kind}'")
        return self


class TriggerUpdate(BaseModel):
    """Body for PUT /scripts/<id>/triggers/<trigger_id>."""
    kind: str = Field(pattern="^(cron|interval|webhook)$")
    expression: str | None = None
    enabled: bool = True
    timezone: str | None = None
    overlap_policy: str = "skip"
    retry_max: int = Field(default=0, ge=0)
    retry_backoff: int = Field(default=0, ge=0)
    queue_max: int = Field(default=10, ge=1, le=100)
    params_json: dict[str, Any] | None = None
    rotate_token: bool = False

    @model_validator(mode="after")
    def _kind_appropriate(self) -> TriggerUpdate:
        if self.kind == "webhook":
            self.expression = None
        return self


class TriggerOut(BaseModel):
    """Standard out for triggers (no token)."""
    id: int
    script_id: int
    kind: str
    expression: str | None
    enabled: bool
    next_run_at: str | None
    retry_max: int
    retry_backoff: int
    timezone: str | None
    overlap_policy: str
    queue_max: int
    params_json: dict[str, Any] | None = None
    run_count: int = 0


def _row_to_out(row, run_count: int = 0) -> TriggerOut:
    params = json.loads(row["params_json"]) if row.get("params_json") else None
    return TriggerOut(
        id=row["id"],
        script_id=row["script_id"],
        kind=row["kind"],
        expression=row["expression"],
        enabled=bool(row["enabled"]),
        next_run_at=row["next_run_at"],
        retry_max=row["retry_max"],
        retry_backoff=row["retry_backoff"],
        timezone=row["timezone"],
        overlap_policy=row["overlap_policy"],
        queue_max=row["queue_max"],
        params_json=params,
        run_count=int(run_count),
    )


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


# --- Endpoints ---------------------------------------------------------------


@router.get("/{script_id}/triggers")
async def list_triggers(
    script_id: int, request: Request, user: User = Depends(current_user),
) -> list[TriggerOut]:
    sf = request.app.state.session_factory
    t = _table()
    r = _runs_table()
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        rows = (await s.execute(
            select(
                t,
                # Count runs per trigger via correlated scalar subquery so the
                # LEFT JOIN's GROUP BY isn't needed. Plain `select(r.c.id)` here
                # would return the id of one matching row (looks like 0/1),
                # not the number of matching rows — wrap in func.count and
                # label so `_row_to_out` can find it on the row mapping.
                select(func.count(r.c.id))
                .where(r.c.schedule_id == t.c.id)
                .correlate(t)
                .scalar_subquery()
                .label("run_count"),
            )
            .where(t.c.script_id == script_id)
            .order_by(t.c.kind, t.c.id)
        )).mappings().all()
    return [_row_to_out(row, row["run_count"]) for row in rows]


@router.post("/{script_id}/triggers", status_code=201)
async def create_trigger(
    script_id: int, body: TriggerCreate, request: Request,
    user: User = Depends(current_user),
):
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(UTC).isoformat()
    if body.kind == "webhook":
        initial_next = None
        expr_value: str | None = None
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_token(raw_token)
    else:
        assert body.expression is not None
        initial_next = advance_next_run(body.kind, body.expression, now)
        expr_value = body.expression
        raw_token = None
        token_hash = None
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = (await s.execute(
            insert(t).values(
                script_id=script_id, kind=body.kind, expression=expr_value,
                enabled=1 if body.enabled else 0, next_run_at=initial_next,
                retry_max=body.retry_max, retry_backoff=body.retry_backoff,
                timezone=body.timezone,
                overlap_policy=body.overlap_policy,
                queue_max=body.queue_max,
                params_json=json.dumps(body.params_json) if body.params_json else None,
                webhook_token_hash=token_hash,
            ).returning(*t.c)
        )).mappings().one()
        await s.commit()
    out = _row_to_out(row).model_dump()
    if raw_token is not None:
        out["token"] = raw_token
    return out


@router.put("/{script_id}/triggers/{trigger_id}")
async def update_trigger(
    script_id: int, trigger_id: int, body: TriggerUpdate,
    request: Request, user: User = Depends(current_user),
):
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    now = datetime.now(UTC).isoformat()
    if body.kind == "webhook":
        new_next = None
        expr_value: str | None = None
    else:
        assert body.expression is not None
        new_next = advance_next_run(body.kind, body.expression, now)
        expr_value = body.expression
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        existing = (await s.execute(
            select(t.c.script_id, t.c.kind).where(t.c.id == trigger_id)
        )).mappings().one_or_none()
        if existing is None or int(existing["script_id"]) != script_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="trigger not found")
        # Token rotation: when the user asks for it AND this is a webhook
        # trigger, generate a fresh token and update the hash.
        new_token: str | None = None
        new_hash: str | None | Any = None
        if body.rotate_token and body.kind == "webhook":
            new_token = secrets.token_urlsafe(32)
            new_hash = hash_token(new_token)
        await s.execute(update(t).where(t.c.id == trigger_id).values(
            kind=body.kind, expression=expr_value,
            enabled=1 if body.enabled else 0, next_run_at=new_next,
            retry_max=body.retry_max, retry_backoff=body.retry_backoff,
            timezone=body.timezone,
            overlap_policy=body.overlap_policy,
            queue_max=body.queue_max,
            params_json=json.dumps(body.params_json) if body.params_json else None,
            **({"webhook_token_hash": new_hash} if new_hash is not None else {}),
        ))
        await s.commit()
        row = (await s.execute(select(t).where(t.c.id == trigger_id))).mappings().one()
    out = _row_to_out(row).model_dump()
    if new_token is not None:
        out["token"] = new_token
    return out


@router.delete("/{script_id}/triggers/{trigger_id}", status_code=204)
async def delete_trigger(
    script_id: int, trigger_id: int, request: Request,
    user: User = Depends(current_user),
):
    _require(user)
    sf = request.app.state.session_factory
    t = _table()
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        existing = (await s.execute(
            select(t.c.script_id).where(t.c.id == trigger_id)
        )).mappings().one_or_none()
        if existing is None or int(existing["script_id"]) != script_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="trigger not found")
        await s.execute(delete(t).where(t.c.id == trigger_id))
        await s.commit()
    return None
