from __future__ import annotations

import json

import pytest

from app.integrations.seo_migration_artifact_provider import (
    SEOMigrationArtifactGenerationOutput,
    SEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
    SEOMigrationGeneratedFileOutput,
)
from app.integrations.seo_migration_github_publisher import (
    SEOMigrationGitHubDeployResult,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishResult,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
)
from app.models.business import Business
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_audit_summary_repository import SEOAuditSummaryRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_competitor_summary_repository import SEOCompetitorSummaryRepository
from app.repositories.seo_migration_repository import SEOMigrationRepository
from app.repositories.seo_recommendation_narrative_repository import SEORecommendationNarrativeRepository
from app.repositories.seo_recommendation_repository import SEORecommendationRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.seo_migration import SEOMigrationService, SEOMigrationValidationError
from app.services.seo_migration_context import SEOMigrationContextAssembler
from app.services.seo_migration_ingest import SEOMigrationSourceIngestService


class _StaticMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, output: SEOMigrationArtifactGenerationOutput) -> None:
        self.output = output

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        return self.output


class _RaisingMigrationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(self, error: SEOMigrationArtifactProviderError) -> None:
        self.error = error

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        raise self.error


class _RecordingGitHubPublisher(SEOMigrationGitHubPublisher):
    def __init__(self, *, fail_publish: bool = False, fail_deploy: bool = False) -> None:
        self.fail_publish = fail_publish
        self.fail_deploy = fail_deploy
        self.publish_calls: list[
            tuple[SEOMigrationGitHubPublishTarget, list[SEOMigrationGitHubPublishFile], str, bool]
        ] = []
        self.deploy_calls: list[tuple[SEOMigrationGitHubDeployTarget, bool]] = []

    def publish_files(
        self,
        *,
        target: SEOMigrationGitHubPublishTarget,
        files: list[SEOMigrationGitHubPublishFile],
        commit_message: str,
        dry_run: bool,
    ) -> SEOMigrationGitHubPublishResult:
        self.publish_calls.append((target, list(files), commit_message, dry_run))
        if self.fail_publish:
            raise SEOMigrationGitHubPublisherError(
                code="publish_failed",
                safe_message="Simulated publish failure.",
            )
        return SEOMigrationGitHubPublishResult(
            dry_run=dry_run,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            branch=target.branch,
            artifact_root=target.artifact_root,
            files_published=len(files),
            total_bytes=sum(len(item.content.encode("utf-8")) for item in files),
            commit_shas=() if dry_run else ("abc123",),
            committed_paths=tuple(item.path for item in files),
            published_at="2026-04-07T12:00:00+00:00",
        )

    def dispatch_deploy(
        self,
        *,
        target: SEOMigrationGitHubDeployTarget,
        dry_run: bool,
    ) -> SEOMigrationGitHubDeployResult:
        self.deploy_calls.append((target, dry_run))
        if self.fail_deploy:
            raise SEOMigrationGitHubPublisherError(
                code="deploy_failed",
                safe_message="Simulated deploy failure.",
            )
        return SEOMigrationGitHubDeployResult(
            dry_run=dry_run,
            repo_owner=target.repo_owner,
            repo_name=target.repo_name,
            workflow_id=target.workflow_id,
            ref=target.ref,
            inputs=dict(target.inputs),
            dispatched_at="2026-04-07T12:05:00+00:00",
        )


def _seed_business_and_site(db_session, *, ga_measurement_id: str | None = None) -> tuple[str, str]:
    business_id = "11111111-1111-1111-1111-111111111111"
    site_id = "22222222-2222-2222-2222-222222222222"
    business = Business(
        id=business_id,
        name="TNM Fire Protection",
        notification_phone="+13035550199",
        notification_email="owner@tnmfire.example",
        sms_enabled=True,
        email_enabled=True,
        customer_auto_ack_enabled=True,
        contractor_alerts_enabled=True,
    )
    site = SEOSite(
        id=site_id,
        business_id=business_id,
        display_name="TNM Fire",
        base_url="https://tnmfire.example/",
        normalized_domain="tnmfire.example",
        industry="fire protection",
        primary_location="Longmont, CO",
        ga4_measurement_id=ga_measurement_id,
        service_areas_json=["Longmont", "Boulder"],
        is_active=True,
        is_primary=True,
    )
    db_session.add(business)
    db_session.add(site)
    db_session.commit()
    return business_id, site_id


