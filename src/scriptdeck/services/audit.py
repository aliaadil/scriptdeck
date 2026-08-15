from __future__ import annotations

import json
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession


async def record(
    session: AsyncSession,
    user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: int | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    meta = meta or {}
    stmt = (
        insert(__import__("scriptdeck.db.models", fromlist=["audit_log"]).audit_log)
        .values(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            meta_json=json.dumps(meta),
        )
    )
    await session.execute(stmt)