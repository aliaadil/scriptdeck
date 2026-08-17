from __future__ import annotations

from fastapi import APIRouter

from scriptdeck.services.presets import PRESETS

router = APIRouter()


@router.get("/schedule-presets")
async def list_presets() -> list[dict[str, str]]:
    """Public catalog of common cron schedule presets."""
    return PRESETS
