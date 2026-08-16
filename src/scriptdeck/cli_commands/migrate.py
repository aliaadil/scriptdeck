"""Copy a v1 ScriptDeck SQLite DB + storage into a fresh v2 DB.

v1 schema: scripts, schedules, runs, logs.
v2 inherits all four tables via migrations 001-006 (applied on the fresh
v2 DB before this runs). Then we copy rows directly. No transformation
required because v2 didn't change the four original tables.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite


async def _copy_table(src: aiosqlite.Connection, dst: aiosqlite.Connection, table: str) -> int:
    cur = await src.execute(f"SELECT * FROM {table}")
    rows = await cur.fetchall()
    cols = [c[0] for c in cur.description]
    if not rows:
        return 0
    placeholders = ",".join(["?"] * len(cols))
    col_list = ",".join(cols)
    await dst.executemany(
        f"INSERT OR IGNORE INTO {table} ({col_list}) VALUES ({placeholders})",
        rows,
    )
    await dst.commit()
    return len(rows)


async def run_async(v1_db: str, v1_storage: str, v2_db: str, v2_storage: str) -> int:
    # Caller must have already created v2 DB and applied migrations.
    v1_db_p = Path(v1_db)
    if not v1_db_p.exists():
        raise FileNotFoundError(v1_db)
    Path(v2_storage).mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(v1_db)) as src, aiosqlite.connect(v2_db) as dst:
        total = 0
        for table in ("scripts", "schedules", "runs", "logs"):
            total += await _copy_table(src, dst, table)

    # Copy storage scripts/* if present.
    src_storage = Path(v1_storage) / "scripts"
    if src_storage.exists():
        dest_storage = Path(v2_storage) / "scripts"
        dest_storage.mkdir(parents=True, exist_ok=True)
        for entry in src_storage.iterdir():
            target = dest_storage / entry.name
            if entry.is_dir():
                shutil.copytree(entry, target, dirs_exist_ok=True)
    return total


def run(v1_db: str, v1_storage: str, v2_db: str, v2_storage: str) -> int:
    import asyncio
    n = asyncio.run(run_async(v1_db, v1_storage, v2_db, v2_storage))
    print(f"migrated {n} rows from v1 to v2")
    return 0
