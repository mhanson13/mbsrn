from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

import pytest
import requests

from app.integrations.migration_media_storage import (
    GoogleCloudStorageMigrationMediaStorage,
    LocalMigrationMediaStorage,
    MigrationMediaStorageError,
)


class _FakeResponse:
    def __init__(self, *, status_code: int, body: dict[str, object] | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._body = body
        self.content = content

    def json(self) -> dict[str, object]:
        if self._body is None:
            raise ValueError("not json")
        return self._body


class _SharedFakeGCSSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.objects: dict[tuple[str, str], bytes] = {}
        self.generations: dict[str, int] = {}
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        params = dict(kwargs.get("params", {}) or {})
        if method == "POST":
            key = str(params["name"])
            generation = self.generations.get(key, 0) + 1
            self.generations[key] = generation
            self.objects[(key, str(generation))] = bytes(kwargs.get("data", b""))
            return _FakeResponse(
                status_code=200,
                body={"name": key, "generation": str(generation)},
            )
        encoded_key = url.rsplit("/o/", 1)[-1]
        key = unquote(encoded_key)
        generation = str(params.get("generation") or self.generations.get(key) or "")
        payload = self.objects.get((key, generation))
        if payload is None:
            return _FakeResponse(status_code=404)
        return _FakeResponse(status_code=200, content=payload)


def test_local_storage_records_digest_and_blocks_path_escape(tmp_path: Path) -> None:
    storage = LocalMigrationMediaStorage(root=tmp_path)

    stored = storage.write(key="business/site/photo.png", payload=b"image-bytes", content_type="image/png")

    assert stored.provider == "local"
    assert stored.size_bytes == len(b"image-bytes")
    assert stored.generation == stored.sha256
    assert storage.read(key=stored.key, generation=stored.generation) == b"image-bytes"
    with pytest.raises(MigrationMediaStorageError):
        storage.write(key="../outside.png", payload=b"bad", content_type="image/png")


def test_gcs_generation_can_be_read_by_a_separate_storage_instance() -> None:
    shared_gcs = _SharedFakeGCSSession()
    writer = GoogleCloudStorageMigrationMediaStorage(
        bucket="mbsrn-media-test",
        access_token_provider=lambda: "short-lived-token",
        http_session=shared_gcs,
    )
    reader = GoogleCloudStorageMigrationMediaStorage(
        bucket="mbsrn-media-test",
        access_token_provider=lambda: "short-lived-token",
        http_session=shared_gcs,
    )

    stored = writer.write(
        key="business-1/site-1/asset.png",
        payload=b"first-generation",
        content_type="image/png",
    )
    writer.write(
        key="business-1/site-1/asset.png",
        payload=b"second-generation",
        content_type="image/png",
    )

    assert stored.provider == "gcs"
    assert stored.bucket == "mbsrn-media-test"
    assert stored.generation == "1"
    assert reader.read(key=stored.key, generation=stored.generation) == b"first-generation"
    read_call = shared_gcs.calls[-1]
    assert read_call["params"] == {"alt": "media", "generation": "1"}
    assert read_call["headers"] == {"Authorization": "Bearer short-lived-token"}


def test_gcs_permission_error_is_safe_and_actionable() -> None:
    class _DeniedSession(requests.Session):
        def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
            del method, url, kwargs
            return _FakeResponse(status_code=403, content=b"provider response may contain secrets")

    storage = GoogleCloudStorageMigrationMediaStorage(
        bucket="mbsrn-media-test",
        access_token_provider=lambda: "secret-token",
        http_session=_DeniedSession(),
    )

    with pytest.raises(MigrationMediaStorageError) as error:
        storage.read(key="business/site/asset.png")

    message = str(error.value)
    assert "bucket-scoped object permissions" in message
    assert "secret-token" not in message
    assert "provider response" not in message
