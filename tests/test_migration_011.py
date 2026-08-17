import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine

from kindling.db.migrations import run_migrations_sync


def test_schedules_have_v2_columns(tmp_path: Path):
    db_path = tmp_path / "t.db"
    run_migrations_sync(str(db_path))
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")

    async def _cols(table: str) -> set[str]:
        async with engine.connect() as conn:
            rows = (await conn.exec_driver_sql(
                f"SELECT name FROM pragma_table_info('{table}')"
            )).fetchall()
        return {r[0] for r in rows}

    async def _check():
        s_cols = await _cols("schedules")
        r_cols = await _cols("runs")
        u_cols = await _cols("users")
        await engine.dispose()
        return s_cols, r_cols, u_cols

    s_cols, r_cols, u_cols = asyncio.run(_check())
    assert {"timezone", "blackout_dates", "include_days", "overlap_policy",
            "queue_max", "queue_dropped"}.issubset(s_cols)
    assert {"attempt", "parent_run_id", "next_attempt_at", "skip_reason"}.issubset(r_cols)
    assert "timezone" in u_cols
