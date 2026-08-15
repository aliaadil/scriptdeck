from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/auth")


@router.get("/me")
async def me_stub() -> dict[str, str]:
    """Replaced by full impl in Task 5."""
    return {"stub": "true"}