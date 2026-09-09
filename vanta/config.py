"""Runtime configuration for every Vanta process (validator, miners, tooling).

Settings are read from the environment with the ``VANTA_`` prefix, falling back to
a local ``.env`` file. See ``.env.example`` for the supported keys.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
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

    # Submission window (§7): miners have this long to answer before the deadline. It
    # must stay well below horizon_seconds — ForecastTask enforces that structurally.
    submission_window_seconds: int = Field(default=30, gt=0)

    # Market-data shape used by the live neurons.
    candle_interval_seconds: int = Field(default=60, gt=0)
    lookback_candles: int = Field(default=600, gt=0)

    # --- Bittensor chain layer (Phase 5) -------------------------------------------
    # Wallet *names* only: key material lives in ~/.bittensor/wallets and never in this
    # repo or in configuration (§45). Only the hotkey is used at runtime.
    netuid: int = Field(default=1, ge=0)
    chain_network: str = "local"
    wallet_name: str = "default"
    wallet_hotkey: str = "default"

    # The miner's HTTP endpoint. ``axon_host``/``axon_port`` are what the process binds;
    # ``axon_announce_ip`` is the public address published on chain via ServeAxon, which
    # differs from the bind address behind NAT or in Docker.
    axon_host: str = "0.0.0.0"
    axon_port: int = Field(default=8091, gt=0, le=65535)
    axon_announce_ip: str | None = None

    # Validator -> miner HTTP call budget. Kept at or below the submission window so a
    # slow miner times out rather than blowing through its own deadline.
    request_timeout_seconds: float = Field(default=10.0, gt=0.0)

    # Which reference engine a miner process serves (§11).
    miner_engine: str = "momentum"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        level = value.upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if level not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return level

    @model_validator(mode="after")
    def _submission_window_fits_horizon(self) -> Settings:
        """Fail at startup rather than on the first task the generator refuses to build.

        A submission window reaching the resolution time would let a miner observe the
        outcome it is being asked to forecast (§27, §29).
        """
        if self.submission_window_seconds >= self.horizon_seconds:
            raise ValueError(
                f"submission_window_seconds ({self.submission_window_seconds}) must be "
                f"< horizon_seconds ({self.horizon_seconds})"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached process settings."""
    return Settings()
