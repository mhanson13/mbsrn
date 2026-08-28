from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.orm import Session

from app.integrations.tls_certificate import (
    ComputeSSLCertificateClient,
    ComputeSSLCertificateResource,
    TLSCertificateCapabilityCheck,
    TLSCertificateCapabilityProbe,
    TLSCertificateEndpointObservation,
    TLSCertificateEndpointVerifier,
    TLSCertificateMaterial,
    TLSCertificateProviderError,
    TLSCertificateVault,
)
from app.models.business import Business
from app.models.seo_site import SEOSite
from app.repositories.seo_site_repository import SEOSiteRepository
from app.repositories.tls_certificate_repository import TLSCertificateRepository
from app.services.tls_certificates import (
    TLSCertificateConfigurationError,
    TLSCertificateService,
    TLSCertificateValidationError,
)


class _FakeVault(TLSCertificateVault):
    def __init__(self) -> None:
        self.material_by_version: dict[str, TLSCertificateMaterial] = {}

    def store(
        self,
        *,
        secret_id: str,
        material: TLSCertificateMaterial,
        labels: dict[str, str],
    ) -> str:
        assert labels["managed-by"] == "mbsrn"
        version = f"projects/mbsrn-prod/secrets/{secret_id}/versions/1"
        self.material_by_version[version] = material
        return version

    def load(self, *, secret_version_name: str) -> TLSCertificateMaterial:
        return self.material_by_version[secret_version_name]


class _FakeComputeClient(ComputeSSLCertificateClient):
    def __init__(self) -> None:
        self.resources: dict[str, ComputeSSLCertificateResource] = {}

    def get(self, *, resource_name: str) -> ComputeSSLCertificateResource | None:
        return self.resources.get(resource_name)

    def create(
        self,
        *,
        resource_name: str,
        description: str,
        material: TLSCertificateMaterial,
    ) -> ComputeSSLCertificateResource:
        assert "fingerprint" in description
        certificate = x509.load_pem_x509_certificate(material.certificate_pem.encode("ascii"))
        sans = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
            x509.DNSName
        )
        resource = ComputeSSLCertificateResource(
            name=resource_name,
            certificate_type="SELF_MANAGED",
            certificate_pem=material.certificate_pem,
            subject_alternative_names=tuple(sans),
            expire_time=certificate.not_valid_after_utc.isoformat(),
            self_link=f"https://compute.googleapis.com/compute/v1/projects/mbsrn-prod/global/sslCertificates/{resource_name}",
        )
        self.resources[resource_name] = resource
        return resource


class _FailOnceComputeClient(_FakeComputeClient):
    def __init__(self) -> None:
        super().__init__()
        self.create_attempts = 0

    def create(
        self,
        *,
        resource_name: str,
        description: str,
        material: TLSCertificateMaterial,
    ) -> ComputeSSLCertificateResource:
        self.create_attempts += 1
        if self.create_attempts == 1:
            raise TLSCertificateProviderError(
                code="tls_compute_create_failed_provider_unavailable",
                safe_message="The self-managed Google Cloud SSL certificate could not be created.",
                service="compute_ssl_certificates",
                operation="create_certificate",
                http_status=503,
                provider_status="UNAVAILABLE",
                retryable=True,
                next_action="Retry the certificate operation.",
            )
        return super().create(
            resource_name=resource_name,
            description=description,
            material=material,
        )


class _FakeEndpointVerifier(TLSCertificateEndpointVerifier):
    def __init__(self) -> None:
        self.observation: TLSCertificateEndpointObservation | None = None

    def observe(self, *, hostname: str, port: int = 443) -> TLSCertificateEndpointObservation:
        assert hostname == "platfire.site.mbsrn.com"
        assert port == 443
        assert self.observation is not None
        return self.observation


class _MissingCapabilityProbe(TLSCertificateCapabilityProbe):
    def check(self) -> tuple[TLSCertificateCapabilityCheck, ...]:
        return (
            TLSCertificateCapabilityCheck(
                component="secret_manager",
                required_permissions=("secretmanager.secrets.create", "secretmanager.versions.add"),
                granted_permissions=("secretmanager.versions.add",),
            ),
            TLSCertificateCapabilityCheck(
                component="compute_ssl_certificates",
                required_permissions=("compute.sslCertificates.create", "compute.sslCertificates.get"),
                granted_permissions=("compute.sslCertificates.get",),
            ),
        )


