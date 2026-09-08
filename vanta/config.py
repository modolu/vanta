"""Runtime configuration for every Vanta process (validator, miners, tooling).

Settings are read from the environment with the ``VANTA_`` prefix, falling back to
a local ``.env`` file. See ``.env.example`` for the supported keys.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "testnet", "mainnet"]


class Settings(BaseSettings):
    """Process-wide settings. Instantiate via :func:`get_settings`."""

    model_config = SettingsConfigDict(
        env_prefix="VANTA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "local"

    # Logging
    log_level: str = "INFO"

    # Storage. SQLite is the local default; the URL must stay PostgreSQL-compatible
    # so the same schema runs under Docker/testnet.
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/vanta.db"

    # Forecast task definition (ARCHITECTURE.md §8, §9).
    asset: str = "ETH-USD"
    horizon_seconds: int = Field(default=900, gt=0)

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return level


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings."""
    return Settings()
