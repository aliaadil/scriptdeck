from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from scriptdeck.auth.deps import current_user
from scriptdeck.auth.users import User

router = APIRouter()


@router.get("/stats")
async def stats(request: Request, user: User = Depends(current_user)) -> dict:
    sf = request.app.state.session_factory
    now = datetime.now(UTC)
    since = (now - timedelta(hours=24)).isoformat()
    from scriptdeck.db.models import runs, scripts
    async with sf() as s:
        total_scripts = (await s.execute(
            select(func.count()).select_from(scripts)
        )).scalar() or 0
        total_runs_24h = (await s.execute(
            select(func.count()).select_from(runs).where(runs.c.started_at >= since)
        )).scalar() or 0
        success = (await s.execute(
            select(func.count()).select_from(runs).where(
                runs.c.started_at >= since, runs.c.status == "success",
            )
        )).scalar() or 0
        running_now = (await s.execute(
            select(func.count()).select_from(runs).where(runs.c.status == "running")
        )).scalar() or 0
        recent = (await s.execute(
            select(runs).order_by(runs.c.id.desc()).limit(10)
        )).mappings().all()
    success_rate = (success / total_runs_24h) if total_runs_24h else 0.0
    return {
        "total_scripts": int(total_scripts),
        "total_runs_24h": int(total_runs_24h),
        "success_rate_24h": float(success_rate),
        "running_now": int(running_now),
        "recent_runs": [dict(r) for r in recent],
    }
