from __future__ import annotations

import os
import platform


_RUNTIME_METADATA_MAX_LEN = 120


def _normalize(value: object, *, max_len: int = _RUNTIME_METADATA_MAX_LEN) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = " ".join(text.split())
    if not compact:
        return None
    if len(compact) > max_len:
        return compact[:max_len]
    return compact


def _first_nonempty_env(*names: str) -> str | None:
    for name in names:
        value = _normalize(os.getenv(name))
        if value:
            return value
    return None


def get_runtime_build_metadata(*, app_env: str | None = None) -> dict[str, str]:
    resolved_app_env = _normalize(app_env) or _normalize(os.getenv("APP_ENV")) or "unknown"
    git_commit = (
        _first_nonempty_env(
            "MBSRN_GIT_COMMIT",
            "GIT_COMMIT_SHA",
            "GIT_COMMIT",
            "SOURCE_COMMIT_SHA",
            "COMMIT_SHA",
        )
        or "unknown"
    )
    build_version = (
        _first_nonempty_env(
            "MBSRN_BUILD_VERSION",
            "BUILD_VERSION",
            "APP_VERSION",
            "RELEASE_VERSION",
        )
        or "unknown"
    )
    build_time = (
        _first_nonempty_env(
            "MBSRN_BUILD_TIME",
            "BUILD_TIME",
            "BUILD_TIMESTAMP",
            "SOURCE_DATE_EPOCH",
        )
        or "unknown"
    )
    image_tag = (
        _first_nonempty_env(
            "MBSRN_IMAGE_TAG",
            "IMAGE_TAG",
            "IMAGE_VERSION",
            "CONTAINER_IMAGE_TAG",
        )
        or "unknown"
    )
    python_version = _normalize(platform.python_version()) or "unknown"
    return {
        "app_env": resolved_app_env,
        "git_commit": git_commit,
        "build_version": build_version,
        "build_time": build_time,
        "image_tag": image_tag,
        "python_version": python_version,
    }
