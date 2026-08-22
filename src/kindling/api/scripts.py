from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

from kindling.api._params import check_params_json
from kindling.api.deps import require_script_owner
from kindling.api.runs import RunOut, _trigger_run
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.script_templates import seed_template
from kindling.services import script_service
from kindling.services.script_files import (
    FileEntry,
    delete_file,
    list_files,
    read_file,
    write_file,
)

router = APIRouter(prefix="/scripts")


SUPPORTED_LANGUAGES = r"^(python|node|bash)$"

# Mirrors the ScriptNew default — must match verbatim (case-insensitive).
UNTITLED_PLACEHOLDER = "untitled script"


class ScriptCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    language: str = Field(pattern=SUPPORTED_LANGUAGES)
    source: str | None = Field(default=None, min_length=1)
    template: str | None = Field(default=None, pattern=SUPPORTED_LANGUAGES)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _no_placeholder_name(cls, v: str) -> str:
        """Reject the frontend default so scripts land in the DB named.

        The ScriptNew page pre-fills the name input with "Untitled script".
        Saving that placeholder pollutes the list and clashes with the
        existing-untitled row on second attempt. Force a real name at the
        boundary so both layers (UI button + DB) reject it.
        """
        if v.strip().lower() == UNTITLED_PLACEHOLDER:
            raise ValueError(
                'Name "Untitled script" is a placeholder — pick a unique '
                "name before saving."
            )
        return v


class ScriptOut(BaseModel):
    id: int
    name: str
    language: str
    source_path: str
    entrypoint: str
    description: str | None


class ScriptUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source: str | None = None
    entrypoint: str | None = None


class FileListOut(BaseModel):
    entries: list[FileEntry]


class FileContentIn(BaseModel):
    content: str


class FileCreateIn(BaseModel):
    path: str
    content: str = ""


class _ManualRunBody(BaseModel):
    """Optional body for POST /scripts/{id}/run.

    Defined at module scope so it isn't recreated on every request, and
    so the same params_json rules used by RunTrigger stay in sync.
    """
    params_json: dict[str, Any] | None = None

    @field_validator("params_json")
    @classmethod
    def _check_params(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        return check_params_json(v)


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
                      source_path=r.source_path, entrypoint=r.entrypoint,
                      description=r.description) for r in rows]


@router.post("", status_code=201)
async def create(
    body: ScriptCreate, request: Request, user: User = Depends(current_user)
) -> ScriptOut:
    _require(user)
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        # Insert row first with a benign placeholder source_path; we'll
        # rewrite it after we've written the on-disk files using the
        # row's id.
        row = await script_service.create_script(
            s, name=body.name, language=body.language,
            source_path="scripts/PENDING", description=body.description,
            user_id=user.id,
        )
        script_dir = storage / "scripts" / str(row.id)
        script_dir.mkdir(parents=True, exist_ok=True)
        if body.template:
            entrypoint = seed_template(body.template, script_dir)
        else:
            if body.source is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    detail="either `template` or `source` is required",
                )
            entrypoint = (
                "main.py" if body.language == "python"
                else "main.js" if body.language == "node"
                else "main.sh"
            )
            (script_dir / entrypoint).write_text(body.source, encoding="utf-8")
        rel_script_dir = script_dir.relative_to(storage)
        await script_service.update_script(
            s, row.id,
            source_path=str(rel_script_dir / entrypoint),
            entrypoint=entrypoint,
        )
        await s.commit()
        new = await script_service.get_script(s, row.id)
    assert new is not None
    return ScriptOut(id=new.id, name=new.name, language=new.language,
                     source_path=new.source_path, entrypoint=new.entrypoint,
                     description=new.description)


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
                     source_path=row.source_path, entrypoint=row.entrypoint,
                     description=row.description)


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
            entrypoint=body.entrypoint,
        )
        if body.source is not None:
            row = await script_service.get_script(s, script_id)
            if row is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
            storage: Path = request.app.state.settings.storage_dir_path
            script_dir = storage / Path(row.source_path).parent
            try:
                write_file(script_dir, row.entrypoint, body.source)
            except ValueError as e:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
        await s.commit()
        new = await script_service.get_script(s, script_id)
    if new is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    return ScriptOut(id=new.id, name=new.name, language=new.language,
                     source_path=new.source_path, entrypoint=new.entrypoint,
                     description=new.description)


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
    script_dir = storage / Path(row.source_path).parent
    try:
        content = read_file(script_dir, row.entrypoint)
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="source missing")
    return JSONResponse({"content": content})


