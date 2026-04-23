from __future__ import annotations

from app.core.runtime_metadata import get_runtime_build_metadata


def test_runtime_build_metadata_uses_env_values(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("MBSRN_GIT_COMMIT", "abc123")
    monkeypatch.setenv("MBSRN_BUILD_VERSION", "2026.04.23-1")
    monkeypatch.setenv("MBSRN_BUILD_TIME", "2026-04-23T12:34:56Z")
    monkeypatch.setenv("MBSRN_IMAGE_TAG", "mbsrn-api:2026.04.23")

    payload = get_runtime_build_metadata()

    assert payload["app_env"] == "production"
    assert payload["git_commit"] == "abc123"
    assert payload["build_version"] == "2026.04.23-1"
    assert payload["build_time"] == "2026-04-23T12:34:56Z"
    assert payload["image_tag"] == "mbsrn-api:2026.04.23"
    assert payload["python_version"]


def test_runtime_build_metadata_has_unknown_fallbacks(monkeypatch) -> None:
    for variable_name in (
        "APP_ENV",
        "MBSRN_GIT_COMMIT",
        "GIT_COMMIT_SHA",
        "GIT_COMMIT",
        "SOURCE_COMMIT_SHA",
        "COMMIT_SHA",
        "MBSRN_BUILD_VERSION",
        "BUILD_VERSION",
        "APP_VERSION",
        "RELEASE_VERSION",
        "MBSRN_BUILD_TIME",
        "BUILD_TIME",
        "BUILD_TIMESTAMP",
        "SOURCE_DATE_EPOCH",
        "MBSRN_IMAGE_TAG",
        "IMAGE_TAG",
        "IMAGE_VERSION",
        "CONTAINER_IMAGE_TAG",
    ):
        monkeypatch.delenv(variable_name, raising=False)

    payload = get_runtime_build_metadata()

    assert payload["app_env"] == "unknown"
    assert payload["git_commit"] == "unknown"
    assert payload["build_version"] == "unknown"
    assert payload["build_time"] == "unknown"
    assert payload["image_tag"] == "unknown"
    assert payload["python_version"]
