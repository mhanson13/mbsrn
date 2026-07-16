from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import app.services.seo_site_delete as seo_site_delete_module
from app.api.deps import TenantContext, get_db, get_seo_site_delete_service, get_tenant_context
from app.api.routes.seo import router as seo_router
from app.integrations.seo_migration_github_publisher import (
    SEOMigrationGitHubPublishPreflightResult,
    SEOMigrationGitHubPublisherError,
)
from app.models.business import Business
from app.models.principal import Principal, PrincipalRole
from app.models.seo_action_chain_draft import SEOActionChainDraft
from app.models.seo_action_decision import SEOActionDecision
from app.models.seo_action_execution_item import SEOActionExecutionItem
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_audit_page import SEOAuditPage
from app.models.seo_audit_run import SEOAuditRun
from app.models.seo_audit_summary import SEOAuditSummary
from app.models.seo_automation_config import SEOAutomationConfig
from app.models.seo_automation_run import SEOAutomationRun
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_competitor_comparison_run import SEOCompetitorComparisonRun
from app.models.seo_competitor_comparison_summary import SEOCompetitorComparisonSummary
from app.models.seo_competitor_domain import SEOCompetitorDomain
from app.models.seo_competitor_domain_feedback import SEOCompetitorDomainFeedback
from app.models.seo_competitor_profile_cleanup_execution import SEOCompetitorProfileCleanupExecution
from app.models.seo_competitor_profile_draft import SEOCompetitorProfileDraft
from app.models.seo_competitor_profile_generation_run import SEOCompetitorProfileGenerationRun
from app.models.seo_competitor_set import SEOCompetitorSet
from app.models.seo_competitor_snapshot_page import SEOCompetitorSnapshotPage
from app.models.seo_competitor_snapshot_run import SEOCompetitorSnapshotRun
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_migration_artifact_version import SEOMigrationArtifactVersion
from app.models.seo_migration_workspace import SEOMigrationWorkspace
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.models.seo_recommendation_run import SEORecommendationRun
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.github_publish_config import GitHubPublishConfigSecretError
from app.services.seo_site_delete import SEOSiteDeleteService


def _override_tenant_context(
    business_id: str,
    principal_id: str | None = None,
    principal_role: PrincipalRole | None = None,
):
    def _resolver() -> TenantContext:
        return TenantContext(
            business_id=business_id,
            principal_id=principal_id or f"test-principal:{business_id}",
            auth_source="test",
            principal_role=principal_role,
        )

    return _resolver


def _make_client(
    db_session,
    *,
    business_id: str,
    principal_id: str | None = None,
    principal_role: PrincipalRole | None = None,
    dependency_overrides: dict[object, object] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(seo_router)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_tenant_context] = _override_tenant_context(
        business_id,
        principal_id=principal_id,
        principal_role=principal_role,
    )
    if dependency_overrides:
        app.dependency_overrides.update(dependency_overrides)
    return TestClient(app)


_SITE_OWNED_MODELS = (
    SEOActionChainDraft,
    SEOActionDecision,
    SEOActionExecutionItem,
    SEOAuditRun,
    SEOAuditPage,
    SEOAuditFinding,
    SEOAuditSummary,
    SEOCompetitorSet,
    SEOCompetitorDomain,
    SEOCompetitorDomainFeedback,
    SEOCompetitorSnapshotRun,
    SEOCompetitorSnapshotPage,
    SEOCompetitorComparisonRun,
    SEOCompetitorComparisonFinding,
    SEOCompetitorComparisonSummary,
    SEORecommendationRun,
    SEORecommendation,
    SEORecommendationNarrative,
    SEOAutomationConfig,
    SEOAutomationRun,
    SEOCompetitorProfileGenerationRun,
    SEOCompetitorProfileDraft,
    SEOCompetitorTuningPreviewEvent,
    SEOCompetitorProfileCleanupExecution,
    SEOMigrationWorkspace,
    SEOMigrationArtifactVersion,
)


def _count_site_rows(*, db_session, model, business_id: str, site_id: str) -> int:
    stmt = (
        select(func.count()).select_from(model).where(model.business_id == business_id).where(model.site_id == site_id)
    )
    return int(db_session.scalar(stmt) or 0)


def _seed_principal(
    *,
    db_session,
    business_id: str,
    principal_id: str,
    role: PrincipalRole,
) -> Principal:
    principal = Principal(
        business_id=business_id,
        id=principal_id,
        display_name="SEO Admin",
        role=role,
        is_active=True,
    )
    db_session.add(principal)
    db_session.commit()
    return principal


def _seed_admin_principal(*, db_session, business_id: str, principal_id: str = "seo-admin") -> Principal:
    return _seed_principal(
        db_session=db_session,
        business_id=business_id,
        principal_id=principal_id,
        role=PrincipalRole.ADMIN,
    )


