from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services import script_service
from scriptdeck.services.dep_detect import detect_deps_for_language

router = APIRouter(prefix="/scripts")


def _table():
    from scriptdeck.db.models import script_deps
    return script_deps


class DepsOut(BaseModel):
    deps: list[str]
    source: str


class DepsIn(BaseModel):
    deps: list[str] = Field(default_factory=list)
    source: str = Field(pattern="^(auto|manual)$")


@router.get("/{script_id}/deps")
async def get_deps(script_id: int, request: Request,
                   user: User = Depends(current_user)) -> DepsOut:
    sf = request.app.state.session_factory
    async with sf() as s:
        t = _table()
        row = (await s.execute(select(t).where(t.c.script_id == script_id))).mappings().one_or_none()
        if row is None:
            return DepsOut(deps=[], source="manual")
        return DepsOut(deps=json.loads(row["deps_json"]), source=row["source"])


@router.post("/{script_id}/deps/detect")
async def detect(script_id: int, request: Request,
                 user: User = Depends(current_user)) -> DepsOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        row = await script_service.get_script(s, script_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        source_text = (storage / row.source_path).read_text(encoding="utf-8")
        deps = detect_deps_for_language(row.language, source_text)
    return DepsOut(deps=deps, source="auto")


@router.put("/{script_id}/deps")
async def set_deps(script_id: int, body: DepsIn, request: Request,
                   user: User = Depends(current_user)) -> DepsOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")
    sf = request.app.state.session_factory
    now = datetime.now(UTC).isoformat()
    async with sf() as s:
        t = _table()
        existing = (await s.execute(select(t).where(t.c.script_id == script_id))).first()
        if existing:
            await s.execute(
                update(t).where(t.c.script_id == script_id).values(
                    deps_json=json.dumps(body.deps), source=body.source, updated_at=now,
                )
            )
        else:
            await s.execute(insert(t).values(
                script_id=script_id, deps_json=json.dumps(body.deps),
                source=body.source, updated_at=now,
            ))
        await s.commit()
    return body
