from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TLSCertificateAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    hostname: str
    display_name: str
    source: str
    custody: str
    certificate_kind: str
    key_algorithm: str
    fingerprint_sha256: str
    serial_number: str
    subject: str
    issuer: str
    san_dns_names: list[str]
    not_valid_before: datetime
    not_valid_after: datetime
    gcp_project_id: str
    gcp_resource_name: str | None
    gcp_resource_scope: str
    status: str
    failure_reason_code: str | None
    failure_message: str | None
    created_at: datetime
    updated_at: datetime


class SiteTLSCertificateBindingRead(BaseModel):
    id: str
    certificate_asset_id: str
    is_active: bool
    manifest_state: str
    serving_state: str
    observed_fingerprint_sha256: str | None
    last_verified_at: datetime | None


class SiteTLSCertificateStatusRead(BaseModel):
    hostname: str
    asset: TLSCertificateAssetRead | None
    binding: SiteTLSCertificateBindingRead | None
    vaulted: bool
    published: bool
    selected_for_ingress: bool
    manifest_state: str
    serving_state: str
    browser_trust: str = "untrusted_self_signed"


class TLSCertificateAssetListRead(BaseModel):
    items: list[TLSCertificateAssetRead]


class TLSCertificateGenerateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    validity_days: int = Field(default=90, ge=1, le=397)
    key_algorithm: str = Field(default="rsa_2048", pattern="^(rsa_2048|ecdsa_p256)$")


class TLSCertificateImportRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    certificate_pem: str = Field(min_length=1, max_length=65536)
    private_key_pem: SecretStr


class TLSCertificateAdoptRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=160)
    gcp_resource_name: str = Field(min_length=1, max_length=63)
