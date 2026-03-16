from __future__ import annotations

from app.main import app


def test_main_app_mounts_seo_routes() -> None:
    paths = {route.path for route in app.routes}
    assert "/api/businesses/{business_id}/seo/sites" in paths
    assert "/api/businesses/{business_id}/seo/sites/{site_id}/audit-runs" in paths
    assert "/api/businesses/{business_id}/seo/audit-runs/{run_id}/summarize" in paths
    assert "/api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets" in paths
    assert "/api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains" in paths
    assert "/api/businesses/{business_id}/seo/competitor-sets/{set_id}/snapshot-runs" in paths
    assert "/api/businesses/{business_id}/seo/competitor-sets/{set_id}/comparison-runs" in paths
    assert "/api/businesses/{business_id}/seo/comparison-runs/{run_id}/findings" in paths
    assert "/api/businesses/{business_id}/seo/comparison-runs/{run_id}/summarize" in paths