def _seed_site_owned_data(*, db_session, business_id: str, site_id: str, token: str) -> None:
    audit_run = SEOAuditRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        max_pages=10,
        crawl_max_pages_used=10,
        max_depth=1,
    )
    db_session.add(audit_run)
    db_session.flush()

    audit_page = SEOAuditPage(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        audit_run_id=audit_run.id,
        url=f"https://{token}.example.com/",
    )
    db_session.add(audit_page)
    db_session.flush()

    db_session.add(
        SEOAuditFinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=audit_run.id,
            page_id=audit_page.id,
            finding_type="missing_title",
            category="metadata",
            severity="warning",
            title="Missing title",
            details="No title tag",
            rule_key="missing_title",
        )
    )
    db_session.add(
        SEOAuditSummary(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=audit_run.id,
            version=1,
            status="completed",
            model_name="mock",
            prompt_version="seo-audit-summary-v1",
        )
    )

    competitor_set = SEOCompetitorSet(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        name=f"{token}-set",
        is_active=True,
    )
    db_session.add(competitor_set)
    db_session.flush()

    competitor_domain = SEOCompetitorDomain(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        domain=f"{token}-competitor.example.com",
        base_url=f"https://{token}-competitor.example.com/",
        source="manual",
        is_active=True,
    )
    db_session.add(competitor_domain)
    db_session.flush()

    snapshot_run = SEOCompetitorSnapshotRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        client_audit_run_id=audit_run.id,
        status="completed",
    )
    db_session.add(snapshot_run)
    db_session.flush()

    db_session.add(
        SEOCompetitorSnapshotPage(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            snapshot_run_id=snapshot_run.id,
            competitor_domain_id=competitor_domain.id,
            url=f"https://{token}-competitor.example.com/service",
        )
    )

    comparison_run = SEOCompetitorComparisonRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        competitor_set_id=competitor_set.id,
        snapshot_run_id=snapshot_run.id,
        baseline_audit_run_id=audit_run.id,
        status="completed",
    )
    db_session.add(comparison_run)
    db_session.flush()

    db_session.add(
        SEOCompetitorComparisonFinding(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            comparison_run_id=comparison_run.id,
            finding_type="gap",
            category="content",
            severity="warning",
            title="Gap",
            details="Gap details",
            rule_key="gap_rule",
        )
    )
    db_session.add(
        SEOCompetitorComparisonSummary(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            competitor_set_id=competitor_set.id,
            comparison_run_id=comparison_run.id,
            version=1,
            status="completed",
            provider_name="mock",
            model_name="mock-model",
            prompt_version="seo-competitor-summary-v1",
        )
    )

    recommendation_run = SEORecommendationRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        audit_run_id=audit_run.id,
        comparison_run_id=comparison_run.id,
        status="completed",
    )
    db_session.add(recommendation_run)
    db_session.flush()

    db_session.add(
        SEORecommendation(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run.id,
            audit_run_id=audit_run.id,
            comparison_run_id=comparison_run.id,
            rule_key=f"{token}_rule",
            category="SEO",
            severity="warning",
            title="Recommendation",
            rationale="Improve title tags.",
            priority_score=50,
            priority_band="medium",
            effort_bucket="MEDIUM",
            status="open",
        )
    )

    recommendation_narrative = SEORecommendationNarrative(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        recommendation_run_id=recommendation_run.id,
        version=1,
        status="completed",
        provider_name="mock",
        model_name="mock-model",
        prompt_version="seo-recommendation-narrative-v1",
    )
    db_session.add(recommendation_narrative)
    db_session.flush()

    automation_config = SEOAutomationConfig(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        is_enabled=False,
        cadence_type="manual",
    )
    db_session.add(automation_config)
    db_session.flush()

    db_session.add(
        SEOAutomationRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            automation_config_id=automation_config.id,
            trigger_source="manual",
            status="completed",
        )
    )

    generation_run = SEOCompetitorProfileGenerationRun(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        status="completed",
        requested_candidate_count=3,
        generated_draft_count=1,
        raw_candidate_count=3,
        included_candidate_count=1,
        excluded_candidate_count=2,
        exclusion_counts_by_reason={"low_relevance": 2},
        provider_name="mock",
        model_name="mock-model",
        prompt_version="seo-competitor-profile-v1",
    )
    db_session.add(generation_run)
    db_session.flush()

    db_session.add(
        SEOCompetitorProfileDraft(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            generation_run_id=generation_run.id,
            suggested_name=f"{token} competitor",
            suggested_domain=f"{token}-draft.example.com",
            competitor_type="direct",
            confidence_score=0.7,
            relevance_score=60,
            source="ai_generated",
            review_status="pending",
        )
    )
    db_session.add(
        SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            source_narrative_id=recommendation_narrative.id,
            source_recommendation_run_id=recommendation_run.id,
            preview_request={"proposed_values": {"competitor_candidate_min_relevance_score": 40}},
            preview_response={"summary": "Preview"},
            evaluated_generation_run_id=generation_run.id,
        )
    )
    db_session.add(
        SEOCompetitorProfileCleanupExecution(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            status="completed",
            stale_runs_reconciled=0,
            raw_output_pruned_runs=0,
            rejected_drafts_pruned=0,
            runs_pruned=0,
            started_at=audit_run.created_at,
            completed_at=audit_run.created_at,
        )
    )

    action_draft = SEOActionChainDraft(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        source_action_id=f"{token}-source-action",
        action_type="publish_update",
        title="Chain draft",
        description="Execute a managed follow-up action.",
        priority="medium",
        state="pending",
        activation_state="pending",
    )
    db_session.add(action_draft)
    db_session.flush()

    db_session.add(
        SEOActionDecision(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            action_id=action_draft.source_action_id,
            decision="accepted",
        )
    )
    db_session.add(
        SEOActionExecutionItem(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            source_action_id=action_draft.source_action_id,
            source_draft_id=action_draft.id,
            action_type="publish_update",
            title="Chain execution item",
            description="Execute the managed action draft.",
            priority="medium",
            state="pending",
        )
    )
    db_session.add(
        SEOCompetitorDomainFeedback(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            domain=f"{token}-feedback.example.com",
            feedback_status="approved",
            display_name=f"{token} feedback",
            operator_note="Approved competitor signal.",
        )
    )

    workspace = SEOMigrationWorkspace(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        source_url=f"https://{token}.example.com/source",
        migration_status="draft",
        publish_status="not_ready",
        deploy_status="not_ready",
    )
    db_session.add(workspace)
    db_session.flush()

    artifact_version = SEOMigrationArtifactVersion(
        id=str(uuid4()),
        business_id=business_id,
        site_id=site_id,
        workspace_id=workspace.id,
        version=1,
        status="completed",
    )
    db_session.add(artifact_version)
    db_session.flush()

    workspace.latest_generated_artifact_version_id = artifact_version.id
    workspace.latest_generated_artifact_version_number = artifact_version.version
    db_session.commit()


class _StubGitHubPublishConfigService:
    def __init__(
        self,
        *,
        repository: str = "mhanson13",
        managed_gcp_deploy_key: str | None = None,
        managed_gcp_deploy_key_error: bool = False,
    ) -> None:
        self.repository = repository
        self.managed_gcp_deploy_key = managed_gcp_deploy_key
        self.managed_gcp_deploy_key_error = managed_gcp_deploy_key_error

    def get(self):
        return SimpleNamespace(repository=self.repository)

    def get_managed_gcp_deploy_key_value(self) -> str | None:
        if self.managed_gcp_deploy_key_error:
            raise GitHubPublishConfigSecretError("managed gcp deploy key unavailable")
        return self.managed_gcp_deploy_key


