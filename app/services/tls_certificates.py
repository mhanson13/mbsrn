from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from uuid import uuid4

from cryptography import x509
from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.tls_certificate import (
    ComputeSSLCertificateClient,
    ComputeSSLCertificateResource,
    TLSCertificateCapabilityCheck,
    TLSCertificateCapabilityProbe,
    TLSCertificateEndpointVerifier,
    TLSCertificateMaterial,
    TLSCertificateProviderError,
    TLSCertificateVault,
)
from app.models.tls_certificate import SiteTLSCertificateBinding, TLSCertificateAsset
from app.repositories.seo_site_repository import SEOSiteRepository
from app.repositories.tls_certificate_repository import TLSCertificateRepository
from app.services.auth_audit import AuthAuditService
from app.core.preview_identity import PreviewIdentityValidationError, build_site_preview_identity


_PREVIEW_SUFFIX = ".site.mbsrn.com"
_HOSTNAME_PATTERN = re.compile(r"^(?=.{1,253}\.?$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\.?$")
_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_SECRET_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


class TLSCertificateNotFoundError(ValueError):
    pass


class TLSCertificateValidationError(ValueError):
    pass


class TLSCertificateConfigurationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "tls_configuration_error",
        missing_permissions: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.missing_permissions = missing_permissions


@dataclass(frozen=True)
class ParsedTLSCertificate:
    certificate: x509.Certificate
    fingerprint_sha256: str
    serial_number: str
    subject: str
    issuer: str
    san_dns_names: tuple[str, ...]
    not_valid_before: datetime
    not_valid_after: datetime
    certificate_kind: str
    key_algorithm: str


@dataclass(frozen=True)
class SiteTLSCertificateStatus:
    hostname: str
    asset: TLSCertificateAsset | None
    binding: SiteTLSCertificateBinding | None
    vaulted: bool
    published: bool
    selected_for_ingress: bool
    manifest_state: str
    serving_state: str


@dataclass(frozen=True)
class TLSCertificateCapabilityStatus:
    project_id: str
    ready: bool
    checks: tuple[TLSCertificateCapabilityCheck, ...]
    reason_code: str
    message: str


