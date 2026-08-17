from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from scriptdeck.api.deps import require_script_owner
from scriptdeck.api.runs import RunOut, _trigger_run
from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User
from scriptdeck.services import script_service

router = APIRouter(prefix="/scripts")


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(pattern="^(python|node)$")
    source: str = Field(min_length=1)
    description: str | None = None


class ScriptOut(BaseModel):
    id: int
    name: str
    language: str
    source_path: str
    description: str | None


class ScriptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: str | None = None


def _require(user: User) -> None:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")


@router.get("")
async def list_endpoint(
    request: Request,
    language: str | None = None,
    q: str | None = None,
    limit: int = 50,
    user: User = Depends(current_user),
) -> list[ScriptOut]:
    sf = request.app.state.session_factory
    # Non-admins only see their own scripts. Admins still see everything.
    user_id_filter: int | None = None if user.role == "admin" else user.id
    async with sf() as s:
        rows = await script_service.list_scripts(
            s, language=language, q=q, limit=limit, user_id=user_id_filter,
        )
    return [ScriptOut(id=r.id, name=r.name, language=r.language,
                      source_path=r.source_path, description=r.description) for r in rows]


@router.post("", status_code=201)
async def create(
    body: ScriptCreate, request: Request, user: User = Depends(current_user)
) -> ScriptOut:
    _require(user)
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        row = await script_service.create_script(
            s, name=body.name, language=body.language,
            source_path="scripts/PLACEHOLDER", description=body.description,
            user_id=user.id,
        )
        script_dir = storage / "scripts" / str(row.id)
        script_dir.mkdir(parents=True, exist_ok=True)
        ext = "py" if body.language == "python" else "js"
        path = script_dir / f"main.{ext}"
        path.write_text(body.source, encoding="utf-8")
        await script_service.update_script(s, row.id, source_path=str(path.relative_to(storage)))
        await s.commit()
        new = await script_service.get_script(s, row.id)
    assert new is not None
    return ScriptOut(id=new.id, name=new.name, language=new.language,
                     source_path=new.source_path, description=new.description)


@router.get("/{script_id}")
async def detail(script_id: int, request: Request,
                 user: User = Depends(current_user)) -> ScriptOut:
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return ScriptOut(id=row.id, name=row.name, language=row.language,
                     source_path=row.source_path, description=row.description)


@router.put("/{script_id}")
async def update(
    script_id: int, body: ScriptUpdate, request: Request, user: User = Depends(current_user)
) -> ScriptOut:
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        await script_service.update_script(
            s, script_id, name=body.name, description=body.description,
        )
        if body.source is not None:
            row = await script_service.get_script(s, script_id)
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
            storage: Path = request.app.state.settings.storage_dir_path
            (storage / row.source_path).write_text(body.source, encoding="utf-8")
        await s.commit()
        new = await script_service.get_script(s, script_id)
    if new is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return ScriptOut(id=new.id, name=new.name, language=new.language,
                     source_path=new.source_path, description=new.description)


@router.delete("/{script_id}", status_code=204)
async def remove(script_id: int, request: Request,
                 user: User = Depends(current_user)):
    _require(user)
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        ok = await script_service.delete_script(s, script_id)
        await s.commit()
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return None


@router.get("/{script_id}/source")
async def get_source(script_id: int, request: Request, user: User = Depends(current_user)):
    sf = request.app.state.session_factory
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    storage: Path = request.app.state.settings.storage_dir_path
    path = storage / row.source_path
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="source missing")
    return JSONResponse({"content": path.read_text(encoding="utf-8")})


@router.post("/{script_id}/run", status_code=201)
async def run_script(script_id: int, request: Request,
                    user: User = Depends(current_user)) -> RunOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot trigger")
    return await _trigger_run(request.app, script_id, user)