class _StubGitHubPublisher:
    def __init__(
        self,
        *,
        preflight_result: SEOMigrationGitHubPublishPreflightResult | None = None,
        preflight_error: SEOMigrationGitHubPublisherError | None = None,
        managed_certificate_error: SEOMigrationGitHubPublisherError | None = None,
    ) -> None:
        self.preflight_result = preflight_result
        self.preflight_error = preflight_error
        self.managed_certificate_error = managed_certificate_error
        self.preflight_calls: list[tuple[str, str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []
        self.timeout_seconds = 15
        self.managed_deploy_service_account_email = None

    def run_publish_preflight(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        target_ref: str,
        auto_create_enabled: bool,
        expected_owner: str | None = None,
        expected_business_id: str | None = None,
        expected_site_id: str | None = None,
    ) -> SEOMigrationGitHubPublishPreflightResult:
        del auto_create_enabled, expected_owner, expected_business_id, expected_site_id
        self.preflight_calls.append((repo_owner, repo_name, target_ref))
        if self.preflight_error is not None:
            raise self.preflight_error
        if self.preflight_result is not None:
            return self.preflight_result
        return SEOMigrationGitHubPublishPreflightResult(
            repo_owner=repo_owner,
            repo_name=repo_name,
            target_ref=target_ref,
            repo_exists=False,
            repo_ensure_outcome="not_found",
            target_ref_exists=False,
            repo_initialized=False,
            can_read_contents=False,
            can_write_contents=False,
            can_write_workflows=False,
            would_auto_create_repo=False,
            would_bootstrap_branch=False,
            preflight_status="not_found",
        )

    def check_managed_certificate_readiness(self, **_: object):
        if self.managed_certificate_error is not None:
            raise self.managed_certificate_error
        return None

    def delete_repository(
        self,
        *,
        repo_owner: str,
        repo_name: str,
    ) -> None:
        self.delete_calls.append((repo_owner, repo_name))


class _StubSEOMigrationService:
    def __init__(
        self,
        *,
        cleanup_summary: dict[str, object] | None = None,
        cleanup_summaries_by_site_id: dict[str, dict[str, object]] | None = None,
        github_publisher: _StubGitHubPublisher | None = None,
        github_publish_config_service: _StubGitHubPublishConfigService | None = None,
    ) -> None:
        self.cleanup_summary = cleanup_summary or {
            "workspace_id": None,
            "publish_target": {},
            "deploy_target": {},
            "admin_deploy_metadata": {},
        }
        self.cleanup_summaries_by_site_id = deepcopy(cleanup_summaries_by_site_id or {})
        self.github_publisher = github_publisher or _StubGitHubPublisher()
        self.github_publish_config_service = github_publish_config_service

    def get_site_cleanup_target_summary(self, *, business_id: str, site_id: str) -> dict[str, object]:
        del business_id
        if site_id in self.cleanup_summaries_by_site_id:
            return deepcopy(self.cleanup_summaries_by_site_id[site_id])
        return deepcopy(self.cleanup_summary)


def _make_delete_service(
    db_session,
    *,
    cleanup_summary: dict[str, object] | None = None,
    cleanup_summaries_by_site_id: dict[str, dict[str, object]] | None = None,
    github_publisher: _StubGitHubPublisher | None = None,
    github_publish_config_service: _StubGitHubPublishConfigService | None = None,
    protected_control_plane_repository: str = "mhanson13/mbsrn",
) -> tuple[SEOSiteDeleteService, _StubGitHubPublisher]:
    publisher = github_publisher or _StubGitHubPublisher()
    migration_service = _StubSEOMigrationService(
        cleanup_summary=cleanup_summary,
        cleanup_summaries_by_site_id=cleanup_summaries_by_site_id,
        github_publisher=publisher,
        github_publish_config_service=github_publish_config_service,
    )
    service = SEOSiteDeleteService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_migration_service=migration_service,  # type: ignore[arg-type]
        protected_control_plane_repository=protected_control_plane_repository,
    )
    return service, publisher


def _publisher_error(code: str, safe_message: str | None = None) -> SEOMigrationGitHubPublisherError:
    return SEOMigrationGitHubPublisherError(
        code=code,
        safe_message=safe_message or code.replace("_", " "),
    )


def _managed_static_ip_cleanup_summary(
    *,
    repo_owner: str = "managed-owner",
    repo_name: str = "delete-me-site",
    ref: str = "main",
    preview_hostname: str | None = None,
    static_ip_name: str | None = None,
    shared_preview_static_ip_name: str | None = None,
    uses_shared_preview_gateway: bool = False,
    dns_managed_zone: str | None = None,
    dns_project_id: str | None = None,
    kubernetes_namespace: str | None = None,
    managed_gke_project_id: str = "project-1",
) -> dict[str, object]:
    deploy_target: dict[str, object] = {
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "ref": ref,
    }
    if preview_hostname is not None:
        deploy_target["preview_hostname"] = preview_hostname
    if static_ip_name is not None:
        deploy_target["expected_static_ip_name"] = static_ip_name
    if shared_preview_static_ip_name is not None:
        deploy_target["shared_preview_static_ip_name"] = shared_preview_static_ip_name
    if uses_shared_preview_gateway:
        deploy_target["uses_shared_preview_gateway"] = True
    if dns_managed_zone is not None:
        deploy_target["expected_dns_managed_zone"] = dns_managed_zone
    if dns_project_id is not None:
        deploy_target["expected_dns_project_id"] = dns_project_id
    if kubernetes_namespace is not None:
        deploy_target["kubernetes_namespace"] = kubernetes_namespace
    return {
        "workspace_id": None,
        "publish_target": {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch": ref,
        },
        "deploy_target": deploy_target,
        "admin_deploy_metadata": {
            "managed_gke_project_id": managed_gke_project_id,
            "namespace_isolation_defaults": {},
        },
    }


def _stub_dns_related_delete_cleanup(delete_service: SEOSiteDeleteService) -> None:
    def _execute_managed_certificate_cleanup(*, selected, context, site, gcp_deploy_key):
        del selected, site, gcp_deploy_key
        return (
            seo_site_delete_module._resource(
                "managed_certificate",
                "not_found",
                "No managed certificate was found for the expected namespace/name.",
                details={
                    "managed_certificate_name": context.managed_certificate_name,
                    "kubernetes_namespace": context.kubernetes_namespace,
                },
            ),
            {"blockers": [], "warnings": []},
        )

    def _execute_dns_cleanup(*, selected, context, gcp_deploy_key):
        del selected, gcp_deploy_key
        return (
            seo_site_delete_module._resource(
                "dns_record",
                "not_found",
                "No managed preview DNS A record was found for the expected hostname.",
                details={
                    "record_name": context.dns_record_name,
                    "managed_zone": context.dns_managed_zone,
                    "project_id": context.dns_project_id,
                },
            ),
            {"blockers": [], "warnings": []},
        )

    delete_service._execute_managed_certificate_cleanup = _execute_managed_certificate_cleanup
    delete_service._execute_dns_cleanup = _execute_dns_cleanup


def _install_static_ip_google_api(
    monkeypatch,
    *,
    address_payload: dict[str, object] | None = None,
    address_payload_sequence: list[dict[str, object] | None] | None = None,
    dns_a_rrset: dict[str, object] | None = None,
    delete_error: SEOMigrationGitHubPublisherError | None = None,
) -> dict[str, object]:
    calls: dict[str, object] = {
        "address_get_count": 0,
        "dns_get_count": 0,
        "delete_urls": [],
    }
    queued_payloads = list(address_payload_sequence or [])

    def _copy_payload(payload: dict[str, object] | None):
        if isinstance(payload, dict):
            return deepcopy(payload)
        return payload

    fallback_payload = _copy_payload(address_payload)

    def _fake_request_google_json(*, method, url, **kwargs):
        del kwargs
        if method == "GET" and "/global/addresses/" in url:
            calls["address_get_count"] = int(calls["address_get_count"]) + 1
            payload = queued_payloads.pop(0) if queued_payloads else _copy_payload(fallback_payload)
            if isinstance(payload, Exception):
                raise payload
            return _copy_payload(payload)
        if method == "GET" and "/managedZones/" in url:
            calls["dns_get_count"] = int(calls["dns_get_count"]) + 1
            if "type=CNAME" in url:
                return {"rrsets": []}
            if dns_a_rrset is None:
                return {"rrsets": []}
            return {"rrsets": [deepcopy(dns_a_rrset)]}
        if method == "DELETE" and "/global/addresses/" in url:
            delete_urls = calls["delete_urls"]
            assert isinstance(delete_urls, list)
            delete_urls.append(url)
            if delete_error is not None:
                raise delete_error
            return {}
        raise AssertionError(f"Unexpected Google request: {method} {url}")

    monkeypatch.setattr(seo_site_delete_module, "_request_google_json", _fake_request_google_json)
    return calls


def test_seo_site_crud_and_business_scoping(db_session, seeded_business) -> None:
    other_business = Business(
        id=str(uuid4()),
        name="Other Tenant",
        notification_phone="+13035550199",
        notification_email="owner@other.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
        timezone="America/Denver",
    )
    db_session.add(other_business)
    db_session.commit()

    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Main Site",
            "base_url": "https://Example.COM/",
            "industry": "Fire Restoration",
            "primary_location": "Denver, CO",
            "service_areas": ["Denver", "Lakewood"],
            "is_active": True,
            "is_primary": True,
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["normalized_domain"] == "example.com"
    assert created["base_url"] == "https://example.com/"
    assert created["last_audit_run_id"] is None
    assert created["last_audit_status"] is None
    assert created["last_audit_completed_at"] is None
    assert created["search_console_property_url"] is None
    assert created["search_console_enabled"] is False
    assert created["ga4_onboarding_status"] == "not_connected"
    assert created["ga4_account_id"] is None
    assert created["ga4_property_id"] is None
    assert created["ga4_data_stream_id"] is None
    assert created["ga4_measurement_id"] is None

    site_id = created["id"]
    list_response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == site_id

    read_response = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}")
    assert read_response.status_code == 200

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"display_name": "Main Site Updated", "base_url": "https://example.com/services/"},
    )
    assert patch_response.status_code == 200
    patched = patch_response.json()
    assert patched["display_name"] == "Main Site Updated"
    assert patched["base_url"] == "https://example.com/services"
    assert patched["search_console_property_url"] is None
    assert patched["search_console_enabled"] is False
    assert patched["ga4_onboarding_status"] == "not_connected"
    assert patched["ga4_account_id"] is None
    assert patched["ga4_property_id"] is None
    assert patched["ga4_data_stream_id"] is None
    assert patched["ga4_measurement_id"] is None

    cross_tenant = client.get(f"/api/businesses/{other_business.id}/seo/sites/{site_id}")
    assert cross_tenant.status_code == 404


