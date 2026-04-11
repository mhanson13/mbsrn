from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.seo_migration_artifact_provider import (
    MisconfiguredSEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactGenerationOutput,
    SEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
    SEOMigrationProviderCompatibilityResult,
)
from app.integrations.seo_migration_github_publisher import (
    MisconfiguredSEOMigrationGitHubPublisher,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
    SEOMigrationGitHubWorkflowProvisionResult,
)
from app.models.business import Business
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
from app.services.ai_response_contract_evaluator import (
    AIResponseContractEvaluation,
    evaluate_migration_artifact_response,
)
from app.services.ai_model_settings import resolve_ai_model_name
from app.services.github_publish_config import GitHubPublishConfigService
from app.services.seo_migration_context import SEOMigrationContextAssembler
from app.services.seo_migration_artifact_quality import evaluate_migration_artifact_quality
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
_DRAFT_FAILURE_REASON_VALUES = {
    "timeout",
    "authentication_failed",
    "rate_limited",
    "malformed_response",
    "malformed_output",
    "empty_response",
    "unsupported_configuration",
    "transport_error",
    "validation_failed",
    "unknown",
}
_DRAFT_PROVIDER_LOG_EVENT = "seo_migration_draft_generation"
_DRAFT_CONTRACT_EVALUATION_LOG_EVENT = "seo_migration_draft_contract_evaluation"
_MIGRATION_READINESS_LOG_EVENT = "seo_migration_readiness_evaluation"
_DRAFT_PROVIDER_COMPATIBILITY_LOG_EVENT = "seo_migration_provider_compatibility_evaluation"
_MIGRATION_RUNTIME_PUBLISHER_LOG_EVENT = "seo_migration_runtime_publisher_readiness"
_MIGRATION_WORKFLOW_PROVISIONED_LOG_EVENT = "migration_workflow_provisioned"
_MIGRATION_DRAFT_TIMEOUT_DEFAULT_SECONDS = 120
_MIGRATION_DRAFT_TIMEOUT_MIN_SECONDS = 60
_MIGRATION_DRAFT_TIMEOUT_MAX_SECONDS = 900
_GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING = "runtime_credential_missing"
_GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID = "runtime_configuration_invalid"
_GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE = "runtime_integration_unavailable"
_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING = "published_artifact_missing"
_DEPLOY_BLOCKER_RUNTIME_UNAVAILABLE = "deploy_runtime_unavailable"
_DEPLOY_BLOCKER_CONFIGURATION_MISSING = "deploy_configuration_missing"
_DEPLOY_BLOCKER_CONFIGURATION_INVALID = "deploy_configuration_invalid"
_DEPLOY_BLOCKER_INTEGRATION_UNAVAILABLE = "deploy_integration_unavailable"

_DRAFT_PROVIDER_COMPAT_REASON_CODES = {
    "supported",
    "provider_not_configured",
    "unsupported_model_configuration",
    "unsupported_request_shape",
    "unsupported_endpoint_mode",
    "tools_required_but_unavailable",
    "degraded_mode_not_allowed",
    "unknown_provider_capability",
}

_DRAFT_READINESS_SCORE_SOURCE_SITE = 15
_DRAFT_READINESS_SCORE_OPERATOR_REQUIREMENTS = 25
_DRAFT_READINESS_SCORE_ENRICHED_CONTENT = 25
_DRAFT_READINESS_SCORE_AUDIT = 10
_DRAFT_READINESS_SCORE_RECOMMENDATIONS = 10
_DRAFT_READINESS_SCORE_COMPETITORS = 10
_DRAFT_READINESS_COMPLETENESS_BONUS = 5

_DRAFT_READINESS_REASON_SOURCE_REQUIRED = "source_site_ingest_required"
_DRAFT_READINESS_REASON_OPERATOR_REQUIRED = "operator_requirements_required"
_DRAFT_READINESS_REASON_ENRICHED_REQUIRED = "enriched_content_required"
_DRAFT_READINESS_REASON_PROVIDER_CONFIG_REQUIRED = "provider_config_missing"
_DRAFT_READINESS_REASON_AUDIT_UNAVAILABLE = "audit_context_unavailable"
_DRAFT_READINESS_REASON_RECOMMENDATIONS_UNAVAILABLE = "recommendations_context_unavailable"
_DRAFT_READINESS_REASON_COMPETITORS_UNAVAILABLE = "competitors_context_unavailable"
_DRAFT_READINESS_REASON_ENRICHED_SPARSE = "enriched_content_sparse"
_DRAFT_GENERATION_STATE_VALUES = {
    "ready",
    "ready_with_warnings",
    "blocked_by_workspace",
    "blocked_by_provider",
    "generation_failed",
    "generation_partial",
    "generation_succeeded",
}


class SEOMigrationNotFoundError(ValueError):
    pass


class SEOMigrationValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        failure_category: str | None = None,
        failure_reason: str | None = None,
        error_code: str | None = None,
        retryable: bool | None = None,
        correlation_id: str | None = None,
        workspace_id: str | None = None,
        artifact_version_id: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        timeout_seconds: int | None = None,
        timeout_source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_category = _normalize_string(failure_category, max_length=40)
        self.failure_reason = _normalize_string(failure_reason, max_length=80)
        self.error_code = _normalize_string(error_code, max_length=80)
        self.retryable = retryable if isinstance(retryable, bool) else None
        self.correlation_id = _normalize_string(correlation_id, max_length=120)
        self.workspace_id = _normalize_string(workspace_id, max_length=36)
        self.artifact_version_id = _normalize_string(artifact_version_id, max_length=36)
        self.provider_name = _normalize_string(provider_name, max_length=64)
        self.model_name = _normalize_string(model_name, max_length=128)
        self.prompt_version = _normalize_string(prompt_version, max_length=64)
        self.timeout_seconds = max(1, int(timeout_seconds)) if isinstance(timeout_seconds, int) else None
        normalized_timeout_source = _normalize_string(timeout_source, max_length=20)
        if normalized_timeout_source in {"admin", "default"}:
            self.timeout_source = normalized_timeout_source
        else:
            self.timeout_source = None

    def to_error_detail(self) -> dict[str, object]:
        detail: dict[str, object] = {"message": str(self)}
        if self.failure_category in _MIGRATION_FAILURE_CATEGORY_VALUES:
            detail["failure_category"] = self.failure_category
        if self.failure_reason in _DRAFT_FAILURE_REASON_VALUES:
            detail["failure_reason"] = self.failure_reason
        if self.error_code:
            detail["error_code"] = self.error_code
        if self.retryable is not None:
            detail["retryable"] = self.retryable
        if self.correlation_id:
            detail["correlation_id"] = self.correlation_id
        if self.workspace_id:
            detail["workspace_id"] = self.workspace_id
        if self.artifact_version_id:
            detail["artifact_version_id"] = self.artifact_version_id
        if self.provider_name:
            detail["provider_name"] = self.provider_name
        if self.model_name:
            detail["model_name"] = self.model_name
        if self.prompt_version:
            detail["prompt_version"] = self.prompt_version
        if self.timeout_seconds is not None:
            detail["timeout_seconds"] = self.timeout_seconds
        if self.timeout_source:
            detail["timeout_source"] = self.timeout_source
        return detail


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


@dataclass(frozen=True)
class SEOMigrationDraftFailure:
    failure_category: str
    failure_reason: str
    error_code: str
    message_for_operator: str
    retryable: bool | None
    provider_name: str
    model_name: str
    prompt_version: str
    correlation_id: str | None = None
    endpoint_path: str | None = None
    execution_mode: str | None = None
    response_format_mode: str | None = None
    request_body_mode: str | None = None
    compatibility_reason_code: str | None = None


