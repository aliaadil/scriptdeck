from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from kindling.config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    url = f"sqlite+aiosqlite:///{settings.db_path}"
    return create_async_engine(url, echo=False, future=True)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