def test_admin_can_set_site_level_search_console_configuration(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Search Console Site",
            "base_url": "https://search-console.example/",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "search_console_property_url": "sc-domain:search-console.example",
            "search_console_enabled": True,
        },
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["search_console_property_url"] == "sc-domain:search-console.example"
    assert payload["search_console_enabled"] is True


def test_admin_can_set_site_level_ga4_onboarding_configuration(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "GA4 Config Site",
            "base_url": "https://ga4-config.example/",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "ga4_account_id": "1000000001",
            "ga4_property_id": "2000000002",
            "ga4_data_stream_id": "3000000003",
            "ga4_measurement_id": "g-abc123xyz",
        },
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["ga4_account_id"] == "1000000001"
    assert payload["ga4_property_id"] == "2000000002"
    assert payload["ga4_data_stream_id"] == "3000000003"
    assert payload["ga4_measurement_id"] == "G-ABC123XYZ"
    assert payload["ga4_onboarding_status"] == "stream_configured"


def test_seo_site_invalid_url_rejected(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Bad URL Site",
            "base_url": "ftp://example.com",
        },
    )
    assert response.status_code == 422


def test_seo_site_duplicate_domain_rejected_for_business(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_role=PrincipalRole.ADMIN,
    )
    first = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Main Site",
            "base_url": "https://example.com/",
        },
    )
    assert first.status_code == 201

    duplicate = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Duplicate Domain",
            "base_url": "https://EXAMPLE.com/services",
        },
    )
    assert duplicate.status_code == 422
    assert "already exists" in duplicate.json()["detail"].lower()


def test_admin_can_deactivate_and_reactivate_site(db_session, seeded_business) -> None:
    admin_principal = Principal(
        business_id=seeded_business.id,
        id="seo-admin",
        display_name="SEO Admin",
        role=PrincipalRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin_principal)
    db_session.commit()
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/deactivate",
    )
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False

    activate_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/activate",
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True


def test_operator_cannot_deactivate_site(db_session, seeded_business) -> None:
    operator_principal = Principal(
        business_id=seeded_business.id,
        id="seo-operator",
        display_name="SEO Operator",
        role=PrincipalRole.OPERATOR,
        is_active=True,
    )
    db_session.add(operator_principal)
    db_session.commit()
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=operator_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    deactivate_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}/deactivate",
    )
    assert deactivate_response.status_code == 403


def test_operator_cannot_patch_site_activation_state(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-test",
        principal_role=PrincipalRole.OPERATOR,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"is_active": False},
    )
    assert patch_response.status_code == 403


def test_operator_cannot_patch_site_name_or_url(db_session, seeded_business) -> None:
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id="operator-test",
        principal_role=PrincipalRole.OPERATOR,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    rename_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"display_name": "Renamed"},
    )
    assert rename_response.status_code == 403

    reurl_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={"base_url": "https://example.com/new"},
    )
    assert reurl_response.status_code == 403

    search_console_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "search_console_property_url": "sc-domain:example.com",
            "search_console_enabled": True,
        },
    )
    assert search_console_response.status_code == 403

    ga4_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "ga4_account_id": "1000000001",
        },
    )
    assert ga4_response.status_code == 403


def test_admin_can_update_site_name_via_admin_endpoint(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"name": "Renamed Site"},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["display_name"] == "Renamed Site"
    assert payload["base_url"] == "https://example.com/"


def test_admin_can_update_site_url_via_admin_endpoint(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"url": "https://EXAMPLE.com/services/"},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["base_url"] == "https://example.com/services"
    assert payload["normalized_domain"] == "example.com"


def test_admin_site_domain_change_clears_stale_industry_when_not_explicitly_updated(
    db_session, seeded_business
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Legacy Roofing Site",
            "base_url": "https://legacy-roofing.example/",
            "industry": "Roofing services",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    assert create_response.json()["industry"] == "Roofing services"

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"url": "https://vmsdata.com/"},
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["normalized_domain"] == "vmsdata.com"
    assert payload["industry"] is None


def test_site_patch_domain_change_keeps_industry_when_explicitly_supplied(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        principal_role=PrincipalRole.ADMIN,
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={
            "display_name": "Legacy Roofing Site",
            "base_url": "https://legacy-roofing.example/",
            "industry": "Roofing services",
        },
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}",
        json={
            "base_url": "https://vmsdata.com/",
            "industry": "Managed IT and cloud hosting services",
        },
    )
    assert patch_response.status_code == 200
    payload = patch_response.json()
    assert payload["normalized_domain"] == "vmsdata.com"
    assert payload["industry"] == "Managed IT and cloud hosting services"


