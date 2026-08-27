from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.tls_certificate import SiteTLSCertificateBinding, TLSCertificateAsset


class TLSCertificateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_asset(self, asset: TLSCertificateAsset) -> TLSCertificateAsset:
        self.session.add(asset)
        self.session.flush()
        return asset

    def save_asset(self, asset: TLSCertificateAsset) -> TLSCertificateAsset:
        self.session.add(asset)
        self.session.flush()
        return asset

    def get_asset_for_business(self, business_id: str, asset_id: str) -> TLSCertificateAsset | None:
        stmt: Select[tuple[TLSCertificateAsset]] = (
            select(TLSCertificateAsset)
            .where(TLSCertificateAsset.business_id == business_id)
            .where(TLSCertificateAsset.id == asset_id)
        )
        return self.session.scalar(stmt)

    def get_asset_by_fingerprint(self, business_id: str, fingerprint_sha256: str) -> TLSCertificateAsset | None:
        stmt: Select[tuple[TLSCertificateAsset]] = (
            select(TLSCertificateAsset)
            .where(TLSCertificateAsset.business_id == business_id)
            .where(TLSCertificateAsset.fingerprint_sha256 == fingerprint_sha256)
        )
        return self.session.scalar(stmt)

    def list_assets_for_business(self, business_id: str, *, hostname: str | None = None) -> list[TLSCertificateAsset]:
        stmt: Select[tuple[TLSCertificateAsset]] = select(TLSCertificateAsset).where(
            TLSCertificateAsset.business_id == business_id
        )
        if hostname:
            stmt = stmt.where(TLSCertificateAsset.hostname == hostname)
        stmt = stmt.order_by(TLSCertificateAsset.created_at.desc(), TLSCertificateAsset.id.desc())
        return list(self.session.scalars(stmt))

    def get_active_binding(self, business_id: str, site_id: str) -> SiteTLSCertificateBinding | None:
        stmt: Select[tuple[SiteTLSCertificateBinding]] = (
            select(SiteTLSCertificateBinding)
            .where(SiteTLSCertificateBinding.business_id == business_id)
            .where(SiteTLSCertificateBinding.site_id == site_id)
            .where(SiteTLSCertificateBinding.is_active.is_(True))
        )
        return self.session.scalar(stmt)

    def list_bindings_for_site(self, business_id: str, site_id: str) -> list[SiteTLSCertificateBinding]:
        stmt: Select[tuple[SiteTLSCertificateBinding]] = (
            select(SiteTLSCertificateBinding)
            .where(SiteTLSCertificateBinding.business_id == business_id)
            .where(SiteTLSCertificateBinding.site_id == site_id)
            .order_by(SiteTLSCertificateBinding.created_at.desc(), SiteTLSCertificateBinding.id.desc())
        )
        return list(self.session.scalars(stmt))

    def create_binding(self, binding: SiteTLSCertificateBinding) -> SiteTLSCertificateBinding:
        self.session.add(binding)
        self.session.flush()
        return binding

    def save_binding(self, binding: SiteTLSCertificateBinding) -> SiteTLSCertificateBinding:
        self.session.add(binding)
        self.session.flush()
        return binding

    def deactivate_bindings_for_site(self, business_id: str, site_id: str) -> None:
        for binding in self.list_bindings_for_site(business_id, site_id):
            if binding.is_active:
                binding.is_active = False
                binding.manifest_state = "retired"
        self.session.flush()