def _build_service(
    db_session,
    provider: SEOMigrationArtifactGenerationProvider,
    *,
    github_publisher: SEOMigrationGitHubPublisher | None = None,
) -> SEOMigrationService:
    return SEOMigrationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_migration_repository=SEOMigrationRepository(db_session),
        seo_audit_repository=SEOAuditRepository(db_session),
        seo_audit_summary_repository=SEOAuditSummaryRepository(db_session),
        seo_recommendation_repository=SEORecommendationRepository(db_session),
        seo_recommendation_narrative_repository=SEORecommendationNarrativeRepository(db_session),
        seo_competitor_repository=SEOCompetitorRepository(db_session),
        seo_competitor_summary_repository=SEOCompetitorSummaryRepository(db_session),
        ingest_service=SEOMigrationSourceIngestService(),
        context_assembler=SEOMigrationContextAssembler(),
        artifact_provider=provider,
        github_publisher=github_publisher,
        provider_name="mock",
        provider_model_name="mock-seo-migration-v1",
    )


def _seed_workspace(service: SEOMigrationService, *, business_id: str, site_id: str) -> None:
    service.create_or_update_workspace(
        business_id=business_id,
        site_id=site_id,
        source_url="https://legacy.example/",
        operator_requirements={"business_objectives": ["Replace legacy site"]},
        enriched_content_notes={"replacement_summary": "Use richer replacement content."},
        publish_config={"target_repo": "org/repo"},
        deploy_config={"target_cluster": "gke-prod"},
        principal_id="principal-1",
    )


def _build_publishable_output(*, index_content: str | None = None) -> SEOMigrationArtifactGenerationOutput:
    return SEOMigrationArtifactGenerationOutput(
        strategy_summary="Draft strategy",
        page_map=[{"path": "/", "title": "Home"}],
        homepage_structure=[],
        service_page_suggestions=[],
        cta_contact_structure={},
        seo_meta_suggestions={},
        redirect_suggestions=[],
        analytics_placeholders=[],
        generated_files=[
            SEOMigrationGeneratedFileOutput(
                path="index.html",
                media_type="text/html",
                content=index_content
                or "<html><head><!-- ANALYTICS_PLACEHOLDER --></head><body><h1>Draft</h1></body></html>",
            ),
            SEOMigrationGeneratedFileOutput(
                path="styles.css",
                media_type="text/css",
                content="body { color: #111; }",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )


def _configure_publish_target(
    service: SEOMigrationService,
    *,
    business_id: str,
    site_id: str,
    artifact_root: str = "",
) -> None:
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": artifact_root,
        },
        principal_id="principal-1",
    )


def _configure_deploy_target(
    service: SEOMigrationService,
    *,
    business_id: str,
    site_id: str,
    workflow_id: str = "deploy-www-prod.yml",
) -> None:
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": workflow_id,
            "ref": "main",
        },
        principal_id="principal-1",
    )


