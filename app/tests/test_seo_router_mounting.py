from __future__ import annotations

from app.main import app


def test_main_app_mounts_seo_routes() -> None:
    route_methods: dict[str, set[str]] = {}
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if methods is None:
            continue
        route_methods.setdefault(route.path, set()).update(method for method in methods if method != "HEAD")

    # Phase 1 SEO surface.
    assert route_methods["/api/businesses/{business_id}/seo/sites"] >= {"GET", "POST"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/audit-runs"] >= {"GET", "POST"}
    assert route_methods["/api/businesses/{business_id}/seo/audit-runs/{run_id}/summarize"] >= {"POST"}

    # Phase 2 competitor sets/domains.
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/competitor-sets"] >= {"GET", "POST"}
    assert route_methods["/api/businesses/{business_id}/seo/competitor-sets/{set_id}"] >= {"GET", "PATCH"}
    assert route_methods["/api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains"] >= {"GET", "POST"}
    assert route_methods["/api/businesses/{business_id}/seo/competitor-sets/{set_id}/domains/{domain_id}"] >= {"DELETE"}

    # Phase 2 snapshot runs.
    assert route_methods["/api/businesses/{business_id}/seo/competitor-sets/{set_id}/snapshot-runs"] >= {"GET", "POST"}
    assert route_methods["/api/businesses/{business_id}/seo/snapshot-runs/{run_id}"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/snapshot-runs/{run_id}/pages"] >= {"GET"}

    # Phase 2 deterministic comparison runs.
    assert route_methods["/api/businesses/{business_id}/seo/competitor-sets/{set_id}/comparison-runs"] >= {
        "GET",
        "POST",
    }
    assert route_methods["/api/businesses/{business_id}/seo/comparison-runs/{run_id}"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/comparison-runs/{run_id}/findings"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/comparison-runs/{run_id}/report"] >= {"GET"}

    # Phase 2 manual-trigger summary surface.
    assert route_methods["/api/businesses/{business_id}/seo/comparison-runs/{run_id}/summarize"] >= {"POST"}
    assert route_methods["/api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/comparison-runs/{run_id}/summaries/latest"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/comparison-summaries/{summary_id}"] >= {"GET"}

    # Phase 3A deterministic recommendations surface.
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs"] >= {"GET", "POST"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}"
    ] >= {"GET"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations"
    ] >= {"GET"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report"
    ] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}"] >= {
        "GET"
    }
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendations"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}"] >= {
        "GET",
        "PATCH",
    }
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendations/backlog"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendations/prioritized-report"] >= {
        "GET"
    }
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/recommendations/tuning-preview"] >= {"POST"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives"
    ] >= {"GET", "POST"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest"
    ] >= {"GET"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/recommendation-narratives/{narrative_id}"
    ] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/automation-config"] >= {
        "GET",
        "POST",
        "PATCH",
    }
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/automation-config/enable"] >= {"POST"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/automation-config/disable"] >= {"POST"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/automation-runs"] >= {"GET", "POST"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/automation-runs/{automation_run_id}"] >= {
        "GET"
    }
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/automation-status"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/analytics/site-summary"] >= {"GET"}
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/analytics/ga4-onboarding-status"] >= {
        "GET"
    }
    assert route_methods["/api/businesses/{business_id}/seo/sites/{site_id}/analytics/ga4-accessible-accounts"] >= {
        "GET"
    }

    # Phase 2 v1 site-scoped compatibility surface.
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-sets"] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-sets/{competitor_set_id}"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-sets/{competitor_set_id}/domains"
    ] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-sets/{competitor_set_id}/snapshot-runs"
    ] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-snapshot-runs/{snapshot_run_id}"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-snapshot-runs/{snapshot_run_id}/pages"
    ] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-comparison-runs"] >= {
        "GET",
        "POST",
    }
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/findings"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/report"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries"
    ] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-comparison-runs/{comparison_run_id}/summaries/latest"
    ] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-summaries/{summary_id}"] >= {
        "GET"
    }
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs"] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/recommendations"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/report"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}"
    ] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations"] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations/{recommendation_id}"
    ] >= {
        "GET",
        "PATCH",
    }
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations/backlog"] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations/prioritized-report"] >= {
        "GET"
    }
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendations/tuning-preview"] >= {
        "POST"
    }
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives"
    ] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-runs/{recommendation_run_id}/narratives/latest"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/recommendation-narratives/{narrative_id}"
    ] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/automation-config"] >= {
        "GET",
        "POST",
        "PATCH",
    }
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/automation-config/enable"] >= {"POST"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/automation-config/disable"] >= {"POST"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/automation-runs"] >= {"GET", "POST"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/automation-runs/{automation_run_id}"
    ] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/automation-status"] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/analytics/site-summary"] >= {"GET"}
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/analytics/ga4-onboarding-status"] >= {
        "GET"
    }
    assert route_methods["/api/v1/businesses/{business_id}/seo/sites/{site_id}/analytics/ga4-accessible-accounts"] >= {
        "GET"
    }

    # Phase 4 scheduler-ready due-run entrypoint.
    assert route_methods["/api/jobs/seo-automation/run-due"] >= {"POST"}
    assert route_methods["/api/jobs/seo-competitor-profile-generation/cleanup"] >= {"POST"}
    assert route_methods["/api/jobs/seo-competitor-profile-generation/cleanup-status"] >= {"GET"}
    assert route_methods[
        "/api/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    ] >= {"GET"}
    assert route_methods[
        "/api/v1/businesses/{business_id}/seo/sites/{site_id}/competitor-profile-generation-runs/summary"
    ] >= {"GET"}
