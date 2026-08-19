from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class ScriptRow:
    id: int
    name: str
    language: str
    source_path: str
    requirements_path: str | None
    interpreter_path: str | None
    created_at: str
    updated_at: str
    description: str | None
    user_id: int | None
    entrypoint: str


def _table():
    from kindling.db.models import scripts
    return scripts


async def create_script(
    session: AsyncSession,
    *,
    name: str,
    language: str,
    source_path: str,
    description: str | None = None,
    user_id: int,
) -> ScriptRow:
    t = _table()
    stmt = (
        insert(t)
        .values(
            name=name,
            language=language,
            source_path=source_path,
            description=description,
            user_id=user_id,
        )
        .returning(*t.c)
    )
    return ScriptRow(**(await session.execute(stmt)).mappings().one())


async def get_script(session: AsyncSession, script_id: int) -> ScriptRow | None:
    t = _table()
    row = (await session.execute(select(t).where(t.c.id == script_id))).mappings().one_or_none()
    return ScriptRow(**row) if row else None


async def list_scripts(
    session: AsyncSession,
    language: str | None = None,
    q: str | None = None,
    limit: int = 50,
    user_id: int | None = None,
) -> list[ScriptRow]:
    t = _table()
    stmt = select(t).order_by(t.c.id.desc()).limit(limit)
    if language:
        stmt = stmt.where(t.c.language == language)
    if q:
        stmt = stmt.where(t.c.name.like(f"%{q}%"))
    if user_id is not None:
        stmt = stmt.where(t.c.user_id == user_id)
    return [ScriptRow(**r) for r in (await session.execute(stmt)).mappings().all()]


async def update_script(
    session: AsyncSession, script_id: int, *, name: str | None = None,
    description: str | None = None, source_path: str | None = None,
    entrypoint: str | None = None,
) -> bool:
    values = {k: v for k, v in (
        ("name", name), ("description", description),
        ("source_path", source_path), ("entrypoint", entrypoint),
    ) if v is not None}
    if not values:
        return True
    t = _table()
    result = await session.execute(update(t).where(t.c.id == script_id).values(**values))
    return bool(result.rowcount)


async def delete_script(session: AsyncSession, script_id: int) -> bool:
    t = _table()
    result = await session.execute(delete(t).where(t.c.id == script_id))
    return bool(result.rowcount)
