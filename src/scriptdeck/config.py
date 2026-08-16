from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SCRIPTDECK_",
        env_file=None,
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765
    db_path: str = "scriptdeck.db"
    storage_dir: str = "storage"
    runner_concurrency: int = 4
    scheduler_interval: int = 5
    audit_retention_days: int = 90
    log_buffer_lines: int = 200

    # Required on real boot; nullable here so tests can construct Settings()
    jwt_secret: str | None = None
    env_encryption_key: str | None = None  # base64, 32 bytes

    @property
    def storage_dir_path(self) -> Path:
        return Path(self.storage_dir)
