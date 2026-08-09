"""Runtime configuration for ScriptRunner.

All paths and listener values are overrideable through environment variables so
local development and a systemd/container deployment use the same code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .auth import BasicAuth, parse_basic_auth


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
    basic_auth: BasicAuth | None = None

    @classmethod
    def from_env(cls) -> Settings:
        # The README and operator docs advertise `SCRIPTDECK_*` env-var names —
        # that's the canonical contract users see. The legacy `SCRIPTRUNNER_*`
        # names are accepted as fallbacks for users who already deployed
        # against the v0.1-era code. `SCRIPTDECK_*` wins when both are set.
        return cls(
            db_path=Path(os.getenv("SCRIPTDECK_DB_PATH")
                         or os.getenv("SCRIPTRUNNER_DB_PATH", "scriptrunner.db")),
            storage_dir=Path(os.getenv("SCRIPTDECK_STORAGE_DIR")
                             or os.getenv("SCRIPTRUNNER_STORAGE_DIR", "storage")),
            host=os.getenv("SCRIPTDECK_HOST")
                  or os.getenv("SCRIPTRUNNER_HOST", "127.0.0.1"),
            port=_positive_int(
                os.getenv("SCRIPTDECK_PORT")
                or os.getenv("SCRIPTRUNNER_PORT", "8765"),
                "SCRIPTDECK_PORT",
            ),
            basic_auth=parse_basic_auth(os.getenv("SCRIPTDECK_BASIC_AUTH")),
        )
