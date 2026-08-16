from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class Invite:
    id: int
    email: str
    token: str
    role: str
    expires_at: str
    used_at: str | None


def _table():
    from scriptdeck.db.models import invites

    return invites


async def create_invite(
    session: AsyncSession, email: str, role: str, ttl_hours: int = 72
) -> Invite:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(hours=ttl_hours)).isoformat()
    stmt = (
        insert(_table())
        .values(email=email, token=token, role=role, expires_at=expires)
        .returning(
            _table().c.id,
            _table().c.email,
            _table().c.token,
            _table().c.role,
            _table().c.expires_at,
            _table().c.used_at,
        )
    )
    row = (await session.execute(stmt)).mappings().one()
    return Invite(**row)


async def accept_invite(
    session: AsyncSession, token: str
) -> Invite | None:
    stmt = select(_table()).where(_table().c.token == token)
    row = (await session.execute(stmt)).mappings().one_or_none()
    if row is None or row["used_at"] is not None:
        return None
    inv = Invite(**row)
    if datetime.fromisoformat(inv.expires_at) < datetime.now(UTC):
        return None
    await session.execute(
        update(_table())
        .where(_table().c.id == inv.id)
        .values(used_at=datetime.now(UTC).isoformat())
    )
    return inv
