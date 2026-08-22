"""POST /scripts/{script_id}/install — manually install a package into a
script's venv (Python) or node_modules (Node).

The escape hatch for the case where a run failed with
``ModuleNotFoundError: No module named 'boto3'`` and the user wants to
recover without editing requirements.txt / package.json by hand.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import insert, select, update

from kindling.api.deps import require_script_owner
from kindling.auth.deps import current_user
from kindling.auth.users import User
from kindling.services import install as install_service
from kindling.services import script_service

router = APIRouter(prefix="/scripts")


# Mirrors the regex in services.install._PACKAGE_RE — duplicated here so
# the API rejects bad input before we ever shell out, even when the
# service module is monkey-patched out in tests.
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_.+:\-/@\[\]^~=<>!*,]+$")


class InstallIn(BaseModel):
    packages: list[str] = Field(min_length=1, max_length=20)

    @field_validator("packages")
    @classmethod
    def _no_unsafe_chars(cls, v: list[str]) -> list[str]:
        for p in v:
            if not _PACKAGE_NAME_RE.match(p):
                raise ValueError(f"invalid package name: {p!r}")
        return v


class InstallOut(BaseModel):
    output: str
    installed: list[str]


def _deps_table():
    from kindling.db.models import script_deps
    return script_deps


@router.post("/{script_id}/install", status_code=200)
async def install_packages(
    script_id: int, body: InstallIn, request: Request,
    user: User = Depends(current_user),
) -> InstallOut:
    """Install ``packages`` into this script's environment. Requires
    script ownership (or admin). On success, updates ``script_deps`` so
    the next run also auto-installs the same package.
    """
    if user.role == "viewer":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="viewer cannot modify")
    sf = request.app.state.session_factory
    storage: Path = request.app.state.settings.storage_dir_path
    async with sf() as s:
        owner_id = await require_script_owner(s, script_id, user)
        row = await script_service.get_script(s, script_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
        language = row.language
    # Pre-check here (in addition to the service-layer guard) so a bash
    # script gets a clean 400 from the API even if the underlying
    # install_packages function is monkey-patched out in tests.
    if language not in ("python", "node"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"install not supported for language={language!r}",
        )
    try:
        output = await install_service.install_packages(
            language=language,
            user_id=owner_id,
            script_id=script_id,
            storage_dir=storage,
            packages=body.packages,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except RuntimeError as exc:
        # pip/npm exited non-zero — surface the underlying output so the
        # UI can show "why didn't boto3 install?" without a second round
        # trip.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )

    # Persist to script_deps so subsequent runs auto-provision. Merge with
    # any existing manual list rather than overwriting — installing
    # ``boto3`` should not blow away ``requests`` someone added earlier.
    now = datetime.now(UTC).isoformat()
    async with sf() as s:
        t = _deps_table()
        existing = (
            await s.execute(select(t).where(t.c.script_id == script_id))
        ).mappings().one_or_none()
        if existing:
            try:
                current = json.loads(existing["deps_json"])
            except (TypeError, ValueError):
                current = []
            if not isinstance(current, list):
                current = []
            merged = list(dict.fromkeys([*current, *body.packages]))
            await s.execute(
                update(t).where(t.c.script_id == script_id).values(
                    deps_json=json.dumps(merged),
                    source="manual",
                    updated_at=now,
                )
            )
        else:
            await s.execute(insert(t).values(
                script_id=script_id,
                deps_json=json.dumps(body.packages),
                source="manual",
                updated_at=now,
            ))
        await s.commit()

    return InstallOut(output=output, installed=body.packages)
