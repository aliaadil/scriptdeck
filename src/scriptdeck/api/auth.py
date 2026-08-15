from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.invites import accept_invite
from scriptdeck.auth.jwt import decode_jwt, encode_jwt, revoke
from scriptdeck.auth.passwords import verify_password
from scriptdeck.auth.users import (
    User,
    count_users,
    create_user,
    get_by_email,
    update_last_login,
    update_password,
)
from scriptdeck.services.audit import record as audit

router = APIRouter(prefix="/auth")


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    token: str
    user: dict


class MeOut(BaseModel):
    id: int
    email: str
    role: str


class PasswordIn(BaseModel):
    current: str
    new: str = Field(min_length=8)


class SetupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


@router.post("/setup", status_code=201)
async def setup(request: Request, body: SetupIn) -> dict:
    """First-boot only. Returns 404 once any user exists."""
    sf = request.app.state.session_factory
    async with sf() as s:
        if await count_users(s) > 0:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="setup disabled")
        u = await create_user(s, body.email, body.password, role="admin")
        await s.commit()
        await audit(s, u.id, "user_created", "user", u.id)
        await s.commit()
    settings = request.app.state.settings
    token, _, _ = encode_jwt(u.id, u.role, settings.jwt_secret or "")
    return {"token": token, "user": {"id": u.id, "email": u.email, "role": u.role}}


@router.post("/login")
async def login(request: Request, body: LoginIn) -> dict:
    sf = request.app.state.session_factory
    async with sf() as s:
        u = await get_by_email(s, body.email)
        if u is None or not verify_password(body.password, u.password_hash):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad credentials")
        await update_last_login(s, u.id)
        await audit(s, u.id, "login", "user", u.id)
        await s.commit()
    settings = request.app.state.settings
    token, _, _ = encode_jwt(u.id, u.role, settings.jwt_secret or "")
    return {"token": token, "user": {"id": u.id, "email": u.email, "role": u.role}}


@router.post("/refresh")
async def refresh(
    request: Request,
    authorization: str = Header(...),
) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1]
    settings = request.app.state.settings
    payload = decode_jwt(token, secret=settings.jwt_secret or "")
    new_token, _, _ = encode_jwt(int(payload["sub"]), payload["role"], settings.jwt_secret or "")
    return {"token": new_token}


@router.post("/logout")
async def logout(request: Request, authorization: str = Header(...)) -> dict:
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing bearer")
    token = authorization.split(" ", 1)[1]
    settings = request.app.state.settings
    try:
        payload = decode_jwt(token, secret=settings.jwt_secret or "")
    except Exception:
        return {"ok": True}
    revoke(payload["jti"], int(payload["exp"]))
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user)) -> MeOut:
    return MeOut(id=user.id, email=user.email, role=user.role)


@router.put("/me/password")
async def change_password(
    request: Request,
    body: PasswordIn,
    user: User = Depends(current_user),
) -> dict:
    sf = request.app.state.session_factory
    async with sf() as s:
        u = await get_by_email(s, user.email)
        assert u is not None
        if not verify_password(body.current, u.password_hash):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="wrong current password")
        await update_password(s, u.id, body.new)
        await audit(s, u.id, "password_changed", "user", u.id)
        await s.commit()
    return {"ok": True}