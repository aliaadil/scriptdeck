from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kindling.auth.passwords import hash_password


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    role: str
    created_at: str
    last_login_at: str | None
    timezone: str = "UTC"


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
    from kindling.db.models import users

    return users


async def count_users(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(_table())
    return int((await session.execute(stmt)).scalar() or 0)


async def update_last_login(session: AsyncSession, user_id: int) -> None:
    now = datetime.now(UTC).isoformat()
    stmt = update(_table()).where(_table().c.id == user_id).values(last_login_at=now)
    await session.execute(stmt)


async def update_password(session: AsyncSession, user_id: int, new_password: str) -> None:
    stmt = update(_table()).where(_table().c.id == user_id).values(
        password_hash=hash_password(new_password)
    )
    await session.execute(stmt)


async def list_users(session: AsyncSession) -> list[User]:
    stmt = select(_table()).order_by(_table().c.id)
    return [User(**r) for r in (await session.execute(stmt)).mappings().all()]


async def delete_user(session: AsyncSession, user_id: int) -> bool:
    from sqlalchemy import delete

    stmt = delete(_table()).where(_table().c.id == user_id)
    result = await session.execute(stmt)
    return result.rowcount > 0  # type: ignore[no-any-return]


async def update_role(session: AsyncSession, user_id: int, role: str) -> bool:
    stmt = update(_table()).where(_table().c.id == user_id).values(role=role)
    result = await session.execute(stmt)
    return result.rowcount > 0  # type: ignore[no-any-return]
