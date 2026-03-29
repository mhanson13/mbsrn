from __future__ import annotations

import os

from app.core.config import get_settings


def test_pytest_sets_app_env_default() -> None:
    app_env = os.getenv("APP_ENV")
    assert app_env is not None
    if app_env != "ci":
        assert app_env == "test"


def test_settings_load_under_test_or_ci_app_env() -> None:
    settings = get_settings()
    assert settings.app_env in {"test", "ci"}
