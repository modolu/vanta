from __future__ import annotations

import pytest
from pydantic import ValidationError

from vanta.config import Settings, get_settings


def test_defaults_match_locked_mvp_decisions(settings: Settings) -> None:
    assert settings.environment == "local"
    assert settings.asset == "ETH-USD"
    assert settings.horizon_seconds == 900
    assert settings.database_url.startswith("sqlite://")


def test_env_overrides_are_read(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VANTA_HORIZON_SECONDS", "3600")
    monkeypatch.setenv("VANTA_LOG_LEVEL", "debug")
    loaded = Settings()
    assert loaded.horizon_seconds == 3600
    assert loaded.log_level == "DEBUG"


def test_horizon_must_be_positive(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VANTA_HORIZON_SECONDS", "0")
    with pytest.raises(ValidationError):
        Settings()


def test_rejects_unknown_log_level(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VANTA_LOG_LEVEL", "chatty")
    with pytest.raises(ValidationError):
        Settings()


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    assert get_settings() is get_settings()
