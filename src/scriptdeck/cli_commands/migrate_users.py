"""Move existing flat /storage/scripts/<id>/ data into /storage/users/<uid>/.

Idempotent. Logs every move; dry-run prints moves without applying.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

SUBDIRS = ("scripts", "envs", "venvs", "node_modules")


def migrate_users_run(storage_dir: str, db_path: str, dry_run: bool = True) -> int:
    storage = Path(storage_dir)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, user_id FROM scripts WHERE user_id IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    n = 0
    for script_id, user_id in rows:
        user_root = storage / "users" / str(user_id)
        for sub in SUBDIRS:
            src = storage / sub / str(script_id)
            if not src.exists():
                continue
            dst = user_root / sub / str(script_id)
            if dst.exists():
                log.info("skip %s -> %s (already exists)", src, dst)
                continue
            log.info("move %s -> %s%s", src, dst, " [dry-run]" if dry_run else "")
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
        logs_src = storage / "logs" / f"{script_id}.log"
        if logs_src.exists():
            dst = user_root / "logs" / f"{script_id}.log"
            if not dst.exists():
                log.info("move %s -> %s%s", logs_src, dst, " [dry-run]" if dry_run else "")
                if not dry_run:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(logs_src), str(dst))
        n += 1
    print(f"migration {'planned' if dry_run else 'applied'}: {n} scripts")
    return 0