def test_generate_artifacts_applies_guardrails_and_analytics_normalization(db_session) -> None:
    output = SEOMigrationArtifactGenerationOutput(
        strategy_summary="Draft strategy",
        page_map=[{"path": "/", "title": "Home"}],
        homepage_structure=[],
        service_page_suggestions=[],
        cta_contact_structure={},
        seo_meta_suggestions={},
        redirect_suggestions=[],
        analytics_placeholders=[],
        generated_files=[
            SEOMigrationGeneratedFileOutput(
                path="index.html",
                media_type="text/html",
                content=(
                    "<html><head><script>gtag('config','G-ABCD1234');</script></head>"
                    "<body><h1>Draft</h1></body></html>"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="styles.css",
                media_type="text/css",
                content="body { color: #111; }",
            ),
            SEOMigrationGeneratedFileOutput(
                path="app/main.py",
                media_type="text/plain",
                content="print('forbidden')",
            ),
            SEOMigrationGeneratedFileOutput(
                path="../escape.html",
                media_type="text/html",
                content="<html></html>",
            ),
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "completed"
    assert artifact.file_count == 2
    files = artifact.generated_files_json or []
    paths = {str(item["path"]) for item in files if isinstance(item, dict)}
    assert paths == {"index.html", "styles.css"}
    index_file = next(item for item in files if item["path"] == "index.html")
    index_content = str(index_file["content"])
    assert "<!-- ANALYTICS_PLACEHOLDER -->" in index_content
    assert "gtag(" not in index_content
    warnings = artifact.parse_warnings_json or []
    assert any("forbidden generated path" in warning for warning in warnings)
    assert any("invalid path" in warning for warning in warnings)


def test_generate_artifacts_salvages_partial_provider_output(db_session) -> None:
    provider_error = SEOMigrationArtifactProviderError(
        code="schema_validation",
        safe_message="Provider returned malformed structured output.",
        provider_name="openai",
        model_name="gpt-4o-mini",
        prompt_version="seo-migration-v1",
        raw_output=json.dumps(
            {
                "strategy_summary": "Partial salvage strategy",
                "generated_files": [
                    {
                        "path": "index.html",
                        "media_type": "text/html",
                        "content": "<html><head></head><body>Recovered</body></html>",
                    },
                    {
                        "path": "app/main.py",
                        "media_type": "text/plain",
                        "content": "forbidden",
                    },
                ],
            },
            ensure_ascii=True,
        ),
    )
    service = _build_service(db_session, _RaisingMigrationProvider(provider_error))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    assert artifact.status == "partial"
    assert artifact.error_summary == "Provider returned malformed structured output."
    assert artifact.file_count == 1
    assert (artifact.generated_files_json or [])[0]["path"] == "index.html"
    warnings = artifact.parse_warnings_json or []
    assert any("Recovered partial provider output." in warning for warning in warnings)
    assert any("partially salvaged" in warning for warning in warnings)


def test_generate_artifacts_rejects_when_no_valid_files_remain(db_session) -> None:
    output = SEOMigrationArtifactGenerationOutput(
        strategy_summary="No usable files",
        page_map=[],
        homepage_structure=[],
        service_page_suggestions=[],
        cta_contact_structure={},
        seo_meta_suggestions={},
        redirect_suggestions=[],
        analytics_placeholders=[],
        generated_files=[
            SEOMigrationGeneratedFileOutput(
                path="app/main.py",
                media_type="text/plain",
                content="forbidden",
            )
        ],
        provider_name="mock",
        model_name="mock-seo-migration-v1",
        prompt_version="seo-migration-v1",
    )
    service = _build_service(db_session, _StaticMigrationProvider(output))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)

    with pytest.raises(SEOMigrationValidationError, match="No valid static files were generated"):
        service.generate_draft_artifacts(
            business_id=business_id,
            site_id=site_id,
            principal_id="principal-1",
        )


def test_publish_requires_approved_artifact(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "sites/tnmfire",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="not approved"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=True,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert publisher.publish_calls == []


def test_publish_and_deploy_flow_records_status_and_analytics(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session, ga_measurement_id="G-SITE1234")
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "sites/tnmfire",
        },
        principal_id="principal-1",
    )
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
        },
        principal_id="principal-1",
    )
    service.update_analytics_config(
        business_id=business_id,
        site_id=site_id,
        analytics_config={
            "enabled": True,
            "ga_measurement_id": "G-WORK1234",
            "insertion_mode": "publish_and_deploy",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved for publish",
        principal_id="principal-1",
    )

    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message="Publish migration",
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert publish_result.artifact.publish_status == "published"
    assert publish_result.workspace.publish_status == "published"
    assert publish_result.workspace.last_published_artifact_version_id == artifact.id
    assert publish_result.workspace.last_published_commit_sha == "abc123"
    assert publisher.publish_calls
    _, published_files, _, _ = publisher.publish_calls[-1]
    index_file = next(item for item in published_files if item.path == "index.html")
    assert "G-WORK1234" in index_file.content
    assert "ANALYTICS_PLACEHOLDER" not in index_file.content

    deploy_result = service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert deploy_result.artifact.deploy_status == "deploy_requested"
    assert deploy_result.workspace.deploy_status == "deploy_requested"
    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert deploy_target.inputs.get("ga_measurement_id") == "G-WORK1234"


def test_publish_filters_invalid_stored_paths_before_publish(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    artifact.generated_files_json = [
        {"path": "index.html", "content": "<html><head></head><body>ok</body></html>", "media_type": "text/html"},
        {"path": "app/main.py", "content": "print('bad')", "media_type": "text/plain"},
        {"path": "../escape.html", "content": "<html>bad</html>", "media_type": "text/html"},
    ]
    service.seo_migration_repository.save_artifact_version(artifact)
    db_session.commit()
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    publish_result = service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=True,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    assert publisher.publish_calls
    _, files, _, dry_run = publisher.publish_calls[-1]
    assert dry_run is True
    assert [item.path for item in files] == ["index.html"]
    warnings = publish_result.result.get("warnings")
    assert isinstance(warnings, list)
    assert any("outside static package boundary" in str(item) for item in warnings)


def test_publish_failure_records_failed_state_and_history(db_session) -> None:
    publisher = _RecordingGitHubPublisher(fail_publish=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated publish failure."):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    updated_artifact = service.get_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
    )
    updated_workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert updated_artifact.publish_status == "publish_failed"
    assert updated_workspace.publish_status == "publish_failed"
    history = updated_workspace.publish_history_json or []
    assert history
    last_entry = history[-1]
    assert last_entry.get("action") == "publish"
    assert last_entry.get("status") == "failed"
    assert last_entry.get("timestamp")
    assert last_entry.get("repo_owner") == "acme"
    assert last_entry.get("repo_name") == "tnmfire-site"
    assert last_entry.get("branch") == "main"
    assert last_entry.get("failure_category") == "provider_error"
    assert last_entry.get("error_summary") == "Simulated publish failure."
    assert "traceback" not in str(last_entry.get("error_summary", "")).lower()
    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    assert summary.publish_readiness.get("last_status") == "failed"
    assert summary.publish_readiness.get("last_failure_category") == "provider_error"
    assert summary.publish_readiness.get("last_failure_message") == "Simulated publish failure."
    migration_diagnostics = summary.context_summary.get("migration_diagnostics")
    assert isinstance(migration_diagnostics, dict)
    assert migration_diagnostics.get("last_publish_status") == "failed"
    assert migration_diagnostics.get("last_publish_failure_category") == "provider_error"
    assert bool(summary.deploy_readiness.get("ready")) is False
    deploy_reasons = [str(item).lower() for item in summary.deploy_readiness.get("reasons", [])]
    assert any("must be published before deploy" in reason for reason in deploy_reasons)


def test_deploy_omits_ga_input_when_analytics_mode_is_publish_only(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session, ga_measurement_id="G-SITE1234")
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    service.update_publish_config(
        business_id=business_id,
        site_id=site_id,
        publish_config={
            "enabled": True,
            "repo_owner": "acme",
            "repo_name": "tnmfire-site",
            "branch": "main",
            "artifact_root": "",
        },
        principal_id="principal-1",
    )
    service.update_deploy_config(
        business_id=business_id,
        site_id=site_id,
        deploy_config={
            "enabled": True,
            "workflow_id": "deploy-www-prod.yml",
            "ref": "main",
        },
        principal_id="principal-1",
    )
    service.update_analytics_config(
        business_id=business_id,
        site_id=site_id,
        analytics_config={
            "enabled": True,
            "ga_measurement_id": "G-WORK1234",
            "insertion_mode": "publish_only",
        },
        principal_id="principal-1",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    assert publisher.deploy_calls
    deploy_target, _ = publisher.deploy_calls[-1]
    assert "ga_measurement_id" not in deploy_target.inputs


def test_approve_twice_is_rejected(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved once",
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="already approved"):
        service.approve_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            approval_notes="Approved twice",
            principal_id="principal-1",
        )


def test_publish_duplicate_non_dry_run_is_rejected(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    with pytest.raises(SEOMigrationValidationError, match="already published"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert len(publisher.publish_calls) == 1


def test_deploy_duplicate_non_dry_run_is_rejected(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    with pytest.raises(SEOMigrationValidationError, match="already recorded"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert len(publisher.deploy_calls) == 1


def test_publish_retry_after_failure_is_deterministic(db_session) -> None:
    publisher = _RecordingGitHubPublisher(fail_publish=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="Simulated publish failure."):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    publisher.fail_publish = False
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    history = workspace.publish_history_json or []
    assert [str(item.get("status")) for item in history[-2:]] == ["failed", "published"]
    assert workspace.publish_status == "published"
    assert workspace.last_published_commit_sha == "abc123"


def test_deploy_retry_after_failure_preserves_publish_state(db_session) -> None:
    publisher = _RecordingGitHubPublisher(fail_deploy=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    workspace_after_publish = service.get_workspace(business_id=business_id, site_id=site_id)
    published_sha = workspace_after_publish.last_published_commit_sha

    with pytest.raises(SEOMigrationValidationError, match="Simulated deploy failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    workspace_after_failed_deploy = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history = workspace_after_failed_deploy.deploy_history_json or []
    assert workspace_after_failed_deploy.publish_status == "published"
    assert workspace_after_failed_deploy.last_published_commit_sha == published_sha
    assert workspace_after_failed_deploy.deploy_status == "deploy_failed"
    assert deploy_history
    last_failure = deploy_history[-1]
    assert last_failure.get("action") == "deploy"
    assert last_failure.get("status") == "failed"
    assert last_failure.get("workflow_id") == "deploy-www-prod.yml"
    assert last_failure.get("ref") == "main"
    assert last_failure.get("error_summary") == "Simulated deploy failure."

    publisher.fail_deploy = False
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )
    workspace_after_retry = service.get_workspace(business_id=business_id, site_id=site_id)
    deploy_history_after_retry = workspace_after_retry.deploy_history_json or []
    assert [str(item.get("status")) for item in deploy_history_after_retry[-2:]] == ["failed", "deploy_requested"]
    assert workspace_after_retry.publish_status == "published"
    assert workspace_after_retry.deploy_status == "deploy_requested"


def test_publish_rejects_reserved_git_root_path(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(
        service,
        business_id=business_id,
        site_id=site_id,
        artifact_root=".git/releases",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="artifact_root is invalid"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )
    assert not publisher.publish_calls


def test_deploy_rejects_reserved_workflow_path(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(
        service,
        business_id=business_id,
        site_id=site_id,
        workflow_id=".github/workflows/deploy-www-prod.yml",
    )
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="workflow_id is invalid"):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )
    assert not publisher.deploy_calls


def test_publish_analytics_insertion_collapses_duplicate_placeholders(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(
            _build_publishable_output(
                index_content=(
                    "<html><head><!-- ANALYTICS_PLACEHOLDER -->"
                    "<!-- ANALYTICS_PLACEHOLDER --></head><body>Draft</body></html>"
                )
            )
        ),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id="G-ABCD1234",
        principal_id="principal-1",
    )
    assert publisher.publish_calls
    _, published_files, _, _ = publisher.publish_calls[-1]
    index_file = next(item for item in published_files if item.path == "index.html")
    assert index_file.content.count("googletagmanager.com/gtag/js?id=G-ABCD1234") == 1
    assert index_file.content.count("gtag('config', 'G-ABCD1234');") == 1
    assert "ANALYTICS_PLACEHOLDER" not in index_file.content


def test_publish_dry_run_does_not_overwrite_published_state(db_session) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=True,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    updated_artifact = service.get_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
    )
    workspace = service.get_workspace(business_id=business_id, site_id=site_id)
    assert updated_artifact.publish_status == "published"
    assert workspace.publish_status == "published"
    assert workspace.last_published_commit_sha == "abc123"
    publish_history = workspace.publish_history_json or []
    assert publish_history[-1].get("status") == "dry_run"


def test_missing_publisher_config_is_categorized_for_readiness_and_errors(db_session) -> None:
    service = _build_service(db_session, _StaticMigrationProvider(_build_publishable_output()))
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )

    with pytest.raises(SEOMigrationValidationError, match="not configured"):
        service.publish_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            commit_message=None,
            analytics_measurement_id=None,
            principal_id="principal-1",
        )

    summary = service.get_workspace_summary(business_id=business_id, site_id=site_id)
    assert summary.publish_readiness.get("failure_category") == "config_missing"
    publish_prereqs = summary.publish_readiness.get("config_prerequisites")
    assert isinstance(publish_prereqs, dict)
    assert publish_prereqs.get("github_publisher_configured") is False
    assert summary.deploy_readiness.get("failure_category") == "config_missing"


def test_publish_deploy_emit_structured_control_plane_logs(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher()
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes="Approved",
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )
    service.deploy_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        principal_id="principal-1",
    )

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
    ]
    assert payloads
    for payload in payloads:
        assert payload.get("business_id") == business_id
        assert payload.get("site_id") == site_id
        assert payload.get("workspace_id")
        assert payload.get("artifact_version_id") == artifact.id
        assert isinstance(payload.get("timestamp"), str)
        assert isinstance(payload.get("target"), dict)
        assert "failure_category" in payload
    assert any(payload.get("action") == "approve" and payload.get("status") == "requested" for payload in payloads)
    assert any(
        payload.get("action") == "approve"
        and payload.get("status") == "completed"
        and isinstance(payload.get("duration_ms"), int)
        for payload in payloads
    )
    assert any(
        payload.get("action") == "publish"
        and payload.get("status") == "completed"
        and isinstance(payload.get("target"), dict)
        and payload.get("target", {}).get("repo_owner") == "acme"
        for payload in payloads
    )
    assert any(
        payload.get("action") == "deploy"
        and payload.get("status") == "completed"
        and isinstance(payload.get("target"), dict)
        and payload.get("target", {}).get("workflow_id") == "deploy-www-prod.yml"
        for payload in payloads
    )


def test_deploy_failure_logs_failure_category(db_session, caplog) -> None:
    publisher = _RecordingGitHubPublisher(fail_deploy=True)
    service = _build_service(
        db_session,
        _StaticMigrationProvider(_build_publishable_output()),
        github_publisher=publisher,
    )
    business_id, site_id = _seed_business_and_site(db_session)
    _seed_workspace(service, business_id=business_id, site_id=site_id)
    _configure_publish_target(service, business_id=business_id, site_id=site_id)
    _configure_deploy_target(service, business_id=business_id, site_id=site_id)
    artifact = service.generate_draft_artifacts(
        business_id=business_id,
        site_id=site_id,
        principal_id="principal-1",
    )
    service.approve_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        approval_notes=None,
        principal_id="principal-1",
    )
    service.publish_artifact_version(
        business_id=business_id,
        site_id=site_id,
        artifact_version_id=artifact.id,
        dry_run=False,
        commit_message=None,
        analytics_measurement_id=None,
        principal_id="principal-1",
    )

    caplog.set_level("INFO", logger="app.services.seo_migration")
    with pytest.raises(SEOMigrationValidationError, match="Simulated deploy failure."):
        service.deploy_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact.id,
            dry_run=False,
            principal_id="principal-1",
        )

    payloads = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_control_plane_action"
    ]
    assert any(
        payload.get("action") == "deploy"
        and payload.get("status") == "failed"
        and payload.get("failure_category") == "deploy_error"
        and payload.get("failure_reason") == "Simulated deploy failure."
        for payload in payloads
    )