def _seed_site(db_session: Session) -> tuple[Business, SEOSite]:
    business = Business(
        id="11111111-1111-1111-1111-111111111111",
        name="Platinum Fire",
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    site = SEOSite(
        id="22222222-2222-2222-2222-222222222222",
        business_id=business.id,
        display_name="Platinum Fire",
        base_url="https://www.platfire.com",
        normalized_domain="www.platfire.com",
        preview_slug="platfire",
        is_active=True,
        is_primary=True,
    )
    db_session.add_all([business, site])
    db_session.commit()
    return business, site


def _service(
    db_session: Session,
) -> tuple[TLSCertificateService, _FakeVault, _FakeComputeClient, _FakeEndpointVerifier]:
    vault = _FakeVault()
    compute = _FakeComputeClient()
    verifier = _FakeEndpointVerifier()
    service = TLSCertificateService(
        session=db_session,
        site_repository=SEOSiteRepository(db_session),
        certificate_repository=TLSCertificateRepository(db_session),
        vault=vault,
        compute_client=compute,
        endpoint_verifier=verifier,
        gcp_project_id="mbsrn-prod",
    )
    return service, vault, compute, verifier


def _self_signed_material(hostname: str) -> TLSCertificateMaterial:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(private_key, hashes.SHA256())
    )
    return TLSCertificateMaterial(
        certificate_pem=certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        private_key_pem=private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii"),
    )


def test_generate_vaults_publishes_and_selects_self_signed_preview_certificate(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, vault, compute, _ = _service(db_session)

    status = service.generate_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )

    assert status.hostname == "platfire.site.mbsrn.com"
    assert status.vaulted is True
    assert status.published is True
    assert status.selected_for_ingress is True
    assert status.manifest_state == "republish_required"
    assert status.serving_state == "not_verified"
    assert status.asset is not None
    assert status.asset.certificate_kind == "self_signed"
    assert status.asset.custody == "vaulted"
    assert status.asset.san_dns_names_json == ["platfire.site.mbsrn.com"]
    assert status.asset.gcp_resource_name in compute.resources
    assert status.asset.vault_secret_version in vault.material_by_version
    assert not hasattr(status.asset, "private_key_pem")
    db_session.refresh(site)
    assert site.preview_slug_locked_at is not None


def test_generate_stops_before_key_creation_when_capabilities_are_missing(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    vault = _FakeVault()
    compute = _FakeComputeClient()
    service = TLSCertificateService(
        session=db_session,
        site_repository=SEOSiteRepository(db_session),
        certificate_repository=TLSCertificateRepository(db_session),
        vault=vault,
        compute_client=compute,
        endpoint_verifier=_FakeEndpointVerifier(),
        gcp_project_id="mbsrn-prod",
        capability_probe=_MissingCapabilityProbe(),
    )

    capability_status = service.get_capabilities()
    assert capability_status.ready is False
    assert capability_status.reason_code == "tls_permissions_missing"
    with pytest.raises(TLSCertificateConfigurationError) as error:
        service.generate_for_site(
            business_id=business.id,
            site_id=site.id,
            principal_id="principal-1",
        )

    assert error.value.missing_permissions == (
        "secretmanager.secrets.create",
        "compute.sslCertificates.create",
    )
    assert vault.material_by_version == {}
    assert compute.resources == {}
    db_session.refresh(site)
    assert site.preview_slug_locked_at is None


def test_ensure_reuses_published_certificate_without_generating_another(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, vault, compute, _ = _service(db_session)
    first = service.generate_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )
    first_asset_id = first.asset.id if first.asset is not None else None

    ensured = service.ensure_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )

    assert ensured.asset is not None
    assert ensured.asset.id == first_asset_id
    assert len(vault.material_by_version) == 1
    assert len(compute.resources) == 1
    assert len(TLSCertificateRepository(db_session).list_assets_for_business(business.id)) == 1


def test_ensure_resumes_vaulted_certificate_after_compute_publication_failure(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    vault = _FakeVault()
    compute = _FailOnceComputeClient()
    service = TLSCertificateService(
        session=db_session,
        site_repository=SEOSiteRepository(db_session),
        certificate_repository=TLSCertificateRepository(db_session),
        vault=vault,
        compute_client=compute,
        endpoint_verifier=_FakeEndpointVerifier(),
        gcp_project_id="mbsrn-prod",
    )

    with pytest.raises(TLSCertificateConfigurationError) as first_error:
        service.generate_for_site(
            business_id=business.id,
            site_id=site.id,
            principal_id="principal-1",
        )

    assert first_error.value.retryable is True
    assets_after_failure = TLSCertificateRepository(db_session).list_assets_for_business(business.id)
    assert len(assets_after_failure) == 1
    failed_asset = assets_after_failure[0]
    assert failed_asset.custody == "vaulted"
    assert failed_asset.vault_secret_version in vault.material_by_version

    ensured = service.ensure_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )

    assert ensured.asset is not None
    assert ensured.asset.id == failed_asset.id
    assert ensured.asset.status == "published"
    assert compute.create_attempts == 2
    assert len(vault.material_by_version) == 1
    assert len(compute.resources) == 1
    assert len(TLSCertificateRepository(db_session).list_assets_for_business(business.id)) == 1


