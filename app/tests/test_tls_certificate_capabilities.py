from __future__ import annotations

import base64
from pathlib import Path

import pytest
import requests
from fastapi import HTTPException

from app.api.routes.tls_certificates import _raise_http_error
from app.integrations.tls_certificate import (
    GoogleComputeSSLCertificateClient,
    GoogleSecretManagerTLSCertificateVault,
    GoogleTLSCertificateCapabilityProbe,
    TLSCertificateProviderError,
    TLSCertificateMaterial,
    _GoogleJSONClient,
)
from app.services.tls_certificates import TLSCertificateConfigurationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class _CapabilitySession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        raise AssertionError("The runtime readiness probe must not call provider permission-test endpoints.")


def test_google_tls_capability_probe_checks_credentials_without_calling_unsupported_permission_endpoint() -> None:
    session = _CapabilitySession()
    token_requests: list[str] = []
    probe = GoogleTLSCertificateCapabilityProbe(
        project_id="mbsrn-prod",
        token_provider=lambda: token_requests.append("requested") or "short-lived-token",
        session=session,
    )

    secret_manager, compute = probe.check()

    assert secret_manager.ready is True
    assert compute.ready is True
    assert secret_manager.verification_state == "operation_required"
    assert compute.verification_state == "operation_required"
    assert secret_manager.missing_permissions == ()
    assert compute.missing_permissions == ()
    assert token_requests == ["requested"]
    assert session.calls == []


class _VaultReadResponse:
    status_code = 200

    def __init__(self) -> None:
        bundle = b'{"schema_version":1,"certificate_pem":"certificate-pem",' b'"private_key_pem":"private-key-pem"}'
        self._payload = {"payload": {"data": base64.b64encode(bundle).decode("ascii")}}
        self.content = b"payload"

    def json(self) -> dict[str, object]:
        return self._payload


class _VaultReadSession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _VaultReadResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        return _VaultReadResponse()


def test_secret_manager_vault_load_accepts_numeric_canonical_project_reference() -> None:
    session = _VaultReadSession()
    vault = GoogleSecretManagerTLSCertificateVault(
        project_id="mbsrn-prod",
        token_provider=lambda: "short-lived-token",
        session=session,
    )

    material = vault.load(
        secret_version_name=("projects/1068908288067/secrets/mbsrn-tls-bec9b51e-8b87-4088-b26e-b5ca73a164d0/versions/1")
    )

    assert material.certificate_pem == "certificate-pem"
    assert material.private_key_pem == "private-key-pem"
    assert session.calls[0]["url"] == (
        "https://secretmanager.googleapis.com/v1/projects/mbsrn-prod/secrets/"
        "mbsrn-tls-bec9b51e-8b87-4088-b26e-b5ca73a164d0/versions/1:access"
    )


def test_secret_manager_vault_load_rejects_another_named_project() -> None:
    session = _VaultReadSession()
    vault = GoogleSecretManagerTLSCertificateVault(
        project_id="mbsrn-prod",
        token_provider=lambda: "short-lived-token",
        session=session,
    )

    with pytest.raises(TLSCertificateProviderError) as error:
        vault.load(secret_version_name="projects/another-project/secrets/mbsrn-tls-test/versions/1")

    assert error.value.code == "tls_vault_reference_invalid"
    assert session.calls == []


class _FailureResponse:
    content = b'{"error":{"status":"PERMISSION_DENIED","message":"provider detail must stay private"}}'

    def __init__(self, status_code: int, provider_status: str) -> None:
        self.status_code = status_code
        self.provider_status = provider_status

    def json(self) -> dict[str, object]:
        return {
            "error": {
                "status": self.provider_status,
                "message": "provider detail must stay private",
            }
        }


