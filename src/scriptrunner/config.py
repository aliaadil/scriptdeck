"""Runtime configuration for ScriptRunner.

All paths and listener values are overrideable through environment variables so
local development and a systemd/container deployment use the same code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _positive_int(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must not be negative")
    return parsed


@dataclass(frozen=True)
class Settings:
    db_path: Path = Path("scriptrunner.db")
    storage_dir: Path = Path("storage")
    host: str = "127.0.0.1"
    port: int = 8765

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            db_path=Path(os.getenv("SCRIPTRUNNER_DB_PATH", "scriptrunner.db")),
            storage_dir=Path(os.getenv("SCRIPTRUNNER_STORAGE_DIR", "storage")),
            host=os.getenv("SCRIPTRUNNER_HOST", "127.0.0.1"),
            port=_positive_int(os.getenv("SCRIPTRUNNER_PORT", "8765"), "SCRIPTRUNNER_PORT"),
        )
