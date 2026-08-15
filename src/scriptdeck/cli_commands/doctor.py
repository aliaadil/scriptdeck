"""Validate ScriptDeck config + DB state.

Runs `run_migrations` against the configured DB (SCRIPTDECK_DB_PATH or
default). The migration runner is idempotent — it creates tables only when
missing and skips versions already recorded in `schema_version` — so this
is safe to run against production. Pointing at a fresh DB will bootstrap
the schema; pointing at an up-to-date DB is a no-op.
"""
from __future__ import annotations

import asyncio

from scriptdeck.config import Settings
from scriptdeck.db import make_engine, run_migrations


def run() -> int:
    s = Settings()
    print(f"db_path:        {s.db_path}")
    print(f"storage_dir:    {s.storage_dir}")
    print(f"runner_conc:    {s.runner_concurrency}")
    print(f"sched_interval: {s.scheduler_interval}s")

    async def check():
        engine = make_engine(s)
        try:
            await run_migrations(engine)
            from sqlalchemy import text
            async with engine.connect() as conn:
                ver = (await conn.execute(text("SELECT MAX(version) FROM schema_version"))).scalar()
                runs = (await conn.execute(text("SELECT COUNT(*) FROM runs"))).scalar()
                orphans = (await conn.execute(text(
                    "SELECT COUNT(*) FROM runs WHERE script_id NOT IN (SELECT id FROM scripts)"
                ))).scalar()
            print(f"schema_version: {ver}")
            print(f"runs total:     {runs}")
            print(f"orphan runs:    {orphans}")
            return 0 if orphans == 0 else 1
        finally:
            await engine.dispose()

    return asyncio.run(check())
