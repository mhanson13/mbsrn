from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import socket
import ssl
import time
import urllib.parse

import requests
from cryptography import x509
from cryptography.hazmat.primitives import serialization


_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class TLSCertificateProviderError(RuntimeError):
    def __init__(self, *, code: str, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message


@dataclass(frozen=True)
class TLSCertificateMaterial:
    certificate_pem: str
    private_key_pem: str


@dataclass(frozen=True)
class ComputeSSLCertificateResource:
    name: str
    certificate_type: str
    certificate_pem: str | None
    subject_alternative_names: tuple[str, ...]
    expire_time: str | None
    self_link: str | None


@dataclass(frozen=True)
class TLSCertificateEndpointObservation:
    fingerprint_sha256: str
    certificate_pem: str


@dataclass(frozen=True)
class TLSCertificateCapabilityCheck:
    component: str
    required_permissions: tuple[str, ...]
    granted_permissions: tuple[str, ...]

    @property
    def missing_permissions(self) -> tuple[str, ...]:
        granted = set(self.granted_permissions)
        return tuple(permission for permission in self.required_permissions if permission not in granted)

    @property
    def ready(self) -> bool:
        return not self.missing_permissions


class TLSCertificateCapabilityProbe:
    def check(self) -> tuple[TLSCertificateCapabilityCheck, ...]:
        raise NotImplementedError


class TLSCertificateVault:
    def store(
        self,
        *,
        secret_id: str,
        material: TLSCertificateMaterial,
        labels: dict[str, str],
    ) -> str:
        raise NotImplementedError

    def load(self, *, secret_version_name: str) -> TLSCertificateMaterial:
        raise NotImplementedError


class ComputeSSLCertificateClient:
    def get(self, *, resource_name: str) -> ComputeSSLCertificateResource | None:
        raise NotImplementedError

    def create(
        self,
        *,
        resource_name: str,
        description: str,
        material: TLSCertificateMaterial,
    ) -> ComputeSSLCertificateResource:
        raise NotImplementedError


class TLSCertificateEndpointVerifier:
    def observe(self, *, hostname: str, port: int = 443) -> TLSCertificateEndpointObservation:
        raise NotImplementedError


class SocketTLSCertificateEndpointVerifier(TLSCertificateEndpointVerifier):
    def __init__(self, *, timeout_seconds: int = 10) -> None:
        self.timeout_seconds = max(1, min(int(timeout_seconds), 30))

    def observe(self, *, hostname: str, port: int = 443) -> TLSCertificateEndpointObservation:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        try:
            with socket.create_connection((hostname, port), timeout=self.timeout_seconds) as raw_socket:
                with context.wrap_socket(raw_socket, server_hostname=hostname) as tls_socket:
                    certificate_der = tls_socket.getpeercert(binary_form=True)
        except (OSError, ssl.SSLError) as exc:
            raise TLSCertificateProviderError(
                code="tls_endpoint_unreachable",
                safe_message="The preview TLS endpoint could not be reached.",
            ) from exc
        if not certificate_der:
            raise TLSCertificateProviderError(
                code="tls_certificate_missing",
                safe_message="The preview endpoint did not return a TLS certificate.",
            )
        certificate = x509.load_der_x509_certificate(certificate_der)
        certificate_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
        return TLSCertificateEndpointObservation(
            fingerprint_sha256=hashlib.sha256(certificate_der).hexdigest(),
            certificate_pem=certificate_pem,
        )


class _GoogleAccessTokenProvider:
    def __call__(self) -> str:
        try:
            from google.auth import default as google_auth_default
            from google.auth.transport.requests import Request as GoogleAuthRequest

            credentials, _ = google_auth_default(scopes=[_CLOUD_PLATFORM_SCOPE])
            credentials.refresh(GoogleAuthRequest())
            token = str(getattr(credentials, "token", "") or "").strip()
        except Exception as exc:  # noqa: BLE001
            raise TLSCertificateProviderError(
                code="google_credentials_unavailable",
                safe_message="Google Cloud credentials are unavailable for TLS certificate operations.",
            ) from exc
        if not token:
            raise TLSCertificateProviderError(
                code="google_credentials_unavailable",
                safe_message="Google Cloud credentials are unavailable for TLS certificate operations.",
            )
        return token


class _GoogleJSONClient:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        token_provider: Callable[[], str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout_seconds = max(1, min(int(timeout_seconds), 60))
        self.token_provider = token_provider or _GoogleAccessTokenProvider()
        self.session = session or requests.Session()

    def request_json(
        self,
        *,
        method: str,
        url: str,
        body: dict[str, object] | None = None,
        allowed_statuses: tuple[int, ...] = (200,),
        error_code: str,
        error_message: str,
    ) -> tuple[int, dict[str, object]]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token_provider()}",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self.session.request(
                method,
                url,
                headers=headers,
                json=body,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise TLSCertificateProviderError(code=error_code, safe_message=error_message) from exc
        if response.status_code not in allowed_statuses:
            raise TLSCertificateProviderError(code=error_code, safe_message=error_message)
        if not response.content:
            return response.status_code, {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise TLSCertificateProviderError(code=error_code, safe_message=error_message) from exc
        if not isinstance(payload, dict):
            raise TLSCertificateProviderError(code=error_code, safe_message=error_message)
        return response.status_code, payload


class GoogleTLSCertificateCapabilityProbe(TLSCertificateCapabilityProbe):
    SECRET_MANAGER_PERMISSIONS = (
        "secretmanager.secrets.create",
        "secretmanager.versions.add",
    )
    COMPUTE_PERMISSIONS = (
        "compute.sslCertificates.create",
        "compute.sslCertificates.get",
        "compute.globalOperations.get",
    )

    def __init__(
        self,
        *,
        project_id: str,
        timeout_seconds: int = 30,
        token_provider: Callable[[], str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.project_id = str(project_id or "").strip()
        self.client = _GoogleJSONClient(
            timeout_seconds=timeout_seconds,
            token_provider=token_provider,
            session=session,
        )

    def check(self) -> tuple[TLSCertificateCapabilityCheck, ...]:
        if not self.project_id:
            raise TLSCertificateProviderError(
                code="tls_gcp_project_missing",
                safe_message="The Google Cloud project for TLS certificates is not configured.",
            )
        quoted_project = urllib.parse.quote(self.project_id, safe="")
        _, secret_payload = self.client.request_json(
            method="POST",
            url=(f"https://secretmanager.googleapis.com/v1/projects/{quoted_project}:testIamPermissions"),
            body={"permissions": list(self.SECRET_MANAGER_PERMISSIONS)},
            allowed_statuses=(200,),
            error_code="tls_secret_manager_capability_check_failed",
            error_message="Secret Manager certificate permissions could not be checked.",
        )
        _, compute_payload = self.client.request_json(
            method="POST",
            url=(f"https://compute.googleapis.com/compute/v1/projects/{quoted_project}/testIamPermissions"),
            body={"permissions": list(self.COMPUTE_PERMISSIONS)},
            allowed_statuses=(200,),
            error_code="tls_compute_capability_check_failed",
            error_message="Compute SSL certificate permissions could not be checked.",
        )
        return (
            TLSCertificateCapabilityCheck(
                component="secret_manager",
                required_permissions=self.SECRET_MANAGER_PERMISSIONS,
                granted_permissions=self._normalize_permissions(secret_payload.get("permissions")),
            ),
            TLSCertificateCapabilityCheck(
                component="compute_ssl_certificates",
                required_permissions=self.COMPUTE_PERMISSIONS,
                granted_permissions=self._normalize_permissions(compute_payload.get("permissions")),
            ),
        )

    @staticmethod
    def _normalize_permissions(value: object) -> tuple[str, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))


class GoogleSecretManagerTLSCertificateVault(TLSCertificateVault):
    def __init__(
        self,
        *,
        project_id: str,
        timeout_seconds: int = 30,
        token_provider: Callable[[], str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.project_id = str(project_id or "").strip()
        self.client = _GoogleJSONClient(
            timeout_seconds=timeout_seconds,
            token_provider=token_provider,
            session=session,
        )

    def store(
        self,
        *,
        secret_id: str,
        material: TLSCertificateMaterial,
        labels: dict[str, str],
    ) -> str:
        self._require_project()
        quoted_project = urllib.parse.quote(self.project_id, safe="")
        quoted_secret = urllib.parse.quote(secret_id, safe="")
        create_url = (
            f"https://secretmanager.googleapis.com/v1/projects/{quoted_project}/secrets" f"?secretId={quoted_secret}"
        )
        self.client.request_json(
            method="POST",
            url=create_url,
            body={"replication": {"automatic": {}}, "labels": labels},
            allowed_statuses=(200, 409),
            error_code="tls_vault_create_failed",
            error_message="The TLS certificate vault entry could not be created.",
        )
        bundle = json.dumps(
            {
                "schema_version": 1,
                "certificate_pem": material.certificate_pem,
                "private_key_pem": material.private_key_pem,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(bundle) > 65536:
            raise TLSCertificateProviderError(
                code="tls_vault_payload_too_large",
                safe_message="The TLS certificate material exceeds the Secret Manager payload limit.",
            )
        add_version_url = (
            f"https://secretmanager.googleapis.com/v1/projects/{quoted_project}/secrets/{quoted_secret}:addVersion"
        )
        _, payload = self.client.request_json(
            method="POST",
            url=add_version_url,
            body={"payload": {"data": base64.b64encode(bundle).decode("ascii")}},
            allowed_statuses=(200,),
            error_code="tls_vault_write_failed",
            error_message="The TLS certificate material could not be vaulted.",
        )
        version_name = str(payload.get("name") or "").strip()
        if not version_name:
            raise TLSCertificateProviderError(
                code="tls_vault_write_failed",
                safe_message="The TLS certificate material could not be vaulted.",
            )
        return version_name

    def load(self, *, secret_version_name: str) -> TLSCertificateMaterial:
        self._require_project()
        normalized_name = str(secret_version_name or "").strip().lstrip("/")
        expected_prefix = f"projects/{self.project_id}/secrets/"
        if not normalized_name.startswith(expected_prefix) or "/versions/" not in normalized_name:
            raise TLSCertificateProviderError(
                code="tls_vault_reference_invalid",
                safe_message="The TLS certificate vault reference is invalid.",
            )
        access_url = f"https://secretmanager.googleapis.com/v1/{normalized_name}:access"
        _, payload = self.client.request_json(
            method="GET",
            url=access_url,
            allowed_statuses=(200,),
            error_code="tls_vault_read_failed",
            error_message="The TLS certificate material could not be read from the vault.",
        )
        payload_record = payload.get("payload")
        encoded_data = payload_record.get("data") if isinstance(payload_record, dict) else None
        try:
            decoded = base64.b64decode(str(encoded_data or ""), validate=True)
            bundle = json.loads(decoded.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TLSCertificateProviderError(
                code="tls_vault_payload_invalid",
                safe_message="The vaulted TLS certificate material is invalid.",
            ) from exc
        if not isinstance(bundle, dict):
            raise TLSCertificateProviderError(
                code="tls_vault_payload_invalid",
                safe_message="The vaulted TLS certificate material is invalid.",
            )
        certificate_pem = str(bundle.get("certificate_pem") or "")
        private_key_pem = str(bundle.get("private_key_pem") or "")
        if not certificate_pem or not private_key_pem:
            raise TLSCertificateProviderError(
                code="tls_vault_payload_invalid",
                safe_message="The vaulted TLS certificate material is invalid.",
            )
        return TLSCertificateMaterial(certificate_pem=certificate_pem, private_key_pem=private_key_pem)

    def _require_project(self) -> None:
        if not self.project_id:
            raise TLSCertificateProviderError(
                code="tls_gcp_project_missing",
                safe_message="The Google Cloud project for TLS certificates is not configured.",
            )


class GoogleComputeSSLCertificateClient(ComputeSSLCertificateClient):
    def __init__(
        self,
        *,
        project_id: str,
        timeout_seconds: int = 30,
        token_provider: Callable[[], str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.project_id = str(project_id or "").strip()
        self.client = _GoogleJSONClient(
            timeout_seconds=timeout_seconds,
            token_provider=token_provider,
            session=session,
        )

    def get(self, *, resource_name: str) -> ComputeSSLCertificateResource | None:
        self._require_project()
        quoted_project = urllib.parse.quote(self.project_id, safe="")
        quoted_name = urllib.parse.quote(resource_name, safe="")
        url = (
            f"https://compute.googleapis.com/compute/v1/projects/{quoted_project}/global/sslCertificates/{quoted_name}"
        )
        status_code, payload = self.client.request_json(
            method="GET",
            url=url,
            allowed_statuses=(200, 404),
            error_code="tls_compute_read_failed",
            error_message="The Google Cloud SSL certificate resource could not be read.",
        )
        if status_code == 404:
            return None
        return self._to_resource(payload)

    def create(
        self,
        *,
        resource_name: str,
        description: str,
        material: TLSCertificateMaterial,
    ) -> ComputeSSLCertificateResource:
        self._require_project()
        quoted_project = urllib.parse.quote(self.project_id, safe="")
        url = f"https://compute.googleapis.com/compute/v1/projects/{quoted_project}/global/sslCertificates"
        status_code, payload = self.client.request_json(
            method="POST",
            url=url,
            body={
                "name": resource_name,
                "description": description,
                "type": "SELF_MANAGED",
                "certificate": material.certificate_pem,
                "privateKey": material.private_key_pem,
            },
            allowed_statuses=(200, 409),
            error_code="tls_compute_create_failed",
            error_message="The self-managed Google Cloud SSL certificate could not be created.",
        )
        if status_code != 409:
            self._wait_for_operation(payload)
        resource = self.get(resource_name=resource_name)
        if resource is None:
            raise TLSCertificateProviderError(
                code="tls_compute_create_not_visible",
                safe_message="The self-managed Google Cloud SSL certificate is not visible after creation.",
            )
        return resource

    def _wait_for_operation(self, payload: dict[str, object]) -> None:
        operation_name = str(payload.get("name") or "").strip()
        if not operation_name:
            return
        quoted_project = urllib.parse.quote(self.project_id, safe="")
        quoted_operation = urllib.parse.quote(operation_name, safe="")
        url = (
            f"https://compute.googleapis.com/compute/v1/projects/{quoted_project}"
            f"/global/operations/{quoted_operation}"
        )
        deadline = time.monotonic() + self.client.timeout_seconds
        while time.monotonic() < deadline:
            _, operation = self.client.request_json(
                method="GET",
                url=url,
                allowed_statuses=(200,),
                error_code="tls_compute_operation_failed",
                error_message="The Google Cloud SSL certificate operation could not be verified.",
            )
            if str(operation.get("status") or "").upper() == "DONE":
                if operation.get("error"):
                    raise TLSCertificateProviderError(
                        code="tls_compute_create_failed",
                        safe_message="The self-managed Google Cloud SSL certificate could not be created.",
                    )
                return
            time.sleep(0.5)
        raise TLSCertificateProviderError(
            code="tls_compute_operation_timeout",
            safe_message="The Google Cloud SSL certificate operation timed out.",
        )

    @staticmethod
    def _to_resource(payload: dict[str, object]) -> ComputeSSLCertificateResource:
        raw_sans = payload.get("subjectAlternativeNames")
        sans = (
            tuple(str(item).strip().lower() for item in raw_sans if str(item).strip())
            if isinstance(raw_sans, list)
            else ()
        )
        return ComputeSSLCertificateResource(
            name=str(payload.get("name") or ""),
            certificate_type=str(payload.get("type") or "UNKNOWN").upper(),
            certificate_pem=(str(payload.get("certificate")) if payload.get("certificate") else None),
            subject_alternative_names=sans,
            expire_time=(str(payload.get("expireTime")) if payload.get("expireTime") else None),
            self_link=(str(payload.get("selfLink")) if payload.get("selfLink") else None),
        )

    def _require_project(self) -> None:
        if not self.project_id:
            raise TLSCertificateProviderError(
                code="tls_gcp_project_missing",
                safe_message="The Google Cloud project for TLS certificates is not configured.",
            )