def test_admin_site_url_validation_rejects_invalid_url(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Main Site", "base_url": "https://example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    patch_response = client.patch(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
        json={"url": "ftp://example.com"},
    )
    assert patch_response.status_code == 422
    assert "http or https" in patch_response.json()["detail"].lower()


def test_operator_cannot_plan_or_execute_permanent_site_delete(db_session, seeded_business) -> None:
    operator_principal = _seed_principal(
        db_session=db_session,
        business_id=seeded_business.id,
        principal_id="seo-operator-delete",
        role=PrincipalRole.OPERATOR,
    )
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=operator_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Protected Site", "base_url": "https://protected.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 403
    assert plan_response.json()["detail"]["reason_code"] == "site_delete_not_authorized"

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={"confirmation_phrase": "DELETE protected"},
    )
    assert execute_response.status_code == 403
    assert execute_response.json()["detail"]["reason_code"] == "site_delete_not_authorized"


def test_admin_site_delete_plan_returns_safe_summary_without_deleting(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    cleanup_summary = {
        "workspace_id": None,
        "publish_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "branch": "main",
            "private_token": "do-not-leak",
        },
        "deploy_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "ref": "main",
            "preview_url": "https://private-preview.internal",
            "private_preview_url": "https://private-preview.internal/secret",
        },
        "admin_deploy_metadata": {
            "token": "SECRET_TOKEN",
            "namespace_isolation_defaults": {},
        },
    }
    delete_service, _publisher = _make_delete_service(
        db_session,
        cleanup_summary=cleanup_summary,
        github_publish_config_service=_StubGitHubPublishConfigService(),
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    _seed_site_owned_data(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=site_id,
        token="delete-plan",
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    payload = plan_response.json()
    assert payload["reason_code"] == "site_delete_plan_ready"
    assert payload["site_id"] == site_id
    assert payload["is_active"] is False
    assert payload["generated_repo_owner"] == "managed-owner"
    assert payload["generated_repo_name"] == "delete-me-site"
    assert payload["db_dependency_total"] >= len(_SITE_OWNED_MODELS)
    assert any(item["category"] == "migration" for item in payload["db_dependencies"])
    assert any(item["category"] == "actions" for item in payload["db_dependencies"])
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}").status_code == 200

    payload_text = json.dumps(payload, sort_keys=True)
    assert "SECRET_TOKEN" not in payload_text
    assert "private-preview.internal/secret" not in payload_text
    assert "do-not-leak" not in payload_text


def test_admin_site_delete_plan_uses_precise_warning_codes_for_limited_verification(
    db_session, seeded_business
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    cleanup_summary = {
        "workspace_id": None,
        "publish_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "branch": "main",
        },
        "deploy_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "ref": "main",
            "preview_hostname": "delete-me.preview.example.com",
            "kubernetes_namespace": "site-delete-me",
            "managed_certificate_name": "delete-me-cert",
        },
        "admin_deploy_metadata": {
            "managed_gke_cluster_name": "cluster-1",
            "managed_gke_cluster_location": "us-central1",
            "managed_gke_project_id": "project-1",
            "namespace_isolation_defaults": {},
        },
    }
    publisher = _StubGitHubPublisher(
        preflight_error=_publisher_error("repo_preflight_failed"),
        managed_certificate_error=_publisher_error("managed_certificate_check_failed"),
    )
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=cleanup_summary,
        github_publisher=publisher,
        github_publish_config_service=_StubGitHubPublishConfigService(managed_gcp_deploy_key_error=True),
    )

    def _raise_runtime_inspection(*, context, gcp_deploy_key):
        del context, gcp_deploy_key
        raise _publisher_error("runtime_inspection_failed")

    delete_service._inspect_runtime_resources = _raise_runtime_inspection

    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    payload = plan_response.json()
    warning_codes = {item["reason_code"] for item in payload["warnings"]}
    assert payload["reason_code"] == "site_delete_plan_ready"
    assert "site_delete_plan_ready" not in warning_codes
    assert "site_delete_external_verification_limited" in warning_codes
    assert "site_delete_git_repo_verification_limited" in warning_codes
    assert "site_delete_runtime_verification_limited" in warning_codes
    assert "site_delete_managed_certificate_verification_limited" in warning_codes


def test_admin_site_delete_plan_uses_precise_static_ip_warning_codes(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    cleanup_summary = {
        "workspace_id": None,
        "publish_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "branch": "main",
        },
        "deploy_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "ref": "main",
            "expected_static_ip_name": "delete-me-ip",
            "uses_shared_preview_gateway": True,
        },
        "admin_deploy_metadata": {
            "managed_gke_project_id": "project-1",
            "namespace_isolation_defaults": {},
        },
    }
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=cleanup_summary,
        github_publish_config_service=_StubGitHubPublishConfigService(),
    )

    def _raise_static_ip_inspection(*, context, gcp_deploy_key):
        del context, gcp_deploy_key
        raise _publisher_error("static_ip_inspection_failed")

    delete_service._inspect_static_ip = _raise_static_ip_inspection

    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    warning_codes = {item["reason_code"] for item in plan_response.json()["warnings"]}
    assert "site_delete_plan_ready" not in warning_codes
    assert "site_delete_static_ip_shared_gateway_not_auto_deleted" in warning_codes
    assert "site_delete_static_ip_verification_limited" in warning_codes


def test_admin_site_delete_plan_uses_precise_dns_warning_codes(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    cleanup_summary = {
        "workspace_id": None,
        "publish_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "branch": "main",
        },
        "deploy_target": {
            "repo_owner": "managed-owner",
            "repo_name": "delete-me-site",
            "ref": "main",
            "preview_hostname": "delete-me.preview.example.com",
            "expected_static_ip_name": "delete-me-ip",
            "expected_dns_managed_zone": "preview-zone",
            "expected_dns_project_id": "dns-project-1",
        },
        "admin_deploy_metadata": {
            "managed_gke_project_id": "project-1",
            "namespace_isolation_defaults": {},
        },
    }
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=cleanup_summary,
        github_publish_config_service=_StubGitHubPublishConfigService(),
    )

    def _return_static_ip_inspection(*, context, gcp_deploy_key):
        del context, gcp_deploy_key
        return {
            "status": "ready",
            "summary": "Managed preview static IP ownership is ready for cleanup.",
            "details": {
                "static_ip_name": "delete-me-ip",
                "observed_address": "203.0.113.10",
            },
        }

    def _raise_dns_inspection(*, context, gcp_deploy_key, expected_ip_address):
        del context, gcp_deploy_key, expected_ip_address
        raise _publisher_error("dns_inspection_failed")

    delete_service._inspect_static_ip = _return_static_ip_inspection
    delete_service._inspect_dns_record = _raise_dns_inspection

    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    warning_codes = {item["reason_code"] for item in plan_response.json()["warnings"]}
    assert "site_delete_plan_ready" not in warning_codes
    assert "site_delete_dns_verification_limited" in warning_codes