class TLSCertificateService:
    def __init__(
        self,
        *,
        session: Session,
        site_repository: SEOSiteRepository,
        certificate_repository: TLSCertificateRepository,
        vault: TLSCertificateVault,
        compute_client: ComputeSSLCertificateClient,
        endpoint_verifier: TLSCertificateEndpointVerifier,
        gcp_project_id: str,
        capability_probe: TLSCertificateCapabilityProbe | None = None,
        auth_audit_service: AuthAuditService | None = None,
        preview_suffix: str = _PREVIEW_SUFFIX,
        secret_prefix: str = "mbsrn-tls",
    ) -> None:
        self.session = session
        self.site_repository = site_repository
        self.certificate_repository = certificate_repository
        self.vault = vault
        self.compute_client = compute_client
        self.endpoint_verifier = endpoint_verifier
        self.gcp_project_id = str(gcp_project_id or "").strip()
        self.capability_probe = capability_probe
        self.auth_audit_service = auth_audit_service
        self.preview_suffix = self._normalize_preview_suffix(preview_suffix)
        self.secret_prefix = self._normalize_secret_prefix(secret_prefix)

    def list_assets(
        self,
        *,
        business_id: str,
        site_id: str | None = None,
    ) -> list[TLSCertificateAsset]:
        assets = self.certificate_repository.list_assets_for_business(business_id)
        if not site_id:
            return assets
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        return [asset for asset in assets if self._hostname_is_covered(hostname, tuple(asset.san_dns_names_json or []))]

    def get_capabilities(self) -> TLSCertificateCapabilityStatus:
        if not self.gcp_project_id:
            return TLSCertificateCapabilityStatus(
                project_id="",
                ready=False,
                checks=(),
                reason_code="tls_gcp_project_missing",
                message="The Google Cloud project for TLS certificates is not configured.",
            )
        if self.capability_probe is None:
            return TLSCertificateCapabilityStatus(
                project_id=self.gcp_project_id,
                ready=False,
                checks=(),
                reason_code="tls_capability_probe_unavailable",
                message="TLS certificate capability checks are unavailable in this runtime.",
            )
        try:
            checks = self.capability_probe.check()
        except TLSCertificateProviderError as exc:
            return TLSCertificateCapabilityStatus(
                project_id=self.gcp_project_id,
                ready=False,
                checks=(),
                reason_code=exc.code,
                message=exc.safe_message,
            )
        ready = bool(checks) and all(check.ready for check in checks)
        return TLSCertificateCapabilityStatus(
            project_id=self.gcp_project_id,
            ready=ready,
            checks=checks,
            reason_code="tls_capabilities_ready" if ready else "tls_permissions_missing",
            message=(
                "Certificate vault and publication permissions are ready."
                if ready
                else "The API runtime identity is missing certificate vault or publication permissions."
            ),
        )

    def get_site_status(self, *, business_id: str, site_id: str) -> SiteTLSCertificateStatus:
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        binding = self.certificate_repository.get_active_binding(business_id, site_id)
        asset = binding.certificate_asset if binding is not None else None
        return SiteTLSCertificateStatus(
            hostname=hostname,
            asset=asset,
            binding=binding,
            vaulted=bool(asset and asset.custody == "vaulted" and asset.vault_secret_version),
            published=bool(asset and asset.status == "published" and asset.gcp_resource_name),
            selected_for_ingress=binding is not None,
            manifest_state=(binding.manifest_state if binding is not None else "not_selected"),
            serving_state=(binding.serving_state if binding is not None else "not_verified"),
        )

    def generate_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        principal_id: str | None,
        display_name: str | None = None,
        validity_days: int = 90,
        key_algorithm: str = "rsa_2048",
    ) -> SiteTLSCertificateStatus:
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        self._require_write_capabilities()
        bounded_validity_days = max(1, min(int(validity_days), 397))
        normalized_algorithm = str(key_algorithm or "rsa_2048").strip().lower()
        if normalized_algorithm == "rsa_2048":
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            signing_algorithm: hashes.HashAlgorithm = hashes.SHA256()
        elif normalized_algorithm == "ecdsa_p256":
            private_key = ec.generate_private_key(ec.SECP256R1())
            signing_algorithm = hashes.SHA256()
        else:
            raise TLSCertificateValidationError("key_algorithm must be rsa_2048 or ecdsa_p256.")

        now = datetime.now(timezone.utc)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)])
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5))
            .not_valid_after(now + timedelta(days=bounded_validity_days))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=isinstance(private_key, rsa.RSAPrivateKey),
                    data_encipherment=False,
                    key_agreement=isinstance(private_key, ec.EllipticCurvePrivateKey),
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=None,
                    decipher_only=None,
                ),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(private_key=private_key, algorithm=signing_algorithm)
        )
        material = TLSCertificateMaterial(
            certificate_pem=certificate.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            private_key_pem=private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode("ascii"),
        )
        self._parse_certificate_and_key(material, hostname=hostname)
        self._hostname_for_site(business_id=business_id, site_id=site_id, lock=True)
        asset = self._vault_publish_and_bind(
            business_id=business_id,
            site_id=site_id,
            hostname=hostname,
            material=material,
            source="generated",
            display_name=display_name or f"{hostname} self-signed certificate",
            principal_id=principal_id,
        )
        self._audit(
            business_id=business_id,
            principal_id=principal_id,
            asset=asset,
            event_type="tls_certificate_generated",
            details={"site_id": site_id, "hostname": hostname, "validity_days": bounded_validity_days},
        )
        self.session.commit()
        return self.get_site_status(business_id=business_id, site_id=site_id)

    def ensure_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        principal_id: str | None,
        display_name: str | None = None,
        validity_days: int = 90,
        key_algorithm: str = "rsa_2048",
        minimum_validity_days: int = 14,
    ) -> SiteTLSCertificateStatus:
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        minimum_expiry = datetime.now(timezone.utc) + timedelta(days=max(0, int(minimum_validity_days)))
        active_binding = self.certificate_repository.get_active_binding(business_id, site_id)
        candidate_assets: list[TLSCertificateAsset] = []
        if active_binding is not None:
            candidate_assets.append(active_binding.certificate_asset)
        for asset in self.certificate_repository.list_assets_for_business(business_id):
            if all(existing.id != asset.id for existing in candidate_assets):
                candidate_assets.append(asset)
        for asset in candidate_assets:
            not_valid_after = asset.not_valid_after
            if not_valid_after.tzinfo is None:
                not_valid_after = not_valid_after.replace(tzinfo=timezone.utc)
            if (
                asset.status != "published"
                or not asset.gcp_resource_name
                or not_valid_after <= minimum_expiry
                or not self._hostname_is_covered(hostname, tuple(asset.san_dns_names_json or []))
            ):
                continue
            try:
                resource = self.compute_client.get(resource_name=asset.gcp_resource_name)
            except TLSCertificateProviderError as exc:
                raise TLSCertificateConfigurationError(exc.safe_message, reason_code=exc.code) from exc
            if resource is None or resource.certificate_type != "SELF_MANAGED":
                continue
            self._hostname_for_site(business_id=business_id, site_id=site_id, lock=True)
            if active_binding is None or active_binding.certificate_asset_id != asset.id:
                self._activate_binding(
                    business_id=business_id,
                    site_id=site_id,
                    asset=asset,
                    principal_id=principal_id,
                )
                self.session.commit()
            return self.get_site_status(business_id=business_id, site_id=site_id)
        return self.generate_for_site(
            business_id=business_id,
            site_id=site_id,
            principal_id=principal_id,
            display_name=display_name,
            validity_days=validity_days,
            key_algorithm=key_algorithm,
        )

    def import_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        certificate_pem: str,
        private_key_pem: str,
        principal_id: str | None,
        display_name: str | None = None,
    ) -> SiteTLSCertificateStatus:
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        self._require_write_capabilities()
        material = TLSCertificateMaterial(
            certificate_pem=str(certificate_pem or ""),
            private_key_pem=str(private_key_pem or ""),
        )
        self._parse_certificate_and_key(material, hostname=hostname)
        self._hostname_for_site(business_id=business_id, site_id=site_id, lock=True)
        asset = self._vault_publish_and_bind(
            business_id=business_id,
            site_id=site_id,
            hostname=hostname,
            material=material,
            source="imported",
            display_name=display_name or f"{hostname} imported self-signed certificate",
            principal_id=principal_id,
        )
        self._audit(
            business_id=business_id,
            principal_id=principal_id,
            asset=asset,
            event_type="tls_certificate_imported",
            details={"site_id": site_id, "hostname": hostname},
        )
        self.session.commit()
        return self.get_site_status(business_id=business_id, site_id=site_id)

    def adopt_for_site(
        self,
        *,
        business_id: str,
        site_id: str,
        resource_name: str,
        principal_id: str | None,
        display_name: str | None = None,
    ) -> SiteTLSCertificateStatus:
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        normalized_resource_name = self._validate_resource_name(resource_name)
        try:
            resource = self.compute_client.get(resource_name=normalized_resource_name)
        except TLSCertificateProviderError as exc:
            raise TLSCertificateConfigurationError(exc.safe_message, reason_code=exc.code) from exc
        if resource is None:
            raise TLSCertificateNotFoundError("The requested Google Cloud SSL certificate resource was not found.")
        if resource.certificate_type != "SELF_MANAGED":
            raise TLSCertificateValidationError("Only existing self-managed SSL certificate resources can be adopted.")
        if not resource.certificate_pem:
            raise TLSCertificateValidationError("The existing SSL certificate metadata is unavailable.")
        parsed = self._parse_certificate(resource.certificate_pem, hostname=hostname, require_self_signed=True)
        self._hostname_for_site(business_id=business_id, site_id=site_id, lock=True)
        asset = self.certificate_repository.get_asset_by_fingerprint(business_id, parsed.fingerprint_sha256)
        if asset is None:
            asset = self._new_asset(
                business_id=business_id,
                hostname=hostname,
                display_name=display_name or f"{hostname} adopted self-signed certificate",
                source="adopted",
                custody="external",
                parsed=parsed,
                principal_id=principal_id,
            )
            asset.gcp_resource_name = normalized_resource_name
            asset.status = "published"
            self.certificate_repository.create_asset(asset)
        else:
            if asset.gcp_resource_name and asset.gcp_resource_name != normalized_resource_name:
                raise TLSCertificateValidationError(
                    "This certificate is already tracked under a different Google Cloud resource name."
                )
            asset.gcp_resource_name = normalized_resource_name
            asset.status = "published"
            self.certificate_repository.save_asset(asset)
        self._activate_binding(
            business_id=business_id,
            site_id=site_id,
            asset=asset,
            principal_id=principal_id,
        )
        self._audit(
            business_id=business_id,
            principal_id=principal_id,
            asset=asset,
            event_type="tls_certificate_adopted",
            details={"site_id": site_id, "hostname": hostname, "gcp_resource_name": normalized_resource_name},
        )
        self.session.commit()
        return self.get_site_status(business_id=business_id, site_id=site_id)

    def bind_existing_asset(
        self,
        *,
        business_id: str,
        site_id: str,
        asset_id: str,
        principal_id: str | None,
    ) -> SiteTLSCertificateStatus:
        hostname = self._hostname_for_site(business_id=business_id, site_id=site_id)
        asset = self.certificate_repository.get_asset_for_business(business_id, asset_id)
        if asset is None:
            raise TLSCertificateNotFoundError("TLS certificate asset not found.")
        if asset.status != "published" or not asset.gcp_resource_name:
            raise TLSCertificateValidationError("The TLS certificate must be published before it can be selected.")
        self._ensure_hostname_covered(hostname, tuple(asset.san_dns_names_json or []))
        self._hostname_for_site(business_id=business_id, site_id=site_id, lock=True)
        self._activate_binding(
            business_id=business_id,
            site_id=site_id,
            asset=asset,
            principal_id=principal_id,
        )
        self._audit(
            business_id=business_id,
            principal_id=principal_id,
            asset=asset,
            event_type="tls_certificate_bound",
            details={"site_id": site_id, "hostname": hostname},
        )
        self.session.commit()
        return self.get_site_status(business_id=business_id, site_id=site_id)

    def verify_site_endpoint(
        self,
        *,
        business_id: str,
        site_id: str,
        principal_id: str | None,
    ) -> SiteTLSCertificateStatus:
        status = self.get_site_status(business_id=business_id, site_id=site_id)
        if status.asset is None or status.binding is None:
            raise TLSCertificateValidationError("Select a published TLS certificate before verification.")
        try:
            observation = self.endpoint_verifier.observe(hostname=status.hostname)
        except TLSCertificateProviderError as exc:
            status.binding.serving_state = "unreachable"
            status.binding.last_verified_at = utc_now()
            self.certificate_repository.save_binding(status.binding)
            self.session.commit()
            raise TLSCertificateValidationError(exc.safe_message) from exc
        status.binding.observed_fingerprint_sha256 = observation.fingerprint_sha256
        status.binding.last_verified_at = utc_now()
        status.binding.serving_state = (
            "serving" if observation.fingerprint_sha256 == status.asset.fingerprint_sha256 else "fingerprint_mismatch"
        )
        self.certificate_repository.save_binding(status.binding)
        self._audit(
            business_id=business_id,
            principal_id=principal_id,
            asset=status.asset,
            event_type="tls_certificate_endpoint_verified",
            details={
                "site_id": site_id,
                "hostname": status.hostname,
                "serving_state": status.binding.serving_state,
                "observed_fingerprint_sha256": observation.fingerprint_sha256,
            },
        )
        self.session.commit()
        return self.get_site_status(business_id=business_id, site_id=site_id)

    def _vault_publish_and_bind(
        self,
        *,
        business_id: str,
        site_id: str,
        hostname: str,
        material: TLSCertificateMaterial,
        source: str,
        display_name: str,
        principal_id: str | None,
    ) -> TLSCertificateAsset:
        self._require_project()
        parsed = self._parse_certificate_and_key(material, hostname=hostname)
        asset = self.certificate_repository.get_asset_by_fingerprint(business_id, parsed.fingerprint_sha256)
        if asset is None:
            asset = self._new_asset(
                business_id=business_id,
                hostname=hostname,
                display_name=display_name,
                source=source,
                custody="pending_vault",
                parsed=parsed,
                principal_id=principal_id,
            )
            self.certificate_repository.create_asset(asset)
            self.session.commit()
        if asset.custody != "vaulted" or not asset.vault_secret_version:
            secret_id = self._secret_id(asset.id)
            try:
                version_name = self.vault.store(
                    secret_id=secret_id,
                    material=material,
                    labels={
                        "managed-by": "mbsrn",
                        "business-id": business_id.lower(),
                        "site-id": site_id.lower(),
                    },
                )
            except TLSCertificateProviderError as exc:
                self._mark_failed(asset, exc)
                raise TLSCertificateConfigurationError(exc.safe_message, reason_code=exc.code) from exc
            asset.custody = "vaulted"
            asset.vault_secret_name = secret_id
            asset.vault_secret_version = version_name
            asset.status = "vaulted"
            asset.failure_reason_code = None
            asset.failure_message = None
            self.certificate_repository.save_asset(asset)
            self.session.commit()
        resource_name = asset.gcp_resource_name or self._resource_name(hostname, parsed.fingerprint_sha256)
        try:
            resource = self.compute_client.create(
                resource_name=resource_name,
                description=f"MBSRN preview TLS certificate for {hostname}; fingerprint {parsed.fingerprint_sha256}",
                material=material,
            )
            self._verify_compute_resource(resource, expected_fingerprint=parsed.fingerprint_sha256)
        except TLSCertificateProviderError as exc:
            self._mark_failed(asset, exc)
            raise TLSCertificateConfigurationError(exc.safe_message, reason_code=exc.code) from exc
        asset.gcp_resource_name = resource_name
        asset.status = "published"
        asset.failure_reason_code = None
        asset.failure_message = None
        self.certificate_repository.save_asset(asset)
        self._activate_binding(
            business_id=business_id,
            site_id=site_id,
            asset=asset,
            principal_id=principal_id,
        )
        return asset

    def _new_asset(
        self,
        *,
        business_id: str,
        hostname: str,
        display_name: str,
        source: str,
        custody: str,
        parsed: ParsedTLSCertificate,
        principal_id: str | None,
    ) -> TLSCertificateAsset:
        return TLSCertificateAsset(
            id=str(uuid4()),
            business_id=business_id,
            hostname=hostname,
            display_name=str(display_name or hostname).strip()[:160],
            source=source,
            custody=custody,
            certificate_kind=parsed.certificate_kind,
            key_algorithm=parsed.key_algorithm,
            fingerprint_sha256=parsed.fingerprint_sha256,
            serial_number=parsed.serial_number,
            subject=parsed.subject,
            issuer=parsed.issuer,
            san_dns_names_json=list(parsed.san_dns_names),
            not_valid_before=parsed.not_valid_before,
            not_valid_after=parsed.not_valid_after,
            gcp_project_id=self.gcp_project_id,
            gcp_resource_scope="global",
            status="validated",
            created_by_principal_id=principal_id,
        )

    def _activate_binding(
        self,
        *,
        business_id: str,
        site_id: str,
        asset: TLSCertificateAsset,
        principal_id: str | None,
    ) -> SiteTLSCertificateBinding:
        current = self.certificate_repository.get_active_binding(business_id, site_id)
        if current is not None and current.certificate_asset_id == asset.id:
            current.manifest_state = "republish_required"
            current.serving_state = "not_verified"
            return self.certificate_repository.save_binding(current)
        self.certificate_repository.deactivate_bindings_for_site(business_id, site_id)
        binding = SiteTLSCertificateBinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            certificate_asset_id=asset.id,
            is_active=True,
            manifest_state="republish_required",
            serving_state="not_verified",
            created_by_principal_id=principal_id,
        )
        return self.certificate_repository.create_binding(binding)

    def _mark_failed(self, asset: TLSCertificateAsset, exc: TLSCertificateProviderError) -> None:
        asset.status = "failed"
        asset.failure_reason_code = exc.code
        asset.failure_message = exc.safe_message
        self.certificate_repository.save_asset(asset)
        self.session.commit()

    def _require_write_capabilities(self) -> None:
        if self.capability_probe is None:
            return
        status = self.get_capabilities()
        if status.ready:
            return
        missing_permissions = tuple(permission for check in status.checks for permission in check.missing_permissions)
        raise TLSCertificateConfigurationError(
            status.message,
            reason_code=status.reason_code,
            missing_permissions=missing_permissions,
        )

    def _hostname_for_site(self, *, business_id: str, site_id: str, lock: bool = False) -> str:
        site = self.site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise TLSCertificateNotFoundError("Site not found.")
        try:
            identity = build_site_preview_identity(site.preview_slug)
        except PreviewIdentityValidationError as exc:
            raise TLSCertificateValidationError(str(exc)) from exc
        if lock and site.preview_slug_locked_at is None:
            site.preview_slug_locked_at = utc_now()
            self.site_repository.save(site)
            self.session.commit()
            self.session.refresh(site)
        hostname = identity.hostname
        return self._validate_preview_hostname(hostname)

    def _validate_preview_hostname(self, hostname: str) -> str:
        normalized = str(hostname or "").strip().lower().rstrip(".")
        if not _HOSTNAME_PATTERN.fullmatch(normalized):
            raise TLSCertificateValidationError("The preview hostname is invalid.")
        if not normalized.endswith(self.preview_suffix) or normalized == self.preview_suffix.lstrip("."):
            raise TLSCertificateValidationError(f"Self-signed certificates are restricted to *{self.preview_suffix}.")
        return normalized

    @classmethod
    def _parse_certificate_and_key(
        cls,
        material: TLSCertificateMaterial,
        *,
        hostname: str,
    ) -> ParsedTLSCertificate:
        if len(material.certificate_pem) > 65536 or len(material.private_key_pem) > 65536:
            raise TLSCertificateValidationError("Certificate and private key PEM values must not exceed 64 KiB each.")
        parsed = cls._parse_certificate(material.certificate_pem, hostname=hostname, require_self_signed=True)
        try:
            private_key = serialization.load_pem_private_key(material.private_key_pem.encode("utf-8"), password=None)
        except (TypeError, ValueError) as exc:
            raise TLSCertificateValidationError(
                "The private key must be a valid, unencrypted RSA or ECDSA PEM key."
            ) from exc
        if not isinstance(private_key, (rsa.RSAPrivateKey, ec.EllipticCurvePrivateKey)):
            raise TLSCertificateValidationError("The private key must use RSA or ECDSA.")
        certificate_public_key = parsed.certificate.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        private_public_key = private_key.public_key().public_bytes(
            serialization.Encoding.DER,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        if certificate_public_key != private_public_key:
            raise TLSCertificateValidationError("The private key does not match the certificate.")
        return parsed

    @classmethod
    def _parse_certificate(
        cls,
        certificate_pem: str,
        *,
        hostname: str,
        require_self_signed: bool,
    ) -> ParsedTLSCertificate:
        try:
            certificate = x509.load_pem_x509_certificate(str(certificate_pem or "").encode("utf-8"))
        except ValueError as exc:
            raise TLSCertificateValidationError("The certificate must be valid PEM.") from exc
        try:
            san_extension = certificate.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            san_dns_names = tuple(
                name.lower().rstrip(".") for name in san_extension.value.get_values_for_type(x509.DNSName)
            )
        except x509.ExtensionNotFound as exc:
            raise TLSCertificateValidationError("The certificate must contain a DNS Subject Alternative Name.") from exc
        cls._ensure_hostname_covered(hostname, san_dns_names)
        now = datetime.now(timezone.utc)
        not_valid_before = certificate.not_valid_before_utc
        not_valid_after = certificate.not_valid_after_utc
        if now < not_valid_before:
            raise TLSCertificateValidationError("The certificate is not valid yet.")
        if now >= not_valid_after:
            raise TLSCertificateValidationError("The certificate has expired.")
        certificate_kind = "self_signed" if cls._is_self_signed(certificate) else "ca_signed"
        if require_self_signed and certificate_kind != "self_signed":
            raise TLSCertificateValidationError("Only self-signed certificates are supported for preview sites.")
        public_key = certificate.public_key()
        if isinstance(public_key, rsa.RSAPublicKey):
            if public_key.key_size < 2048:
                raise TLSCertificateValidationError("RSA certificates must use a key of at least 2048 bits.")
            key_algorithm = f"rsa_{public_key.key_size}"
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            key_algorithm = f"ecdsa_{public_key.curve.name}"
        else:
            raise TLSCertificateValidationError("The certificate must use RSA or ECDSA.")
        fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
        return ParsedTLSCertificate(
            certificate=certificate,
            fingerprint_sha256=fingerprint,
            serial_number=format(certificate.serial_number, "x"),
            subject=certificate.subject.rfc4514_string(),
            issuer=certificate.issuer.rfc4514_string(),
            san_dns_names=san_dns_names,
            not_valid_before=not_valid_before,
            not_valid_after=not_valid_after,
            certificate_kind=certificate_kind,
            key_algorithm=key_algorithm,
        )

    @staticmethod
    def _is_self_signed(certificate: x509.Certificate) -> bool:
        if certificate.subject != certificate.issuer:
            return False
        try:
            certificate.verify_directly_issued_by(certificate)
        except (InvalidSignature, TypeError, UnsupportedAlgorithm, ValueError):
            return False
        return True

    @staticmethod
    def _ensure_hostname_covered(hostname: str, san_dns_names: tuple[str, ...]) -> None:
        if TLSCertificateService._hostname_is_covered(hostname, san_dns_names):
            return
        raise TLSCertificateValidationError("The certificate SAN does not cover the site preview hostname.")

    @staticmethod
    def _hostname_is_covered(hostname: str, san_dns_names: tuple[str, ...]) -> bool:
        normalized_hostname = hostname.lower().rstrip(".")
        for san in san_dns_names:
            normalized_san = san.lower().rstrip(".")
            if normalized_san == normalized_hostname:
                return True
            if normalized_san.startswith("*."):
                suffix = normalized_san[1:]
                if normalized_hostname.endswith(suffix) and normalized_hostname.count(".") == normalized_san.count("."):
                    return True
        return False

    def _verify_compute_resource(
        self,
        resource: ComputeSSLCertificateResource,
        *,
        expected_fingerprint: str,
    ) -> None:
        if resource.certificate_type != "SELF_MANAGED":
            raise TLSCertificateProviderError(
                code="tls_compute_resource_type_mismatch",
                safe_message="The Google Cloud SSL certificate resource is not self-managed.",
            )
        if not resource.certificate_pem:
            return
        try:
            certificate = x509.load_pem_x509_certificate(resource.certificate_pem.encode("utf-8"))
        except ValueError as exc:
            raise TLSCertificateProviderError(
                code="tls_compute_resource_invalid",
                safe_message="The Google Cloud SSL certificate resource metadata is invalid.",
            ) from exc
        observed_fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
        if observed_fingerprint != expected_fingerprint:
            raise TLSCertificateProviderError(
                code="tls_compute_resource_conflict",
                safe_message="The Google Cloud SSL certificate name is already used by different certificate material.",
            )

    def _resource_name(self, hostname: str, fingerprint: str) -> str:
        site_label = re.sub(r"[^a-z0-9-]+", "-", hostname.split(".", 1)[0]).strip("-") or "site"
        name = f"mbsrn-preview-{site_label[:30]}-{fingerprint[:12]}"[:63].rstrip("-")
        return self._validate_resource_name(name)

    @staticmethod
    def _validate_resource_name(resource_name: str) -> str:
        normalized = str(resource_name or "").strip().lower()
        if not _RESOURCE_NAME_PATTERN.fullmatch(normalized):
            raise TLSCertificateValidationError("The Google Cloud SSL certificate resource name is invalid.")
        return normalized

    def _secret_id(self, asset_id: str) -> str:
        secret_id = f"{self.secret_prefix}-{asset_id.lower()}"
        if not _SECRET_ID_PATTERN.fullmatch(secret_id):
            raise TLSCertificateValidationError("The TLS certificate vault identifier is invalid.")
        return secret_id

    @staticmethod
    def _normalize_preview_suffix(value: str) -> str:
        normalized = str(value or _PREVIEW_SUFFIX).strip().lower().rstrip(".")
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        if normalized != _PREVIEW_SUFFIX:
            raise TLSCertificateConfigurationError(
                "Self-signed TLS certificates are restricted to the .site.mbsrn.com preview domain."
            )
        return normalized

    @staticmethod
    def _normalize_secret_prefix(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "mbsrn-tls")).strip("-")
        return normalized[:80] or "mbsrn-tls"

    def _require_project(self) -> None:
        if not self.gcp_project_id:
            raise TLSCertificateConfigurationError("The Google Cloud project for TLS certificates is not configured.")

    def _audit(
        self,
        *,
        business_id: str,
        principal_id: str | None,
        asset: TLSCertificateAsset,
        event_type: str,
        details: dict[str, object],
    ) -> None:
        if self.auth_audit_service is None:
            return
        self.auth_audit_service.record_event(
            business_id=business_id,
            actor_principal_id=principal_id,
            target_type="tls_certificate",
            target_id=asset.id,
            event_type=event_type,
            details={
                **details,
                "fingerprint_sha256": asset.fingerprint_sha256,
                "custody": asset.custody,
                "status": asset.status,
            },
        )
