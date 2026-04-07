from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.seo_migration_artifact_provider import (
    SEOMigrationArtifactGenerationOutput,
    SEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
)
from app.integrations.seo_migration_github_publisher import (
    MisconfiguredSEOMigrationGitHubPublisher,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
)
from app.models.seo_migration_artifact_version import SEOMigrationArtifactVersion
from app.models.seo_migration_workspace import SEOMigrationWorkspace
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
from app.services.seo_migration_context import SEOMigrationContextAssembler
from app.services.seo_migration_ingest import SEOMigrationSourceIngestError, SEOMigrationSourceIngestService
from app.services.seo_migration_prompt import SEO_MIGRATION_PROMPT_VERSION, build_seo_migration_prompt

logger = logging.getLogger(__name__)


_MAX_GENERATED_FILES = 12
_MAX_FILE_BYTES = 120_000
_MAX_TOTAL_BYTES = 350_000
_MAX_CONTENT_FOR_STORAGE = 120_000
_MAX_HISTORY_ITEMS = 80
_ALLOWED_FILE_EXTENSIONS = (
    ".html",
    ".css",
    ".js",
    ".json",
    ".txt",
    ".xml",
    ".ico",
    ".webmanifest",
)
_FORBIDDEN_PATH_PREFIXES = (
    ".git/",
    "app/",
    "backend/",
    "infra/",
    "alembic/",
    "scripts/",
    ".github/",
    "k8s/",
)
_FORBIDDEN_PATH_EXACT = {
    ".git",
    ".gitattributes",
    ".gitignore",
    ".env",
    "dockerfile",
    "docker-compose.yml",
    "requirements.txt",
    "package.json",
    "main.py",
    "server.js",
}
_VALID_RELATIVE_PATH_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,160}$")
_VALID_REPO_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
_VALID_REPO_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_VALID_BRANCH_OR_REF_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")
_VALID_REPO_ROOT_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{0,120}$")
_VALID_WORKFLOW_ID_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,160}$")
_VALID_GA_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]{4,32}$")
_ANALYTICS_SCRIPT_PATTERN = re.compile(
    r"<script[^>]*>(?:(?!</script>).)*(googletagmanager|google-analytics|gtag|analytics)[\s\S]*?</script>",
    re.IGNORECASE,
)
_GA_MEASUREMENT_PATTERN = re.compile(r"\bG-[A-Z0-9]{4,}\b")
_GA4_SCRIPT_TEMPLATE = (
    '<script async src="https://www.googletagmanager.com/gtag/js?id={measurement_id}"></script>\n'
    "<script>\n"
    "  window.dataLayer = window.dataLayer || [];\n"
    "  function gtag(){{dataLayer.push(arguments);}}\n"
    "  gtag('js', new Date());\n"
    "  gtag('config', '{measurement_id}');\n"
    "</script>"
)
_MIGRATION_FAILURE_CATEGORY_VALUES = {
    "config_missing",
    "target_invalid",
    "approval_required",
    "duplicate_request",
    "artifact_invalid",
    "provider_error",
    "deploy_error",
    "unknown_error",
}


class SEOMigrationNotFoundError(ValueError):
    pass


class SEOMigrationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEOMigrationPromptPreview:
    provider_name: str
    model_name: str
    prompt_version: str
    context_json: dict[str, object]
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class SEOMigrationWorkspaceSummary:
    workspace: SEOMigrationWorkspace
    context_summary: dict[str, object]
    latest_artifact: SEOMigrationArtifactVersion | None
    source_snapshot: dict[str, object]
    publish_readiness: dict[str, object]
    deploy_readiness: dict[str, object]
    publish_history: list[dict[str, object]]
    deploy_history: list[dict[str, object]]


@dataclass(frozen=True)
class SEOMigrationPublishActionResult:
    workspace: SEOMigrationWorkspace
    artifact: SEOMigrationArtifactVersion
    result: dict[str, object]
    readiness: dict[str, object]


@dataclass(frozen=True)
class SEOMigrationDeployActionResult:
    workspace: SEOMigrationWorkspace
    artifact: SEOMigrationArtifactVersion
    result: dict[str, object]
    readiness: dict[str, object]


class SEOMigrationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_site_repository: SEOSiteRepository,
        seo_migration_repository: SEOMigrationRepository,
        seo_audit_repository: SEOAuditRepository,
        seo_audit_summary_repository: SEOAuditSummaryRepository,
        seo_recommendation_repository: SEORecommendationRepository,
        seo_recommendation_narrative_repository: SEORecommendationNarrativeRepository,
        seo_competitor_repository: SEOCompetitorRepository,
        seo_competitor_summary_repository: SEOCompetitorSummaryRepository,
        ingest_service: SEOMigrationSourceIngestService,
        context_assembler: SEOMigrationContextAssembler,
        artifact_provider: SEOMigrationArtifactGenerationProvider,
        github_publisher: SEOMigrationGitHubPublisher | None = None,
        provider_name: str,
        provider_model_name: str,
        prompt_version: str = SEO_MIGRATION_PROMPT_VERSION,
        prompt_text_recommendations: str = "",
        publish_commit_message_prefix: str = "[MBSRN Migration]",
        deploy_default_workflow_id: str = "deploy-www-prod.yml",
        deploy_default_ref: str = "main",
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_site_repository = seo_site_repository
        self.seo_migration_repository = seo_migration_repository
        self.seo_audit_repository = seo_audit_repository
        self.seo_audit_summary_repository = seo_audit_summary_repository
        self.seo_recommendation_repository = seo_recommendation_repository
        self.seo_recommendation_narrative_repository = seo_recommendation_narrative_repository
        self.seo_competitor_repository = seo_competitor_repository
        self.seo_competitor_summary_repository = seo_competitor_summary_repository
        self.ingest_service = ingest_service
        self.context_assembler = context_assembler
        self.artifact_provider = artifact_provider
        if github_publisher is None:
            github_publisher = MisconfiguredSEOMigrationGitHubPublisher(
                safe_message="GitHub migration publisher is not configured.",
            )
        self.github_publisher = github_publisher
        self.github_publisher_configured = not isinstance(
            github_publisher,
            MisconfiguredSEOMigrationGitHubPublisher,
        )
        self.provider_name = provider_name
        self.provider_model_name = provider_model_name
        self.prompt_version = prompt_version
        self.prompt_text_recommendations = prompt_text_recommendations
        self.publish_commit_message_prefix = publish_commit_message_prefix.strip() or "[MBSRN Migration]"
        self.deploy_default_workflow_id = deploy_default_workflow_id.strip() or "deploy-www-prod.yml"
        self.deploy_default_ref = deploy_default_ref.strip() or "main"

    def create_or_update_workspace(
        self,
        *,
        business_id: str,
        site_id: str,
        source_url: str | None = None,
        operator_requirements: dict[str, object] | None = None,
        enriched_content_notes: dict[str, object] | None = None,
        publish_config: dict[str, object] | None = None,
        deploy_config: dict[str, object] | None = None,
        analytics_config: dict[str, object] | None = None,
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace = self.seo_migration_repository.get_workspace_for_business_site(business_id, site_id)
        if workspace is None:
            workspace = SEOMigrationWorkspace(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                source_url=source_url,
                source_site_status="not_ingested",
                migration_status="draft",
                operator_requirements_json=_normalize_json_dict(operator_requirements),
                enriched_content_notes_json=_normalize_json_dict(enriched_content_notes),
                brand_business_facts_snapshot_json=self._build_brand_business_snapshot(site),
                imported_source_snapshot_json={},
                publish_config_json=_normalize_publish_config(publish_config),
                deploy_config_json=_normalize_deploy_config(deploy_config),
                analytics_config_json=_normalize_analytics_config(analytics_config),
                publish_status="not_ready",
                deploy_status="not_ready",
                publish_history_json=[],
                deploy_history_json=[],
                created_by_principal_id=principal_id,
                updated_by_principal_id=principal_id,
            )
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            self.seo_migration_repository.create_workspace(workspace)
        else:
            if source_url is not None:
                workspace.source_url = source_url
            if operator_requirements is not None:
                workspace.operator_requirements_json = _normalize_json_dict(operator_requirements)
            if enriched_content_notes is not None:
                workspace.enriched_content_notes_json = _normalize_json_dict(enriched_content_notes)
            if publish_config is not None:
                workspace.publish_config_json = _normalize_publish_config(publish_config)
            if deploy_config is not None:
                workspace.deploy_config_json = _normalize_deploy_config(deploy_config)
            if analytics_config is not None:
                workspace.analytics_config_json = _normalize_analytics_config(analytics_config)
            workspace.brand_business_facts_snapshot_json = self._build_brand_business_snapshot(site)
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            workspace.updated_by_principal_id = principal_id
            self.seo_migration_repository.save_workspace(workspace)
        self._commit_with_constraint_handling()
        self.session.refresh(workspace)
        return workspace

    def get_workspace(self, *, business_id: str, site_id: str) -> SEOMigrationWorkspace:
        self._require_site(business_id=business_id, site_id=site_id)
        workspace = self.seo_migration_repository.get_workspace_for_business_site(business_id, site_id)
        if workspace is None:
            raise SEOMigrationNotFoundError("Migration workspace not found")
        return workspace

    def ingest_source_snapshot(
        self,
        *,
        business_id: str,
        site_id: str,
        source_url: str | None,
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        effective_source_url = (source_url or workspace.source_url or "").strip()
        if not effective_source_url:
            raise SEOMigrationValidationError("source_url is required before ingest")

        try:
            ingest_result = self.ingest_service.ingest_homepage(source_url=effective_source_url)
        except SEOMigrationSourceIngestError as exc:
            workspace.source_url = effective_source_url
            workspace.source_site_status = "ingest_failed"
            workspace.migration_status = "source_needs_review"
            workspace.updated_by_principal_id = principal_id
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            self.seo_migration_repository.save_workspace(workspace)
            self.session.commit()
            raise SEOMigrationValidationError(str(exc)) from exc

        workspace.source_url = ingest_result.source_url
        workspace.source_site_status = "ingested"
        workspace.migration_status = "source_ingested"
        workspace.imported_source_snapshot_json = ingest_result.snapshot
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        return workspace

    def update_operator_requirements(
        self,
        *,
        business_id: str,
        site_id: str,
        operator_requirements: dict[str, object],
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        workspace.operator_requirements_json = _normalize_json_dict(operator_requirements)
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        return workspace

    def update_enriched_content_notes(
        self,
        *,
        business_id: str,
        site_id: str,
        enriched_content_notes: dict[str, object],
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        workspace.enriched_content_notes_json = _normalize_json_dict(enriched_content_notes)
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        return workspace

    def update_publish_config(
        self,
        *,
        business_id: str,
        site_id: str,
        publish_config: dict[str, object],
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace.publish_config_json = _normalize_publish_config(publish_config)
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        return workspace

    def update_deploy_config(
        self,
        *,
        business_id: str,
        site_id: str,
        deploy_config: dict[str, object],
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace.deploy_config_json = _normalize_deploy_config(deploy_config)
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        return workspace

    def update_analytics_config(
        self,
        *,
        business_id: str,
        site_id: str,
        analytics_config: dict[str, object],
        principal_id: str | None,
    ) -> SEOMigrationWorkspace:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace.analytics_config_json = _normalize_analytics_config(analytics_config)
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        return workspace

    def approve_artifact_version(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
        approval_notes: str | None,
        principal_id: str | None,
    ) -> SEOMigrationArtifactVersion:
        started_at = time.monotonic()
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        artifact = self.get_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )
        self._log_control_plane_action(
            action="approve",
            status="requested",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
        )
        if artifact.file_count <= 0:
            failure_message = "Artifact version does not include generated static files."
            self._log_control_plane_action(
                action="approve",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                failure_category="artifact_invalid",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message)
        if artifact.approval_status == "approved":
            failure_message = "Artifact version is already approved."
            self._log_control_plane_action(
                action="approve",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                failure_category="duplicate_request",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message)

        artifact.approval_status = "approved"
        artifact.approved_at = utc_now()
        artifact.approved_by_principal_id = principal_id
        artifact.approval_notes = _normalize_string(approval_notes, max_length=1200)

        workspace.latest_approved_artifact_version_id = artifact.id
        workspace.latest_approved_artifact_version_number = artifact.version
        workspace.migration_status = "draft_approved"
        if workspace.last_published_artifact_version_id != artifact.id:
            workspace.publish_status = "not_ready"
            workspace.deploy_status = "not_ready"
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)

        self.seo_migration_repository.save_artifact_version(artifact)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(artifact)
        self._log_control_plane_action(
            action="approve",
            status="completed",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            duration_ms=self._duration_ms(started_at),
        )
        return artifact

    def publish_artifact_version(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
        dry_run: bool,
        commit_message: str | None,
        analytics_measurement_id: str | None,
        principal_id: str | None,
    ) -> SEOMigrationPublishActionResult:
        started_at = time.monotonic()
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        artifact = self.get_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )
        self._log_control_plane_action(
            action="publish",
            status="requested",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            dry_run=dry_run,
            target_summary=self._safe_publish_target_summary(workspace.publish_config_json),
        )
        readiness = self._build_publish_readiness(
            site=site,
            workspace=workspace,
            artifact=artifact,
        )
        if not readiness["ready"]:
            reason_text = "; ".join(str(item) for item in readiness.get("reasons", [])) or "Publish readiness failed."
            failure_category = self._categorize_readiness_failure(
                reasons=readiness.get("reasons"),
                action="publish",
            )
            self._log_control_plane_action(
                action="publish",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=readiness.get("target"),
                failure_category=failure_category,
                failure_reason=reason_text,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(reason_text)

        try:
            target = _resolve_publish_target(workspace.publish_config_json)
        except ValueError as exc:
            failure_message = str(exc) or "Publish target is invalid."
            self._log_control_plane_action(
                action="publish",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=self._safe_publish_target_summary(workspace.publish_config_json),
                failure_category="target_invalid",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message) from exc
        if not dry_run and _is_duplicate_publish_attempt(
            history=workspace.publish_history_json,
            artifact_version_id=artifact.id,
            target=target,
        ):
            failure_message = "This artifact version is already published to the configured GitHub target."
            self._log_control_plane_action(
                action="publish",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=target,
                failure_category="duplicate_request",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message)
        effective_ga_measurement_id = _resolve_effective_ga_measurement_id(
            site=site,
            workspace=workspace,
            override_measurement_id=analytics_measurement_id,
            phase="publish",
        )
        analytics_config = _normalize_analytics_config(workspace.analytics_config_json)
        analytics_insertion_mode = str(analytics_config.get("insertion_mode") or "publish_and_deploy")
        publish_files, analytics_injected_paths, publish_warnings = _prepare_publish_files(
            artifact=artifact,
            ga_measurement_id=effective_ga_measurement_id,
        )
        if not publish_files:
            failure_message = "No publishable files were available for this artifact version."
            self._log_control_plane_action(
                action="publish",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=target,
                failure_category="artifact_invalid",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message)

        normalized_commit_message = _normalize_string(commit_message, max_length=180)
        if not normalized_commit_message:
            normalized_commit_message = (
                f"{self.publish_commit_message_prefix} site={site.id} artifact=v{artifact.version}"
            )
        try:
            publish_result = self.github_publisher.publish_files(
                target=SEOMigrationGitHubPublishTarget(
                    repo_owner=target["repo_owner"],
                    repo_name=target["repo_name"],
                    branch=target["branch"],
                    artifact_root=target["artifact_root"],
                ),
                files=publish_files,
                commit_message=normalized_commit_message,
                dry_run=dry_run,
            )
        except SEOMigrationGitHubPublisherError as exc:
            failure_category = self._categorize_publisher_failure(exc=exc, action="publish")
            artifact.publish_status = "publish_failed"
            artifact.last_publish_error_summary = exc.safe_message
            workspace.publish_status = "publish_failed"
            workspace.updated_by_principal_id = principal_id
            now = utc_now()
            workspace.publish_history_json = _append_history_item(
                workspace.publish_history_json,
                {
                    "action": "publish",
                    "status": "failed",
                    "artifact_version_id": artifact.id,
                    "artifact_version": artifact.version,
                    "principal_id": principal_id,
                    "timestamp": now.isoformat(),
                    "dry_run": dry_run,
                    "repo_owner": target["repo_owner"],
                    "repo_name": target["repo_name"],
                    "branch": target["branch"],
                    "artifact_root": target["artifact_root"],
                    "analytics_measurement_id": effective_ga_measurement_id,
                    "analytics_insertion_mode": analytics_insertion_mode,
                    "failure_category": failure_category,
                    "error": exc.safe_message,
                    "error_summary": exc.safe_message,
                },
            )
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            self.seo_migration_repository.save_artifact_version(artifact)
            self.seo_migration_repository.save_workspace(workspace)
            self.session.commit()
            self._log_control_plane_action(
                action="publish",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=target,
                failure_category=failure_category,
                failure_reason=exc.safe_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(exc.safe_message) from exc

        now = utc_now()
        status_label = "dry_run" if dry_run else "published"
        if not dry_run:
            artifact.publish_status = "published"
            artifact.last_published_at = now
            artifact.last_publish_error_summary = None
            artifact.last_published_commit_sha = publish_result.commit_shas[-1] if publish_result.commit_shas else None
            workspace.last_published_artifact_version_id = artifact.id
            workspace.last_published_artifact_version_number = artifact.version
            workspace.last_published_commit_sha = artifact.last_published_commit_sha
            workspace.last_published_at = now
            workspace.last_published_by_principal_id = principal_id
            workspace.publish_status = "published"
            workspace.migration_status = "published_to_github"
        else:
            if artifact.publish_status not in {"published", "publish_failed"}:
                artifact.publish_status = "dry_run"
            if workspace.publish_status not in {"published", "publish_failed"}:
                workspace.publish_status = "ready"

        workspace.updated_by_principal_id = principal_id
        history_payload: dict[str, object] = {
            "action": "publish",
            "status": status_label,
            "artifact_version_id": artifact.id,
            "artifact_version": artifact.version,
            "principal_id": principal_id,
            "timestamp": now.isoformat(),
            "dry_run": dry_run,
            "repo_owner": publish_result.repo_owner,
            "repo_name": publish_result.repo_name,
            "branch": publish_result.branch,
            "artifact_root": publish_result.artifact_root,
            "files_published": publish_result.files_published,
            "total_bytes": publish_result.total_bytes,
            "commit_shas": list(publish_result.commit_shas),
            "latest_commit_sha": artifact.last_published_commit_sha,
            "published_at": publish_result.published_at,
            "analytics_measurement_id": effective_ga_measurement_id,
            "analytics_insertion_mode": analytics_insertion_mode,
            "analytics_applied": bool(analytics_injected_paths),
            "analytics_injected_paths": analytics_injected_paths,
            "warnings": publish_warnings,
        }
        workspace.publish_history_json = _append_history_item(
            workspace.publish_history_json,
            history_payload,
        )
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_artifact_version(artifact)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(artifact)
        self.session.refresh(workspace)
        self._log_control_plane_action(
            action="publish",
            status="completed",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            dry_run=dry_run,
            target_summary={
                "repo_owner": publish_result.repo_owner,
                "repo_name": publish_result.repo_name,
                "branch": publish_result.branch,
                "artifact_root": publish_result.artifact_root,
            },
            duration_ms=self._duration_ms(started_at),
        )
        return SEOMigrationPublishActionResult(
            workspace=workspace,
            artifact=artifact,
            readiness=readiness,
            result=history_payload,
        )

    def deploy_artifact_version(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
        dry_run: bool,
        principal_id: str | None,
    ) -> SEOMigrationDeployActionResult:
        started_at = time.monotonic()
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        artifact = self.get_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )
        self._log_control_plane_action(
            action="deploy",
            status="requested",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            dry_run=dry_run,
            target_summary=self._safe_deploy_target_summary(
                workspace=workspace,
            ),
        )
        readiness = self._build_deploy_readiness(
            site=site,
            workspace=workspace,
            artifact=artifact,
        )
        if not readiness["ready"]:
            reason_text = "; ".join(str(item) for item in readiness.get("reasons", [])) or "Deploy readiness failed."
            failure_category = self._categorize_readiness_failure(
                reasons=readiness.get("reasons"),
                action="deploy",
            )
            self._log_control_plane_action(
                action="deploy",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=readiness.get("target"),
                failure_category=failure_category,
                failure_reason=reason_text,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(reason_text)

        try:
            deploy_target = _resolve_deploy_target(
                deploy_config=workspace.deploy_config_json,
                publish_config=workspace.publish_config_json,
                default_workflow_id=self.deploy_default_workflow_id,
                default_ref=self.deploy_default_ref,
            )
        except ValueError as exc:
            failure_message = str(exc) or "Deploy target is invalid."
            self._log_control_plane_action(
                action="deploy",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary=self._safe_deploy_target_summary(workspace=workspace),
                failure_category="target_invalid",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message) from exc
        deploy_inputs = dict(deploy_target["inputs"])
        deploy_inputs.setdefault("site_id", site.id)
        deploy_inputs.setdefault("artifact_version", str(artifact.version))
        deploy_inputs.setdefault("artifact_version_id", artifact.id)
        if workspace.last_published_commit_sha:
            deploy_inputs.setdefault("published_commit_sha", workspace.last_published_commit_sha)
        analytics_config = _normalize_analytics_config(workspace.analytics_config_json)
        analytics_insertion_mode = str(analytics_config.get("insertion_mode") or "publish_and_deploy")
        effective_ga_measurement_id = _resolve_effective_ga_measurement_id(
            site=site,
            workspace=workspace,
            override_measurement_id=None,
            phase="deploy",
        )
        if effective_ga_measurement_id:
            deploy_inputs.setdefault("ga_measurement_id", effective_ga_measurement_id)
        if not dry_run and _is_duplicate_deploy_attempt(
            history=workspace.deploy_history_json,
            artifact_version_id=artifact.id,
            target={
                **deploy_target,
                "inputs": deploy_inputs,
            },
        ):
            failure_message = "A deploy request for this artifact and target is already recorded."
            self._log_control_plane_action(
                action="deploy",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary={
                    **deploy_target,
                    "inputs": _normalize_history_inputs(deploy_inputs),
                },
                failure_category="duplicate_request",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(failure_message)

        try:
            deploy_result = self.github_publisher.dispatch_deploy(
                target=SEOMigrationGitHubDeployTarget(
                    repo_owner=deploy_target["repo_owner"],
                    repo_name=deploy_target["repo_name"],
                    workflow_id=deploy_target["workflow_id"],
                    ref=deploy_target["ref"],
                    inputs=deploy_inputs,
                ),
                dry_run=dry_run,
            )
        except SEOMigrationGitHubPublisherError as exc:
            failure_category = self._categorize_publisher_failure(exc=exc, action="deploy")
            artifact.deploy_status = "deploy_failed"
            artifact.last_deploy_error_summary = exc.safe_message
            workspace.deploy_status = "deploy_failed"
            workspace.updated_by_principal_id = principal_id
            now = utc_now()
            workspace.deploy_history_json = _append_history_item(
                workspace.deploy_history_json,
                {
                    "action": "deploy",
                    "status": "failed",
                    "artifact_version_id": artifact.id,
                    "artifact_version": artifact.version,
                    "principal_id": principal_id,
                    "timestamp": now.isoformat(),
                    "dry_run": dry_run,
                    "repo_owner": deploy_target["repo_owner"],
                    "repo_name": deploy_target["repo_name"],
                    "workflow_id": deploy_target["workflow_id"],
                    "ref": deploy_target["ref"],
                    "inputs": deploy_inputs,
                    "analytics_measurement_id": effective_ga_measurement_id,
                    "analytics_insertion_mode": analytics_insertion_mode,
                    "failure_category": failure_category,
                    "error": exc.safe_message,
                    "error_summary": exc.safe_message,
                },
            )
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            self.seo_migration_repository.save_artifact_version(artifact)
            self.seo_migration_repository.save_workspace(workspace)
            self.session.commit()
            self._log_control_plane_action(
                action="deploy",
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                artifact_version_id=artifact.id,
                artifact_version=artifact.version,
                principal_id=principal_id,
                dry_run=dry_run,
                target_summary={
                    "repo_owner": deploy_target["repo_owner"],
                    "repo_name": deploy_target["repo_name"],
                    "workflow_id": deploy_target["workflow_id"],
                    "ref": deploy_target["ref"],
                },
                failure_category=failure_category,
                failure_reason=exc.safe_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(exc.safe_message) from exc

        now = utc_now()
        status_label = "dry_run" if dry_run else "deploy_requested"
        if not dry_run:
            artifact.deploy_status = "deploy_requested"
            artifact.last_deployed_at = now
            artifact.last_deploy_error_summary = None
            workspace.last_deployed_artifact_version_id = artifact.id
            workspace.last_deployed_artifact_version_number = artifact.version
            workspace.last_deployed_at = now
            workspace.last_deployed_by_principal_id = principal_id
            workspace.deploy_status = "deploy_requested"
            workspace.migration_status = "deploy_requested"
        else:
            if artifact.deploy_status not in {"deploy_requested", "deploy_failed"}:
                artifact.deploy_status = "dry_run"
            if workspace.deploy_status not in {"deploy_requested", "deploy_failed"}:
                workspace.deploy_status = "ready"

        workspace.updated_by_principal_id = principal_id
        history_payload: dict[str, object] = {
            "action": "deploy",
            "status": status_label,
            "artifact_version_id": artifact.id,
            "artifact_version": artifact.version,
            "principal_id": principal_id,
            "timestamp": now.isoformat(),
            "dry_run": dry_run,
            "repo_owner": deploy_result.repo_owner,
            "repo_name": deploy_result.repo_name,
            "workflow_id": deploy_result.workflow_id,
            "ref": deploy_result.ref,
            "inputs": deploy_result.inputs,
            "analytics_measurement_id": effective_ga_measurement_id,
            "analytics_insertion_mode": analytics_insertion_mode,
            "analytics_applied": bool(effective_ga_measurement_id),
            "dispatched_at": deploy_result.dispatched_at,
        }
        workspace.deploy_history_json = _append_history_item(
            workspace.deploy_history_json,
            history_payload,
        )
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_artifact_version(artifact)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(artifact)
        self.session.refresh(workspace)
        self._log_control_plane_action(
            action="deploy",
            status="completed",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            dry_run=dry_run,
            target_summary={
                "repo_owner": deploy_result.repo_owner,
                "repo_name": deploy_result.repo_name,
                "workflow_id": deploy_result.workflow_id,
                "ref": deploy_result.ref,
            },
            duration_ms=self._duration_ms(started_at),
        )
        return SEOMigrationDeployActionResult(
            workspace=workspace,
            artifact=artifact,
            readiness=readiness,
            result=history_payload,
        )

    def list_publish_history(self, *, business_id: str, site_id: str) -> list[dict[str, object]]:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        return _normalize_history_list(workspace.publish_history_json)

    def list_deploy_history(self, *, business_id: str, site_id: str) -> list[dict[str, object]]:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        return _normalize_history_list(workspace.deploy_history_json)

    def get_prompt_preview(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> SEOMigrationPromptPreview:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        context_json, _ = self._assemble_context(site=site, workspace=workspace)
        prompt = build_seo_migration_prompt(
            migration_context=context_json,
            prompt_version=self.prompt_version,
            prompt_text_recommendations=self.prompt_text_recommendations,
        )
        return SEOMigrationPromptPreview(
            provider_name=self.provider_name,
            model_name=self.provider_model_name,
            prompt_version=prompt.prompt_version,
            context_json=context_json,
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
        )

    def generate_draft_artifacts(
        self,
        *,
        business_id: str,
        site_id: str,
        principal_id: str | None,
    ) -> SEOMigrationArtifactVersion:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        context_json, _ = self._assemble_context(site=site, workspace=workspace)

        provider_output: SEOMigrationArtifactGenerationOutput | None = None
        parse_warnings: list[str] = []
        generation_status = "completed"
        generation_error_summary: str | None = None
        try:
            provider_output = self.artifact_provider.generate_artifacts(migration_context=context_json)
        except SEOMigrationArtifactProviderError as exc:
            salvaged_output = self._salvage_provider_error_output(exc)
            if salvaged_output is None:
                workspace.migration_status = "draft_generation_failed"
                workspace.updated_by_principal_id = principal_id
                self._update_workspace_readiness_statuses(workspace=workspace, site=site)
                self.seo_migration_repository.save_workspace(workspace)
                self.session.commit()
                raise SEOMigrationValidationError(exc.safe_message) from exc
            provider_output = salvaged_output
            generation_status = "partial"
            generation_error_summary = exc.safe_message
            parse_warnings.append("Provider response partially salvaged after schema failure.")

        normalized_files, file_warnings = self._validate_and_normalize_files(provider_output.generated_files)
        parse_warnings.extend(file_warnings)
        if not normalized_files:
            workspace.migration_status = "draft_generation_failed"
            workspace.updated_by_principal_id = principal_id
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            self.seo_migration_repository.save_workspace(workspace)
            self.session.commit()
            raise SEOMigrationValidationError("No valid static files were generated.")

        artifact_version_number = self.seo_migration_repository.next_artifact_version_number(workspace.id)
        total_bytes = sum(len(str(item["content"]).encode("utf-8")) for item in normalized_files)
        artifact = SEOMigrationArtifactVersion(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            version=artifact_version_number,
            status=generation_status,
            context_json=context_json,
            strategy_summary=provider_output.strategy_summary,
            page_map_json=_normalize_json_list(provider_output.page_map),
            homepage_structure_json=_normalize_json_list(provider_output.homepage_structure),
            service_page_suggestions_json=_normalize_json_list(provider_output.service_page_suggestions),
            cta_contact_structure_json=_normalize_json_dict(provider_output.cta_contact_structure),
            seo_meta_suggestions_json=_normalize_json_dict(provider_output.seo_meta_suggestions),
            redirect_suggestions_json=_normalize_json_list(provider_output.redirect_suggestions),
            analytics_placeholders_json=_normalize_json_list(provider_output.analytics_placeholders),
            generated_files_json=normalized_files,
            file_count=len(normalized_files),
            total_bytes=total_bytes,
            provider_name=provider_output.provider_name,
            model_name=provider_output.model_name,
            prompt_version=provider_output.prompt_version,
            parse_warnings_json=[*provider_output.parse_warnings, *parse_warnings] or None,
            error_summary=generation_error_summary,
            approval_status="pending",
            publish_status="not_published",
            deploy_status="not_deployed",
            created_by_principal_id=principal_id,
        )
        self.seo_migration_repository.create_artifact_version(artifact)

        workspace.latest_generated_artifact_version_id = artifact.id
        workspace.latest_generated_artifact_version_number = artifact.version
        workspace.migration_status = "draft_generated"
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def list_artifact_versions(self, *, business_id: str, site_id: str) -> list[SEOMigrationArtifactVersion]:
        self._require_site(business_id=business_id, site_id=site_id)
        return self.seo_migration_repository.list_artifact_versions_for_business_site(business_id, site_id)

    def get_artifact_version(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
    ) -> SEOMigrationArtifactVersion:
        self._require_site(business_id=business_id, site_id=site_id)
        artifact = self.seo_migration_repository.get_artifact_version_for_business_site(
            business_id,
            site_id,
            artifact_version_id,
        )
        if artifact is None:
            raise SEOMigrationNotFoundError("Migration artifact version not found")
        return artifact

    def preview_artifact_file(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
        path: str,
    ) -> tuple[str, str]:
        artifact = self.get_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )
        normalized_path = _normalize_generated_path(path)
        if normalized_path is None:
            raise SEOMigrationValidationError("Invalid file path")
        generated_files = artifact.generated_files_json if isinstance(artifact.generated_files_json, list) else []
        for item in generated_files:
            if not isinstance(item, dict):
                continue
            file_path = _normalize_generated_path(item.get("path"))
            if file_path != normalized_path:
                continue
            content = str(item.get("content") or "")
            media_type = str(item.get("media_type") or "text/plain")
            return media_type, content
        raise SEOMigrationNotFoundError("Migration artifact file not found")

    def get_workspace_summary(self, *, business_id: str, site_id: str) -> SEOMigrationWorkspaceSummary:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        context_json, context_summary = self._assemble_context(site=site, workspace=workspace)
        existing_context_summaries = context_json.get("existing_context_summaries")
        if isinstance(existing_context_summaries, dict):
            context_summary = {
                **context_summary,
                "existing_context_summaries": _normalize_json_dict(existing_context_summaries),
            }
        latest_artifact = None
        if workspace.latest_generated_artifact_version_id:
            latest_artifact = self.seo_migration_repository.get_artifact_version_for_business_site(
                business_id,
                site_id,
                workspace.latest_generated_artifact_version_id,
            )
        approved_artifact = None
        if workspace.latest_approved_artifact_version_id:
            approved_artifact = self.seo_migration_repository.get_artifact_version_for_business_site(
                business_id,
                site_id,
                workspace.latest_approved_artifact_version_id,
            )
        source_snapshot = _normalize_json_dict(workspace.imported_source_snapshot_json)
        publish_readiness = self._build_publish_readiness(
            site=site,
            workspace=workspace,
            artifact=approved_artifact,
        )
        deploy_readiness = self._build_deploy_readiness(
            site=site,
            workspace=workspace,
            artifact=approved_artifact,
        )
        publish_diagnostics = self._derive_action_diagnostics(
            history=workspace.publish_history_json,
            action="publish",
        )
        deploy_diagnostics = self._derive_action_diagnostics(
            history=workspace.deploy_history_json,
            action="deploy",
        )
        publish_readiness = {
            **publish_readiness,
            "last_status": publish_diagnostics.get("last_status"),
            "last_failure_category": publish_diagnostics.get("last_failure_category"),
            "last_failure_message": publish_diagnostics.get("last_failure_message"),
        }
        deploy_readiness = {
            **deploy_readiness,
            "last_status": deploy_diagnostics.get("last_status"),
            "last_failure_category": deploy_diagnostics.get("last_failure_category"),
            "last_failure_message": deploy_diagnostics.get("last_failure_message"),
        }
        context_summary = {
            **context_summary,
            "migration_diagnostics": {
                "last_publish_status": publish_diagnostics.get("last_status"),
                "last_publish_failure_category": publish_diagnostics.get("last_failure_category"),
                "last_publish_failure_message": publish_diagnostics.get("last_failure_message"),
                "last_deploy_status": deploy_diagnostics.get("last_status"),
                "last_deploy_failure_category": deploy_diagnostics.get("last_failure_category"),
                "last_deploy_failure_message": deploy_diagnostics.get("last_failure_message"),
            },
        }
        return SEOMigrationWorkspaceSummary(
            workspace=workspace,
            context_summary=context_summary,
            latest_artifact=latest_artifact,
            source_snapshot=source_snapshot,
            publish_readiness=publish_readiness,
            deploy_readiness=deploy_readiness,
            publish_history=_normalize_history_list(workspace.publish_history_json),
            deploy_history=_normalize_history_list(workspace.deploy_history_json),
        )

    def _require_business(self, business_id: str) -> None:
        if self.business_repository.get(business_id) is None:
            raise SEOMigrationNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> SEOSite:
        self._require_business(business_id)
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEOMigrationNotFoundError("SEO site not found")
        return site

    def _assemble_context(
        self,
        *,
        site: SEOSite,
        workspace: SEOMigrationWorkspace,
    ) -> tuple[dict[str, object], dict[str, object]]:
        latest_audit_summary = None
        latest_audit_run = self.seo_audit_repository.get_latest_completed_run_for_business_site(
            site.business_id,
            site.id,
        )
        if latest_audit_run is not None:
            summaries = self.seo_audit_summary_repository.list_for_business_run(site.business_id, latest_audit_run.id)
            latest_audit_summary = summaries[-1] if summaries else None

        latest_recommendation_narrative = None
        recommendation_runs = self.seo_recommendation_repository.list_runs_for_business_site(site.business_id, site.id)
        latest_completed_recommendation_run = next(
            (item for item in recommendation_runs if item.status == "completed"),
            None,
        )
        if latest_completed_recommendation_run is not None:
            latest_recommendation_narrative = self.seo_recommendation_narrative_repository.get_latest_for_business_run(
                site.business_id,
                latest_completed_recommendation_run.id,
            )

        latest_competitor_summary = None
        comparison_runs = self.seo_competitor_repository.list_comparison_runs_for_business_site(
            site.business_id, site.id
        )
        latest_completed_comparison_run = next((item for item in comparison_runs if item.status == "completed"), None)
        if latest_completed_comparison_run is not None:
            latest_competitor_summary = self.seo_competitor_summary_repository.get_latest_for_business_run(
                site.business_id,
                latest_completed_comparison_run.id,
            )

        assembly = self.context_assembler.assemble(
            site=site,
            workspace=workspace,
            latest_audit_summary=latest_audit_summary,
            latest_recommendation_narrative=latest_recommendation_narrative,
            latest_competitor_summary=latest_competitor_summary,
        )
        return assembly.context_json, assembly.context_summary

    def _build_brand_business_snapshot(self, site: SEOSite) -> dict[str, object]:
        host = (urlsplit(site.base_url).hostname or "").strip().lower()
        return {
            "site_id": site.id,
            "display_name": site.display_name,
            "base_url": site.base_url,
            "normalized_domain": site.normalized_domain,
            "base_url_host": host,
            "industry": site.industry,
            "primary_location": site.primary_location,
            "service_areas": site.service_areas_json or [],
            "captured_at": utc_now().isoformat(),
        }

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return max(0, int((time.monotonic() - started_at) * 1000))

    @staticmethod
    def _emit_structured_service_log(
        *,
        payload: dict[str, object],
        fallback_message: str,
        level: int,
    ) -> None:
        try:
            message = json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            message = fallback_message
        logger.log(level, message, extra={"json_fields": payload})

    def _log_control_plane_action(
        self,
        *,
        action: str,
        status: str,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        artifact_version_id: str | None,
        artifact_version: int | None = None,
        principal_id: str | None,
        target_summary: object | None = None,
        dry_run: bool | None = None,
        duration_ms: int | None = None,
        failure_category: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        safe_failure_category = failure_category if failure_category in _MIGRATION_FAILURE_CATEGORY_VALUES else None
        safe_failure_reason = _normalize_string(failure_reason, max_length=300)
        payload: dict[str, object] = {
            "event": "seo_migration_control_plane_action",
            "timestamp": utc_now().isoformat(),
            "action": _normalize_string(action, max_length=32) or "unknown",
            "status": _normalize_string(status, max_length=32) or "unknown",
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "artifact_version_id": artifact_version_id,
            "artifact_version": artifact_version,
            "principal_id": principal_id,
            "target": _normalize_json_dict(target_summary),
            "failure_category": safe_failure_category,
        }
        if dry_run is not None:
            payload["dry_run"] = bool(dry_run)
        if duration_ms is not None:
            payload["duration_ms"] = max(0, int(duration_ms))
        if safe_failure_reason:
            payload["failure_reason"] = safe_failure_reason
        level = logging.INFO if payload["status"] != "failed" else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message="seo_migration_control_plane_action",
            level=level,
        )

    @staticmethod
    def _safe_publish_target_summary(config: object) -> dict[str, object]:
        normalized = _normalize_publish_config(config)
        return {
            "enabled": bool(normalized.get("enabled")),
            "repo_owner": str(normalized.get("repo_owner") or "").strip(),
            "repo_name": str(normalized.get("repo_name") or "").strip(),
            "branch": str(normalized.get("branch") or "").strip(),
            "artifact_root": str(normalized.get("artifact_root") or "").strip(),
        }

    def _safe_deploy_target_summary(self, *, workspace: SEOMigrationWorkspace) -> dict[str, object]:
        normalized = _normalize_deploy_config(workspace.deploy_config_json)
        fallback_publish = self._safe_publish_target_summary(workspace.publish_config_json)
        return {
            "enabled": bool(normalized.get("enabled")),
            "repo_owner": str(normalized.get("repo_owner") or fallback_publish.get("repo_owner") or "").strip(),
            "repo_name": str(normalized.get("repo_name") or fallback_publish.get("repo_name") or "").strip(),
            "workflow_id": str(normalized.get("workflow_id") or self.deploy_default_workflow_id).strip(),
            "ref": str(normalized.get("ref") or self.deploy_default_ref).strip(),
        }

    @staticmethod
    def _categorize_readiness_failure(*, reasons: object, action: str) -> str:
        normalized_reasons = [str(item or "").strip().lower() for item in reasons or [] if str(item or "").strip()]
        if not normalized_reasons:
            return "unknown_error"
        if any("not configured" in reason or "configuration" in reason for reason in normalized_reasons):
            return "config_missing"
        if any("invalid" in reason or "requires" in reason for reason in normalized_reasons):
            return "target_invalid"
        if any(
            "already" in reason and ("published" in reason or "recorded" in reason) for reason in normalized_reasons
        ):
            return "duplicate_request"
        if any(
            "not approved" in reason
            or "must be published before deploy" in reason
            or "published yet" in reason
            or "latest published version" in reason
            for reason in normalized_reasons
        ):
            return "approval_required"
        if any("no generated files" in reason or "no approved artifact" in reason for reason in normalized_reasons):
            return "artifact_invalid"
        if action == "deploy":
            return "deploy_error"
        return "provider_error"

    @staticmethod
    def _categorize_publisher_failure(*, exc: SEOMigrationGitHubPublisherError, action: str) -> str:
        code = str(exc.code or "").strip().lower()
        if code in {"publisher_not_configured"}:
            return "config_missing"
        if code in {"github_target_not_found"}:
            return "target_invalid"
        if action == "deploy":
            return "deploy_error"
        return "provider_error"

    @staticmethod
    def _derive_action_diagnostics(*, history: object, action: str) -> dict[str, object]:
        normalized_history = _normalize_history_list(history)
        target_action = (action or "").strip().lower()
        last_status: str | None = None
        last_failure_category: str | None = None
        last_failure_message: str | None = None
        for item in reversed(normalized_history):
            if str(item.get("action") or "").strip().lower() != target_action:
                continue
            if last_status is None:
                status_value = _normalize_string(item.get("status"), max_length=40)
                if status_value:
                    last_status = status_value
            status_lower = str(item.get("status") or "").strip().lower()
            if status_lower == "failed":
                category_value = _normalize_string(item.get("failure_category"), max_length=40)
                if category_value in _MIGRATION_FAILURE_CATEGORY_VALUES:
                    last_failure_category = category_value
                else:
                    last_failure_category = "unknown_error"
                last_failure_message = _normalize_string(
                    item.get("error_summary"), max_length=300
                ) or _normalize_string(item.get("error"), max_length=300)
                break
        return {
            "last_status": last_status,
            "last_failure_category": last_failure_category,
            "last_failure_message": last_failure_message,
        }

    def _update_workspace_readiness_statuses(
        self,
        *,
        workspace: SEOMigrationWorkspace,
        site: SEOSite,
    ) -> None:
        approved_artifact = None
        if workspace.latest_approved_artifact_version_id:
            approved_artifact = self.seo_migration_repository.get_artifact_version_for_business_site(
                workspace.business_id,
                workspace.site_id,
                workspace.latest_approved_artifact_version_id,
            )
        publish_readiness = self._build_publish_readiness(
            site=site,
            workspace=workspace,
            artifact=approved_artifact,
        )
        deploy_readiness = self._build_deploy_readiness(
            site=site,
            workspace=workspace,
            artifact=approved_artifact,
        )
        if workspace.publish_status not in {"published", "publish_failed"}:
            workspace.publish_status = "ready" if publish_readiness["ready"] else "not_ready"
        if workspace.deploy_status not in {"deploy_requested", "deploy_failed"}:
            workspace.deploy_status = "ready" if deploy_readiness["ready"] else "not_ready"

    def _build_publish_readiness(
        self,
        *,
        site: SEOSite,
        workspace: SEOMigrationWorkspace,
        artifact: SEOMigrationArtifactVersion | None,
    ) -> dict[str, object]:
        reasons: list[str] = []
        target_summary: dict[str, object] = {}
        target_valid = False
        try:
            target = _resolve_publish_target(workspace.publish_config_json)
            target_valid = True
            target_summary = {
                "enabled": target["enabled"],
                "repo_owner": target["repo_owner"],
                "repo_name": target["repo_name"],
                "branch": target["branch"],
                "artifact_root": target["artifact_root"],
            }
            if not target["enabled"]:
                reasons.append("Publish target is not enabled.")
        except ValueError as exc:
            reasons.append(str(exc))
        if artifact is None:
            reasons.append("No approved artifact version selected.")
        else:
            if artifact.approval_status != "approved":
                reasons.append("Selected artifact version is not approved.")
            if artifact.file_count <= 0:
                reasons.append("Selected artifact version has no generated files.")
        if not self.github_publisher_configured:
            reasons.append("GitHub migration publisher is not configured.")
        failure_category: str | None = None
        if reasons:
            failure_category = self._categorize_readiness_failure(reasons=reasons, action="publish")
        return {
            "ready": not reasons,
            "reasons": reasons,
            "failure_category": failure_category,
            "target": target_summary,
            "config_prerequisites": {
                "github_publisher_configured": self.github_publisher_configured,
                "target_config_valid": target_valid,
                "target_enabled": bool(target_summary.get("enabled")),
            },
            "site_ga_measurement_id": _normalize_ga_measurement_id(site.ga4_measurement_id),
            "workspace_ga_measurement_id": _normalize_ga_measurement_id(
                _normalize_json_dict(workspace.analytics_config_json).get("ga_measurement_id")
            ),
            "approved_artifact_version_id": artifact.id if artifact else None,
            "approved_artifact_version_number": artifact.version if artifact else None,
        }

    def _build_deploy_readiness(
        self,
        *,
        site: SEOSite,
        workspace: SEOMigrationWorkspace,
        artifact: SEOMigrationArtifactVersion | None,
    ) -> dict[str, object]:
        reasons: list[str] = []
        target_summary: dict[str, object] = {}
        target_valid = False
        try:
            target = _resolve_deploy_target(
                deploy_config=workspace.deploy_config_json,
                publish_config=workspace.publish_config_json,
                default_workflow_id=self.deploy_default_workflow_id,
                default_ref=self.deploy_default_ref,
            )
            target_valid = True
            target_summary = {
                "enabled": target["enabled"],
                "repo_owner": target["repo_owner"],
                "repo_name": target["repo_name"],
                "workflow_id": target["workflow_id"],
                "ref": target["ref"],
                "inputs": target["inputs"],
            }
            if not target["enabled"]:
                reasons.append("Deploy target is not enabled.")
        except ValueError as exc:
            reasons.append(str(exc))
        if artifact is None:
            reasons.append("No approved artifact version selected.")
        else:
            if artifact.approval_status != "approved":
                reasons.append("Selected artifact version is not approved.")
            if artifact.publish_status != "published":
                reasons.append("Selected artifact version must be published before deploy.")
        if not self.github_publisher_configured:
            reasons.append("GitHub migration publisher is not configured.")
        if not workspace.last_published_artifact_version_id:
            reasons.append("No artifact version has been published yet.")
        elif artifact is not None and workspace.last_published_artifact_version_id != artifact.id:
            reasons.append("Selected artifact is not the latest published version.")
        failure_category: str | None = None
        if reasons:
            failure_category = self._categorize_readiness_failure(reasons=reasons, action="deploy")
        return {
            "ready": not reasons,
            "reasons": reasons,
            "failure_category": failure_category,
            "target": target_summary,
            "config_prerequisites": {
                "github_publisher_configured": self.github_publisher_configured,
                "target_config_valid": target_valid,
                "target_enabled": bool(target_summary.get("enabled")),
            },
            "site_ga_measurement_id": _normalize_ga_measurement_id(site.ga4_measurement_id),
            "workspace_ga_measurement_id": _normalize_ga_measurement_id(
                _normalize_json_dict(workspace.analytics_config_json).get("ga_measurement_id")
            ),
            "approved_artifact_version_id": artifact.id if artifact else None,
            "approved_artifact_version_number": artifact.version if artifact else None,
            "last_published_artifact_version_id": workspace.last_published_artifact_version_id,
            "last_published_artifact_version_number": workspace.last_published_artifact_version_number,
        }

    def _validate_and_normalize_files(
        self,
        files: list,
    ) -> tuple[list[dict[str, object]], list[str]]:
        warnings: list[str] = []
        if len(files) > _MAX_GENERATED_FILES:
            warnings.append("Generated file list exceeded max count and was truncated.")
        normalized: list[dict[str, object]] = []
        seen_paths: set[str] = set()
        total_bytes = 0
        for raw_file in files[:_MAX_GENERATED_FILES]:
            path = _normalize_generated_path(getattr(raw_file, "path", None))
            if path is None:
                warnings.append("Dropped generated file with invalid path.")
                continue
            if path in seen_paths:
                warnings.append(f"Dropped duplicate generated path '{path}'.")
                continue
            if _is_forbidden_path(path):
                warnings.append(f"Dropped forbidden generated path '{path}'.")
                continue
            if not path.endswith(_ALLOWED_FILE_EXTENSIONS):
                warnings.append(f"Dropped generated path outside static package boundary '{path}'.")
                continue
            content = _normalize_generated_content(getattr(raw_file, "content", None))
            if content is None:
                warnings.append(f"Dropped generated path '{path}' due to empty content.")
                continue
            if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
                warnings.append(f"Dropped generated path '{path}' due to file size limit.")
                continue
            media_type = _normalize_media_type(path=path, value=getattr(raw_file, "media_type", None))
            normalized_content = _normalize_analytics_placeholders(path=path, content=content)
            content_bytes = len(normalized_content.encode("utf-8"))
            if total_bytes + content_bytes > _MAX_TOTAL_BYTES:
                warnings.append("Generated file payload exceeded aggregate size limit and was truncated.")
                break
            total_bytes += content_bytes
            seen_paths.add(path)
            normalized.append(
                {
                    "path": path,
                    "media_type": media_type,
                    "content": normalized_content[:_MAX_CONTENT_FOR_STORAGE],
                    "size_bytes": content_bytes,
                }
            )
        return normalized, warnings

    def _salvage_provider_error_output(
        self,
        provider_error: SEOMigrationArtifactProviderError,
    ) -> SEOMigrationArtifactGenerationOutput | None:
        raw_output = (provider_error.raw_output or "").strip()
        if not raw_output:
            return None
        payload = _try_parse_json_payload(raw_output)
        if payload is None:
            return None
        strategy_summary = (
            _normalize_string(payload.get("strategy_summary"), max_length=8000) or "Draft strategy summary."
        )
        page_map = _coerce_object_list(payload.get("page_map"), max_items=24)
        homepage_structure = _coerce_object_list(payload.get("homepage_structure"), max_items=24)
        service_page_suggestions = _coerce_object_list(payload.get("service_page_suggestions"), max_items=24)
        cta_contact_structure = _normalize_json_dict(payload.get("cta_contact_structure"))
        seo_meta_suggestions = _normalize_json_dict(payload.get("seo_meta_suggestions"))
        redirect_suggestions = _coerce_object_list(payload.get("redirect_suggestions"), max_items=24)
        analytics_placeholders = _coerce_object_list(payload.get("analytics_placeholders"), max_items=24)
        generated_files_raw = payload.get("generated_files")
        if not isinstance(generated_files_raw, list):
            return None

        files = []
        for item in generated_files_raw:
            if not isinstance(item, dict):
                continue
            path = _normalize_generated_path(item.get("path"))
            content = _normalize_generated_content(item.get("content"))
            media_type = _normalize_media_type(path=path or "", value=item.get("media_type"))
            if path is None or content is None:
                continue
            files.append(
                type(
                    "_GeneratedFile",
                    (),
                    {"path": path, "content": content, "media_type": media_type},
                )
            )
            if len(files) >= _MAX_GENERATED_FILES:
                break
        if not files:
            return None
        return SEOMigrationArtifactGenerationOutput(
            strategy_summary=strategy_summary,
            page_map=page_map,
            homepage_structure=homepage_structure,
            service_page_suggestions=service_page_suggestions,
            cta_contact_structure=cta_contact_structure,
            seo_meta_suggestions=seo_meta_suggestions,
            redirect_suggestions=redirect_suggestions,
            analytics_placeholders=analytics_placeholders,
            generated_files=files,  # type: ignore[arg-type]
            provider_name=provider_error.provider_name,
            model_name=provider_error.model_name,
            prompt_version=provider_error.prompt_version,
            raw_response=raw_output,
            parse_warnings=("Recovered partial provider output.",),
        )

    def _commit_with_constraint_handling(self) -> None:
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            error_text = str(exc).lower()
            if "uq_seo_migration_workspaces_business_site" in error_text:
                raise SEOMigrationValidationError("Migration workspace already exists for this site.") from exc
            if "uq_seo_migration_artifact_versions_workspace_version" in error_text:
                raise SEOMigrationValidationError("Migration artifact version already exists.") from exc
            raise SEOMigrationValidationError("Migration data violated a database constraint.") from exc


def _normalize_json_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            cleaned_key = str(key).strip()
            if not cleaned_key:
                continue
            normalized[cleaned_key] = item
        return normalized
    return {}


def _normalize_json_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(_normalize_json_dict(item))
        if len(normalized) >= 40:
            break
    return normalized


def _normalize_publish_config(value: object) -> dict[str, object]:
    source = _normalize_json_dict(value)
    target_repo = _normalize_string(source.get("target_repo"), max_length=240)
    repo_owner = _normalize_string(source.get("repo_owner"), max_length=80)
    repo_name = _normalize_string(source.get("repo_name"), max_length=120)
    if target_repo and (not repo_owner or not repo_name):
        parts = [item.strip() for item in target_repo.split("/", 1)]
        if len(parts) == 2:
            repo_owner = repo_owner or parts[0]
            repo_name = repo_name or parts[1]
    branch = _normalize_string(source.get("branch"), max_length=120) or "main"
    artifact_root = _normalize_string(source.get("artifact_root"), max_length=120)
    if artifact_root is None:
        artifact_root = _normalize_string(source.get("base_path"), max_length=120)
    enabled = _coerce_bool(source.get("enabled"), default=False)
    return {
        "enabled": enabled,
        "repo_owner": repo_owner or "",
        "repo_name": repo_name or "",
        "branch": branch,
        "artifact_root": artifact_root or "",
    }


def _normalize_deploy_config(value: object) -> dict[str, object]:
    source = _normalize_json_dict(value)
    repo_owner = _normalize_string(source.get("repo_owner"), max_length=80)
    repo_name = _normalize_string(source.get("repo_name"), max_length=120)
    workflow_id = _normalize_string(source.get("workflow_id"), max_length=160)
    if workflow_id is None:
        workflow_id = _normalize_string(source.get("workflow_file"), max_length=160)
    ref = _normalize_string(source.get("ref"), max_length=120)
    raw_inputs = source.get("inputs")
    inputs: dict[str, str] = {}
    if isinstance(raw_inputs, dict):
        for raw_key, raw_value in raw_inputs.items():
            key = _normalize_string(raw_key, max_length=80)
            value = _normalize_string(raw_value, max_length=240)
            if key is None or value is None:
                continue
            inputs[key] = value
            if len(inputs) >= 20:
                break
    enabled = _coerce_bool(source.get("enabled"), default=False)
    return {
        "enabled": enabled,
        "repo_owner": repo_owner or "",
        "repo_name": repo_name or "",
        "workflow_id": workflow_id or "",
        "ref": ref or "",
        "inputs": inputs,
    }


def _normalize_analytics_config(value: object) -> dict[str, object]:
    source = _normalize_json_dict(value)
    enabled = _coerce_bool(source.get("enabled"), default=True)
    ga_measurement_id = _normalize_ga_measurement_id(source.get("ga_measurement_id"))
    insertion_mode = _normalize_string(source.get("insertion_mode"), max_length=40) or "publish_and_deploy"
    if insertion_mode not in {"publish_only", "publish_and_deploy"}:
        insertion_mode = "publish_and_deploy"
    return {
        "enabled": enabled,
        "ga_measurement_id": ga_measurement_id,
        "insertion_mode": insertion_mode,
    }


def _resolve_publish_target(config: object) -> dict[str, object]:
    normalized = _normalize_publish_config(config)
    repo_owner = str(normalized.get("repo_owner") or "").strip()
    repo_name = str(normalized.get("repo_name") or "").strip()
    branch = str(normalized.get("branch") or "").strip()
    artifact_root = str(normalized.get("artifact_root") or "").strip()
    enabled = bool(normalized.get("enabled"))

    if repo_owner and not _VALID_REPO_OWNER_PATTERN.fullmatch(repo_owner):
        raise ValueError("Publish repo_owner is invalid.")
    if repo_name and not _VALID_REPO_NAME_PATTERN.fullmatch(repo_name):
        raise ValueError("Publish repo_name is invalid.")
    if branch and (not _VALID_BRANCH_OR_REF_PATTERN.fullmatch(branch) or ".." in branch):
        raise ValueError("Publish branch is invalid.")
    if artifact_root and (
        not _VALID_REPO_ROOT_PATTERN.fullmatch(artifact_root) or artifact_root.startswith("/") or ".." in artifact_root
    ):
        raise ValueError("Publish artifact_root is invalid.")
    if artifact_root and _has_reserved_git_segment(artifact_root):
        raise ValueError("Publish artifact_root is invalid.")
    if enabled and (not repo_owner or not repo_name):
        raise ValueError("Publish target requires repo_owner and repo_name when enabled.")
    if enabled and not branch:
        raise ValueError("Publish target requires branch when enabled.")
    return {
        "enabled": enabled,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "branch": branch or "main",
        "artifact_root": artifact_root.strip("/"),
    }


def _resolve_deploy_target(
    *,
    deploy_config: object,
    publish_config: object,
    default_workflow_id: str,
    default_ref: str,
) -> dict[str, object]:
    normalized = _normalize_deploy_config(deploy_config)
    publish_target = _resolve_publish_target(publish_config)
    enabled = bool(normalized.get("enabled"))
    repo_owner = str(normalized.get("repo_owner") or publish_target.get("repo_owner") or "").strip()
    repo_name = str(normalized.get("repo_name") or publish_target.get("repo_name") or "").strip()
    workflow_id = str(normalized.get("workflow_id") or default_workflow_id or "").strip()
    ref = str(normalized.get("ref") or default_ref or "").strip()
    inputs = normalized.get("inputs")
    normalized_inputs: dict[str, str] = {}
    if isinstance(inputs, dict):
        for raw_key, raw_value in inputs.items():
            key = _normalize_string(raw_key, max_length=80)
            value = _normalize_string(raw_value, max_length=240)
            if key is None or value is None:
                continue
            normalized_inputs[key] = value
            if len(normalized_inputs) >= 20:
                break

    if repo_owner and not _VALID_REPO_OWNER_PATTERN.fullmatch(repo_owner):
        raise ValueError("Deploy repo_owner is invalid.")
    if repo_name and not _VALID_REPO_NAME_PATTERN.fullmatch(repo_name):
        raise ValueError("Deploy repo_name is invalid.")
    if workflow_id and (not _VALID_WORKFLOW_ID_PATTERN.fullmatch(workflow_id) or ".." in workflow_id):
        raise ValueError("Deploy workflow_id is invalid.")
    if workflow_id and _has_reserved_git_segment(workflow_id):
        raise ValueError("Deploy workflow_id is invalid.")
    if ref and (not _VALID_BRANCH_OR_REF_PATTERN.fullmatch(ref) or ".." in ref):
        raise ValueError("Deploy ref is invalid.")
    if enabled and (not repo_owner or not repo_name):
        raise ValueError("Deploy target requires repo_owner and repo_name when enabled.")
    if enabled and not workflow_id:
        raise ValueError("Deploy target requires workflow_id when enabled.")
    if enabled and not ref:
        raise ValueError("Deploy target requires ref when enabled.")
    return {
        "enabled": enabled,
        "repo_owner": repo_owner,
        "repo_name": repo_name,
        "workflow_id": workflow_id or default_workflow_id,
        "ref": ref or default_ref,
        "inputs": normalized_inputs,
    }


def _normalize_history_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(_normalize_json_dict(item))
        if len(normalized) >= _MAX_HISTORY_ITEMS:
            break
    return normalized


def _append_history_item(current: object, item: dict[str, object]) -> list[dict[str, object]]:
    normalized = _normalize_history_list(current)
    normalized.append(_normalize_json_dict(item))
    if len(normalized) > _MAX_HISTORY_ITEMS:
        return normalized[-_MAX_HISTORY_ITEMS:]
    return normalized


def _is_duplicate_publish_attempt(
    *,
    history: object,
    artifact_version_id: str,
    target: dict[str, object],
) -> bool:
    normalized = _normalize_history_list(history)
    for item in reversed(normalized):
        if str(item.get("action") or "").strip().lower() != "publish":
            continue
        status = str(item.get("status") or "").strip().lower()
        if status != "published":
            continue
        if str(item.get("artifact_version_id") or "").strip() != artifact_version_id:
            continue
        if _coerce_bool(item.get("dry_run"), default=False):
            continue
        if str(item.get("repo_owner") or "").strip() != str(target.get("repo_owner") or "").strip():
            continue
        if str(item.get("repo_name") or "").strip() != str(target.get("repo_name") or "").strip():
            continue
        if str(item.get("branch") or "").strip() != str(target.get("branch") or "").strip():
            continue
        if str(item.get("artifact_root") or "").strip() != str(target.get("artifact_root") or "").strip():
            continue
        return True
    return False


def _is_duplicate_deploy_attempt(
    *,
    history: object,
    artifact_version_id: str,
    target: dict[str, object],
) -> bool:
    normalized = _normalize_history_list(history)
    expected_inputs = _normalize_history_inputs(target.get("inputs"))
    for item in reversed(normalized):
        if str(item.get("action") or "").strip().lower() != "deploy":
            continue
        status = str(item.get("status") or "").strip().lower()
        if status != "deploy_requested":
            continue
        if str(item.get("artifact_version_id") or "").strip() != artifact_version_id:
            continue
        if _coerce_bool(item.get("dry_run"), default=False):
            continue
        if str(item.get("repo_owner") or "").strip() != str(target.get("repo_owner") or "").strip():
            continue
        if str(item.get("repo_name") or "").strip() != str(target.get("repo_name") or "").strip():
            continue
        if str(item.get("workflow_id") or "").strip() != str(target.get("workflow_id") or "").strip():
            continue
        if str(item.get("ref") or "").strip() != str(target.get("ref") or "").strip():
            continue
        if _normalize_history_inputs(item.get("inputs")) != expected_inputs:
            continue
        return True
    return False


def _normalize_history_inputs(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = _normalize_string(raw_key, max_length=80)
        item_value = _normalize_string(raw_value, max_length=240)
        if key is None or item_value is None:
            continue
        normalized[key] = item_value
    return normalized


def _resolve_effective_ga_measurement_id(
    *,
    site: SEOSite,
    workspace: SEOMigrationWorkspace,
    override_measurement_id: str | None,
    phase: str,
) -> str | None:
    override_normalized = _normalize_ga_measurement_id(override_measurement_id)
    if override_normalized:
        return override_normalized

    analytics_config = _normalize_analytics_config(workspace.analytics_config_json)
    if not bool(analytics_config.get("enabled", True)):
        return None
    insertion_mode = str(analytics_config.get("insertion_mode") or "publish_and_deploy").strip().lower()
    if phase == "deploy" and insertion_mode != "publish_and_deploy":
        return None
    workspace_measurement = _normalize_ga_measurement_id(analytics_config.get("ga_measurement_id"))
    if workspace_measurement:
        return workspace_measurement
    return _normalize_ga_measurement_id(site.ga4_measurement_id)


def _normalize_ga_measurement_id(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=40)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if not _VALID_GA_MEASUREMENT_ID_PATTERN.fullmatch(normalized):
        return None
    return normalized


def _prepare_publish_files(
    *,
    artifact: SEOMigrationArtifactVersion,
    ga_measurement_id: str | None,
) -> tuple[list[SEOMigrationGitHubPublishFile], list[str], list[str]]:
    generated_files = artifact.generated_files_json if isinstance(artifact.generated_files_json, list) else []
    publish_files: list[SEOMigrationGitHubPublishFile] = []
    analytics_injected_paths: list[str] = []
    warnings: list[str] = []
    seen_paths: set[str] = set()
    for item in generated_files:
        if not isinstance(item, dict):
            continue
        path = _normalize_generated_path(item.get("path"))
        if path is None:
            warnings.append("Dropped publish file with invalid path.")
            continue
        if path in seen_paths:
            warnings.append(f"Dropped duplicate publish path '{path}'.")
            continue
        if _is_forbidden_path(path):
            warnings.append(f"Dropped publish file outside static package boundary '{path}'.")
            continue
        if not path.endswith(_ALLOWED_FILE_EXTENSIONS):
            warnings.append(f"Dropped publish file outside static package boundary '{path}'.")
            continue
        content = _normalize_generated_content(item.get("content"))
        if content is None:
            warnings.append(f"Dropped publish file '{path}' due to empty content.")
            continue
        if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
            warnings.append(f"Dropped publish file '{path}' due to file size limit.")
            continue
        media_type = _normalize_media_type(path=path, value=item.get("media_type"))
        normalized = _normalize_analytics_placeholders(path=path, content=content)
        if ga_measurement_id:
            enriched = _inject_analytics_measurement_id(
                path=path,
                content=normalized,
                ga_measurement_id=ga_measurement_id,
            )
            if enriched != normalized:
                analytics_injected_paths.append(path)
            normalized = enriched
        publish_files.append(
            SEOMigrationGitHubPublishFile(
                path=path,
                content=normalized,
                media_type=media_type,
            )
        )
        seen_paths.add(path)
    return publish_files, analytics_injected_paths, warnings


def _normalize_generated_path(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().replace("\\", "/")
    if not normalized:
        return None
    if normalized.startswith("/"):
        return None
    if ".." in normalized:
        return None
    if not _VALID_RELATIVE_PATH_PATTERN.fullmatch(normalized):
        return None
    return normalized


def _is_forbidden_path(path: str) -> bool:
    lowered = path.lower()
    if lowered in _FORBIDDEN_PATH_EXACT:
        return True
    if _has_reserved_git_segment(lowered):
        return True
    return any(lowered.startswith(prefix) for prefix in _FORBIDDEN_PATH_PREFIXES)


def _has_reserved_git_segment(path: str) -> bool:
    normalized = str(path or "").strip().replace("\\", "/").strip("/")
    if not normalized:
        return False
    segments = [segment for segment in normalized.split("/") if segment]
    for segment in segments:
        lowered = segment.lower()
        if lowered.startswith(".git") or lowered.startswith(".github"):
            return True
    return False


def _normalize_generated_content(value: object) -> str | None:
    normalized = str(value or "").replace("\r\n", "\n").strip()
    if not normalized:
        return None
    return normalized


def _normalize_media_type(*, path: str, value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized:
        return normalized
    if path.endswith(".html"):
        return "text/html"
    if path.endswith(".css"):
        return "text/css"
    if path.endswith(".js"):
        return "application/javascript"
    if path.endswith(".json"):
        return "application/json"
    if path.endswith(".xml"):
        return "application/xml"
    if path.endswith(".ico"):
        return "image/x-icon"
    return "text/plain"


def _normalize_analytics_placeholders(*, path: str, content: str) -> str:
    normalized = content
    marker = "<!-- ANALYTICS_PLACEHOLDER -->"
    if path.endswith(".html") or path.endswith(".js"):
        if _ANALYTICS_SCRIPT_PATTERN.search(normalized):
            normalized = _ANALYTICS_SCRIPT_PATTERN.sub(marker, normalized)
        if _GA_MEASUREMENT_PATTERN.search(normalized):
            normalized = _GA_MEASUREMENT_PATTERN.sub("{{GA4_MEASUREMENT_ID}}", normalized)
    if path.endswith(".html"):
        placeholder_count = normalized.count(marker)
        if placeholder_count > 1:
            first_idx = normalized.find(marker)
            if first_idx >= 0:
                after_first_idx = first_idx + len(marker)
                normalized = normalized[:after_first_idx] + normalized[after_first_idx:].replace(marker, "")
    if path.endswith(".html") and marker not in normalized:
        lower = normalized.lower()
        if "</head>" in lower:
            idx = lower.index("</head>")
            normalized = normalized[:idx] + "\n  <!-- ANALYTICS_PLACEHOLDER -->\n" + normalized[idx:]
    return normalized


def _inject_analytics_measurement_id(*, path: str, content: str, ga_measurement_id: str) -> str:
    marker = "<!-- ANALYTICS_PLACEHOLDER -->"
    normalized = content.replace("{{GA4_MEASUREMENT_ID}}", ga_measurement_id)
    if not path.endswith(".html"):
        return normalized
    if normalized.count(marker) > 1:
        first_idx = normalized.find(marker)
        if first_idx >= 0:
            after_first_idx = first_idx + len(marker)
            normalized = normalized[:after_first_idx] + normalized[after_first_idx:].replace(marker, "")
    script_block = _GA4_SCRIPT_TEMPLATE.format(measurement_id=ga_measurement_id)
    if marker in normalized:
        return normalized.replace(marker, script_block, 1)
    lower = normalized.lower()
    if "</head>" not in lower:
        return normalized
    idx = lower.index("</head>")
    return normalized[:idx] + "\n  " + script_block + "\n" + normalized[idx:]


def _coerce_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _try_parse_json_payload(raw_output: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_output, re.IGNORECASE)
        if fenced_match is None:
            return None
        try:
            parsed = json.loads(fenced_match.group(1))
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _normalize_string(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _coerce_object_list(value: object, *, max_items: int) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized.append(_normalize_json_dict(item))
        if len(normalized) >= max_items:
            break
    return normalized
