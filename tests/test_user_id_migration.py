from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from kindling.db.migrations import run_migrations_sync


def test_scripts_user_id_column_exists(tmp_path: Path):
    db_path = tmp_path / "t.db"
    run_migrations_sync(str(db_path))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def _check():
        async with engine.connect() as conn:
            rows = (await conn.exec_driver_sql(
                "SELECT name FROM pragma_table_info('scripts')"
            )).fetchall()
        await engine.dispose()
        return {r[0] for r in rows}

    names = asyncio.run(_check())
    assert "user_id" in names