from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_DB_PATH = Path('./data/kindling.db')
DEFAULT_CONFIG_FILE = Path('kindling.toml')
ENV_PREFIX = 'KINDLING_'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix=ENV_PREFIX,
        env_file=".env",
        extra="ignore",
    )

    host: str = "127.0.0.1"
    port: int = 8765
    db_path: Path = DEFAULT_DB_PATH
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

    # Test-only escape hatch: skip the fail-fast check on missing
    # env_encryption_key. Production code must never set this True.
    allow_insecure_defaults_for_tests: bool = False

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


def _resolve_config_path() -> Path | None:
    """Return the path to the TOML config file, or None if not found.

    Resolution order:
    1. ``KINDLING_CONFIG`` env var (explicit path).
    2. ``./kindling.toml`` in the current working directory.
    """
    explicit = os.environ.get(f"{ENV_PREFIX}CONFIG")
    if explicit:
        return Path(explicit)
    candidate = DEFAULT_CONFIG_FILE
    if candidate.exists():
        return candidate
    return None


def _load_toml_overrides() -> dict[str, Any]:
    path = _resolve_config_path()
    if path is None:
        return {}
    try:
        with path.open("rb") as fp:
            data = tomllib.load(fp)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


_cached_config: Settings | None = None


def reset_cache() -> None:
    """Clear the cached config so the next ``load_config`` re-reads env/TOML."""
    global _cached_config
    _cached_config = None


def load_config() -> Settings:
    """Load the effective ``Settings`` instance.

    Priority (lowest to highest): TOML config file -> ``KINDLING_*`` env vars.
    The result is cached per call to ``reset_cache`` so tests can mutate
    environment between scenarios.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    overrides = _load_toml_overrides()
    _cached_config = Settings(**overrides)
    return _cached_config
