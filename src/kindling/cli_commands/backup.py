"""Tar db + storage backup helpers.

Reads KINDLING_DB_PATH and KINDLING_STORAGE_DIR from env (via Settings
defaults: db_path="kindling.db", storage_dir="storage"). For real ops the
operator must set these env vars before running `kindling backup` or
`kindling restore`.
"""
from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path

from kindling.config import Settings


def run(output: str) -> int:
    s = Settings()
    db = Path(s.db_path)
    storage = Path(s.storage_dir)
    if not db.exists():
        raise FileNotFoundError(db)
    with tarfile.open(output, "w:gz") as tar:
        tar.add(db, arcname=db.name)
        if storage.exists():
            tar.add(storage, arcname=storage.name)
    print(f"wrote {output}")
    return 0


def restore(input: str) -> int:
    s = Settings()
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(input, "r:gz") as tar:
            tar.extractall(tmp)
        db_src = Path(tmp) / Path(s.db_path).name
        storage_src = Path(tmp) / Path(s.storage_dir).name
        if db_src.exists():
            shutil.copy(db_src, s.db_path)
        if storage_src.exists():
            target = Path(s.storage_dir)
            target.mkdir(parents=True, exist_ok=True)
            for entry in storage_src.iterdir():
                dest = target / entry.name
                if entry.is_dir():
                    shutil.copytree(entry, dest, dirs_exist_ok=True)
                else:
                    shutil.copy(entry, dest)
    print(f"restored from {input}")
    return 0