def test_admin_site_delete_plan_blocks_unverified_static_ip_cleanup(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            preview_hostname="delete-me.preview.example.com",
            static_ip_name="delete-me-ip",
        ),
    )
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "delete-me-ip",
            "address": "203.0.113.10",
            "status": "RESERVED",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": [],
        },
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    static_ip_resource = next(
        item for item in plan_response.json()["external_resources"] if item["resource_type"] == "static_ip"
    )
    assert static_ip_resource["status"] == "blocked"
    assert static_ip_resource["reason_code"] == "static_ip_delete_skipped_unverified_ownership"
    assert static_ip_resource["details"]["ownership_status"] == "unverified"
    assert static_ip_resource["details"]["delete_eligible"] is False
    assert static_ip_resource["details"]["observed_address"] == "203.0.113.10"


def test_admin_site_delete_execute_deletes_label_verified_static_ip(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            preview_hostname="delete-me.preview.example.com",
            static_ip_name="delete-me-ip",
        ),
    )
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "delete-me-ip",
            "address": "203.0.113.11",
            "status": "RESERVED",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": [],
            "labels": {
                "app.kubernetes.io/managed-by": "mbsrn",
                "mbsrn.io/site-id": site_id,
                "mbsrn.io/repo": "delete-me-site",
                "mbsrn.io/preview-hostname": "delete-me.preview.example.com",
            },
            "labelFingerprint": "fingerprint-1",
        },
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    static_ip_result = next(item for item in result["external_resources"] if item["resource_type"] == "static_ip")
    assert result["reason_code"] == "site_delete_completed"
    assert result["site_deleted"] is True
    assert result["external_cleanup_selected"] is True
    assert result["external_cleanup_partial"] is False
    assert static_ip_result["status"] == "deleted"
    assert static_ip_result["reason_code"] == "static_ip_deleted"
    assert static_ip_result["details"]["ownership_status"] == "verified"
    assert static_ip_result["details"]["ownership_verification_method"] == "labels"
    assert static_ip_result["details"]["delete_eligible"] is True
    assert google_calls["delete_urls"]
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}").status_code == 404


def test_admin_site_delete_execute_deletes_static_ip_with_dns_fallback(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            preview_hostname="delete-me.preview.example.com",
            static_ip_name="delete-me-ip",
            dns_managed_zone="preview-zone",
            dns_project_id="dns-project-1",
        ),
    )
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "delete-me-ip",
            "address": "203.0.113.12",
            "status": "RESERVED",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": [],
        },
        dns_a_rrset={
            "name": "delete-me.preview.example.com.",
            "type": "A",
            "ttl": 300,
            "rrdatas": ["203.0.113.12"],
        },
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    static_ip_result = next(
        item for item in execute_response.json()["external_resources"] if item["resource_type"] == "static_ip"
    )
    assert static_ip_result["status"] == "deleted"
    assert static_ip_result["reason_code"] == "static_ip_deleted"
    assert static_ip_result["details"]["ownership_status"] == "verified"
    assert static_ip_result["details"]["ownership_verification_method"] == "dns_name_fallback"
    assert google_calls["delete_urls"]


def test_admin_site_delete_execute_skips_static_ip_when_in_use(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            static_ip_name="delete-me-ip",
        ),
    )
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "delete-me-ip",
            "address": "203.0.113.13",
            "status": "IN_USE",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": ["https://compute.googleapis.com/compute/v1/projects/project-1/global/forwardingRules/site-web"],
        },
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    static_ip_result = next(item for item in result["external_resources"] if item["resource_type"] == "static_ip")
    assert result["site_deleted"] is True
    assert result["external_cleanup_partial"] is True
    assert static_ip_result["status"] == "skipped"
    assert static_ip_result["reason_code"] == "static_ip_delete_skipped_in_use"
    assert static_ip_result["details"]["ownership_status"] == "in_use"
    assert static_ip_result["details"]["delete_eligible"] is False
    assert google_calls["delete_urls"] == []


def test_admin_site_delete_execute_skips_shared_gateway_static_ip(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            static_ip_name="shared-preview-ip",
            shared_preview_static_ip_name="shared-preview-ip",
            uses_shared_preview_gateway=True,
        ),
    )
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "shared-preview-ip",
            "address": "203.0.113.14",
            "status": "RESERVED",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": [],
        },
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]
    plan_get_count = int(google_calls["address_get_count"])

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    static_ip_result = next(
        item for item in execute_response.json()["external_resources"] if item["resource_type"] == "static_ip"
    )
    assert static_ip_result["status"] == "skipped"
    assert static_ip_result["reason_code"] == "static_ip_delete_skipped_shared_gateway"
    assert static_ip_result["details"]["ownership_status"] == "shared"
    assert int(google_calls["address_get_count"]) == plan_get_count + 1
    assert google_calls["delete_urls"] == []


def test_admin_site_delete_execute_skips_conflicting_static_ip_reference(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(db_session)
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_one = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    create_two = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Keep Me", "base_url": "https://keep-me.example.com/", "is_active": False},
    )
    assert create_one.status_code == 201
    assert create_two.status_code == 201
    delete_site_id = create_one.json()["id"]
    keep_site_id = create_two.json()["id"]
    delete_service.seo_migration_service.cleanup_summaries_by_site_id = {
        delete_site_id: _managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            preview_hostname="delete-me.preview.example.com",
            static_ip_name="shared-delete-ip",
        ),
        keep_site_id: _managed_static_ip_cleanup_summary(
            repo_name="keep-me-site",
            preview_hostname="keep-me.preview.example.com",
            static_ip_name="shared-delete-ip",
        ),
    }
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "shared-delete-ip",
            "address": "203.0.113.15",
            "status": "RESERVED",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": [],
        },
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{delete_site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{delete_site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    static_ip_result = next(item for item in result["external_resources"] if item["resource_type"] == "static_ip")
    assert result["site_deleted"] is True
    assert static_ip_result["status"] == "skipped"
    assert static_ip_result["reason_code"] == "static_ip_delete_skipped_conflicting_reference"
    assert static_ip_result["details"]["ownership_status"] == "conflicting_reference"
    assert static_ip_result["details"]["conflicting_reference_count"] == 1
    assert "static_ip_name" in static_ip_result["details"]["conflicting_reference_types"]
    assert google_calls["delete_urls"] == []
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{keep_site_id}").status_code == 200


def test_admin_site_delete_execute_revalidates_static_ip_before_delete(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            preview_hostname="delete-me.preview.example.com",
            static_ip_name="delete-me-ip",
        ),
    )
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    verified_payload = {
        "name": "delete-me-ip",
        "address": "203.0.113.16",
        "status": "RESERVED",
        "addressType": "EXTERNAL",
        "ipVersion": "IPV4",
        "users": [],
        "labels": {
            "app.kubernetes.io/managed-by": "mbsrn",
            "mbsrn.io/site-id": site_id,
            "mbsrn.io/repo": "delete-me-site",
            "mbsrn.io/preview-hostname": "delete-me.preview.example.com",
        },
        "labelFingerprint": "fingerprint-2",
    }
    _install_static_ip_google_api(monkeypatch, address_payload=verified_payload)
    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload_sequence=[
            verified_payload,
            {
                "name": "delete-me-ip",
                "address": "203.0.113.16",
                "status": "IN_USE",
                "addressType": "EXTERNAL",
                "ipVersion": "IPV4",
                "users": [
                    "https://compute.googleapis.com/compute/v1/projects/project-1/global/forwardingRules/site-web"
                ],
                "labels": {
                    "app.kubernetes.io/managed-by": "mbsrn",
                    "mbsrn.io/site-id": site_id,
                    "mbsrn.io/repo": "delete-me-site",
                    "mbsrn.io/preview-hostname": "delete-me.preview.example.com",
                },
                "labelFingerprint": "fingerprint-3",
            },
        ],
    )

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    static_ip_result = next(item for item in result["external_resources"] if item["resource_type"] == "static_ip")
    assert result["site_deleted"] is True
    assert static_ip_result["status"] == "skipped"
    assert static_ip_result["reason_code"] == "static_ip_delete_skipped_in_use"
    assert static_ip_result["details"]["ownership_status"] == "in_use"
    assert int(google_calls["address_get_count"]) == 2
    assert google_calls["delete_urls"] == []