@dataclass(frozen=True)
class SEOMigrationDraftReadinessReason:
    code: str
    severity: str
    message: str

    def to_payload(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }


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
        github_publish_config_service: GitHubPublishConfigService | None = None,
        provider_name: str,
        provider_model_name: str,
        env_default_model_name: str | None = None,
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
        self.draft_provider_configured = not isinstance(
            artifact_provider,
            MisconfiguredSEOMigrationArtifactGenerationProvider,
        )
        if github_publisher is None:
            github_publisher = MisconfiguredSEOMigrationGitHubPublisher(
                safe_message="GitHub publishing integration is unavailable in this runtime.",
                reason_code=_GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE,
            )
        self.github_publisher = github_publisher
        self.github_publisher_configured = not isinstance(
            github_publisher,
            MisconfiguredSEOMigrationGitHubPublisher,
        )
        self.github_publisher_reason_code = ""
        self.github_publisher_status_message = ""
        self.github_publisher_safe_message = ""
        if isinstance(github_publisher, MisconfiguredSEOMigrationGitHubPublisher):
            normalized_reason_code = _normalize_string(
                getattr(github_publisher, "reason_code", None),
                max_length=80,
            )
            self.github_publisher_reason_code = normalized_reason_code or "publisher_not_configured"
            self.github_publisher_safe_message = (
                _normalize_string(getattr(github_publisher, "safe_message", None), max_length=240)
                or "GitHub publishing integration is unavailable in this runtime."
            )
            self.github_publisher_status_message = self._runtime_publisher_reason_message(
                reason_code=self.github_publisher_reason_code,
                action="publish",
            )
        self.github_publish_config_service = github_publish_config_service
        self.provider_name = provider_name
        self.provider_model_name = provider_model_name
        self._configured_provider_model_name = _normalize_string(provider_model_name, max_length=128)
        self._env_default_model_name = _normalize_string(env_default_model_name, max_length=128)
        self.prompt_version = prompt_version
        self.prompt_text_recommendations = prompt_text_recommendations
        self.publish_commit_message_prefix = publish_commit_message_prefix.strip() or "[MBSRN Migration]"
        self.deploy_default_workflow_id = deploy_default_workflow_id.strip() or "deploy-www-prod.yml"
        self.deploy_default_ref = deploy_default_ref.strip() or "main"
        self._resolved_migration_draft_timeout_seconds = _MIGRATION_DRAFT_TIMEOUT_DEFAULT_SECONDS
        self._resolved_migration_draft_timeout_source = "default"

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
                publish_config_json=_normalize_workspace_publish_config(publish_config),
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
                workspace.publish_config_json = _normalize_workspace_publish_config(publish_config)
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
        workspace.publish_config_json = _normalize_workspace_publish_config(publish_config)
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
            target_summary=self._safe_effective_publish_target_summary(workspace.publish_config_json),
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
                blocker_codes=readiness.get("blocker_codes"),
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
            effective_publish_config, _, _ = self._build_effective_publish_config(
                workspace_publish_config=workspace.publish_config_json,
                require_admin=True,
            )
            target = _resolve_publish_target(effective_publish_config)
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
                target_summary=self._safe_effective_publish_target_summary(workspace.publish_config_json),
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
        deploy_workflow_provision_result: SEOMigrationGitHubWorkflowProvisionResult | None = None
        try:
            deploy_target_for_workflow: dict[str, object] | None = None
            try:
                deploy_target_for_workflow = _resolve_deploy_target(
                    deploy_config=workspace.deploy_config_json,
                    publish_config=effective_publish_config,
                    default_workflow_id=self.deploy_default_workflow_id,
                    default_ref=self.deploy_default_ref,
                )
            except ValueError:
                deploy_target_for_workflow = None

            if (
                not dry_run
                and isinstance(deploy_target_for_workflow, dict)
                and bool(deploy_target_for_workflow.get("enabled"))
            ):
                deploy_workflow_provision_result = self.github_publisher.ensure_deploy_workflow(
                    repo_owner=str(deploy_target_for_workflow.get("repo_owner") or target["repo_owner"]),
                    repo_name=str(deploy_target_for_workflow.get("repo_name") or target["repo_name"]),
                    branch=str(deploy_target_for_workflow.get("ref") or target["branch"]),
                    workflow_id=str(deploy_target_for_workflow.get("workflow_id") or self.deploy_default_workflow_id),
                    dry_run=False,
                )
                if deploy_workflow_provision_result.provisioned:
                    self._log_workflow_provisioned(
                        business_id=business_id,
                        site_id=site_id,
                        workspace_id=workspace.id,
                        principal_id=principal_id,
                        provision_result=deploy_workflow_provision_result,
                    )
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
            "deploy_workflow_provisioned": bool(
                not dry_run
                and deploy_workflow_provision_result is not None
                and deploy_workflow_provision_result.provisioned
            ),
        }
        if not dry_run and deploy_workflow_provision_result is not None:
            history_payload["deploy_workflow_id"] = deploy_workflow_provision_result.workflow_id
            history_payload["deploy_workflow_path"] = deploy_workflow_provision_result.workflow_path
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
                blocker_codes=readiness.get("blocker_codes"),
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
            effective_publish_config, _, _ = self._build_effective_publish_config(
                workspace_publish_config=workspace.publish_config_json,
                require_admin=True,
            )
            deploy_target = _resolve_deploy_target(
                deploy_config=workspace.deploy_config_json,
                publish_config=effective_publish_config,
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
        started_at = time.monotonic()
        draft_run_id = str(uuid4())
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        model_requested: str | None = None
        model_resolved = _normalize_string(self.provider_model_name, max_length=128)
        draft_timeout_seconds = max(1, int(self._resolved_migration_draft_timeout_seconds))
        draft_timeout_source = (
            self._resolved_migration_draft_timeout_source
            if self._resolved_migration_draft_timeout_source in {"admin", "default"}
            else "default"
        )
        context_json, context_summary = self._assemble_context(site=site, workspace=workspace)
        draft_readiness = self._build_draft_generation_readiness(
            business_id=business_id,
            site_id=site_id,
            workspace=workspace,
            context_summary=context_summary,
            emit_log=True,
        )
        if bool(draft_readiness.get("hard_blocked")):
            first_blocking_reason = next(
                (
                    item
                    for item in draft_readiness.get("reasons", [])
                    if isinstance(item, dict) and str(item.get("severity") or "").strip().lower() == "blocking"
                ),
                None,
            )
            blocking_code = (
                _normalize_string(
                    first_blocking_reason.get("code") if isinstance(first_blocking_reason, dict) else None,
                    max_length=80,
                )
                or "draft_generation_blocked"
            )
            blocking_message = _normalize_string(
                first_blocking_reason.get("message") if isinstance(first_blocking_reason, dict) else None,
                max_length=200,
            )
            summary_message = (
                _normalize_string(draft_readiness.get("summary"), max_length=280)
                or "Not ready yet. Resolve blocking migration inputs before generating a draft."
            )
            message = summary_message
            if blocking_message and blocking_message not in summary_message:
                message = f"{summary_message} {blocking_message}"
            failure_category = (
                "config_missing"
                if blocking_code == _DRAFT_READINESS_REASON_PROVIDER_CONFIG_REQUIRED
                else "unknown_error"
            )
            failure_reason = "unsupported_configuration" if failure_category == "config_missing" else "unknown"
            raise SEOMigrationValidationError(
                message,
                failure_category=failure_category,
                failure_reason=failure_reason,
                error_code=blocking_code,
                retryable=False,
                correlation_id=draft_run_id,
                workspace_id=workspace.id,
                provider_name=self.provider_name,
                model_name=model_resolved or self.provider_model_name,
                prompt_version=self.prompt_version,
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
        provider_compatibility = self._evaluate_draft_provider_compatibility(
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            emit_log=True,
            model_requested=model_requested,
            model_resolved=model_resolved,
        )
        draft_endpoint_path = _normalize_string(provider_compatibility.endpoint_path, max_length=120)
        draft_execution_mode = _normalize_string(provider_compatibility.execution_mode, max_length=40)
        draft_response_format_mode = _normalize_string(provider_compatibility.response_format_mode, max_length=60)
        draft_request_body_mode = _normalize_string(provider_compatibility.request_body_mode, max_length=80)
        if not provider_compatibility.supported:
            draft_failure = self._draft_failure_from_provider_compatibility(
                compatibility=provider_compatibility,
                prompt_version=self.prompt_version,
                draft_run_id=draft_run_id,
            )
            failed_artifact = self._record_failed_draft_generation(
                workspace=workspace,
                site=site,
                context_json=context_json,
                draft_run_id=draft_run_id,
                failure=draft_failure,
                principal_id=principal_id,
                model_requested=model_requested,
                model_resolved=model_resolved,
                model_used=draft_failure.model_name,
                failure_source="local_preflight",
                duration_ms=self._duration_ms(started_at),
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
            self._log_draft_generation_event(
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                draft_run_id=draft_run_id,
                artifact_version_id=failed_artifact.id,
                artifact_version=failed_artifact.version,
                provider_name=draft_failure.provider_name,
                model_name=draft_failure.model_name,
                prompt_version=draft_failure.prompt_version,
                failure_category=draft_failure.failure_category,
                failure_reason=draft_failure.failure_reason,
                retryable=draft_failure.retryable,
                correlation_id=draft_failure.correlation_id or failed_artifact.id,
                duration_ms=self._duration_ms(started_at),
                model_requested=model_requested,
                model_resolved=model_resolved,
                model_used=draft_failure.model_name,
                endpoint_path=draft_failure.endpoint_path,
                execution_mode=draft_failure.execution_mode,
                response_format_mode=draft_failure.response_format_mode,
                request_body_mode=draft_failure.request_body_mode,
                compatibility_decision="blocked_local_preflight",
                failure_source="local_preflight",
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
            raise SEOMigrationValidationError(
                draft_failure.message_for_operator,
                failure_category=draft_failure.failure_category,
                failure_reason=draft_failure.failure_reason,
                error_code=draft_failure.error_code,
                retryable=draft_failure.retryable,
                correlation_id=draft_failure.correlation_id or failed_artifact.id,
                workspace_id=workspace.id,
                artifact_version_id=failed_artifact.id,
                provider_name=draft_failure.provider_name,
                model_name=draft_failure.model_name,
                prompt_version=draft_failure.prompt_version,
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
        self._log_draft_generation_event(
            status="requested",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            draft_run_id=draft_run_id,
            provider_name=self.provider_name,
            model_name=self.provider_model_name,
            prompt_version=self.prompt_version,
            model_requested=model_requested,
            model_resolved=model_resolved,
            model_used=model_resolved,
            compatibility_decision="allowed",
            timeout_seconds=draft_timeout_seconds,
            timeout_source=draft_timeout_source,
        )

        provider_output: SEOMigrationArtifactGenerationOutput | None = None
        draft_failure: SEOMigrationDraftFailure | None = None
        parse_warnings: list[str] = []
        generation_status = "completed"
        generation_error_summary: str | None = None
        try:
            provider_output = self.artifact_provider.generate_artifacts(migration_context=context_json)
        except SEOMigrationArtifactProviderError as exc:
            draft_failure = self._classify_draft_provider_failure(exc)
            salvaged_output = self._salvage_provider_error_output(exc)
            if salvaged_output is None:
                failed_artifact = self._record_failed_draft_generation(
                    workspace=workspace,
                    site=site,
                    context_json=context_json,
                    draft_run_id=draft_run_id,
                    failure=draft_failure,
                    principal_id=principal_id,
                    model_requested=model_requested,
                    model_resolved=model_resolved,
                    model_used=draft_failure.model_name,
                    failure_source="remote_provider",
                    duration_ms=self._duration_ms(started_at),
                    timeout_seconds=draft_timeout_seconds,
                    timeout_source=draft_timeout_source,
                )
                self._log_draft_generation_event(
                    status="failed",
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    draft_run_id=draft_run_id,
                    artifact_version_id=failed_artifact.id,
                    artifact_version=failed_artifact.version,
                    provider_name=draft_failure.provider_name,
                    model_name=draft_failure.model_name,
                    prompt_version=draft_failure.prompt_version,
                    failure_category=draft_failure.failure_category,
                    failure_reason=draft_failure.failure_reason,
                    retryable=draft_failure.retryable,
                    correlation_id=draft_failure.correlation_id or failed_artifact.id,
                    duration_ms=self._duration_ms(started_at),
                    model_requested=model_requested,
                    model_resolved=model_resolved,
                    model_used=draft_failure.model_name,
                    endpoint_path=draft_failure.endpoint_path,
                    execution_mode=draft_failure.execution_mode,
                    response_format_mode=draft_failure.response_format_mode,
                    request_body_mode=draft_failure.request_body_mode,
                    compatibility_decision="allowed",
                    failure_source="remote_provider",
                    timeout_seconds=draft_timeout_seconds,
                    timeout_source=draft_timeout_source,
                )
                raise SEOMigrationValidationError(
                    draft_failure.message_for_operator,
                    failure_category=draft_failure.failure_category,
                    failure_reason=draft_failure.failure_reason,
                    error_code=draft_failure.error_code,
                    retryable=draft_failure.retryable,
                    correlation_id=draft_failure.correlation_id or failed_artifact.id,
                    workspace_id=workspace.id,
                    artifact_version_id=failed_artifact.id,
                    provider_name=draft_failure.provider_name,
                    model_name=draft_failure.model_name,
                    prompt_version=draft_failure.prompt_version,
                    timeout_seconds=draft_timeout_seconds,
                    timeout_source=draft_timeout_source,
                ) from exc
            provider_output = salvaged_output
            generation_status = "partial"
            generation_error_summary = draft_failure.message_for_operator
            parse_warnings.append("Provider response partially salvaged after schema failure.")
        except Exception as exc:  # noqa: BLE001
            draft_failure = self._unknown_draft_failure(
                provider_name=self.provider_name,
                model_name=self.provider_model_name,
                prompt_version=self.prompt_version,
            )
            failed_artifact = self._record_failed_draft_generation(
                workspace=workspace,
                site=site,
                context_json=context_json,
                draft_run_id=draft_run_id,
                failure=draft_failure,
                principal_id=principal_id,
                model_requested=model_requested,
                model_resolved=model_resolved,
                model_used=draft_failure.model_name,
                failure_source="unknown",
                duration_ms=self._duration_ms(started_at),
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
            self._log_draft_generation_event(
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                draft_run_id=draft_run_id,
                artifact_version_id=failed_artifact.id,
                artifact_version=failed_artifact.version,
                provider_name=draft_failure.provider_name,
                model_name=draft_failure.model_name,
                prompt_version=draft_failure.prompt_version,
                failure_category=draft_failure.failure_category,
                failure_reason=draft_failure.failure_reason,
                retryable=draft_failure.retryable,
                correlation_id=failed_artifact.id,
                duration_ms=self._duration_ms(started_at),
                error_type=type(exc).__name__,
                model_requested=model_requested,
                model_resolved=model_resolved,
                model_used=draft_failure.model_name,
                compatibility_decision="allowed",
                failure_source="unknown",
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
            raise SEOMigrationValidationError(
                draft_failure.message_for_operator,
                failure_category=draft_failure.failure_category,
                failure_reason=draft_failure.failure_reason,
                error_code=draft_failure.error_code,
                retryable=draft_failure.retryable,
                correlation_id=failed_artifact.id,
                workspace_id=workspace.id,
                artifact_version_id=failed_artifact.id,
                provider_name=draft_failure.provider_name,
                model_name=draft_failure.model_name,
                prompt_version=draft_failure.prompt_version,
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            ) from exc

        normalized_files, file_warnings = self._validate_and_normalize_files(provider_output.generated_files)
        parse_warnings.extend(file_warnings)
        draft_contract_evaluation = evaluate_migration_artifact_response(
            strategy_summary=provider_output.strategy_summary,
            generated_files=normalized_files,
            raw_generated_file_count=max(0, int(len(provider_output.generated_files))),
            page_map_count=max(0, int(len(provider_output.page_map))),
        )
        self._log_draft_contract_evaluation(
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            draft_run_id=draft_run_id,
            provider_name=str(provider_output.provider_name or self.provider_name),
            model_name=str(provider_output.model_name or self.provider_model_name),
            evaluation=draft_contract_evaluation,
        )
        parse_warnings.extend(self._draft_contract_warnings(evaluation=draft_contract_evaluation))
        if draft_contract_evaluation.status == "salvaged" and generation_status == "completed":
            generation_status = "partial"
            if generation_error_summary is None:
                generation_error_summary = "Migration draft generated with partial contract salvage."

        if draft_contract_evaluation.status == "rejected" or not normalized_files:
            reason_code = (
                draft_contract_evaluation.reasons[0] if draft_contract_evaluation.reasons else "validation_failed"
            )
            draft_failure = SEOMigrationDraftFailure(
                failure_category="artifact_invalid",
                failure_reason="validation_failed",
                error_code=reason_code,
                message_for_operator=self._draft_contract_rejection_message(
                    evaluation=draft_contract_evaluation,
                ),
                retryable=draft_contract_evaluation.retryable,
                provider_name=str(provider_output.provider_name or self.provider_name),
                model_name=str(provider_output.model_name or self.provider_model_name),
                prompt_version=str(provider_output.prompt_version or self.prompt_version),
                correlation_id=draft_run_id,
            )
            failed_artifact = self._record_failed_draft_generation(
                workspace=workspace,
                site=site,
                context_json=context_json,
                draft_run_id=draft_run_id,
                failure=draft_failure,
                principal_id=principal_id,
                model_requested=model_requested,
                model_resolved=model_resolved,
                model_used=draft_failure.model_name,
                failure_source="local_validation",
                duration_ms=self._duration_ms(started_at),
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
            self._log_draft_generation_event(
                status="failed",
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                draft_run_id=draft_run_id,
                artifact_version_id=failed_artifact.id,
                artifact_version=failed_artifact.version,
                provider_name=draft_failure.provider_name,
                model_name=draft_failure.model_name,
                prompt_version=draft_failure.prompt_version,
                failure_category=draft_failure.failure_category,
                failure_reason=draft_failure.failure_reason,
                retryable=draft_failure.retryable,
                correlation_id=failed_artifact.id,
                duration_ms=self._duration_ms(started_at),
                model_requested=model_requested,
                model_resolved=model_resolved,
                model_used=draft_failure.model_name,
                compatibility_decision="allowed",
                failure_source="local_validation",
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )
            raise SEOMigrationValidationError(
                draft_failure.message_for_operator,
                failure_category=draft_failure.failure_category,
                failure_reason=draft_failure.failure_reason,
                error_code=draft_failure.error_code,
                retryable=draft_failure.retryable,
                correlation_id=failed_artifact.id,
                workspace_id=workspace.id,
                artifact_version_id=failed_artifact.id,
                provider_name=draft_failure.provider_name,
                model_name=draft_failure.model_name,
                prompt_version=draft_failure.prompt_version,
                timeout_seconds=draft_timeout_seconds,
                timeout_source=draft_timeout_source,
            )

        artifact_version_number = self.seo_migration_repository.next_artifact_version_number(workspace.id)
        total_bytes = sum(len(str(item["content"]).encode("utf-8")) for item in normalized_files)
        artifact_model_used = _normalize_string(provider_output.model_name, max_length=128) or model_resolved
        generation_duration_ms = self._duration_ms(started_at)
        artifact_quality_evaluation = evaluate_migration_artifact_quality(
            {
                "generated_files": normalized_files,
                "page_map": _normalize_json_list(provider_output.page_map),
                "strategy_summary": _normalize_string(provider_output.strategy_summary, max_length=8000),
                "business_name": _normalize_string(site.display_name, max_length=255),
                "location_hints": self._build_artifact_quality_location_hints(site=site),
                "expected_service_terms": self._build_artifact_quality_service_terms(
                    workspace=workspace,
                    context_json=context_json,
                ),
            }
        )
        artifact_context_json = self._build_draft_execution_context(
            context_json=context_json,
            model_requested=model_requested,
            model_resolved=model_resolved,
            model_used=artifact_model_used,
            endpoint_path=(
                draft_failure.endpoint_path
                if draft_failure and generation_status == "partial"
                else draft_endpoint_path
            ),
            execution_mode=(
                draft_failure.execution_mode
                if draft_failure and generation_status == "partial"
                else draft_execution_mode
            ),
            response_format_mode=(
                draft_failure.response_format_mode
                if draft_failure and generation_status == "partial"
                else draft_response_format_mode
            ),
            request_body_mode=(
                draft_failure.request_body_mode
                if draft_failure and generation_status == "partial"
                else draft_request_body_mode
            ),
            compatibility_decision="allowed",
            failure_source=("remote_provider" if draft_failure and generation_status == "partial" else None),
            artifact_status=generation_status,
            duration_ms=generation_duration_ms,
            timeout_seconds=draft_timeout_seconds,
            timeout_source=draft_timeout_source,
        )
        artifact = SEOMigrationArtifactVersion(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            version=artifact_version_number,
            status=generation_status,
            context_json=artifact_context_json,
            strategy_summary=provider_output.strategy_summary,
            page_map_json=_normalize_json_list(provider_output.page_map),
            homepage_structure_json=_normalize_json_list(provider_output.homepage_structure),
            service_page_suggestions_json=_normalize_json_list(provider_output.service_page_suggestions),
            cta_contact_structure_json=_normalize_json_dict(provider_output.cta_contact_structure),
            seo_meta_suggestions_json=_normalize_json_dict(provider_output.seo_meta_suggestions),
            redirect_suggestions_json=_normalize_json_list(provider_output.redirect_suggestions),
            analytics_placeholders_json=_normalize_json_list(provider_output.analytics_placeholders),
            generated_files_json=normalized_files,
            artifact_quality_evaluation_json=_normalize_json_dict(artifact_quality_evaluation),
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
        self._log_draft_generation_event(
            status=generation_status,
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            draft_run_id=draft_run_id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            provider_name=artifact.provider_name,
            model_name=artifact.model_name,
            prompt_version=artifact.prompt_version,
            failure_category=(
                draft_failure.failure_category if draft_failure and generation_status == "partial" else None
            ),
            failure_reason=(draft_failure.failure_reason if draft_failure and generation_status == "partial" else None),
            retryable=(draft_failure.retryable if draft_failure and generation_status == "partial" else None),
            correlation_id=(draft_failure.correlation_id if draft_failure and generation_status == "partial" else None),
            duration_ms=self._duration_ms(started_at),
            model_requested=model_requested,
            model_resolved=model_resolved,
            model_used=artifact.model_name,
            endpoint_path=(draft_failure.endpoint_path if draft_failure and generation_status == "partial" else None),
            execution_mode=(draft_failure.execution_mode if draft_failure and generation_status == "partial" else None),
            response_format_mode=(
                draft_failure.response_format_mode if draft_failure and generation_status == "partial" else None
            ),
            request_body_mode=(draft_failure.request_body_mode if draft_failure and generation_status == "partial" else None),
            compatibility_decision="allowed",
            failure_source=("remote_provider" if draft_failure and generation_status == "partial" else None),
        )
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
        draft_diagnostics = self._derive_draft_generation_diagnostics(artifact=latest_artifact)
        draft_readiness = self._build_draft_generation_readiness(
            business_id=business_id,
            site_id=site_id,
            workspace=workspace,
            context_summary=context_summary,
            emit_log=True,
        )
        draft_provider_compatibility = self._evaluate_draft_provider_compatibility(
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            emit_log=True,
        )
        ai_execution_summary = self._derive_draft_ai_execution_summary(
            artifact=latest_artifact,
            draft_provider_compatibility=draft_provider_compatibility,
        )
        draft_generation_state = self._build_draft_generation_state(
            draft_readiness=draft_readiness,
            draft_provider_compatibility=draft_provider_compatibility,
            draft_diagnostics=draft_diagnostics,
        )
        destination_summary = self._build_destination_summary(
            site=site,
            workspace=workspace,
            latest_artifact=latest_artifact,
            publish_readiness=publish_readiness,
            deploy_readiness=deploy_readiness,
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
                "last_draft_generation_status": draft_diagnostics.get("last_status"),
                "last_draft_failure_category": draft_diagnostics.get("last_failure_category"),
                "last_draft_failure_reason": draft_diagnostics.get("last_failure_reason"),
                "last_draft_failure_message": draft_diagnostics.get("last_failure_message"),
                "last_draft_failure_retryable": draft_diagnostics.get("last_failure_retryable"),
                "last_draft_failure_code": draft_diagnostics.get("last_failure_code"),
                "last_draft_failure_correlation_id": draft_diagnostics.get("last_failure_correlation_id"),
                "last_draft_failure_artifact_version_id": draft_diagnostics.get("last_failure_artifact_version_id"),
                "last_draft_failure_source": draft_diagnostics.get("last_failure_source"),
                "last_draft_failure_endpoint_path": draft_diagnostics.get("last_failure_endpoint_path"),
                "last_draft_failure_execution_mode": draft_diagnostics.get("last_failure_execution_mode"),
                "last_draft_failure_response_format_mode": draft_diagnostics.get(
                    "last_failure_response_format_mode"
                ),
                "last_draft_failure_request_body_mode": draft_diagnostics.get("last_failure_request_body_mode"),
                "last_draft_failure_model_requested": draft_diagnostics.get("last_failure_model_requested"),
                "last_draft_failure_model_resolved": draft_diagnostics.get("last_failure_model_resolved"),
                "last_draft_failure_model_used": draft_diagnostics.get("last_failure_model_used"),
                "last_draft_failure_timeout_seconds": draft_diagnostics.get("last_failure_timeout_seconds"),
                "last_draft_failure_timeout_source": draft_diagnostics.get("last_failure_timeout_source"),
                "last_draft_execution_duration_ms": ai_execution_summary.get("duration_ms"),
                "last_draft_request_contract_status": ai_execution_summary.get("request_contract_status"),
                "last_draft_provider_execution_status": ai_execution_summary.get("provider_execution_status"),
                "last_draft_artifact_status": ai_execution_summary.get("artifact_status"),
                "last_draft_artifact_result": ai_execution_summary.get("artifact_result"),
                "draft_model_requested": None,
                "draft_model_resolved": _normalize_string(self.provider_model_name, max_length=128),
                "draft_model_used": _normalize_string(
                    latest_artifact.model_name if latest_artifact is not None else None,
                    max_length=128,
                ),
                "draft_timeout_seconds": max(1, int(self._resolved_migration_draft_timeout_seconds)),
                "draft_timeout_source": (
                    self._resolved_migration_draft_timeout_source
                    if self._resolved_migration_draft_timeout_source in {"admin", "default"}
                    else "default"
                ),
                "draft_provider_compatibility_supported": bool(draft_provider_compatibility.supported),
                "draft_provider_compatibility_reason_code": draft_provider_compatibility.reason_code,
                "draft_provider_compatibility_message": draft_provider_compatibility.operator_message,
                "draft_provider_compatibility_retryable": bool(draft_provider_compatibility.retryable),
                "draft_provider_compatibility_provider_name": draft_provider_compatibility.provider_name,
                "draft_provider_compatibility_model_name": draft_provider_compatibility.model_name,
                "draft_provider_compatibility_endpoint_path": draft_provider_compatibility.endpoint_path,
                "draft_provider_compatibility_execution_mode": draft_provider_compatibility.execution_mode,
                "draft_provider_compatibility_response_format_mode": draft_provider_compatibility.response_format_mode,
                "draft_provider_compatibility_request_body_mode": draft_provider_compatibility.request_body_mode,
                "draft_provider_compatibility_admin_summary": draft_provider_compatibility.admin_summary,
                "draft_generation_state_status": draft_generation_state.get("status"),
                "draft_generation_state_summary": draft_generation_state.get("summary"),
            },
            "ai_execution": ai_execution_summary,
            "draft_generation_readiness": draft_readiness,
            "draft_provider_compatibility": self._serialize_draft_provider_compatibility(
                compatibility=draft_provider_compatibility,
            ),
            "draft_generation_state": draft_generation_state,
            "destination_summary": destination_summary,
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

    def _derive_draft_generation_diagnostics(
        self, *, artifact: SEOMigrationArtifactVersion | None
    ) -> dict[str, object]:
        if artifact is None:
            return {
                "last_status": None,
                "last_failure_category": None,
                "last_failure_reason": None,
                "last_failure_message": None,
                "last_failure_retryable": None,
                "last_failure_code": None,
                "last_failure_correlation_id": None,
                "last_failure_artifact_version_id": None,
                "last_failure_source": None,
                "last_failure_endpoint_path": None,
                "last_failure_execution_mode": None,
                "last_failure_response_format_mode": None,
                "last_failure_request_body_mode": None,
                "last_failure_model_requested": None,
                "last_failure_model_resolved": None,
                "last_failure_model_used": None,
                "last_failure_timeout_seconds": None,
                "last_failure_timeout_source": None,
            }

        diagnostics_payload = {}
        if isinstance(artifact.context_json, dict):
            diagnostics_payload = _normalize_json_dict(artifact.context_json.get("draft_generation_failure"))
        status_value = _normalize_string(artifact.status, max_length=40)
        failure_category = _normalize_string(diagnostics_payload.get("failure_category"), max_length=40)
        if failure_category not in _MIGRATION_FAILURE_CATEGORY_VALUES:
            failure_category = "artifact_invalid" if status_value == "failed" else None
        failure_reason = _normalize_string(diagnostics_payload.get("failure_reason"), max_length=80)
        if failure_reason not in _DRAFT_FAILURE_REASON_VALUES:
            failure_reason = None
        failure_code = _normalize_string(diagnostics_payload.get("error_code"), max_length=80)
        retryable = diagnostics_payload.get("retryable")
        retryable_flag = retryable if isinstance(retryable, bool) else None
        correlation_id = _normalize_string(diagnostics_payload.get("correlation_id"), max_length=120)
        failure_source = _normalize_string(diagnostics_payload.get("failure_source"), max_length=40)
        if failure_source not in {"local_preflight", "remote_provider", "local_validation", "unknown"}:
            failure_source = None
        endpoint_path = _normalize_string(diagnostics_payload.get("endpoint_path"), max_length=120)
        execution_mode = _normalize_string(diagnostics_payload.get("execution_mode"), max_length=40)
        response_format_mode = _normalize_string(diagnostics_payload.get("response_format_mode"), max_length=60)
        request_body_mode = _normalize_string(diagnostics_payload.get("request_body_mode"), max_length=80)
        model_requested = _normalize_string(diagnostics_payload.get("model_requested"), max_length=128)
        model_resolved = _normalize_string(diagnostics_payload.get("model_resolved"), max_length=128)
        model_used = _normalize_string(diagnostics_payload.get("model_used"), max_length=128)
        timeout_seconds_raw = diagnostics_payload.get("timeout_seconds")
        timeout_seconds = (
            max(1, int(timeout_seconds_raw))
            if isinstance(timeout_seconds_raw, int)
            else None
        )
        timeout_source = _normalize_string(diagnostics_payload.get("timeout_source"), max_length=20)
        if timeout_source not in {"admin", "default"}:
            timeout_source = None
        return {
            "last_status": status_value,
            "last_failure_category": failure_category,
            "last_failure_reason": failure_reason,
            "last_failure_message": _normalize_string(artifact.error_summary, max_length=400),
            "last_failure_retryable": retryable_flag,
            "last_failure_code": failure_code,
            "last_failure_correlation_id": correlation_id,
            "last_failure_artifact_version_id": artifact.id,
            "last_failure_source": failure_source,
            "last_failure_endpoint_path": endpoint_path,
            "last_failure_execution_mode": execution_mode,
            "last_failure_response_format_mode": response_format_mode,
            "last_failure_request_body_mode": request_body_mode,
            "last_failure_model_requested": model_requested,
            "last_failure_model_resolved": model_resolved,
            "last_failure_model_used": model_used,
            "last_failure_timeout_seconds": timeout_seconds,
            "last_failure_timeout_source": timeout_source,
        }

    def _build_draft_generation_state(
        self,
        *,
        draft_readiness: dict[str, object],
        draft_provider_compatibility: SEOMigrationProviderCompatibilityResult,
        draft_diagnostics: dict[str, object],
    ) -> dict[str, object]:
        readiness_status = _normalize_string(draft_readiness.get("status"), max_length=40) or "not_ready"
        readiness_summary = _normalize_string(draft_readiness.get("summary"), max_length=320)
        readiness_hard_blocked = bool(draft_readiness.get("hard_blocked"))
        latest_generation_status = _normalize_string(draft_diagnostics.get("last_status"), max_length=40)
        latest_failure_message = _normalize_string(draft_diagnostics.get("last_failure_message"), max_length=320)
        latest_failure_category = _normalize_string(draft_diagnostics.get("last_failure_category"), max_length=40)
        latest_failure_reason = _normalize_string(draft_diagnostics.get("last_failure_reason"), max_length=80)
        latest_failure_retryable = draft_diagnostics.get("last_failure_retryable")
        retryable = latest_failure_retryable if isinstance(latest_failure_retryable, bool) else None
        compatibility_supported = bool(draft_provider_compatibility.supported)
        compatibility_reason_code = (
            _normalize_string(draft_provider_compatibility.reason_code, max_length=80) or "unknown_provider_capability"
        )
        compatibility_message = _normalize_string(draft_provider_compatibility.operator_message, max_length=320)

        status = "ready"
        summary = "Ready to generate draft."
        if readiness_hard_blocked:
            status = "blocked_by_workspace"
            summary = readiness_summary or "Not ready yet — resolve blocking migration readiness issues."
        elif not compatibility_supported:
            status = "blocked_by_provider"
            summary = (
                compatibility_message
                or "Blocked: current AI model/configuration is not compatible with migration draft generation."
            )
        elif latest_generation_status == "failed":
            status = "generation_failed"
            summary = latest_failure_message or "Draft generation failed."
        elif latest_generation_status == "partial":
            status = "generation_partial"
            summary = "Partial draft generated."
        elif latest_generation_status == "completed":
            status = "generation_succeeded"
            summary = "Draft generated successfully."
        elif readiness_status == "ready_with_warnings":
            status = "ready_with_warnings"
            summary = readiness_summary or "Ready, but draft quality may be limited."
        else:
            status = "ready"
            summary = readiness_summary or "Ready to generate draft."

        if status not in _DRAFT_GENERATION_STATE_VALUES:
            status = "ready"
        return {
            "status": status,
            "summary": summary,
            "readiness_status": readiness_status,
            "readiness_hard_blocked": readiness_hard_blocked,
            "provider_compatibility_supported": compatibility_supported,
            "provider_compatibility_reason_code": compatibility_reason_code,
            "latest_generation_status": latest_generation_status,
            "latest_failure_category": latest_failure_category,
            "latest_failure_reason": latest_failure_reason,
            "retryable": retryable,
        }

    def _derive_draft_ai_execution_summary(
        self,
        *,
        artifact: SEOMigrationArtifactVersion | None,
        draft_provider_compatibility: SEOMigrationProviderCompatibilityResult,
    ) -> dict[str, object]:
        execution_payload: dict[str, object] = {}
        if artifact is not None and isinstance(artifact.context_json, dict):
            execution_payload = _normalize_json_dict(artifact.context_json.get("draft_generation_execution"))
        model_requested = _normalize_string(execution_payload.get("model_requested"), max_length=128)
        model_resolved = _normalize_string(execution_payload.get("model_resolved"), max_length=128)
        if model_resolved is None:
            model_resolved = _normalize_string(self.provider_model_name, max_length=128)
        model_used = _normalize_string(execution_payload.get("model_used"), max_length=128)
        if model_used is None and artifact is not None:
            model_used = _normalize_string(artifact.model_name, max_length=128)
        if model_used is None:
            model_used = _normalize_string(draft_provider_compatibility.model_name, max_length=128)
        endpoint_path = _normalize_string(execution_payload.get("endpoint_path"), max_length=120)
        if endpoint_path is None:
            endpoint_path = _normalize_string(draft_provider_compatibility.endpoint_path, max_length=120)
        request_body_mode = _normalize_string(execution_payload.get("request_body_mode"), max_length=80)
        if request_body_mode is None:
            request_body_mode = _normalize_string(draft_provider_compatibility.request_body_mode, max_length=80)
        compatibility_decision = _normalize_string(execution_payload.get("compatibility_decision"), max_length=40)
        if compatibility_decision not in {"allowed", "blocked_local_preflight"}:
            compatibility_decision = "allowed" if draft_provider_compatibility.supported else "blocked_local_preflight"
        failure_source = _normalize_string(execution_payload.get("failure_source"), max_length=40)
        if failure_source not in {"local_preflight", "remote_provider", "local_validation", "unknown"}:
            failure_source = None
        artifact_status = _normalize_string(execution_payload.get("artifact_status"), max_length=40)
        if artifact_status not in {"completed", "partial", "failed"}:
            artifact_status = _normalize_string(artifact.status, max_length=40) if artifact is not None else None
        if artifact_status not in {"completed", "partial", "failed"}:
            artifact_status = None
        artifact_result = _normalize_string(execution_payload.get("artifact_result"), max_length=40)
        if artifact_result not in {"succeeded", "partial", "failed"}:
            artifact_result = self._artifact_result_from_status(artifact_status)
        duration_ms_raw = execution_payload.get("duration_ms")
        duration_ms = max(0, int(duration_ms_raw)) if isinstance(duration_ms_raw, int) else None
        request_contract_status = _normalize_string(execution_payload.get("request_contract_status"), max_length=60)
        if request_contract_status not in {"accepted", "accepted_with_warnings", "blocked", "rejected"}:
            request_contract_status = self._derive_request_contract_status(
                compatibility_decision=compatibility_decision,
                failure_source=failure_source,
                artifact_status=artifact_status,
            )
        provider_execution_status = _normalize_string(execution_payload.get("provider_execution_status"), max_length=40)
        if provider_execution_status not in {"accepted", "rejected", "not_called", "unknown"}:
            provider_execution_status = self._derive_provider_execution_status(
                compatibility_decision=compatibility_decision,
                failure_source=failure_source,
                artifact_status=artifact_status,
            )
        timeout_seconds_raw = execution_payload.get("timeout_seconds")
        timeout_seconds = (
            max(1, int(timeout_seconds_raw))
            if isinstance(timeout_seconds_raw, int)
            else max(1, int(self._resolved_migration_draft_timeout_seconds))
        )
        timeout_source = _normalize_string(execution_payload.get("timeout_source"), max_length=20)
        if timeout_source not in {"admin", "default"}:
            timeout_source = (
                self._resolved_migration_draft_timeout_source
                if self._resolved_migration_draft_timeout_source in {"admin", "default"}
                else "default"
            )
        return {
            "model_requested": model_requested,
            "model_resolved": model_resolved,
            "model_used": model_used,
            "endpoint_path": endpoint_path,
            "request_body_mode": request_body_mode,
            "compatibility_decision": compatibility_decision,
            "failure_source": failure_source,
            "request_contract_status": request_contract_status,
            "provider_execution_status": provider_execution_status,
            "artifact_status": artifact_status,
            "artifact_result": artifact_result,
            "duration_ms": duration_ms,
            "timeout_seconds": timeout_seconds,
            "timeout_source": timeout_source,
        }

    def _build_draft_generation_readiness(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace: SEOMigrationWorkspace,
        context_summary: dict[str, object],
        emit_log: bool,
    ) -> dict[str, object]:
        normalized_summary = _normalize_json_dict(context_summary)
        reused_context = _normalize_json_dict(normalized_summary.get("reused_context"))
        audit_context = _normalize_json_dict(reused_context.get("audit"))
        recommendation_context = _normalize_json_dict(reused_context.get("recommendations"))
        competitor_context = _normalize_json_dict(reused_context.get("competitors"))
        has_source_snapshot = bool(normalized_summary.get("has_source_snapshot"))
        has_operator_requirements = bool(normalized_summary.get("has_operator_requirements"))
        has_enriched_notes = bool(normalized_summary.get("has_enriched_content_notes"))
        signals = {
            "source_site_ingested": has_source_snapshot
            or str(workspace.source_site_status or "").strip() == "ingested",
            "operator_requirements_present": has_operator_requirements,
            "enriched_content_present": has_enriched_notes,
            "audit_available": bool(normalized_summary.get("has_audit_summary"))
            or bool(audit_context.get("available")),
            "recommendations_available": bool(normalized_summary.get("has_recommendation_summary"))
            or bool(recommendation_context.get("available")),
            "competitors_available": bool(normalized_summary.get("has_competitor_summary"))
            or bool(competitor_context.get("available")),
            "draft_provider_configured": bool(self.draft_provider_configured),
        }
        blocking_reasons: list[SEOMigrationDraftReadinessReason] = []
        warning_reasons: list[SEOMigrationDraftReadinessReason] = []

        if not signals["source_site_ingested"]:
            blocking_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_SOURCE_REQUIRED,
                    severity="blocking",
                    message="Run source ingest to capture baseline source-site context.",
                )
            )
        if not signals["operator_requirements_present"]:
            blocking_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_OPERATOR_REQUIRED,
                    severity="blocking",
                    message="Add operator requirements before generating a draft.",
                )
            )
        if not signals["enriched_content_present"]:
            blocking_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_ENRICHED_REQUIRED,
                    severity="blocking",
                    message="Add enriched replacement content notes before generating a draft.",
                )
            )
        if not signals["draft_provider_configured"]:
            blocking_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_PROVIDER_CONFIG_REQUIRED,
                    severity="blocking",
                    message="AI provider configuration is missing or invalid for migration draft generation.",
                )
            )

        if not signals["audit_available"]:
            warning_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_AUDIT_UNAVAILABLE,
                    severity="warning",
                    message="Audit context is not available; draft quality may be limited.",
                )
            )
        if not signals["recommendations_available"]:
            warning_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_RECOMMENDATIONS_UNAVAILABLE,
                    severity="warning",
                    message="Recommendation context is not available; draft quality may be limited.",
                )
            )
        if not signals["competitors_available"]:
            warning_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_COMPETITORS_UNAVAILABLE,
                    severity="warning",
                    message="Competitor context is not available; draft quality may be limited.",
                )
            )
        if signals["enriched_content_present"] and self._is_sparse_enriched_content(
            workspace.enriched_content_notes_json
        ):
            warning_reasons.append(
                SEOMigrationDraftReadinessReason(
                    code=_DRAFT_READINESS_REASON_ENRICHED_SPARSE,
                    severity="warning",
                    message="Enriched replacement content is sparse; add more detail for better draft quality.",
                )
            )

        score = 0
        if signals["source_site_ingested"]:
            score += _DRAFT_READINESS_SCORE_SOURCE_SITE
        if signals["operator_requirements_present"]:
            score += _DRAFT_READINESS_SCORE_OPERATOR_REQUIREMENTS
        if signals["enriched_content_present"]:
            score += _DRAFT_READINESS_SCORE_ENRICHED_CONTENT
        if signals["audit_available"]:
            score += _DRAFT_READINESS_SCORE_AUDIT
        if signals["recommendations_available"]:
            score += _DRAFT_READINESS_SCORE_RECOMMENDATIONS
        if signals["competitors_available"]:
            score += _DRAFT_READINESS_SCORE_COMPETITORS
        if (
            signals["source_site_ingested"]
            and signals["operator_requirements_present"]
            and signals["enriched_content_present"]
            and signals["audit_available"]
            and signals["recommendations_available"]
            and signals["competitors_available"]
        ):
            score += _DRAFT_READINESS_COMPLETENESS_BONUS
        bounded_score = min(100, max(0, int(score)))
        hard_blocked = bool(blocking_reasons)
        if hard_blocked:
            status = "not_ready"
        elif bounded_score >= 80:
            status = "ready"
        else:
            status = "ready_with_warnings"
        reason_payload = [*blocking_reasons, *warning_reasons]
        summary = self._build_draft_readiness_summary(
            status=status,
            blocking_codes=[item.code for item in blocking_reasons],
        )
        payload: dict[str, object] = {
            "status": status,
            "score": bounded_score,
            "hard_blocked": hard_blocked,
            "summary": summary,
            "reasons": [item.to_payload() for item in reason_payload],
            "signals": signals,
        }
        if emit_log:
            self._log_draft_readiness_evaluation(
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace.id,
                readiness_status=status,
                readiness_score=bounded_score,
                hard_blocked=hard_blocked,
                blocking_reason_codes=[item.code for item in blocking_reasons],
                warning_reason_codes=[item.code for item in warning_reasons],
            )
        return payload

    @staticmethod
    def _build_draft_readiness_summary(*, status: str, blocking_codes: list[str]) -> str:
        if status == "ready":
            return "Ready to generate draft."
        if status == "ready_with_warnings":
            return "Ready, but draft quality may be limited."
        blocking = set(blocking_codes)
        if (
            _DRAFT_READINESS_REASON_OPERATOR_REQUIRED in blocking
            and _DRAFT_READINESS_REASON_ENRICHED_REQUIRED in blocking
        ):
            return "Not ready yet — add operator requirements and enriched replacement content first."
        if _DRAFT_READINESS_REASON_OPERATOR_REQUIRED in blocking:
            return "Not ready yet — add operator requirements first."
        if _DRAFT_READINESS_REASON_ENRICHED_REQUIRED in blocking:
            return "Not ready yet — add enriched replacement content first."
        if _DRAFT_READINESS_REASON_SOURCE_REQUIRED in blocking:
            return "Not ready yet — run source ingest first."
        if _DRAFT_READINESS_REASON_PROVIDER_CONFIG_REQUIRED in blocking:
            return "Not ready yet — check AI provider configuration."
        return "Not ready yet — resolve blocking migration readiness issues before generating a draft."

    @staticmethod
    def _is_sparse_enriched_content(value: object) -> bool:
        payload = _normalize_json_dict(value)
        if not payload:
            return True
        text_keys = (
            "replacement_summary",
            "homepage_value_proposition",
            "about_business",
            "additional_notes",
        )
        text_signal_count = 0
        for key in text_keys:
            text = _normalize_string(payload.get(key), max_length=8000)
            if text and len(text) >= 40:
                text_signal_count += 1
        list_signal_count = 0
        for key in ("service_highlights", "trust_signals", "faq_items"):
            items = payload.get(key)
            if isinstance(items, list) and any(_normalize_string(item, max_length=240) for item in items):
                list_signal_count += 1
        contact_overrides = _normalize_json_dict(payload.get("contact_overrides"))
        aggregate_signal = text_signal_count + min(2, list_signal_count) + (1 if contact_overrides else 0)
        return aggregate_signal < 2

    def _log_draft_readiness_evaluation(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        readiness_status: str,
        readiness_score: int,
        hard_blocked: bool,
        blocking_reason_codes: list[str],
        warning_reason_codes: list[str],
    ) -> None:
        payload: dict[str, object] = {
            "event": _MIGRATION_READINESS_LOG_EVENT,
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "migration_workspace_id": workspace_id,
            "readiness_status": _normalize_string(readiness_status, max_length=40),
            "readiness_score": max(0, int(readiness_score)),
            "hard_blocked": bool(hard_blocked),
            "blocking_reason_codes": [item for item in blocking_reason_codes if item],
            "warning_reason_codes": [item for item in warning_reason_codes if item],
        }
        level = logging.WARNING if hard_blocked else logging.INFO
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_MIGRATION_READINESS_LOG_EVENT,
            level=level,
        )

    def _evaluate_draft_provider_compatibility(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str,
        emit_log: bool,
        model_requested: str | None = None,
        model_resolved: str | None = None,
    ) -> SEOMigrationProviderCompatibilityResult:
        compatibility_error_type: str | None = None
        try:
            raw_result = self.artifact_provider.evaluate_compatibility()
        except Exception as exc:  # noqa: BLE001
            compatibility_error_type = type(exc).__name__
            raw_result = SEOMigrationProviderCompatibilityResult(
                supported=False,
                reason_code="unknown_provider_capability",
                operator_message="The current AI configuration does not support migration draft generation.",
                admin_summary="compatibility_evaluation_failed",
                retryable=False,
                provider_name=self.provider_name,
                model_name=self.provider_model_name,
                endpoint_path=None,
                execution_mode="full",
                web_search_enabled=False,
                degraded_mode=False,
                response_format_mode=None,
                request_body_mode=None,
            )
        compatibility = self._normalize_draft_provider_compatibility_result(raw_result)
        if emit_log:
            self._log_draft_provider_compatibility_evaluation(
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace_id,
                compatibility=compatibility,
                error_type=compatibility_error_type,
                model_requested=model_requested,
                model_resolved=model_resolved,
            )
        return compatibility

    def _normalize_draft_provider_compatibility_result(
        self,
        result: SEOMigrationProviderCompatibilityResult,
    ) -> SEOMigrationProviderCompatibilityResult:
        supported = bool(result.supported)
        raw_reason_code = _normalize_string(result.reason_code, max_length=80)
        if supported:
            reason_code = "supported"
        elif raw_reason_code in _DRAFT_PROVIDER_COMPAT_REASON_CODES:
            reason_code = raw_reason_code
        else:
            reason_code = "unknown_provider_capability"
        if reason_code == "supported" and not supported:
            reason_code = "unknown_provider_capability"

        provider_name = _normalize_string(result.provider_name, max_length=64) or self.provider_name
        model_name = _normalize_string(result.model_name, max_length=128) or self.provider_model_name
        endpoint_path = _normalize_string(result.endpoint_path, max_length=120)
        execution_mode = _normalize_string(result.execution_mode, max_length=40) or "full"
        response_format_mode = _normalize_string(result.response_format_mode, max_length=60)
        request_body_mode = _normalize_string(result.request_body_mode, max_length=80)
        web_search_enabled = result.web_search_enabled if isinstance(result.web_search_enabled, bool) else False
        degraded_mode = result.degraded_mode if isinstance(result.degraded_mode, bool) else False
        retryable = result.retryable if isinstance(result.retryable, bool) else False
        operator_message = _normalize_string(result.operator_message, max_length=320)
        if operator_message is None:
            operator_message = self._default_draft_provider_compatibility_message(reason_code=reason_code)
        admin_summary = _normalize_string(result.admin_summary, max_length=240) or reason_code
        return SEOMigrationProviderCompatibilityResult(
            supported=supported,
            reason_code=reason_code,
            operator_message=operator_message,
            admin_summary=admin_summary,
            retryable=retryable,
            provider_name=provider_name,
            model_name=model_name,
            endpoint_path=endpoint_path,
            execution_mode=execution_mode,
            web_search_enabled=web_search_enabled,
            degraded_mode=degraded_mode,
            response_format_mode=response_format_mode,
            request_body_mode=request_body_mode,
        )

    @staticmethod
    def _default_draft_provider_compatibility_message(*, reason_code: str) -> str:
        if reason_code == "supported":
            return "AI configuration is compatible with migration draft generation."
        if reason_code == "provider_not_configured":
            return "The current AI configuration does not support migration draft generation."
        if reason_code in {"unsupported_model_configuration", "unsupported_request_shape", "unsupported_endpoint_mode"}:
            return "This model/provider setup is not compatible with the current migration request settings."
        if reason_code in {"tools_required_but_unavailable", "degraded_mode_not_allowed"}:
            return "Full AI capability is required for migration draft generation."
        return "The current AI configuration does not support migration draft generation."

    @staticmethod
    def _serialize_draft_provider_compatibility(
        *,
        compatibility: SEOMigrationProviderCompatibilityResult,
    ) -> dict[str, object]:
        return {
            "supported": bool(compatibility.supported),
            "reason_code": compatibility.reason_code,
            "operator_message": compatibility.operator_message,
            "retryable": bool(compatibility.retryable),
            "provider_name": compatibility.provider_name,
            "model_name": compatibility.model_name,
            "endpoint_path": compatibility.endpoint_path,
            "execution_mode": compatibility.execution_mode,
            "web_search_enabled": bool(compatibility.web_search_enabled),
            "degraded_mode": bool(compatibility.degraded_mode),
            "response_format_mode": compatibility.response_format_mode,
            "request_body_mode": compatibility.request_body_mode,
            "admin_summary": compatibility.admin_summary,
        }

    def _log_draft_provider_compatibility_evaluation(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str,
        compatibility: SEOMigrationProviderCompatibilityResult,
        error_type: str | None = None,
        model_requested: str | None = None,
        model_resolved: str | None = None,
    ) -> None:
        compatibility_decision = "allowed" if compatibility.supported else "blocked_local_preflight"
        payload: dict[str, object] = {
            "event": _DRAFT_PROVIDER_COMPATIBILITY_LOG_EVENT,
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "migration_workspace_id": workspace_id,
            "provider_name": compatibility.provider_name,
            "model": compatibility.model_name,
            "endpoint_path": compatibility.endpoint_path,
            "execution_mode": compatibility.execution_mode,
            "web_search_enabled": bool(compatibility.web_search_enabled),
            "degraded_mode": bool(compatibility.degraded_mode),
            "response_format_mode": compatibility.response_format_mode,
            "request_body_mode": compatibility.request_body_mode,
            "supported": bool(compatibility.supported),
            "reason_code": compatibility.reason_code,
            "retryable": bool(compatibility.retryable),
            "decision": compatibility_decision,
            "compatibility_decision": compatibility_decision,
            "failure_source": (None if compatibility.supported else "local_preflight"),
            "model_requested": _normalize_string(model_requested, max_length=128),
            "model_resolved": _normalize_string(model_resolved, max_length=128),
            "model_used": _normalize_string(
                compatibility.model_name if compatibility.supported else model_resolved,
                max_length=128,
            ),
            "timeout_seconds": max(1, int(self._resolved_migration_draft_timeout_seconds)),
            "timeout_source": (
                self._resolved_migration_draft_timeout_source
                if self._resolved_migration_draft_timeout_source in {"admin", "default"}
                else "default"
            ),
            "error_type": _normalize_string(error_type, max_length=80),
        }
        level = logging.INFO if compatibility.supported else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_DRAFT_PROVIDER_COMPATIBILITY_LOG_EVENT,
            level=level,
        )

    def _draft_failure_from_provider_compatibility(
        self,
        *,
        compatibility: SEOMigrationProviderCompatibilityResult,
        prompt_version: str,
        draft_run_id: str,
    ) -> SEOMigrationDraftFailure:
        reason_code = (
            compatibility.reason_code
            if compatibility.reason_code in _DRAFT_PROVIDER_COMPAT_REASON_CODES
            else "unknown_provider_capability"
        )
        failure_category = "config_missing"
        failure_reason = "unsupported_configuration"
        if reason_code == "unknown_provider_capability":
            failure_category = "unknown_error"
            failure_reason = "unknown"
        return SEOMigrationDraftFailure(
            failure_category=failure_category,
            failure_reason=failure_reason,
            error_code=reason_code,
            message_for_operator=(
                _normalize_string(compatibility.operator_message, max_length=400)
                or "The current AI configuration does not support migration draft generation."
            ),
            retryable=compatibility.retryable if isinstance(compatibility.retryable, bool) else False,
            provider_name=_normalize_string(compatibility.provider_name, max_length=64) or self.provider_name,
            model_name=_normalize_string(compatibility.model_name, max_length=128) or self.provider_model_name,
            prompt_version=_normalize_string(prompt_version, max_length=64) or self.prompt_version,
            correlation_id=_normalize_string(draft_run_id, max_length=120),
            endpoint_path=_normalize_string(compatibility.endpoint_path, max_length=120),
            execution_mode=_normalize_string(compatibility.execution_mode, max_length=40),
            response_format_mode=_normalize_string(compatibility.response_format_mode, max_length=60),
            request_body_mode=_normalize_string(compatibility.request_body_mode, max_length=80),
            compatibility_reason_code=reason_code,
        )

    def _record_failed_draft_generation(
        self,
        *,
        workspace: SEOMigrationWorkspace,
        site: SEOSite,
        context_json: dict[str, object],
        draft_run_id: str,
        failure: SEOMigrationDraftFailure,
        principal_id: str | None,
        model_requested: str | None = None,
        model_resolved: str | None = None,
        model_used: str | None = None,
        failure_source: str | None = None,
        duration_ms: int | None = None,
        timeout_seconds: int | None = None,
        timeout_source: str | None = None,
    ) -> SEOMigrationArtifactVersion:
        artifact_version_number = self.seo_migration_repository.next_artifact_version_number(workspace.id)
        failure_context = self._build_draft_failure_context(
            context_json=context_json,
            draft_run_id=draft_run_id,
            failure=failure,
            model_requested=model_requested,
            model_resolved=model_resolved,
            model_used=model_used,
            failure_source=failure_source,
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            timeout_source=timeout_source,
        )
        artifact = SEOMigrationArtifactVersion(
            id=str(uuid4()),
            business_id=workspace.business_id,
            site_id=workspace.site_id,
            workspace_id=workspace.id,
            version=artifact_version_number,
            status="failed",
            context_json=failure_context,
            strategy_summary=None,
            page_map_json=[],
            homepage_structure_json=[],
            service_page_suggestions_json=[],
            cta_contact_structure_json={},
            seo_meta_suggestions_json={},
            redirect_suggestions_json=[],
            analytics_placeholders_json=[],
            generated_files_json=[],
            artifact_quality_evaluation_json=None,
            file_count=0,
            total_bytes=0,
            provider_name=failure.provider_name,
            model_name=failure.model_name,
            prompt_version=failure.prompt_version,
            parse_warnings_json=[
                f"draft_generation_failure_reason={failure.failure_reason}",
                f"draft_generation_failure_code={failure.error_code}",
            ],
            error_summary=failure.message_for_operator,
            approval_status="pending",
            publish_status="not_published",
            deploy_status="not_deployed",
            created_by_principal_id=principal_id,
        )
        self.seo_migration_repository.create_artifact_version(artifact)

        workspace.latest_generated_artifact_version_id = artifact.id
        workspace.latest_generated_artifact_version_number = artifact.version
        workspace.migration_status = "draft_generation_failed"
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(artifact)
        return artifact

    def _build_draft_failure_context(
        self,
        *,
        context_json: dict[str, object],
        draft_run_id: str,
        failure: SEOMigrationDraftFailure,
        model_requested: str | None = None,
        model_resolved: str | None = None,
        model_used: str | None = None,
        failure_source: str | None = None,
        duration_ms: int | None = None,
        timeout_seconds: int | None = None,
        timeout_source: str | None = None,
    ) -> dict[str, object]:
        normalized_failure_source = _normalize_string(failure_source, max_length=40)
        if normalized_failure_source not in {"local_preflight", "remote_provider", "local_validation", "unknown"}:
            normalized_failure_source = None
        compatibility_decision = "blocked_local_preflight" if normalized_failure_source == "local_preflight" else "allowed"
        resolved_timeout_seconds = (
            max(1, int(timeout_seconds))
            if isinstance(timeout_seconds, int)
            else max(1, int(self._resolved_migration_draft_timeout_seconds))
        )
        normalized_timeout_source = _normalize_string(timeout_source, max_length=20)
        if normalized_timeout_source not in {"admin", "default"}:
            normalized_timeout_source = (
                self._resolved_migration_draft_timeout_source
                if self._resolved_migration_draft_timeout_source in {"admin", "default"}
                else "default"
            )
        payload = self._build_draft_execution_context(
            context_json=context_json,
            model_requested=model_requested,
            model_resolved=model_resolved,
            model_used=model_used,
            endpoint_path=failure.endpoint_path,
            execution_mode=failure.execution_mode,
            response_format_mode=failure.response_format_mode,
            request_body_mode=failure.request_body_mode,
            compatibility_decision=compatibility_decision,
            failure_source=normalized_failure_source,
            artifact_status="failed",
            duration_ms=duration_ms,
            timeout_seconds=resolved_timeout_seconds,
            timeout_source=normalized_timeout_source,
        )
        payload["draft_generation_failure"] = {
            "failure_category": failure.failure_category,
            "failure_reason": failure.failure_reason,
            "error_code": failure.error_code,
            "message": failure.message_for_operator,
            "retryable": failure.retryable,
            "failure_source": normalized_failure_source,
            "correlation_id": failure.correlation_id or draft_run_id,
            "provider_name": failure.provider_name,
            "model_name": failure.model_name,
            "prompt_version": failure.prompt_version,
            "endpoint_path": _normalize_string(failure.endpoint_path, max_length=120),
            "execution_mode": _normalize_string(failure.execution_mode, max_length=40),
            "response_format_mode": _normalize_string(failure.response_format_mode, max_length=60),
            "request_body_mode": _normalize_string(failure.request_body_mode, max_length=80),
            "compatibility_reason_code": _normalize_string(failure.compatibility_reason_code, max_length=80),
            "model_requested": _normalize_string(model_requested, max_length=128),
            "model_resolved": _normalize_string(model_resolved, max_length=128),
            "model_used": _normalize_string(model_used, max_length=128),
            "timeout_seconds": resolved_timeout_seconds,
            "timeout_source": normalized_timeout_source,
            "recorded_at": utc_now().isoformat(),
        }
        return payload

    @staticmethod
    def _build_draft_execution_context(
        *,
        context_json: dict[str, object],
        model_requested: str | None,
        model_resolved: str | None,
        model_used: str | None,
        endpoint_path: str | None,
        execution_mode: str | None,
        response_format_mode: str | None,
        request_body_mode: str | None,
        compatibility_decision: str | None,
        failure_source: str | None,
        artifact_status: str | None = None,
        duration_ms: int | None = None,
        timeout_seconds: int | None = None,
        timeout_source: str | None = None,
    ) -> dict[str, object]:
        normalized_failure_source = _normalize_string(failure_source, max_length=40)
        if normalized_failure_source not in {"local_preflight", "remote_provider", "local_validation", "unknown"}:
            normalized_failure_source = None
        normalized_compatibility_decision = _normalize_string(compatibility_decision, max_length=40)
        if normalized_compatibility_decision not in {"allowed", "blocked_local_preflight"}:
            normalized_compatibility_decision = None
        normalized_artifact_status = _normalize_string(artifact_status, max_length=40)
        if normalized_artifact_status not in {"completed", "partial", "failed"}:
            normalized_artifact_status = None
        normalized_timeout_source = _normalize_string(timeout_source, max_length=20)
        if normalized_timeout_source not in {"admin", "default"}:
            normalized_timeout_source = None
        normalized_timeout_seconds = max(1, int(timeout_seconds)) if isinstance(timeout_seconds, int) else None
        normalized_duration_ms = max(0, int(duration_ms)) if isinstance(duration_ms, int) else None
        artifact_result = SEOMigrationService._artifact_result_from_status(normalized_artifact_status)
        request_contract_status = SEOMigrationService._derive_request_contract_status(
            compatibility_decision=normalized_compatibility_decision,
            failure_source=normalized_failure_source,
            artifact_status=normalized_artifact_status,
        )
        provider_execution_status = SEOMigrationService._derive_provider_execution_status(
            compatibility_decision=normalized_compatibility_decision,
            failure_source=normalized_failure_source,
            artifact_status=normalized_artifact_status,
        )
        payload = _normalize_json_dict(context_json)
        payload["draft_generation_execution"] = {
            "model_requested": _normalize_string(model_requested, max_length=128),
            "model_resolved": _normalize_string(model_resolved, max_length=128),
            "model_used": _normalize_string(model_used, max_length=128),
            "endpoint_path": _normalize_string(endpoint_path, max_length=120),
            "execution_mode": _normalize_string(execution_mode, max_length=40),
            "response_format_mode": _normalize_string(response_format_mode, max_length=60),
            "request_body_mode": _normalize_string(request_body_mode, max_length=80),
            "compatibility_decision": normalized_compatibility_decision,
            "failure_source": normalized_failure_source,
            "request_contract_status": request_contract_status,
            "provider_execution_status": provider_execution_status,
            "artifact_status": normalized_artifact_status,
            "artifact_result": artifact_result,
            "duration_ms": normalized_duration_ms,
            "timeout_seconds": normalized_timeout_seconds,
            "timeout_source": normalized_timeout_source,
            "recorded_at": utc_now().isoformat(),
        }
        return payload

    @staticmethod
    def _artifact_result_from_status(status: str | None) -> str | None:
        if status == "completed":
            return "succeeded"
        if status == "partial":
            return "partial"
        if status == "failed":
            return "failed"
        return None

    @staticmethod
    def _derive_request_contract_status(
        *,
        compatibility_decision: str | None,
        failure_source: str | None,
        artifact_status: str | None,
    ) -> str | None:
        if compatibility_decision == "blocked_local_preflight":
            return "blocked"
        if artifact_status == "completed":
            return "accepted"
        if artifact_status == "partial":
            return "accepted_with_warnings"
        if artifact_status == "failed":
            if failure_source in {"remote_provider", "local_validation", "unknown"}:
                return "rejected"
            return "rejected"
        return None

    @staticmethod
    def _derive_provider_execution_status(
        *,
        compatibility_decision: str | None,
        failure_source: str | None,
        artifact_status: str | None,
    ) -> str | None:
        if compatibility_decision == "blocked_local_preflight":
            return "not_called"
        if artifact_status in {"completed", "partial"}:
            return "accepted"
        if artifact_status == "failed":
            if failure_source == "remote_provider":
                return "rejected"
            if failure_source == "local_validation":
                return "accepted"
            if failure_source == "unknown":
                return "unknown"
            return "unknown"
        return None

    def _classify_draft_provider_failure(self, error: SEOMigrationArtifactProviderError) -> SEOMigrationDraftFailure:
        reason = self._normalize_draft_failure_reason(error.reason or error.code)
        category = "provider_error"
        retryable = error.retryable if isinstance(error.retryable, bool) else None
        details = error.internal_details or {}
        if reason == "timeout":
            category = "config_missing"
            retryable = True
        elif reason in {"authentication_failed", "unsupported_configuration"}:
            category = "config_missing"
            if retryable is None:
                retryable = False
        elif reason in {"malformed_response", "malformed_output", "empty_response", "validation_failed"}:
            category = "artifact_invalid"
            if retryable is None:
                retryable = True
        elif reason == "unknown":
            category = "unknown_error"
        elif retryable is None:
            retryable = reason in {"timeout", "rate_limited", "transport_error"}

        normalized_code = _normalize_string(error.code, max_length=80) or reason
        message = _normalize_string(error.safe_message, max_length=400) or "Migration draft provider request failed."
        provider_name = _normalize_string(error.provider_name, max_length=64) or self.provider_name
        model_name = _normalize_string(error.model_name, max_length=128) or self.provider_model_name
        prompt_version = _normalize_string(error.prompt_version, max_length=64) or self.prompt_version
        return SEOMigrationDraftFailure(
            failure_category=category,
            failure_reason=reason,
            error_code=normalized_code,
            message_for_operator=message,
            retryable=retryable,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
            correlation_id=_normalize_string(error.correlation_id, max_length=120),
            endpoint_path=_normalize_string(details.get("endpoint_path"), max_length=120),
            execution_mode=_normalize_string(details.get("execution_mode"), max_length=40),
            response_format_mode=_normalize_string(details.get("response_format_mode"), max_length=60),
            request_body_mode=_normalize_string(details.get("request_body_mode"), max_length=80),
        )

    @staticmethod
    def _unknown_draft_failure(
        *,
        provider_name: str,
        model_name: str,
        prompt_version: str,
    ) -> SEOMigrationDraftFailure:
        return SEOMigrationDraftFailure(
            failure_category="unknown_error",
            failure_reason="unknown",
            error_code="unknown",
            message_for_operator="Migration draft generation failed due to an unexpected provider error.",
            retryable=None,
            provider_name=provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
        )

    @staticmethod
    def _normalize_draft_failure_reason(value: str | None) -> str:
        normalized = _normalize_string(value, max_length=80) or "unknown"
        if normalized not in _DRAFT_FAILURE_REASON_VALUES:
            return "unknown"
        return normalized

    def _provider_model_fallback_name(self) -> str | None:
        runtime_provider_model = _normalize_string(getattr(self.artifact_provider, "model_name", None), max_length=128)
        return runtime_provider_model or self._configured_provider_model_name

    def _resolve_migration_model_name(self, business: Business, *, requested_model_name: str | None = None) -> str:
        resolved = resolve_ai_model_name(
            requested_model_name=requested_model_name,
            admin_default_model_name=getattr(business, "default_ai_model", None),
            env_default_model_name=self._env_default_model_name,
            provider_fallback_model_name=self._provider_model_fallback_name(),
        )
        return resolved.model_name

    def _resolve_migration_draft_timeout_seconds(self, business: Business) -> tuple[int, str]:
        configured_timeout = getattr(business, "migration_draft_timeout_seconds", None)
        try:
            parsed_timeout = int(configured_timeout) if configured_timeout is not None else None
        except (TypeError, ValueError):
            parsed_timeout = None
        if (
            parsed_timeout is not None
            and _MIGRATION_DRAFT_TIMEOUT_MIN_SECONDS <= parsed_timeout <= _MIGRATION_DRAFT_TIMEOUT_MAX_SECONDS
        ):
            return parsed_timeout, "admin"
        return _MIGRATION_DRAFT_TIMEOUT_DEFAULT_SECONDS, "default"

    def _apply_resolved_migration_model_settings(
        self,
        business: Business,
        *,
        requested_model_name: str | None = None,
    ) -> str:
        model_name = self._resolve_migration_model_name(business, requested_model_name=requested_model_name)
        self.provider_model_name = model_name
        if hasattr(self.artifact_provider, "model_name"):
            setattr(self.artifact_provider, "model_name", model_name)
        timeout_seconds, timeout_source = self._resolve_migration_draft_timeout_seconds(business)
        self._resolved_migration_draft_timeout_seconds = timeout_seconds
        self._resolved_migration_draft_timeout_source = timeout_source
        if hasattr(self.artifact_provider, "timeout_seconds"):
            try:
                setattr(self.artifact_provider, "timeout_seconds", max(1, int(timeout_seconds)))
            except (TypeError, ValueError):
                setattr(self.artifact_provider, "timeout_seconds", _MIGRATION_DRAFT_TIMEOUT_DEFAULT_SECONDS)
        try:
            setattr(self.artifact_provider, "timeout_source", timeout_source)
        except Exception:  # noqa: BLE001
            pass
        return model_name

    def _require_business(self, business_id: str) -> Business:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEOMigrationNotFoundError("Business not found")
        self._apply_resolved_migration_model_settings(business)
        return business

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

        recommendation_page = self.seo_recommendation_repository.list_recommendations_page_for_business_site(
            business_id=site.business_id,
            site_id=site.id,
            page=1,
            page_size=1,
            sort_by="created_at",
            sort_order="desc",
        )
        latest_recommendation = recommendation_page.items[0] if recommendation_page.items else None
        recommendation_count = max(0, int(recommendation_page.total))

        latest_usable_comparison_run = next(
            (item for item in comparison_runs if self._is_usable_comparison_run(item)),
            None,
        )
        competitor_domains = self.seo_competitor_repository.list_domains_for_business_site(site.business_id, site.id)
        active_competitor_domains = [
            item for item in competitor_domains if getattr(item, "is_active", None) is not False
        ]

        reused_context = self._build_reused_context_summary(
            latest_audit_run=latest_audit_run,
            latest_completed_recommendation_run=latest_completed_recommendation_run,
            latest_recommendation_narrative=latest_recommendation_narrative,
            recommendation_count=recommendation_count,
            latest_recommendation_created_at=(
                latest_recommendation.created_at if latest_recommendation is not None else None
            ),
            latest_usable_comparison_run=latest_usable_comparison_run,
            active_competitor_domain_count=len(active_competitor_domains),
            latest_competitor_domain_created_at=(
                active_competitor_domains[-1].created_at if active_competitor_domains else None
            ),
        )

        assembly = self.context_assembler.assemble(
            site=site,
            workspace=workspace,
            latest_audit_summary=latest_audit_summary,
            latest_recommendation_narrative=latest_recommendation_narrative,
            latest_competitor_summary=latest_competitor_summary,
            reused_context=reused_context,
        )
        self._log_migration_context_summary(
            business_id=site.business_id,
            site_id=site.id,
            workspace_id=workspace.id,
            reused_context=reused_context,
        )
        return assembly.context_json, assembly.context_summary

    @staticmethod
    def _is_usable_comparison_run(run: object) -> bool:
        status = _normalize_string(getattr(run, "status", None), max_length=32) or ""
        if status == "completed":
            return True
        total_findings = max(0, int(getattr(run, "total_findings", 0) or 0))
        competitor_pages = max(0, int(getattr(run, "competitor_pages_analyzed", 0) or 0))
        client_pages = max(0, int(getattr(run, "client_pages_analyzed", 0) or 0))
        return total_findings > 0 or competitor_pages > 0 or client_pages > 0

    def _build_reused_context_summary(
        self,
        *,
        latest_audit_run: object | None,
        latest_completed_recommendation_run: object | None,
        latest_recommendation_narrative: object | None,
        recommendation_count: int,
        latest_recommendation_created_at: object | None,
        latest_usable_comparison_run: object | None,
        active_competitor_domain_count: int,
        latest_competitor_domain_created_at: object | None,
    ) -> dict[str, object]:
        audit_available = latest_audit_run is not None
        audit_timestamp = self._format_timestamp(
            getattr(latest_audit_run, "completed_at", None) or getattr(latest_audit_run, "created_at", None)
        )
        recommendation_narrative_available = bool(
            _normalize_string(getattr(latest_recommendation_narrative, "narrative_text", None), max_length=120)
        )
        recommendation_available = (
            recommendation_count > 0
            or recommendation_narrative_available
            or latest_completed_recommendation_run is not None
        )
        recommendation_timestamp = self._format_timestamp(
            latest_recommendation_created_at
            or getattr(latest_recommendation_narrative, "created_at", None)
            or getattr(latest_completed_recommendation_run, "completed_at", None)
            or getattr(latest_completed_recommendation_run, "created_at", None)
        )
        recommendation_total = (
            recommendation_count
            if recommendation_count > 0
            else max(0, int(getattr(latest_completed_recommendation_run, "total_recommendations", 0) or 0))
        )

        competitor_available = latest_usable_comparison_run is not None or active_competitor_domain_count > 0
        competitor_source = "latest_run" if latest_usable_comparison_run is not None else "active_domains"
        competitor_timestamp = self._format_timestamp(
            (
                getattr(latest_usable_comparison_run, "completed_at", None)
                or getattr(latest_usable_comparison_run, "created_at", None)
            )
            if latest_usable_comparison_run is not None
            else latest_competitor_domain_created_at
        )
        competitor_count = (
            max(0, int(getattr(latest_usable_comparison_run, "total_findings", 0) or 0))
            if latest_usable_comparison_run is not None
            else max(0, int(active_competitor_domain_count))
        )

        return {
            "audit": {
                "available": audit_available,
                "source": "latest_successful_run" if audit_available else "none",
                "run_id": getattr(latest_audit_run, "id", None) if audit_available else None,
                "timestamp": audit_timestamp,
            },
            "recommendations": {
                "available": recommendation_available,
                "source": ("latest_generated" if recommendation_available else "none"),
                "run_id": (
                    getattr(latest_completed_recommendation_run, "id", None)
                    if latest_completed_recommendation_run is not None
                    else None
                ),
                "timestamp": recommendation_timestamp,
                "count": recommendation_total,
            },
            "competitors": {
                "available": competitor_available,
                "source": competitor_source if competitor_available else "none",
                "run_id": (
                    getattr(latest_usable_comparison_run, "id", None)
                    if latest_usable_comparison_run is not None
                    else None
                ),
                "timestamp": competitor_timestamp,
                "count": competitor_count,
            },
        }

    @staticmethod
    def _format_timestamp(value: object | None) -> str | None:
        if value is None:
            return None
        iso = getattr(value, "isoformat", None)
        if callable(iso):
            try:
                return str(iso())
            except Exception:
                return None
        normalized = _normalize_string(value, max_length=80)
        return normalized or None

    def _log_migration_context_summary(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        reused_context: dict[str, object],
    ) -> None:
        audit = _normalize_json_dict(reused_context.get("audit"))
        recommendations = _normalize_json_dict(reused_context.get("recommendations"))
        competitors = _normalize_json_dict(reused_context.get("competitors"))
        payload: dict[str, object] = {
            "event": "migration_context_summary",
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "audit_available": bool(audit.get("available")),
            "recommendation_available": bool(recommendations.get("available")),
            "competitor_available": bool(competitors.get("available")),
            "audit_source": _normalize_string(audit.get("source"), max_length=80),
            "recommendation_source": _normalize_string(recommendations.get("source"), max_length=80),
            "competitor_source": _normalize_string(competitors.get("source"), max_length=80),
        }
        self._emit_structured_service_log(
            payload=payload,
            fallback_message="migration_context_summary",
            level=logging.INFO,
        )

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

    def _log_draft_generation_event(
        self,
        *,
        status: str,
        business_id: str,
        site_id: str,
        workspace_id: str,
        draft_run_id: str,
        artifact_version_id: str | None = None,
        artifact_version: int | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        prompt_version: str | None = None,
        failure_category: str | None = None,
        failure_reason: str | None = None,
        retryable: bool | None = None,
        correlation_id: str | None = None,
        duration_ms: int | None = None,
        error_type: str | None = None,
        model_requested: str | None = None,
        model_resolved: str | None = None,
        model_used: str | None = None,
        endpoint_path: str | None = None,
        execution_mode: str | None = None,
        response_format_mode: str | None = None,
        request_body_mode: str | None = None,
        compatibility_decision: str | None = None,
        failure_source: str | None = None,
        timeout_seconds: int | None = None,
        timeout_source: str | None = None,
    ) -> None:
        normalized_status = _normalize_string(status, max_length=40) or "unknown"
        normalized_failure_source = _normalize_string(failure_source, max_length=40)
        if normalized_failure_source not in {"local_preflight", "remote_provider", "local_validation", "unknown"}:
            normalized_failure_source = None
        normalized_compatibility_decision = _normalize_string(compatibility_decision, max_length=40)
        if normalized_compatibility_decision not in {"allowed", "blocked_local_preflight"}:
            normalized_compatibility_decision = None
        normalized_timeout_source = _normalize_string(timeout_source, max_length=20)
        if normalized_timeout_source not in {"admin", "default"}:
            normalized_timeout_source = (
                self._resolved_migration_draft_timeout_source
                if self._resolved_migration_draft_timeout_source in {"admin", "default"}
                else "default"
            )
        normalized_timeout_seconds = (
            max(1, int(timeout_seconds))
            if isinstance(timeout_seconds, int)
            else max(1, int(self._resolved_migration_draft_timeout_seconds))
        )
        payload: dict[str, object] = {
            "event": _DRAFT_PROVIDER_LOG_EVENT,
            "timestamp": utc_now().isoformat(),
            "status": normalized_status,
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "draft_run_id": draft_run_id,
            "artifact_version_id": artifact_version_id,
            "artifact_version": artifact_version,
            "provider_name": _normalize_string(provider_name, max_length=64),
            "model_name": _normalize_string(model_name, max_length=128),
            "prompt_version": _normalize_string(prompt_version, max_length=64),
            "failure_category": (failure_category if failure_category in _MIGRATION_FAILURE_CATEGORY_VALUES else None),
            "failure_reason": (failure_reason if failure_reason in _DRAFT_FAILURE_REASON_VALUES else None),
            "retryable": retryable if isinstance(retryable, bool) else None,
            "correlation_id": _normalize_string(correlation_id, max_length=120),
            "duration_ms": max(0, int(duration_ms)) if duration_ms is not None else None,
            "error_type": _normalize_string(error_type, max_length=60),
            "model_requested": _normalize_string(model_requested, max_length=128),
            "model_resolved": _normalize_string(model_resolved, max_length=128),
            "model_used": _normalize_string(model_used, max_length=128),
            "endpoint_path": _normalize_string(endpoint_path, max_length=120),
            "execution_mode": _normalize_string(execution_mode, max_length=40),
            "response_format_mode": _normalize_string(response_format_mode, max_length=60),
            "request_body_mode": _normalize_string(request_body_mode, max_length=80),
            "compatibility_decision": normalized_compatibility_decision,
            "failure_source": normalized_failure_source,
            "timeout_seconds": normalized_timeout_seconds,
            "timeout_source": normalized_timeout_source,
        }
        level = logging.INFO if normalized_status not in {"failed", "error"} else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_DRAFT_PROVIDER_LOG_EVENT,
            level=level,
        )

    def _log_draft_contract_evaluation(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str,
        draft_run_id: str,
        provider_name: str,
        model_name: str,
        evaluation: AIResponseContractEvaluation,
    ) -> None:
        payload: dict[str, object] = {
            "event": _DRAFT_CONTRACT_EVALUATION_LOG_EVENT,
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "draft_run_id": draft_run_id,
            "provider_name": _normalize_string(provider_name, max_length=64),
            "model_name": _normalize_string(model_name, max_length=128),
            "evaluation_status": _normalize_string(evaluation.status, max_length=40),
            "evaluation_score": max(0, int(evaluation.score)),
            "reason_codes": list(evaluation.reasons),
            "warning_codes": list(evaluation.warnings),
            "valid_item_count": max(0, int(evaluation.valid_item_count)),
            "dropped_item_count": max(0, int(evaluation.dropped_item_count)),
            "required_fields_present": bool(evaluation.required_fields_present),
            "retryable": evaluation.retryable if isinstance(evaluation.retryable, bool) else None,
        }
        level = logging.INFO if evaluation.status != "rejected" else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_DRAFT_CONTRACT_EVALUATION_LOG_EVENT,
            level=level,
        )

    @staticmethod
    def _draft_contract_warnings(*, evaluation: AIResponseContractEvaluation) -> list[str]:
        warnings: list[str] = []
        if evaluation.status == "accepted_with_warnings":
            warnings.append("response_contract_status=accepted_with_warnings")
        elif evaluation.status == "salvaged":
            warnings.append("response_contract_status=salvaged")
        if evaluation.warnings:
            warnings.append("response_contract_warning_codes=" + ",".join(sorted(evaluation.warnings)))
        if evaluation.dropped_item_count > 0:
            warnings.append(f"response_contract_dropped_item_count={max(0, int(evaluation.dropped_item_count))}")
        return warnings

    @staticmethod
    def _draft_contract_rejection_message(*, evaluation: AIResponseContractEvaluation) -> str:
        primary_reason = evaluation.reasons[0] if evaluation.reasons else "validation_failed"
        reason_to_message = {
            "empty_artifact_package": "Migration draft output was empty and could not be used.",
            "missing_required_artifact_files": "Migration draft output did not include required static files.",
            "invalid_artifact_structure": "Migration draft output did not match required static artifact structure.",
            "insufficient_content_density": "Migration draft output was too thin to proceed safely.",
            "validation_failed": "Migration draft output did not satisfy quality contract requirements.",
        }
        return reason_to_message.get(
            primary_reason,
            "Migration draft output did not satisfy quality contract requirements.",
        )

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

    def _log_workflow_provisioned(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        principal_id: str | None,
        provision_result: SEOMigrationGitHubWorkflowProvisionResult,
    ) -> None:
        payload: dict[str, object] = {
            "event": _MIGRATION_WORKFLOW_PROVISIONED_LOG_EVENT,
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "principal_id": principal_id,
            "repo_owner": provision_result.repo_owner,
            "repo_name": provision_result.repo_name,
            "branch": provision_result.branch,
            "workflow_id": provision_result.workflow_id,
            "workflow_path": provision_result.workflow_path,
            "commit_sha": provision_result.commit_sha,
        }
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_MIGRATION_WORKFLOW_PROVISIONED_LOG_EVENT,
            level=logging.INFO,
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

    @staticmethod
    def _normalize_admin_repo_owner(value: object) -> str:
        normalized = _normalize_string(value, max_length=120) or ""
        # Backward compatibility: older admin config rows may still contain owner/repo.
        # Ownership split now treats admin config as owner-only.
        if "/" in normalized:
            normalized = normalized.split("/", 1)[0].strip()
        return normalized

    @staticmethod
    def _is_default_workspace_publish_config(config: dict[str, object]) -> bool:
        return (
            not bool(config.get("enabled"))
            and not str(config.get("repo_name") or "").strip()
            and not str(config.get("branch") or "").strip()
            and not str(config.get("artifact_root") or "").strip()
        )

    def _build_effective_publish_config(
        self,
        *,
        workspace_publish_config: object,
        require_admin: bool,
    ) -> tuple[dict[str, object], dict[str, bool], list[str]]:
        normalized_workspace = _normalize_publish_config(workspace_publish_config)
        effective_config = dict(normalized_workspace)
        prerequisites = {
            "admin_publish_config_present": False,
            "admin_publish_config_enabled": False,
            "admin_publish_config_valid": False,
            "admin_publish_configured": False,
            "operator_repository_configured": False,
        }
        reasons: list[str] = []

        if self.github_publish_config_service is None:
            if require_admin:
                reasons.append("Admin must configure a GitHub publish target before publish is available.")
            return effective_config, prerequisites, reasons

        admin_config = self.github_publish_config_service.get()
        owner = self._normalize_admin_repo_owner(getattr(admin_config, "repository", None))
        default_branch = _normalize_string(getattr(admin_config, "default_branch", None), max_length=120) or "main"
        base_path = _normalize_string(getattr(admin_config, "base_path", None), max_length=160) or "/"
        normalized_artifact_root = base_path.strip().replace("\\", "/").strip("/")
        enabled = bool(getattr(admin_config, "enabled", False))

        prerequisites["admin_publish_config_present"] = bool(owner)
        prerequisites["admin_publish_config_enabled"] = enabled
        if not owner:
            if require_admin:
                reasons.append("Admin must configure a GitHub publish target before publish is available.")
            return effective_config, prerequisites, reasons
        if not enabled:
            if require_admin:
                reasons.append("Admin has disabled GitHub publishing.")
            return effective_config, prerequisites, reasons

        if not _VALID_REPO_OWNER_PATTERN.fullmatch(owner):
            if require_admin:
                reasons.append("Admin GitHub account/owner is invalid.")
            return effective_config, prerequisites, reasons

        prerequisites["admin_publish_config_valid"] = True
        prerequisites["admin_publish_configured"] = True
        effective_config["enabled"] = True
        effective_config["repo_owner"] = owner
        if self._is_default_workspace_publish_config(normalized_workspace):
            effective_config["repo_name"] = ""
        if not str(effective_config.get("branch") or "").strip():
            effective_config["branch"] = default_branch
        if not str(effective_config.get("artifact_root") or "").strip():
            effective_config["artifact_root"] = normalized_artifact_root
        prerequisites["operator_repository_configured"] = bool(str(effective_config.get("repo_name") or "").strip())
        return effective_config, prerequisites, reasons

    def _safe_effective_publish_target_summary(self, config: object) -> dict[str, object]:
        effective, _, _ = self._build_effective_publish_config(
            workspace_publish_config=config,
            require_admin=False,
        )
        return self._safe_publish_target_summary(effective)

    def _safe_deploy_target_summary(self, *, workspace: SEOMigrationWorkspace) -> dict[str, object]:
        normalized = _normalize_deploy_config(workspace.deploy_config_json)
        effective_publish_config, _, _ = self._build_effective_publish_config(
            workspace_publish_config=workspace.publish_config_json,
            require_admin=False,
        )
        fallback_publish = self._safe_publish_target_summary(effective_publish_config)
        return {
            "enabled": bool(normalized.get("enabled")),
            "repo_owner": str(normalized.get("repo_owner") or fallback_publish.get("repo_owner") or "").strip(),
            "repo_name": str(normalized.get("repo_name") or fallback_publish.get("repo_name") or "").strip(),
            "workflow_id": str(normalized.get("workflow_id") or self.deploy_default_workflow_id).strip(),
            "ref": str(normalized.get("ref") or self.deploy_default_ref).strip(),
        }

    def _build_destination_summary(
        self,
        *,
        site: SEOSite,
        workspace: SEOMigrationWorkspace,
        latest_artifact: SEOMigrationArtifactVersion | None,
        publish_readiness: dict[str, object],
        deploy_readiness: dict[str, object],
    ) -> dict[str, object]:
        publish_target = _normalize_json_dict(publish_readiness.get("target"))
        deploy_target = _normalize_json_dict(deploy_readiness.get("target"))
        publish_owner = _normalize_string(publish_target.get("repo_owner"), max_length=80)
        publish_repo = _normalize_string(publish_target.get("repo_name"), max_length=120)
        publish_branch = _normalize_string(publish_target.get("branch"), max_length=120) or "main"
        publish_root = (_normalize_string(publish_target.get("artifact_root"), max_length=120) or "").strip("/")
        publish_repository = (
            f"{publish_owner}/{publish_repo}" if publish_owner and publish_repo else None
        )
        publish_tree_url = self._derive_publish_tree_url(
            repo_owner=publish_owner,
            repo_name=publish_repo,
            branch=publish_branch,
            artifact_root=publish_root,
        )
        publish_root_display = f"/{publish_root}" if publish_root else "/"
        expected_publish_location = (
            f"{publish_repository}@{publish_branch}:{publish_root_display}"
            if publish_repository
            else None
        )

        deploy_url, deploy_url_source = self._resolve_expected_deploy_url(deploy_target=deploy_target)
        deployed_live = bool(workspace.last_deployed_at)
        deploy_state = "unknown"
        if deploy_url and deployed_live:
            deploy_state = "active_live"
        elif deploy_url:
            deploy_state = "expected_after_deploy"

        draft_preview_entry_path = self._derive_preview_entry_path(latest_artifact)
        draft_preview_state = "available" if draft_preview_entry_path else "unavailable"

        return {
            "draft_preview": {
                "state": draft_preview_state,
                "artifact_version_id": latest_artifact.id if latest_artifact is not None else None,
                "artifact_version_number": latest_artifact.version if latest_artifact is not None else None,
                "entry_path": draft_preview_entry_path,
            },
            "publish_destination": {
                "state": "configured" if publish_repository else "unknown",
                "repository": publish_repository,
                "branch": publish_branch if publish_repository else None,
                "artifact_root": publish_root_display if publish_repository else None,
                "expected_location": expected_publish_location,
                "expected_url": publish_tree_url,
                "is_published": bool(workspace.last_published_at),
                "last_published_at": (
                    workspace.last_published_at.isoformat()
                    if hasattr(workspace.last_published_at, "isoformat")
                    else None
                ),
            },
            "deploy_destination": {
                "state": deploy_state,
                "expected_url": deploy_url,
                "active_url": deploy_url if deployed_live else None,
                "url_source": deploy_url_source,
                "is_deployed": deployed_live,
                "last_deployed_at": (
                    workspace.last_deployed_at.isoformat()
                    if hasattr(workspace.last_deployed_at, "isoformat")
                    else None
                ),
                "target_repository": (
                    f"{_normalize_string(deploy_target.get('repo_owner'), max_length=80) or ''}/"
                    f"{_normalize_string(deploy_target.get('repo_name'), max_length=120) or ''}"
                ).strip("/")
                or None,
                "workflow_id": _normalize_string(deploy_target.get("workflow_id"), max_length=160),
                "ref": _normalize_string(deploy_target.get("ref"), max_length=120),
            },
            "current_site_url": _normalize_string(site.base_url, max_length=2048),
        }

    @staticmethod
    def _derive_preview_entry_path(artifact: SEOMigrationArtifactVersion | None) -> str | None:
        if artifact is None:
            return None
        generated_files = artifact.generated_files_json if isinstance(artifact.generated_files_json, list) else []
        html_paths: list[str] = []
        for item in generated_files:
            if not isinstance(item, dict):
                continue
            path = _normalize_generated_path(item.get("path"))
            if path is None:
                continue
            if path.lower().endswith(".html"):
                html_paths.append(path)
        if not html_paths:
            return None
        for candidate in ("index.html", "public/index.html"):
            for path in html_paths:
                if path.lower() == candidate:
                    return path
        html_paths.sort()
        return html_paths[0]

    @staticmethod
    def _derive_publish_tree_url(
        *,
        repo_owner: str | None,
        repo_name: str | None,
        branch: str | None,
        artifact_root: str | None,
    ) -> str | None:
        owner = str(repo_owner or "").strip()
        repo = str(repo_name or "").strip()
        branch_name = str(branch or "").strip()
        if not owner or not repo or not branch_name:
            return None
        root = str(artifact_root or "").strip().strip("/")
        encoded_branch = quote(branch_name, safe="")
        if root:
            return f"https://github.com/{owner}/{repo}/tree/{encoded_branch}/{root}"
        return f"https://github.com/{owner}/{repo}/tree/{encoded_branch}"

    @staticmethod
    def _resolve_expected_deploy_url(*, deploy_target: dict[str, object]) -> tuple[str | None, str]:
        inputs = _normalize_history_inputs(deploy_target.get("inputs"))
        for key in ("deploy_url", "public_url", "site_url", "url"):
            candidate = _normalize_url_candidate(inputs.get(key))
            if candidate:
                return candidate, f"deploy_input:{key}"
        for key in ("host", "domain"):
            candidate = _normalize_host_candidate(inputs.get(key))
            if candidate:
                return candidate, f"deploy_input:{key}"
        return None, "undetermined"

    @staticmethod
    def _runtime_publisher_reason_message(*, reason_code: str, action: str) -> str:
        normalized = str(reason_code or "").strip().lower()
        action_normalized = str(action or "").strip().lower()
        if normalized == _GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING:
            if action_normalized == "deploy":
                return "Platform runtime action required: GitHub deployment credential is unavailable."
            return "Platform runtime action required: GitHub publishing credential is unavailable."
        if normalized == _GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID:
            if action_normalized == "deploy":
                return "Platform runtime action required: GitHub deployment runtime configuration is invalid."
            return "Platform runtime action required: GitHub publishing runtime configuration is invalid."
        if normalized == _GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE:
            if action_normalized == "deploy":
                return "Platform deployment integration is not configured."
            return "Platform runtime action required: GitHub publishing integration is unavailable."
        if action_normalized == "deploy":
            return "Platform/runtime action required: GKE deployment runtime integration is unavailable."
        return "Platform/runtime action required: GitHub migration publisher is not configured."

    def _runtime_publisher_diagnostics(self, *, action: str) -> dict[str, object]:
        if self.github_publisher_configured:
            return {
                "configured": True,
                "reason_code": "",
                "status_message": "",
                "safe_message": "",
            }
        reason_code = self.github_publisher_reason_code or "publisher_not_configured"
        status_message = self.github_publisher_status_message or self._runtime_publisher_reason_message(
            reason_code=reason_code,
            action=action,
        )
        safe_message = self.github_publisher_safe_message or status_message
        return {
            "configured": False,
            "reason_code": reason_code,
            "status_message": status_message,
            "safe_message": safe_message,
        }

    def _log_runtime_publisher_readiness(
        self,
        *,
        action: str,
        workspace: SEOMigrationWorkspace,
        admin_prerequisites: dict[str, bool],
    ) -> None:
        runtime = self._runtime_publisher_diagnostics(action=action)
        if bool(runtime.get("configured")):
            return
        self._emit_structured_service_log(
            payload={
                "event": _MIGRATION_RUNTIME_PUBLISHER_LOG_EVENT,
                "action": action,
                "business_id": workspace.business_id,
                "site_id": workspace.site_id,
                "workspace_id": workspace.id,
                "runtime_publisher_available": False,
                "runtime_publisher_reason_code": str(runtime.get("reason_code") or ""),
                "runtime_publisher_status_message": str(runtime.get("status_message") or ""),
                "admin_publish_configured": bool(admin_prerequisites.get("admin_publish_configured")),
                "admin_publish_config_enabled": bool(admin_prerequisites.get("admin_publish_config_enabled")),
                "operator_repository_configured": bool(admin_prerequisites.get("operator_repository_configured")),
            },
            fallback_message="seo_migration_runtime_publisher_readiness",
            level=logging.INFO,
        )

    @staticmethod
    def _categorize_readiness_failure(*, reasons: object, action: str, blocker_codes: object = None) -> str:
        normalized_blockers = [str(item or "").strip().lower() for item in blocker_codes or [] if str(item or "").strip()]
        if normalized_blockers:
            if _DEPLOY_BLOCKER_CONFIGURATION_INVALID in normalized_blockers:
                return "target_invalid"
            if any(
                code in normalized_blockers
                for code in {
                    _DEPLOY_BLOCKER_CONFIGURATION_MISSING,
                    _DEPLOY_BLOCKER_RUNTIME_UNAVAILABLE,
                    _DEPLOY_BLOCKER_INTEGRATION_UNAVAILABLE,
                }
            ):
                return "config_missing"
            if _DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING in normalized_blockers:
                return "approval_required"
        normalized_reasons = [str(item or "").strip().lower() for item in reasons or [] if str(item or "").strip()]
        if not normalized_reasons:
            return "unknown_error"
        if any(
            "not configured" in reason
            or "configuration" in reason
            or "must configure" in reason
            or ("credential" in reason and "unavailable" in reason)
            or ("integration" in reason and "unavailable" in reason)
            for reason in normalized_reasons
        ):
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
            or "approved artifact is required before publish" in reason
            or "approved artifact is required before deploy" in reason
            or "published artifact is required before deploy" in reason
            or "published yet" in reason
            or "latest published version" in reason
            or "latest published artifact" in reason
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
        if code in {
            "publisher_not_configured",
            _GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING,
            _GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID,
            _GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE,
        }:
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
        blocker_codes: list[str] = []
        target_summary: dict[str, object] = {}
        target_valid = False
        effective_publish_config, admin_prerequisites, admin_reasons = self._build_effective_publish_config(
            workspace_publish_config=workspace.publish_config_json,
            require_admin=True,
        )
        reasons.extend(admin_reasons)
        target_summary = self._safe_publish_target_summary(effective_publish_config)
        if not bool(admin_prerequisites.get("operator_repository_configured")):
            reasons.append("Operator must configure a GitHub repository before publish is available.")
            blocker_codes.append("publish_configuration_missing")
        else:
            try:
                target = _resolve_publish_target(effective_publish_config)
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
                    blocker_codes.append("publish_configuration_missing")
            except ValueError as exc:
                reasons.append(str(exc))
                blocker_codes.append("publish_configuration_invalid")
        if artifact is None:
            reasons.append("An approved artifact is required before publish.")
            blocker_codes.append("publish_artifact_missing")
        else:
            if artifact.approval_status != "approved":
                reasons.append("An approved artifact is required before publish.")
                blocker_codes.append("publish_artifact_missing")
            if artifact.file_count <= 0:
                reasons.append("Selected artifact version has no generated files.")
                blocker_codes.append("publish_artifact_invalid")
        runtime_diagnostics = self._runtime_publisher_diagnostics(action="publish")
        if not bool(runtime_diagnostics.get("configured")):
            reasons.append(str(runtime_diagnostics.get("status_message") or "GitHub migration publisher is not configured."))
            reason_code = str(runtime_diagnostics.get("reason_code") or "").strip().lower()
            if reason_code == _GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE:
                blocker_codes.append("publish_integration_unavailable")
            else:
                blocker_codes.append("publish_runtime_unavailable")
            self._log_runtime_publisher_readiness(
                action="publish",
                workspace=workspace,
                admin_prerequisites=admin_prerequisites,
            )
        failure_category: str | None = None
        if reasons:
            failure_category = self._categorize_readiness_failure(
                reasons=reasons,
                action="publish",
                blocker_codes=blocker_codes,
            )
        return {
            "ready": not reasons,
            "reasons": reasons,
            "blocker_codes": blocker_codes,
            "failure_category": failure_category,
            "target": target_summary,
            "config_prerequisites": {
                "github_publisher_configured": self.github_publisher_configured,
                "github_publisher_reason_code": str(runtime_diagnostics.get("reason_code") or ""),
                "github_publisher_status_message": str(runtime_diagnostics.get("status_message") or ""),
                "publish_runtime_available": bool(runtime_diagnostics.get("configured")),
                "target_config_valid": target_valid,
                "target_enabled": bool(target_summary.get("enabled")),
                **admin_prerequisites,
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
        blocker_codes: list[str] = []
        target_summary: dict[str, object] = {}
        target_valid = False
        effective_publish_config, admin_prerequisites, admin_reasons = self._build_effective_publish_config(
            workspace_publish_config=workspace.publish_config_json,
            require_admin=True,
        )
        reasons.extend(admin_reasons)
        if admin_reasons:
            blocker_codes.append(_DEPLOY_BLOCKER_CONFIGURATION_MISSING)
        if not bool(admin_prerequisites.get("operator_repository_configured")):
            reasons.append("Operator must configure a GitHub repository before publish/deploy is available.")
            blocker_codes.append(_DEPLOY_BLOCKER_CONFIGURATION_MISSING)
        else:
            try:
                target = _resolve_deploy_target(
                    deploy_config=workspace.deploy_config_json,
                    publish_config=effective_publish_config,
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
                    blocker_codes.append(_DEPLOY_BLOCKER_CONFIGURATION_MISSING)
            except ValueError as exc:
                reasons.append(str(exc))
                blocker_codes.append(_DEPLOY_BLOCKER_CONFIGURATION_INVALID)
        if artifact is None:
            reasons.append("An approved artifact is required before deploy.")
            blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
        else:
            if artifact.approval_status != "approved":
                reasons.append("An approved artifact is required before deploy.")
                blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
            if artifact.publish_status != "published":
                reasons.append("A published artifact is required before deploy.")
                blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
        runtime_diagnostics = self._runtime_publisher_diagnostics(action="deploy")
        if not bool(runtime_diagnostics.get("configured")):
            reasons.append(str(runtime_diagnostics.get("status_message") or "GitHub migration publisher is not configured."))
            reason_code = str(runtime_diagnostics.get("reason_code") or "").strip().lower()
            if reason_code == _GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE:
                blocker_codes.append(_DEPLOY_BLOCKER_INTEGRATION_UNAVAILABLE)
            else:
                blocker_codes.append(_DEPLOY_BLOCKER_RUNTIME_UNAVAILABLE)
            self._log_runtime_publisher_readiness(
                action="deploy",
                workspace=workspace,
                admin_prerequisites=admin_prerequisites,
            )
        if not workspace.last_published_artifact_version_id:
            reasons.append("A published artifact is required before deploy.")
            blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
        elif artifact is not None and workspace.last_published_artifact_version_id != artifact.id:
            reasons.append("The selected artifact is not the latest published artifact.")
            blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
        blocker_codes = _dedupe_strings(blocker_codes)
        failure_category: str | None = None
        if reasons:
            failure_category = self._categorize_readiness_failure(
                reasons=reasons,
                action="deploy",
                blocker_codes=blocker_codes,
            )
        return {
            "ready": not reasons,
            "reasons": reasons,
            "blocker_codes": blocker_codes,
            "failure_category": failure_category,
            "target": target_summary,
            "config_prerequisites": {
                "github_publisher_configured": self.github_publisher_configured,
                "github_publisher_reason_code": str(runtime_diagnostics.get("reason_code") or ""),
                "github_publisher_status_message": str(runtime_diagnostics.get("status_message") or ""),
                "deploy_runtime_available": bool(runtime_diagnostics.get("configured")),
                "target_config_valid": target_valid,
                "target_enabled": bool(target_summary.get("enabled")),
                **admin_prerequisites,
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

    def _build_artifact_quality_location_hints(self, *, site: SEOSite) -> list[str]:
        hints: list[str] = []
        seen: set[str] = set()

        primary_location = _normalize_string(site.primary_location, max_length=255)
        if primary_location:
            lowered = primary_location.lower()
            if lowered not in seen:
                seen.add(lowered)
                hints.append(primary_location)

        service_areas = site.service_areas_json if isinstance(site.service_areas_json, list) else []
        for item in service_areas[:8]:
            normalized = _normalize_string(item, max_length=120)
            if not normalized:
                continue
            lowered = normalized.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            hints.append(normalized)

        return hints

    def _build_artifact_quality_service_terms(
        self,
        *,
        workspace: SEOMigrationWorkspace,
        context_json: dict[str, object],
    ) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()

        def _add_term(value: object, *, max_length: int = 120) -> None:
            normalized = _normalize_string(value, max_length=max_length)
            if normalized is None:
                return
            lowered = normalized.lower()
            if lowered in seen:
                return
            seen.add(lowered)
            terms.append(normalized)

        enriched = _normalize_json_dict(workspace.enriched_content_notes_json)
        raw_service_highlights = enriched.get("service_highlights")
        if isinstance(raw_service_highlights, list):
            for item in raw_service_highlights[:12]:
                if isinstance(item, dict):
                    _add_term(item.get("name"), max_length=120)
                    _add_term(item.get("title"), max_length=120)
                else:
                    _add_term(item, max_length=120)

        requirements = _normalize_json_dict(workspace.operator_requirements_json)
        raw_must_include = requirements.get("must_include")
        if isinstance(raw_must_include, list):
            for item in raw_must_include[:12]:
                if isinstance(item, dict):
                    _add_term(item.get("value"), max_length=120)
                    _add_term(item.get("name"), max_length=120)
                else:
                    _add_term(item, max_length=120)

        source_snapshot = _normalize_json_dict(context_json.get("source_snapshot"))
        raw_service_blocks = source_snapshot.get("service_blocks")
        if isinstance(raw_service_blocks, list):
            for item in raw_service_blocks[:12]:
                if isinstance(item, dict):
                    _add_term(item.get("title"), max_length=120)
                    _add_term(item.get("text"), max_length=120)
                else:
                    _add_term(item, max_length=120)

        if not terms:
            _add_term("services")

        return terms

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
    if repo_name is None:
        repo_name = _normalize_string(source.get("repository"), max_length=120)
    if target_repo and (not repo_owner or not repo_name):
        parts = [item.strip() for item in target_repo.split("/", 1)]
        if len(parts) == 2:
            repo_owner = repo_owner or parts[0]
            repo_name = repo_name or parts[1]
        elif len(parts) == 1:
            repo_name = repo_name or parts[0]
    branch = _normalize_string(source.get("branch"), max_length=120) or ""
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


def _normalize_workspace_publish_config(value: object) -> dict[str, object]:
    normalized = _normalize_publish_config(value)
    return {
        "enabled": bool(normalized.get("enabled")),
        # GitHub account/owner is Admin-owned. Workspace config only stores repo + optional branch override.
        "repo_owner": "",
        "repo_name": str(normalized.get("repo_name") or "").strip(),
        "branch": str(normalized.get("branch") or "").strip(),
        "artifact_root": str(normalized.get("artifact_root") or "").strip(),
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


def _normalize_url_candidate(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=2048)
    if normalized is None:
        return None
    lowered = normalized.lower()
    if lowered.startswith("http://") or lowered.startswith("https://"):
        return normalized
    return None


def _normalize_host_candidate(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=253)
    if normalized is None:
        return None
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return _normalize_url_candidate(normalized)
    if "/" in normalized or " " in normalized:
        return None
    if "." not in normalized:
        return None
    return f"https://{normalized}"


def _try_parse_json_payload(raw_output: str) -> dict[str, object] | None:
    normalized = raw_output.strip()
    if not normalized:
        return None
    parsed = _try_parse_json_value(normalized)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        return {"generated_files": parsed}

    fenced_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", normalized, re.IGNORECASE)
    if fenced_match is not None:
        fenced = fenced_match.group(1).strip()
        parsed_fenced = _try_parse_json_value(fenced)
        if isinstance(parsed_fenced, dict):
            return parsed_fenced
        if isinstance(parsed_fenced, list):
            return {"generated_files": parsed_fenced}

    fragment, _ = _extract_first_json_fragment(normalized)
    if fragment is None:
        return None
    parsed_fragment = _try_parse_json_value(fragment)
    if isinstance(parsed_fragment, dict):
        return parsed_fragment
    if isinstance(parsed_fragment, list):
        return {"generated_files": parsed_fragment}
    return None


def _try_parse_json_value(raw_text: str) -> object | None:
    try:
        return json.loads(raw_text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _extract_first_json_fragment(raw_text: str) -> tuple[str | None, bool]:
    candidates = [index for index, ch in enumerate(raw_text) if ch in "{["][:32]
    partial = False
    for start_index in candidates:
        extracted, is_partial = _scan_balanced_json_fragment(raw_text, start_index=start_index)
        if extracted is not None:
            return extracted, False
        if is_partial:
            partial = True
    return None, partial


def _scan_balanced_json_fragment(raw_text: str, *, start_index: int) -> tuple[str | None, bool]:
    if start_index < 0 or start_index >= len(raw_text):
        return None, False
    opening = raw_text[start_index]
    if opening not in "{[":
        return None, False
    closing_for_opening = {"{": "}", "[": "]"}
    stack: list[str] = [closing_for_opening[opening]]
    in_string = False
    escaped = False
    for index in range(start_index + 1, len(raw_text)):
        char = raw_text[index]
        if in_string:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in "{[":
            stack.append(closing_for_opening[char])
            continue
        if char in "}]":
            if not stack or char != stack[-1]:
                return None, False
            stack.pop()
            if not stack:
                return raw_text[start_index : index + 1], False
    return None, bool(stack)


def _normalize_string(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(str(value or "").split()).strip()
        if not normalized:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


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
