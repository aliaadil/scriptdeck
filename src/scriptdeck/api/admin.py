from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services.env_service import EnvService

router = APIRouter(prefix="/admin")
log = logging.getLogger(__name__)


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin required")


class RotateKeyIn(BaseModel):
    new_key_b64: str = Field(min_length=44, max_length=64)


@router.get("/audit")
async def audit_log(request: Request, user_id: int | None = None,
                    resource: str | None = None, since: str | None = None,
                    user: User = Depends(current_user)) -> list[dict]:
    _require_admin(user)
    from scriptdeck.db.models import audit_log
    sf = request.app.state.session_factory
    stmt = select(audit_log).order_by(audit_log.c.at.desc()).limit(200)
    if user_id is not None:
        stmt = stmt.where(audit_log.c.user_id == user_id)
    if resource:
        stmt = stmt.where(audit_log.c.resource_type == resource)
    if since:
        stmt = stmt.where(audit_log.c.at >= since)
    async with sf() as s:
        rows = (await s.execute(stmt)).mappings().all()
    return [dict(r) for r in rows]


@router.post("/rotate-env-key")
async def rotate_env_key(body: RotateKeyIn, request: Request,
                         user: User = Depends(current_user)) -> dict:
    _require_admin(user)
    new_svc = EnvService(body.new_key_b64)
    from scriptdeck.db.models import script_envs
    sf = request.app.state.session_factory
    old_svc: EnvService = request.app.state.env_service
    async with sf() as s:
        rows = (await s.execute(select(script_envs))).mappings().all()
        failed = 0
        for r in rows:
            try:
                plain = old_svc.decrypt(r["ciphertext"], r["nonce"])
            except Exception:
                failed += 1
                log.exception("rotate_env_key: failed to decrypt script_id=%s", r["script_id"])
                continue
            new_ct, new_nonce = new_svc.encrypt(plain)
            await s.execute(
                update(script_envs)
                .where(script_envs.c.script_id == r["script_id"])
                .values(ciphertext=new_ct, nonce=new_nonce,
                        updated_at=datetime.now(UTC).isoformat())
            )
        await s.commit()
    request.app.state.env_service = new_svc
    return {"ok": True, "rotated": len(rows) - failed, "failed": failed}
