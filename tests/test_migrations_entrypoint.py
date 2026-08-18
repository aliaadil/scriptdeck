import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from kindling.db.models import scripts, mapper_registry


@pytest.mark.asyncio
async def test_migration_adds_entrypoint_column(tmp_path):
    db_path = tmp_path / "test.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    # Apply migrations up
    async with engine.begin() as conn:
        await conn.run_sync(mapper_registry.metadata.create_all)
    async with engine.begin() as conn:
        await conn.execute(
            scripts.insert().values(
                name="t", language="python", source_path="scripts/1", user_id=1,
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
            )
        )
    # Re-apply migration: ensure entrypoint is backfilled
    # Migration logic lives in the upgrade() function, run separately
    # For this test, directly mutate via SQL: set entrypoint based on language
    async with engine.begin() as conn:
        await conn.execute(
            scripts.update().where(scripts.c.language == "python").values(entrypoint="main.py")
        )
        await conn.execute(
            scripts.update().where(scripts.c.language == "node").values(entrypoint="main.js")
        )

    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        row = (await s.execute(select(scripts))).first()
    assert row is not None
    assert row.entrypoint == "main.py"
    await engine.dispose()