def test_import_rejects_private_key_that_does_not_match_certificate(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, vault, _, _ = _service(db_session)
    certificate_material = _self_signed_material("platfire.site.mbsrn.com")
    other_material = _self_signed_material("platfire.site.mbsrn.com")

    with pytest.raises(TLSCertificateValidationError, match="does not match"):
        service.import_for_site(
            business_id=business.id,
            site_id=site.id,
            certificate_pem=certificate_material.certificate_pem,
            private_key_pem=other_material.private_key_pem,
            principal_id="principal-1",
        )

    assert vault.material_by_version == {}
    db_session.refresh(site)
    assert site.preview_slug_locked_at is None


def test_adopt_existing_self_managed_certificate_without_private_key(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, vault, compute, _ = _service(db_session)
    material = _self_signed_material("platfire.site.mbsrn.com")
    compute.resources["existing-platfire-cert"] = ComputeSSLCertificateResource(
        name="existing-platfire-cert",
        certificate_type="SELF_MANAGED",
        certificate_pem=material.certificate_pem,
        subject_alternative_names=("platfire.site.mbsrn.com",),
        expire_time=None,
        self_link=None,
    )

    status = service.adopt_for_site(
        business_id=business.id,
        site_id=site.id,
        resource_name="existing-platfire-cert",
        principal_id="principal-1",
    )

    assert status.asset is not None
    assert status.asset.source == "adopted"
    assert status.asset.custody == "external"
    assert status.asset.gcp_resource_name == "existing-platfire-cert"
    assert status.vaulted is False
    assert status.published is True
    assert vault.material_by_version == {}


def test_invalid_adopt_does_not_lock_preview_identity(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, _, compute, _ = _service(db_session)
    material = _self_signed_material("platfire.site.mbsrn.com")
    compute.resources["managed-certificate"] = ComputeSSLCertificateResource(
        name="managed-certificate",
        certificate_type="MANAGED",
        certificate_pem=material.certificate_pem,
        subject_alternative_names=("platfire.site.mbsrn.com",),
        expire_time=None,
        self_link=None,
    )

    with pytest.raises(TLSCertificateValidationError, match="Only existing self-managed"):
        service.adopt_for_site(
            business_id=business.id,
            site_id=site.id,
            resource_name="managed-certificate",
            principal_id="principal-1",
        )

    db_session.refresh(site)
    assert site.preview_slug_locked_at is None


def test_verify_compares_served_certificate_fingerprint(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, _, _, verifier = _service(db_session)
    status = service.generate_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )
    assert status.asset is not None
    material = _self_signed_material("platfire.site.mbsrn.com")
    verifier.observation = TLSCertificateEndpointObservation(
        fingerprint_sha256=status.asset.fingerprint_sha256,
        certificate_pem=material.certificate_pem,
    )

    verified = service.verify_site_endpoint(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )

    assert verified.serving_state == "serving"
    assert verified.binding is not None
    assert verified.binding.observed_fingerprint_sha256 == status.asset.fingerprint_sha256


def test_import_rejects_certificate_for_non_preview_hostname(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, _, _, _ = _service(db_session)
    material = _self_signed_material("www.platfire.com")

    with pytest.raises(TLSCertificateValidationError, match="SAN does not cover"):
        service.import_for_site(
            business_id=business.id,
            site_id=site.id,
            certificate_pem=material.certificate_pem,
            private_key_pem=material.private_key_pem,
            principal_id="principal-1",
        )


def test_rotating_certificate_retires_previous_active_binding(db_session: Session) -> None:
    business, site = _seed_site(db_session)
    service, _, _, _ = _service(db_session)
    first = service.generate_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )
    second = service.generate_for_site(
        business_id=business.id,
        site_id=site.id,
        principal_id="principal-1",
    )

    assert first.asset is not None
    assert second.asset is not None
    assert first.asset.id != second.asset.id
    bindings = TLSCertificateRepository(db_session).list_bindings_for_site(business.id, site.id)
    assert len(bindings) == 2
    assert sum(1 for binding in bindings if binding.is_active) == 1
    retired = next(binding for binding in bindings if not binding.is_active)
    assert retired.manifest_state == "retired"


def test_wildcard_certificate_can_be_reused_by_another_preview_site(db_session: Session) -> None:
    business, first_site = _seed_site(db_session)
    second_site = SEOSite(
        id="33333333-3333-3333-3333-333333333333",
        business_id=business.id,
        display_name="Second Preview",
        base_url="https://www.second-preview.com",
        normalized_domain="www.second-preview.com",
        preview_slug="second-preview",
        is_active=True,
        is_primary=False,
    )
    db_session.add(second_site)
    db_session.commit()
    service, _, _, _ = _service(db_session)
    material = _self_signed_material("*.site.mbsrn.com")

    first_status = service.import_for_site(
        business_id=business.id,
        site_id=first_site.id,
        certificate_pem=material.certificate_pem,
        private_key_pem=material.private_key_pem,
        principal_id="principal-1",
    )
    assert first_status.asset is not None

    reusable_assets = service.list_assets(business_id=business.id, site_id=second_site.id)
    assert [asset.id for asset in reusable_assets] == [first_status.asset.id]

    second_status = service.bind_existing_asset(
        business_id=business.id,
        site_id=second_site.id,
        asset_id=first_status.asset.id,
        principal_id="principal-1",
    )
    assert second_status.asset is not None
    assert second_status.asset.id == first_status.asset.id
    assert second_status.hostname == "second-preview.site.mbsrn.com"