def test_admin_site_delete_execute_reports_static_ip_delete_failure_after_verified_ownership(
    db_session, seeded_business, monkeypatch
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary=_managed_static_ip_cleanup_summary(
            repo_name="delete-me-site",
            preview_hostname="delete-me.preview.example.com",
            static_ip_name="delete-me-ip",
        ),
    )
    _stub_dns_related_delete_cleanup(delete_service)
    delete_service._resolve_google_access_token = lambda **_: ("token", 15)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]
    google_calls = _install_static_ip_google_api(
        monkeypatch,
        address_payload={
            "name": "delete-me-ip",
            "address": "203.0.113.17",
            "status": "RESERVED",
            "addressType": "EXTERNAL",
            "ipVersion": "IPV4",
            "users": [],
            "labels": {
                "app.kubernetes.io/managed-by": "mbsrn",
                "mbsrn.io/site-id": site_id,
                "mbsrn.io/repo": "delete-me-site",
                "mbsrn.io/preview-hostname": "delete-me.preview.example.com",
            },
            "labelFingerprint": "fingerprint-4",
        },
        delete_error=_publisher_error("static_ip_delete_failed"),
    )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
            "delete_dns_resources": True,
            "acknowledge_delete_dns_resources": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    static_ip_result = next(item for item in result["external_resources"] if item["resource_type"] == "static_ip")
    assert result["site_deleted"] is True
    assert result["external_cleanup_partial"] is True
    assert static_ip_result["status"] == "failed"
    assert static_ip_result["reason_code"] == "static_ip_delete_failed"
    assert "publisher_reason_code" not in static_ip_result["details"]
    assert google_calls["delete_urls"]


def test_admin_site_delete_execute_requires_exact_confirmation_phrase(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _publisher = _make_delete_service(db_session)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": "DELETE wrong target",
            "acknowledge_delete_database_records": True,
        },
    )
    assert execute_response.status_code == 422
    assert execute_response.json()["detail"]["reason_code"] == "site_delete_confirmation_mismatch"
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}").status_code == 200


def test_admin_site_delete_blocks_active_site_without_force_delete(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _publisher = _make_delete_service(db_session)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Active Delete", "base_url": "https://active-delete.example.com/"},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    assert any(
        blocker["reason_code"] == "site_delete_active_site_blocked"
        for blocker in plan_payload["blockers"]
    )

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": plan_payload["required_confirmation_phrase"],
            "acknowledge_delete_database_records": True,
            "force_delete_active": False,
        },
    )
    assert execute_response.status_code == 409
    assert execute_response.json()["detail"]["reason_code"] == "site_delete_active_site_blocked"