@router.post("/{script_id}/run", status_code=201)
async def run_script(script_id: int, request: Request,
                    user: User = Depends(current_user)) -> RunOut:
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot trigger")
    # Body is optional — a manual trigger without params sends no body at
    # all. Read it manually so we accept missing/empty/{} without 422,
    # but still let the Pydantic validator surface invalid params_json
    # values as 422.
    try:
        raw = await request.json()
    except json.JSONDecodeError:
        # Starlette's Request.json() raises json.JSONDecodeError when the
        # body isn't valid JSON. Tolerate it here so empty/garbage bodies
        # behave the same as no body at all (params_json stays None);
        # downstream consumers shouldn't see non-JSON as a 500.
        raw = None
    if raw is None or raw == {}:
        body = _ManualRunBody(params_json=None)
    else:
        try:
            body = _ManualRunBody.model_validate(raw)
        except ValidationError as exc:
            # exc.errors() may contain non-JSON-serializable ctx (e.g. the
            # raw ValueError instance); FastAPI normally strips those when
            # raising 422 from a declared body model, but since we validate
            # manually we have to do it ourselves.
            safe = [
                {k: v for k, v in err.items() if k != "ctx"}
                for err in exc.errors()
            ]
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, detail=safe
            )
    return await _trigger_run(
        request.app, script_id, user, params_json=body.params_json,
    )


@router.get("/{script_id}/files")
async def list_files_endpoint(
    script_id: int, request: Request, user: User = Depends(current_user),
) -> FileListOut:
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    script_dir = storage / Path(row.source_path).parent
    entries = list_files(script_dir, entrypoint=row.entrypoint)
    return FileListOut(entries=entries)


@router.get("/{script_id}/files/{file_path:path}")
async def get_file_endpoint(
    script_id: int, file_path: str, request: Request,
    user: User = Depends(current_user),
) -> JSONResponse:
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    script_dir = storage / Path(row.source_path).parent
    try:
        content = read_file(script_dir, file_path)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file not found")
    return JSONResponse({"content": content})


@router.put("/{script_id}/files/{file_path:path}")
async def put_file_endpoint(
    script_id: int, file_path: str, body: FileContentIn,
    request: Request, user: User = Depends(current_user),
) -> FileEntry:
    _require(user)
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    script_dir = storage / Path(row.source_path).parent
    try:
        return write_file(script_dir, file_path, body.content)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{script_id}/files/{file_path:path}", status_code=204)
async def delete_file_endpoint(
    script_id: int, file_path: str, request: Request,
    user: User = Depends(current_user),
):
    _require(user)
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    script_dir = storage / Path(row.source_path).parent
    try:
        delete_file(script_dir, file_path, entrypoint=row.entrypoint)
    except ValueError as e:
        if "entrypoint" in str(e):
            raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="file not found")
    return None


@router.post("/{script_id}/files", status_code=201)
async def create_file_endpoint(
    script_id: int, body: FileCreateIn, request: Request,
    user: User = Depends(current_user),
) -> FileEntry:
    _require(user)
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    script_dir = storage / Path(row.source_path).parent
    files = list_files(script_dir, entrypoint=row.entrypoint)
    if len(files) >= 50:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="max 50 files",
        )
    try:
        return write_file(script_dir, body.path, body.content)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
