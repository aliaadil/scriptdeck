from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, insert, select, update

from kindling.api.deps import require_script_owner
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.services.env_service import EnvService

router = APIRouter(prefix="/scripts")


def _table():
    from kindling.db.models import script_envs
    return script_envs


class EnvOut(BaseModel):
    has_env: bool
    line_count: int = 0
    updated_at: str | None = None


class EnvIn(BaseModel):
    content: str = Field(default="")


@router.get("/{script_id}/env")
async def get_env(script_id: int, request: Request,
                  user: User = Depends(current_user)) -> EnvOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot read env metadata")
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        t = _table()
        row = (await s.execute(select(t).where(t.c.script_id == script_id))).mappings().one_or_none()
    if row is None:
        return EnvOut(has_env=False)
    env: EnvService = request.app.state.env_service
    try:
        lines = env.decrypt_lines(row["ciphertext"], row["nonce"])
    except (ValueError, Exception) as exc:
        # cryptography raises InvalidTag (subclass of ValueError) when the
        # ciphertext was encrypted with a different key. Surface a 503 so the
        # admin knows to rotate.
        from cryptography.exceptions import InvalidTag

        if isinstance(exc, InvalidTag):
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="decrypt failed — key may have been rotated, run admin/rotate-env-key",
            )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="decrypt failed")
    return EnvOut(has_env=True, line_count=len(lines), updated_at=row["updated_at"])


@router.put("/{script_id}/env")
async def set_env(script_id: int, body: EnvIn, request: Request,
                  user: User = Depends(current_user)) -> EnvOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify env")
    sf = request.app.state.session_factory
    env: EnvService = request.app.state.env_service
    cipher, nonce = env.encrypt(body.content.encode("utf-8"))
    now = datetime.now(UTC).isoformat()
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        t = _table()
        existing = (await s.execute(select(t).where(t.c.script_id == script_id))).first()
        if existing:
            await s.execute(
                update(t).where(t.c.script_id == script_id).values(
                    ciphertext=cipher, nonce=nonce, updated_at=now,
                )
            )
        else:
            await s.execute(insert(t).values(
                script_id=script_id, ciphertext=cipher, nonce=nonce, updated_at=now,
            ))
        from kindling.services.audit import record as audit
        await audit(s, user.id, "env_updated", "script", script_id)
        await s.commit()
    return EnvOut(has_env=True, line_count=len(body.content.splitlines()), updated_at=now)


@router.delete("/{script_id}/env")
async def delete_env(script_id: int, request: Request,
                     user: User = Depends(current_user)) -> dict:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify env")
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        t = _table()
        await s.execute(delete(t).where(t.c.script_id == script_id))
        from kindling.services.audit import record as audit
        await audit(s, user.id, "env_deleted", "script", script_id)
        await s.commit()
    return {"ok": True}
