from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="KINDLING_",
        env_file=".env",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765
    db_path: str = "kindling.db"
    storage_dir: str = "storage"
    runner_concurrency: int = 4
    scheduler_interval: int = 5
    sandbox_enabled: bool = False
    audit_retention_days: int = 90
    log_buffer_lines: int = 200
    log_retention_days: int = 7
    gc_interval_seconds: int = 3600
    feature_schedules_v2: bool = False

    # Required on real boot; nullable here so tests can construct Settings()
    jwt_secret: str | None = None
    env_encryption_key: str | None = None  # base64, 32 bytes

    @property
    def storage_dir_path(self) -> Path:
        return Path(self.storage_dir)


def get_settings() -> Settings:
    """Return a fresh Settings instance.

    Intentionally not cached: callers (e.g. `run_script`) may run under
    tests that patch env vars via `monkeypatch.setenv`, and a process-wide
    cache would freeze the first observation. In production, Settings() is
    cheap and is invoked once per request anyway.
    """
    return Settings()
