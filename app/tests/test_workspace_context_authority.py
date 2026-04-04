from __future__ import annotations

from fastapi import HTTPException, status

from app.api.deps import TenantContext, resolve_tenant_business_id


def _tenant_context() -> TenantContext:
    return TenantContext(
        business_id="biz-1",
        principal_id="principal-1",
        auth_source="test",
    )


def test_resolve_tenant_business_id_uses_tenant_scope_when_route_business_missing() -> None:
    resolved = resolve_tenant_business_id(
        tenant_context=_tenant_context(),
        requested_business_id=None,
    )
    assert resolved == "biz-1"


def test_resolve_tenant_business_id_allows_matching_route_business() -> None:
    resolved = resolve_tenant_business_id(
        tenant_context=_tenant_context(),
        requested_business_id="biz-1",
    )
    assert resolved == "biz-1"


def test_resolve_tenant_business_id_rejects_cross_business_scope_spoof() -> None:
    try:
        resolve_tenant_business_id(
            tenant_context=_tenant_context(),
            requested_business_id="biz-2",
        )
        raise AssertionError("Expected HTTPException for cross-business scope spoof.")
    except HTTPException as exc:
        assert exc.status_code == status.HTTP_404_NOT_FOUND
        assert exc.detail == "Business not found"
