from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import threading
from typing import Callable, Protocol
from urllib.parse import quote

import requests


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class MigrationMediaStorageError(RuntimeError):
    """Safe storage failure that never includes object payloads or credentials."""


class MigrationMediaStorageConfigurationError(MigrationMediaStorageError):
    pass


@dataclass(frozen=True)
class StoredMigrationMediaObject:
    provider: str
    key: str
    generation: str
    content_type: str
    size_bytes: int
    sha256: str
    bucket: str | None = None


class MigrationMediaStorage(Protocol):
    @property
    def provider_name(self) -> str: ...

    def write(self, *, key: str, payload: bytes, content_type: str) -> StoredMigrationMediaObject: ...

    def read(self, *, key: str, generation: str | None = None) -> bytes: ...


def normalize_migration_media_storage_key(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    if not normalized:
        raise MigrationMediaStorageError("Migration media storage key is required.")
    fragments = normalized.split("/")
    if any(fragment in {"", ".", ".."} for fragment in fragments):
        raise MigrationMediaStorageError("Migration media storage key is invalid.")
    return normalized


class LocalMigrationMediaStorage:
    def __init__(self, *, root: Path) -> None:
        try:
            self.root = root.expanduser().resolve()
        except OSError:
            self.root = root.expanduser()

    @property
    def provider_name(self) -> str:
        return "local"

    def write(self, *, key: str, payload: bytes, content_type: str) -> StoredMigrationMediaObject:
        normalized_key = normalize_migration_media_storage_key(key)
        target_path = self._resolve_path(normalized_key)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(payload)
        except OSError as exc:
            raise MigrationMediaStorageError("Migration media could not be written to local storage.") from exc
        digest = hashlib.sha256(payload).hexdigest()
        return StoredMigrationMediaObject(
            provider=self.provider_name,
            key=normalized_key,
            generation=digest,
            content_type=content_type,
            size_bytes=len(payload),
            sha256=digest,
        )

    def read(self, *, key: str, generation: str | None = None) -> bytes:
        del generation
        target_path = self._resolve_path(normalize_migration_media_storage_key(key))
        try:
            if not target_path.is_file():
                raise MigrationMediaStorageError("Migration media payload is unavailable.")
            return target_path.read_bytes()
        except MigrationMediaStorageError:
            raise
        except OSError as exc:
            raise MigrationMediaStorageError("Migration media could not be read from local storage.") from exc

    def _resolve_path(self, key: str) -> Path:
        target_path = (self.root / key).resolve()
        if self.root not in target_path.parents:
            raise MigrationMediaStorageError("Migration media storage path is outside the configured root.")
        return target_path


class GoogleCloudStorageMigrationMediaStorage:
    def __init__(
        self,
        *,
        bucket: str,
        project_id: str | None = None,
        timeout_seconds: int = 30,
        api_base_url: str = "https://storage.googleapis.com",
        access_token_provider: Callable[[], str] | None = None,
        http_session: requests.Session | None = None,
    ) -> None:
        normalized_bucket = str(bucket or "").strip()
        if not normalized_bucket:
            raise MigrationMediaStorageConfigurationError("MIGRATION_MEDIA_GCS_BUCKET is required for GCS storage.")
        if any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for character in normalized_bucket):
            raise MigrationMediaStorageConfigurationError("MIGRATION_MEDIA_GCS_BUCKET is invalid.")
        self.bucket = normalized_bucket
        self.project_id = str(project_id or "").strip() or None
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.api_base_url = str(api_base_url or "").rstrip("/") or "https://storage.googleapis.com"
        self._access_token_provider = access_token_provider
        self._http_session = http_session or requests.Session()
        self._credentials = None
        self._credentials_lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "gcs"

    def write(self, *, key: str, payload: bytes, content_type: str) -> StoredMigrationMediaObject:
        normalized_key = normalize_migration_media_storage_key(key)
        response = self._request(
            "POST",
            f"{self.api_base_url}/upload/storage/v1/b/{quote(self.bucket, safe='')}/o",
            params={"uploadType": "media", "name": normalized_key},
            headers={"Content-Type": content_type or "application/octet-stream"},
            data=payload,
        )
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise MigrationMediaStorageError("Google Cloud Storage returned an invalid upload response.") from exc
        generation = str(body.get("generation") or "").strip()
        response_key = str(body.get("name") or "").strip()
        if not generation or response_key != normalized_key:
            raise MigrationMediaStorageError("Google Cloud Storage did not confirm the uploaded object generation.")
        digest = hashlib.sha256(payload).hexdigest()
        return StoredMigrationMediaObject(
            provider=self.provider_name,
            bucket=self.bucket,
            key=normalized_key,
            generation=generation,
            content_type=content_type,
            size_bytes=len(payload),
            sha256=digest,
        )

    def read(self, *, key: str, generation: str | None = None) -> bytes:
        normalized_key = normalize_migration_media_storage_key(key)
        params: dict[str, str] = {"alt": "media"}
        normalized_generation = str(generation or "").strip()
        if normalized_generation:
            params["generation"] = normalized_generation
        response = self._request(
            "GET",
            (f"{self.api_base_url}/storage/v1/b/{quote(self.bucket, safe='')}/o/" f"{quote(normalized_key, safe='')}"),
            params=params,
        )
        return bytes(response.content)

    def _request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {self._access_token()}"
        try:
            response = self._http_session.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout_seconds,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise MigrationMediaStorageError("Google Cloud Storage request failed.") from exc
        if response.status_code >= 400:
            if response.status_code in {401, 403}:
                message = "Google Cloud Storage denied the runtime identity. Check bucket-scoped object permissions."
            elif response.status_code == 404:
                message = "Migration media payload is unavailable in Google Cloud Storage."
            else:
                message = f"Google Cloud Storage request failed with status {response.status_code}."
            raise MigrationMediaStorageError(message)
        return response

    def _access_token(self) -> str:
        if self._access_token_provider is not None:
            token = str(self._access_token_provider() or "").strip()
            if not token:
                raise MigrationMediaStorageConfigurationError("Google Cloud Storage access token is unavailable.")
            return token
        try:
            from google.auth import default as google_auth_default
            from google.auth.transport.requests import Request as GoogleAuthRequest
        except ImportError as exc:
            raise MigrationMediaStorageConfigurationError(
                "google-auth transport is required for Google Cloud Storage."
            ) from exc
        with self._credentials_lock:
            if self._credentials is None:
                try:
                    credentials, detected_project_id = google_auth_default(scopes=[_CLOUD_PLATFORM_SCOPE])
                except Exception as exc:
                    raise MigrationMediaStorageConfigurationError(
                        "Application Default Credentials are unavailable for Google Cloud Storage."
                    ) from exc
                self._credentials = credentials
                if self.project_id is None:
                    self.project_id = str(detected_project_id or "").strip() or None
            credentials = self._credentials
            if not getattr(credentials, "valid", False) or not getattr(credentials, "token", None):
                try:
                    credentials.refresh(GoogleAuthRequest())
                except Exception as exc:
                    raise MigrationMediaStorageError(
                        "Application Default Credentials could not be refreshed for Google Cloud Storage."
                    ) from exc
            token = str(getattr(credentials, "token", "") or "").strip()
        if not token:
            raise MigrationMediaStorageError("Application Default Credentials did not provide an access token.")
        return token
