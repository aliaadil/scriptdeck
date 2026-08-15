from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scriptdeck.auth.passwords import hash_password


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    role: str
    created_at: str
    last_login_at: str | None


async def create_user(
    session: AsyncSession, email: str, password: str, role: str
) -> User:
    from sqlalchemy import insert

    pw_hash = hash_password(password)
    stmt = (
        insert(_table())
        .values(email=email, password_hash=pw_hash, role=role)
        .returning(
            _table().c.id,
            _table().c.email,
            _table().c.password_hash,
            _table().c.role,
            _table().c.created_at,
            _table().c.last_login_at,
        )
    )
    result = await session.execute(stmt)
    row = result.mappings().one()
    return User(**row)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(_table()).where(_table().c.email == email)
    row = (await session.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None
    return User(**row)


async def get_by_id(session: AsyncSession, user_id: int) -> User | None:
    stmt = select(_table()).where(_table().c.id == user_id)
    row = (await session.execute(stmt)).mappings().one_or_none()
    if row is None:
        return None
    return User(**row)


def _table():
    # Defer import to avoid circular deps with db package.
    from scriptdeck.db.models import users

    return users