from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    from sqlalchemy import text

    engine = request.app.state.engine
    db_ok = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = "down"
    sched_ok = "ok" if getattr(request.app.state, "scheduler_running", False) else "stopped"
    overall = "ok" if db_ok == "ok" and sched_ok in ("ok", "stopped") else "degraded"
    return {"status": overall, "db": db_ok, "scheduler": sched_ok}
