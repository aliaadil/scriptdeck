from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.invites import accept_invite, create_invite
from scriptdeck.auth.users import (
    User,
    create_user,
    delete_user,
    list_users,
    update_role,
)
from scriptdeck.db.models import users as users_table
from scriptdeck.services.audit import record as audit

router = APIRouter(prefix="/users")


class InviteIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern="^(admin|editor|viewer)$")


class InviteOut(BaseModel):
    token: str
    expires_at: str


class AcceptInviteIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


class RoleIn(BaseModel):
    role: str = Field(pattern="^(admin|editor|viewer)$")


def require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin required")


@router.get("/")
async def list_endpoint(request: Request, user: User = Depends(current_user)) -> list[dict]:
    require_admin(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        users = await list_users(s)
    return [
        {
            "id": u.id,
            "email": u.email,
            "role": u.role,
            "created_at": u.created_at,
            "last_login_at": u.last_login_at,
        }
        for u in users
    ]


@router.post("/invites", status_code=201)
async def invite(
    request: Request, body: InviteIn, user: User = Depends(current_user)
) -> InviteOut:
    require_admin(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        inv = await create_invite(s, body.email, body.role)
        await audit(
            s,
            user.id,
            "invite_created",
            "invite",
            inv.id,
            {"email": body.email, "role": body.role},
        )
        await s.commit()
    return InviteOut(token=inv.token, expires_at=inv.expires_at)


@router.post("/invites/accept", status_code=201)
async def accept(request: Request, body: AcceptInviteIn) -> dict:
    sf = request.app.state.session_factory
    async with sf() as s:
        inv = await accept_invite(s, body.token)
        if inv is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid or expired invite")
        u = await create_user(s, inv.email, body.password, role=inv.role)
        await audit(s, u.id, "user_created", "user", u.id, {"via_invite": True})
        await s.commit()
    return {"id": u.id, "email": u.email, "role": u.role}


@router.delete("/{user_id}")
async def remove(user_id: int, request: Request, user: User = Depends(current_user)) -> dict:
    require_admin(user)
    if user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="cannot delete self")
    sf = request.app.state.session_factory
    async with sf() as s:
        ok = await delete_user(s, user_id)
        if ok:
            await audit(s, user.id, "user_deleted", "user", user_id)
            await s.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return {"ok": True}


@router.put("/{user_id}/role")
async def change_role(
    user_id: int, body: RoleIn, request: Request, user: User = Depends(current_user)
) -> dict:
    require_admin(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        ok = await update_role(s, user_id, body.role)
        if ok:
            await audit(s, user.id, "role_changed", "user", user_id, {"role": body.role})
            await s.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return {"ok": True}


class UserMePatch(BaseModel):
    timezone: str | None = None


@router.patch("/me")
async def patch_me(
    body: UserMePatch,
    request: Request,
    user: User = Depends(current_user),
) -> dict:
    """Update the current user's mutable profile fields (currently timezone)."""
    values: dict[str, str] = {}
    if body.timezone is not None:
        try:
            ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unknown timezone: {body.timezone}",
            ) from exc
        values["timezone"] = body.timezone
    if values:
        sf = request.app.state.session_factory
        async with sf() as s:
            await s.execute(
                update(users_table).where(users_table.c.id == user.id).values(**values)
            )
            await s.commit()
    return {"ok": True, "updated": list(values.keys())}
