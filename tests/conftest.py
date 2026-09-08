"""Shared pytest fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from vanta.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Keep the cached singleton from leaking between tests."""
    get_settings.cache_clear()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    """Settings isolated from the developer's own .env file and environment."""
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.startswith("VANTA_"):
            monkeypatch.delenv(key, raising=False)
    return Settings()