class _FailureSession(requests.Session):
    def __init__(self, response: _FailureResponse | None = None, error: Exception | None = None) -> None:
        super().__init__()
        self.response = response
        self.error = error

    def request(self, method: str, url: str, **kwargs: object) -> _FailureResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _JSONResponse:
    def __init__(self, status_code: int, payload: dict[str, object]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.content = b"payload"

    def json(self) -> dict[str, object]:
        return self._payload


class _ComputeCreateSession(requests.Session):
    def __init__(self, *, operation_error: dict[str, object] | None = None) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []
        self.operation_error = operation_error

    def request(self, method: str, url: str, **kwargs: object) -> _JSONResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        if method == "POST":
            return _JSONResponse(200, {"name": "operation-1"})
        if "/global/operations/" in url:
            payload: dict[str, object] = {"status": "DONE"}
            if self.operation_error is not None:
                payload.update(self.operation_error)
            return _JSONResponse(200, payload)
        return _JSONResponse(
            200,
            {
                "name": "preview-platfire",
                "type": "SELF_MANAGED",
                "selfManaged": {"certificate": "certificate-pem"},
                "subjectAlternativeNames": ["platfire.site.mbsrn.com"],
            },
        )


def test_compute_certificate_create_uses_explicit_self_managed_payload() -> None:
    session = _ComputeCreateSession()
    client = GoogleComputeSSLCertificateClient(
        project_id="mbsrn-prod",
        token_provider=lambda: "short-lived-token",
        session=session,
    )

    resource = client.create(
        resource_name="preview-platfire",
        description="Platfire preview certificate",
        material=TLSCertificateMaterial(
            certificate_pem="certificate-pem",
            private_key_pem="private-key-pem",
        ),
    )

    create_call = session.calls[0]
    assert create_call["json"] == {
        "name": "preview-platfire",
        "description": "Platfire preview certificate",
        "type": "SELF_MANAGED",
        "selfManaged": {
            "certificate": "certificate-pem",
            "privateKey": "private-key-pem",
        },
    }
    assert "certificate" not in create_call["json"]
    assert "privateKey" not in create_call["json"]
    assert resource.certificate_type == "SELF_MANAGED"
    assert resource.certificate_pem == "certificate-pem"


def test_compute_certificate_operation_invalid_argument_is_non_retryable_and_sanitized() -> None:
    session = _ComputeCreateSession(
        operation_error={
            "httpErrorStatusCode": 400,
            "error": {
                "errors": [
                    {
                        "code": "INVALID_VALUE",
                        "message": "private provider request detail",
                    }
                ]
            },
        }
    )
    client = GoogleComputeSSLCertificateClient(
        project_id="mbsrn-prod",
        token_provider=lambda: "short-lived-token",
        session=session,
    )

    with pytest.raises(TLSCertificateProviderError) as error:
        client.create(
            resource_name="preview-platfire",
            description="Platfire preview certificate",
            material=TLSCertificateMaterial(
                certificate_pem="certificate-pem",
                private_key_pem="private-key-pem",
            ),
        )

    assert error.value.code == "tls_compute_create_failed_invalid_argument"
    assert error.value.http_status == 400
    assert error.value.provider_status == "INVALID_VALUE"
    assert error.value.retryable is False
    assert "private provider request detail" not in error.value.safe_message


@pytest.mark.parametrize(
    ("status_code", "provider_status", "reason_suffix", "retryable"),
    [
        (401, "UNAUTHENTICATED", "_unauthenticated", False),
        (400, "INVALID_ARGUMENT", "_invalid_argument", False),
        (403, "PERMISSION_DENIED", "_permission_denied", False),
        (404, "NOT_FOUND", "_not_found", False),
        (429, "RESOURCE_EXHAUSTED", "_rate_limited", True),
        (503, "UNAVAILABLE", "_provider_unavailable", True),
    ],
)
def test_google_json_client_classifies_provider_failures_without_exposing_raw_detail(
    status_code: int,
    provider_status: str,
    reason_suffix: str,
    retryable: bool,
) -> None:
    client = _GoogleJSONClient(
        timeout_seconds=5,
        token_provider=lambda: "short-lived-token",
        session=_FailureSession(_FailureResponse(status_code, provider_status)),
    )

    with pytest.raises(TLSCertificateProviderError) as error:
        client.request_json(
            method="POST",
            url="https://secretmanager.googleapis.com/v1/projects/test/secrets",
            error_code="tls_vault_create_failed",
            error_message="The TLS certificate vault entry could not be created.",
            service="secret_manager",
            operation="create_secret",
            required_permissions=("secretmanager.secrets.create",),
        )

    assert error.value.code == f"tls_vault_create_failed{reason_suffix}"
    assert error.value.http_status == status_code
    assert error.value.provider_status == provider_status
    assert error.value.retryable is retryable
    assert "provider detail" not in error.value.safe_message
    assert error.value.missing_permissions == (("secretmanager.secrets.create",) if status_code == 403 else ())


def test_google_json_client_classifies_timeout_as_retryable() -> None:
    client = _GoogleJSONClient(
        timeout_seconds=5,
        token_provider=lambda: "short-lived-token",
        session=_FailureSession(error=requests.Timeout("private transport detail")),
    )

    with pytest.raises(TLSCertificateProviderError) as error:
        client.request_json(
            method="GET",
            url="https://compute.googleapis.com/compute/v1/projects/test/global/operations/one",
            error_code="tls_compute_operation_failed",
            error_message="The Google Cloud SSL certificate operation could not be verified.",
            service="compute_ssl_certificates",
            operation="get_global_operation",
        )

    assert error.value.code == "tls_compute_operation_failed_timeout"
    assert error.value.retryable is True
    assert "private transport detail" not in error.value.safe_message


def test_tls_api_error_contract_returns_actionable_sanitized_provider_metadata() -> None:
    configuration_error = TLSCertificateConfigurationError(
        "The TLS certificate vault entry could not be created. Google Cloud denied this operation.",
        reason_code="tls_vault_create_failed_permission_denied",
        missing_permissions=("secretmanager.secrets.create",),
        provider_service="secret_manager",
        provider_operation="create_secret",
        provider_http_status=403,
        provider_status="PERMISSION_DENIED",
        retryable=False,
        next_action="Verify the listed permission and IAM conditions.",
    )

    with pytest.raises(HTTPException) as error:
        _raise_http_error(configuration_error)

    assert error.value.status_code == 503
    assert error.value.detail == {
        "reason_code": "tls_vault_create_failed_permission_denied",
        "message": "The TLS certificate vault entry could not be created. Google Cloud denied this operation.",
        "missing_permissions": ["secretmanager.secrets.create"],
        "provider_service": "secret_manager",
        "provider_operation": "create_secret",
        "provider_http_status": 403,
        "provider_status": "PERMISSION_DENIED",
        "retryable": False,
        "next_action": "Verify the listed permission and IAM conditions.",
    }


def test_preview_tls_secret_read_permission_is_separate_and_prefix_scoped() -> None:
    role_definition = (REPOSITORY_ROOT / "infra" / "gcp" / "preview-tls-operator-role.yaml").read_text(encoding="utf-8")
    bootstrap = (REPOSITORY_ROOT / "scripts" / "bootstrap_preview_tls_permissions.sh").read_text(encoding="utf-8")

    assert "secretmanager.versions.access" not in role_definition
    assert 'SECRET_PREFIX="${TLS_CERTIFICATE_SECRET_PREFIX:-mbsrn-tls}"' in bootstrap
    assert "roles/secretmanager.secretAccessor" in bootstrap
    assert "secretmanager.googleapis.com/SecretVersion" in bootstrap
    assert "resource.name.startsWith('${TLS_SECRET_RESOURCE_PREFIX}')" in bootstrap