def test_admin_can_execute_permanent_site_delete_and_remove_dynamic_site_owned_rows(
    db_session, seeded_business
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    delete_service, _publisher = _make_delete_service(db_session)
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_one = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Me", "base_url": "https://delete-me.example.com/", "is_active": False},
    )
    create_two = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Keep Me", "base_url": "https://keep-me.example.com/", "is_active": False},
    )
    assert create_one.status_code == 201
    assert create_two.status_code == 201
    delete_site_id = create_one.json()["id"]
    keep_site_id = create_two.json()["id"]

    _seed_site_owned_data(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=delete_site_id,
        token="delete-site",
    )
    _seed_site_owned_data(
        db_session=db_session,
        business_id=seeded_business.id,
        site_id=keep_site_id,
        token="keep-site",
    )

    for model in _SITE_OWNED_MODELS:
        assert (
            _count_site_rows(
                db_session=db_session,
                model=model,
                business_id=seeded_business.id,
                site_id=delete_site_id,
            )
            > 0
        )

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{delete_site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    confirmation_phrase = plan_response.json()["required_confirmation_phrase"]

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{delete_site_id}/delete",
        json={
            "confirmation_phrase": confirmation_phrase,
            "acknowledge_delete_database_records": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    assert result["reason_code"] == "site_delete_completed"
    assert result["db_deleted"] is True
    assert result["site_deleted"] is True
    assert result["external_cleanup_selected"] is False
    assert result["external_cleanup_partial"] is False
    assert all(item["reason_code"] == "external_cleanup_not_selected" for item in result["external_resources"])

    deleted_site_read = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{delete_site_id}")
    assert deleted_site_read.status_code == 404

    for model in _SITE_OWNED_MODELS:
        assert (
            _count_site_rows(
                db_session=db_session,
                model=model,
                business_id=seeded_business.id,
                site_id=delete_site_id,
            )
            == 0
        )
        assert (
            _count_site_rows(
                db_session=db_session,
                model=model,
                business_id=seeded_business.id,
                site_id=keep_site_id,
            )
            > 0
        )

    kept_site_read = client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{keep_site_id}")
    assert kept_site_read.status_code == 200


def test_admin_site_delete_reports_unmanaged_repo_blocker_without_deleting_repo(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    preflight_result = SEOMigrationGitHubPublishPreflightResult(
        repo_owner="customer-owner",
        repo_name="customer-repo",
        target_ref="main",
        repo_exists=True,
        repo_ensure_outcome="existing",
        target_ref_exists=True,
        repo_initialized=True,
        can_read_contents=True,
        can_write_contents=True,
        can_write_workflows=True,
        would_auto_create_repo=False,
        would_bootstrap_branch=False,
        preflight_status="blocked",
        preflight_blocker_code="github_repo_adoption_required",
        repo_management_status="unmanaged",
        repo_management_marker_present=False,
        repo_management_marker_valid=False,
        repo_management_marker_matches_site=False,
    )
    publisher = _StubGitHubPublisher(preflight_result=preflight_result)
    delete_service, stub_publisher = _make_delete_service(
        db_session,
        cleanup_summary={
            "workspace_id": None,
            "publish_target": {
                "repo_owner": "customer-owner",
                "repo_name": "customer-repo",
                "branch": "main",
            },
            "deploy_target": {
                "repo_owner": "customer-owner",
                "repo_name": "customer-repo",
                "ref": "main",
            },
            "admin_deploy_metadata": {},
        },
        github_publisher=publisher,
        github_publish_config_service=_StubGitHubPublishConfigService(repository="mhanson13"),
    )
    assert stub_publisher is publisher
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Delete Repo Site", "base_url": "https://delete-repo.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    github_plan_resource = next(
        item for item in plan_payload["external_resources"] if item["resource_type"] == "github_repo"
    )
    assert github_plan_resource["status"] == "blocked"
    assert github_plan_resource["reason_code"] == "github_repo_delete_adoption_required"

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": plan_payload["required_confirmation_phrase"],
            "acknowledge_delete_database_records": True,
            "delete_github_repo": True,
            "acknowledge_delete_github_repo": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    assert result["db_deleted"] is True
    assert result["external_cleanup_selected"] is True
    assert result["external_cleanup_partial"] is True
    github_result = next(item for item in result["external_resources"] if item["resource_type"] == "github_repo")
    assert github_result["status"] == "blocked"
    assert github_result["reason_code"] == "github_repo_delete_adoption_required"
    assert publisher.preflight_calls
    assert all(call[:2] == ("customer-owner", "customer-repo") for call in publisher.preflight_calls)
    assert publisher.delete_calls == []
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}").status_code == 404


def test_admin_site_delete_blocks_protected_control_plane_repo_without_preflight_or_delete(
    db_session, seeded_business
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    publisher = _StubGitHubPublisher()
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary={
            "workspace_id": None,
            "publish_target": {
                "repo_owner": "mhanson13",
                "repo_name": "mbsrn",
                "branch": "main",
            },
            "deploy_target": {
                "repo_owner": " MHanson13 ",
                "repo_name": " MBSRN ",
                "ref": "main",
            },
            "admin_deploy_metadata": {},
        },
        github_publisher=publisher,
        github_publish_config_service=_StubGitHubPublishConfigService(repository="mhanson13"),
        protected_control_plane_repository=" mhanson13 / mbsrn ",
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Protected Repo Site", "base_url": "https://protected-repo.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    github_plan_resource = next(
        item for item in plan_payload["external_resources"] if item["resource_type"] == "github_repo"
    )
    assert github_plan_resource["status"] == "blocked"
    assert github_plan_resource["reason_code"] == "github_repo_delete_protected_control_plane_repo_blocked"
    assert (
        github_plan_resource["summary"]
        == "This repository is configured as the MBSRN control-plane source repo and cannot be deleted by site cleanup."
    )
    assert any(
        blocker["reason_code"] == "github_repo_delete_protected_control_plane_repo_blocked"
        and blocker["message"]
        == "This repository is configured as the MBSRN control-plane source repo and cannot be deleted by site cleanup."
        for blocker in plan_payload["blockers"]
    )
    assert publisher.preflight_calls == []

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": plan_payload["required_confirmation_phrase"],
            "acknowledge_delete_database_records": True,
            "delete_github_repo": True,
            "acknowledge_delete_github_repo": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    github_result = next(item for item in result["external_resources"] if item["resource_type"] == "github_repo")
    assert github_result["status"] == "blocked"
    assert github_result["reason_code"] == "github_repo_delete_protected_control_plane_repo_blocked"
    assert publisher.preflight_calls == []
    assert publisher.delete_calls == []
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}").status_code == 404


def test_admin_site_delete_fails_closed_when_protected_repo_guard_config_is_invalid(
    db_session, seeded_business
) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    publisher = _StubGitHubPublisher()
    delete_service, _ = _make_delete_service(
        db_session,
        cleanup_summary={
            "workspace_id": None,
            "publish_target": {
                "repo_owner": "managed-owner",
                "repo_name": "delete-me-site",
                "branch": "main",
            },
            "deploy_target": {
                "repo_owner": "managed-owner",
                "repo_name": "delete-me-site",
                "ref": "main",
            },
            "admin_deploy_metadata": {},
        },
        github_publisher=publisher,
        github_publish_config_service=_StubGitHubPublishConfigService(repository="managed-owner"),
        protected_control_plane_repository="invalid-repo-name",
    )
    client = _make_client(
        db_session,
        business_id=seeded_business.id,
        principal_id=admin_principal.id,
        dependency_overrides={get_seo_site_delete_service: lambda: delete_service},
    )

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Invalid Guard Site", "base_url": "https://invalid-guard.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    plan_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete-plan",
    )
    assert plan_response.status_code == 200
    plan_payload = plan_response.json()
    github_plan_resource = next(
        item for item in plan_payload["external_resources"] if item["resource_type"] == "github_repo"
    )
    assert github_plan_resource["status"] == "blocked"
    assert github_plan_resource["reason_code"] == "github_repo_delete_unmanaged_repo_blocked"
    assert (
        github_plan_resource["summary"]
        == "GitHub repository deletion is blocked until the protected control-plane repository setting is a valid owner/repo value."
    )
    assert publisher.preflight_calls == []

    execute_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}/delete",
        json={
            "confirmation_phrase": plan_payload["required_confirmation_phrase"],
            "acknowledge_delete_database_records": True,
            "delete_github_repo": True,
            "acknowledge_delete_github_repo": True,
        },
    )
    assert execute_response.status_code == 200
    result = execute_response.json()
    github_result = next(item for item in result["external_resources"] if item["resource_type"] == "github_repo")
    assert github_result["status"] == "blocked"
    assert github_result["reason_code"] == "github_repo_delete_unmanaged_repo_blocked"
    assert publisher.preflight_calls == []
    assert publisher.delete_calls == []
    assert client.get(f"/api/businesses/{seeded_business.id}/seo/sites/{site_id}").status_code == 404


def test_legacy_admin_site_delete_endpoint_requires_plan_and_confirmation(db_session, seeded_business) -> None:
    admin_principal = _seed_admin_principal(db_session=db_session, business_id=seeded_business.id)
    client = _make_client(db_session, business_id=seeded_business.id, principal_id=admin_principal.id)

    create_response = client.post(
        f"/api/businesses/{seeded_business.id}/seo/sites",
        json={"display_name": "Legacy Delete", "base_url": "https://legacy-delete.example.com/", "is_active": False},
    )
    assert create_response.status_code == 201
    site_id = create_response.json()["id"]

    delete_response = client.delete(
        f"/api/businesses/{seeded_business.id}/seo/admin/sites/{site_id}",
    )
    assert delete_response.status_code == 422
    assert delete_response.json()["detail"]["reason_code"] == "site_delete_confirmation_required"
