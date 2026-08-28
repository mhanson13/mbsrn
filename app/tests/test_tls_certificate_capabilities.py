from __future__ import annotations

import requests

from app.integrations.tls_certificate import GoogleTLSCertificateCapabilityProbe


class _FakeResponse:
    status_code = 200
    content = b"{}"

    def __init__(self, permissions: list[str]) -> None:
        self.permissions = permissions

    def json(self) -> dict[str, object]:
        return {"permissions": self.permissions}


class _CapabilitySession(requests.Session):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _FakeResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        requested = list(dict(kwargs.get("json", {}) or {}).get("permissions", []))
        if "secretmanager" in url:
            return _FakeResponse(requested)
        return _FakeResponse([permission for permission in requested if permission != "compute.sslCertificates.create"])


def test_google_tls_capability_probe_reports_exact_missing_permission() -> None:
    session = _CapabilitySession()
    probe = GoogleTLSCertificateCapabilityProbe(
        project_id="mbsrn-prod",
        token_provider=lambda: "short-lived-token",
        session=session,
    )

    secret_manager, compute = probe.check()

    assert secret_manager.ready is True
    assert compute.ready is False
    assert compute.missing_permissions == ("compute.sslCertificates.create",)
    assert len(session.calls) == 2
    assert all(call["headers"]["Authorization"] == "Bearer short-lived-token" for call in session.calls)
