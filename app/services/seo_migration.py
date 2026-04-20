from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import re
import time
from urllib.parse import quote, urlsplit
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.ai_execution_core import build_ai_diagnostics_summary, build_ai_failure_hint
from app.integrations.seo_migration_artifact_provider import (
    MisconfiguredSEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactGenerationOutput,
    SEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
    SEOMigrationProviderCompatibilityResult,
)
from app.integrations.seo_migration_github_publisher import (
    MisconfiguredSEOMigrationGitHubPublisher,
    SEOMigrationGitHubActionsSecretUpsertResult,
    SEOMigrationGitHubDeployTarget,
    SEOMigrationGitHubPublishFile,
    SEOMigrationGitHubPublishResult,
    SEOMigrationGitHubPublishTarget,
    SEOMigrationGitHubPublisher,
    SEOMigrationGitHubPublisherError,
    SEOMigrationGitHubTargetReadinessResult,
    SEOMigrationGitHubWorkflowProvisionResult,
    derive_site_kubernetes_namespace,
    normalize_workflow_dispatch_identifier_for_api,
)
from app.models.business import Business
from app.models.principal import PrincipalRole
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
from app.schemas.github_publish_config import normalize_namespace_isolation_defaults
from app.services.ai_response_contract_evaluator import (
    AIResponseContractEvaluation,
    evaluate_migration_artifact_response,
)
from app.services.ai_model_settings import resolve_ai_model_name
from app.services.github_publish_config import GitHubPublishConfigSecretError, GitHubPublishConfigService
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
_DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS = 30 * 60
_DUPLICATE_DEPLOY_UNVERIFIED_DISPATCH_STALE_SECONDS = 2 * 60
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
_MIGRATION_WORKFLOW_PROVISIONING_LOG_EVENT = "seo_migration_workflow_provisioning"
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
_DEPLOY_WORKFLOW_SOURCE_PUBLISH_HISTORY = "publish_history_workflow"
_DEPLOY_WORKFLOW_SOURCE_SITE_SPECIFIC = "site_specific_workflow"
_DEPLOY_WORKFLOW_SOURCE_WORKSPACE_CONFIG = "workspace_config_workflow"
_DEPLOY_WORKFLOW_SOURCE_DEFAULT = "default_workflow"

_DEPLOY_RESTRICTED_CONFIG_FIELDS = ("repo_owner", "repo_name", "workflow_id", "ref", "inputs")
_MIGRATION_URL_SOURCE_DETERMINISTIC_TARGET_CONFIG = "deterministic_target_config"
_MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT = "workflow_output"
_MIGRATION_URL_SOURCE_DEPLOY_RESULT = "deploy_result"
_MIGRATION_URL_SOURCE_UNKNOWN = "unknown"
_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS: tuple[str, ...] = (
    "resolved_live_url",
    "live_url",
    "deployed_url",
)
_DEPLOY_EVIDENCE_CONTRACT_STATUS_CONFIRMED = "confirmed_live_evidence"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_PLACEHOLDER = "workflow_placeholder_advisory"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_CONTRACT_INCOMPLETE = "workflow_contract_incomplete_advisory"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_SUCCEEDED_NO_EVIDENCE = "workflow_succeeded_without_explicit_evidence"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_RUN_FAILED = "workflow_run_failed_without_explicit_evidence"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_PENDING = "evidence_pending"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_NOT_ATTEMPTED = "evidence_not_attempted"
_DEPLOY_EVIDENCE_CONTRACT_STATUS_UNKNOWN = "unknown"
_POST_CONFORMANCE_STAGE_WORKFLOW_CONFORMANCE_FAILED = "workflow_conformance_failed"
_POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED = "workflow_dispatch_blocked"
_POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED = "workflow_dispatch_attempted"
_POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_FAILED = "workflow_dispatch_failed"
_POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN = "workflow_dispatch_succeeded_waiting_for_run"
_POST_CONFORMANCE_STAGE_WORKFLOW_RUN_FAILED = "workflow_run_failed"
_POST_CONFORMANCE_STAGE_ROLLOUT_FAILED = "rollout_failed"
_POST_CONFORMANCE_STAGE_LIVE_URL_EVIDENCE_MISSING = "live_url_evidence_missing"
_POST_CONFORMANCE_STAGE_DEPLOY_SUCCEEDED = "deploy_succeeded"
_POST_CONFORMANCE_STAGE_VALUES = {
    _POST_CONFORMANCE_STAGE_WORKFLOW_CONFORMANCE_FAILED,
    _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED,
    _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED,
    _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_FAILED,
    _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN,
    _POST_CONFORMANCE_STAGE_WORKFLOW_RUN_FAILED,
    _POST_CONFORMANCE_STAGE_ROLLOUT_FAILED,
    _POST_CONFORMANCE_STAGE_LIVE_URL_EVIDENCE_MISSING,
    _POST_CONFORMANCE_STAGE_DEPLOY_SUCCEEDED,
}
_WORKFLOW_REMEDIATION_OUTCOME_NOT_ATTEMPTED = "remediation_not_attempted"
_WORKFLOW_REMEDIATION_OUTCOME_UPGRADED_MANAGED_PLACEHOLDER = "remediation_upgraded_managed_placeholder"
_WORKFLOW_REMEDIATION_OUTCOME_ALREADY_CURRENT = "remediation_already_current"
_WORKFLOW_REMEDIATION_OUTCOME_PRESERVED_CUSTOM = "remediation_preserved_custom"
_WORKFLOW_REMEDIATION_OUTCOME_WRITE_FAILED = "remediation_write_failed"
_DEPLOY_SECRET_NAME_GCP_DEPLOY_KEY = "GCP_DEPLOY_KEY"
_DEPLOY_SECRET_PROPAGATION_STATUS_NOT_ATTEMPTED = "not_attempted"
_DEPLOY_SECRET_PROPAGATION_STATUS_CREATED = "created"
_DEPLOY_SECRET_PROPAGATION_STATUS_UPDATED = "updated"
_DEPLOY_SECRET_PROPAGATION_STATUS_SKIPPED_GUARDRAIL = "skipped_guardrail"
_DEPLOY_SECRET_PROPAGATION_STATUS_FAILED = "failed"
_DEPLOY_SECRET_SOURCE_ADMIN_MANAGED = "admin_managed_secret"
_DEPLOY_SECRET_SOURCE_RUNTIME_FALLBACK = "runtime_env_fallback"
_DEPLOY_TARGET_REASON_REPO_NOT_FOUND = "repo_not_found"
_DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND = "workflow_not_found"
_DEPLOY_TARGET_REASON_REF_INVALID = "branch_not_found_or_ref_invalid"
_DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED = "workflow_dispatch_not_supported"
_DEPLOY_TARGET_REASON_TOKEN_UNAUTHORIZED = "token_not_authorized"
_DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE = "workflow_not_dispatchable"
_DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY = "workflow_not_production_ready"
_DEPLOY_RUN_FAILURE_REASON_GCP_AUTH = "gcp_auth_failed"
_DEPLOY_RUN_FAILURE_REASON_CLUSTER_CREDENTIALS = "gke_credentials_failed"
_DEPLOY_RUN_FAILURE_REASON_MANIFEST_APPLY = "kubectl_apply_failed"
_DEPLOY_RUN_FAILURE_REASON_ROLLOUT = "rollout_verification_failed"
_DEPLOY_RUN_FAILURE_REASON_INGRESS_VERIFY = "service_ingress_verification_failed"
_DEPLOY_RUN_FAILURE_REASON_INGRESS_EVIDENCE = "ingress_endpoint_not_ready"
_DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_INVALID_STATE = "cloudsql_instance_invalid_state"
_DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_INSPECTION_FAILED = "cloudsql_instance_inspection_failed"
_DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_EPHEMERAL_CERT = "cloudsql_proxy_ephemeral_cert_failed"
_DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_CONNECTION = "cloudsql_proxy_connection_failed"
_DEPLOY_RUN_FAILURE_REASON_CANCELLED = "workflow_run_cancelled"
_DEPLOY_RUN_FAILURE_REASON_TIMED_OUT = "workflow_run_timed_out"
_DEPLOY_RUN_FAILURE_REASON_GENERIC = "workflow_run_failed"
_DEPLOY_RUN_FAILURE_STAGE_GCP_AUTH = "gcp_auth"
_DEPLOY_RUN_FAILURE_STAGE_CLUSTER_CREDENTIALS = "cluster_credentials"
_DEPLOY_RUN_FAILURE_STAGE_MANIFEST_APPLY = "manifest_apply"
_DEPLOY_RUN_FAILURE_STAGE_ROLLOUT = "rollout_verify"
_DEPLOY_RUN_FAILURE_STAGE_INGRESS_VERIFY = "ingress_verify"
_DEPLOY_RUN_FAILURE_STAGE_INGRESS_EVIDENCE = "ingress_evidence"
_DEPLOY_RUN_FAILURE_STAGE_WORKFLOW_EXECUTION = "workflow_execution"
_DEPLOY_DISPATCH_SERVICE_REASON_AVAILABLE = "available"
_DEPLOY_DISPATCH_SERVICE_REASON_RUNTIME_UNAVAILABLE = "runtime_unavailable"
_DEPLOY_DISPATCH_SERVICE_REASON_TARGET_CONFIG_INVALID = "target_configuration_invalid"
_DEPLOY_DISPATCH_SERVICE_REASON_TARGET_DISABLED = "target_disabled"
_DEPLOY_DISPATCH_SERVICE_REASON_TARGET_METADATA_MISSING = "target_metadata_missing"
_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME = "missing_cluster_name"
_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION = "missing_cluster_location"
_DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID = "missing_gcp_project_id"
_DEPLOY_WORKFLOW_MODE_SITE_REPO_TEMPLATE_V1 = "site_repo_template_v1"
_DEPLOY_TARGET_ENVIRONMENT_SOURCE_ADMIN = "admin_config"
_DEPLOY_DEFAULT_TARGET_ENVIRONMENT_KEY = "gke_prod"

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
class SEOMigrationArtifactDeleteResult:
    workspace: SEOMigrationWorkspace
    deleted_artifact_version_id: str
    deleted_artifact_version_number: int


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
    normalized_failure_category: str | None = None
    normalized_failure_reason: str | None = None
    normalized_failure_source: str | None = None
    normalized_retryable: bool | None = None
    provider_attempt_count: int | None = None
    original_input_size: int | None = None
    final_input_size: int | None = None
    trimmed_bytes: int | None = None
    trimming_pass_count: int | None = None
    difficulty_score: int | None = None
    budget_outcome: str | None = None
    retry_suppressed: bool | None = None
    degraded_state: str | None = None


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
        deploy_secret_gcp_key: str | None = None,
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
        self.deploy_secret_gcp_key = (deploy_secret_gcp_key or "").strip() or None
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
        deploy_config_field_names: set[str] | None = None,
        analytics_config: dict[str, object] | None = None,
        principal_id: str | None,
        principal_role: PrincipalRole | str | None = None,
    ) -> SEOMigrationWorkspace:
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace = self.seo_migration_repository.get_workspace_for_business_site(business_id, site_id)
        normalized_deploy_config = (
            self._sanitize_workspace_deploy_config_update(
                current_config=workspace.deploy_config_json if workspace is not None else None,
                incoming_config=deploy_config,
                principal_role=principal_role,
                deploy_config_field_names=deploy_config_field_names,
            )
            if deploy_config is not None
            else _normalize_deploy_config(None)
        )
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
                deploy_config_json=normalized_deploy_config,
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
                workspace.deploy_config_json = normalized_deploy_config
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
        deploy_config_field_names: set[str] | None = None,
        principal_id: str | None,
        principal_role: PrincipalRole | str | None = None,
    ) -> SEOMigrationWorkspace:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        workspace.deploy_config_json = self._sanitize_workspace_deploy_config_update(
            current_config=workspace.deploy_config_json,
            incoming_config=deploy_config,
            principal_role=principal_role,
            deploy_config_field_names=deploy_config_field_names,
        )
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

    @staticmethod
    def _is_admin_principal_role(principal_role: PrincipalRole | str | None) -> bool:
        if principal_role is None:
            # Backward compatibility for existing service-level call sites and tests
            # that do not currently pass principal role context.
            return True
        if isinstance(principal_role, PrincipalRole):
            return principal_role == PrincipalRole.ADMIN
        return str(principal_role).strip().lower() == PrincipalRole.ADMIN.value

    def _sanitize_workspace_deploy_config_update(
        self,
        *,
        current_config: object,
        incoming_config: object,
        principal_role: PrincipalRole | str | None,
        deploy_config_field_names: set[str] | None,
    ) -> dict[str, object]:
        normalized_incoming = _normalize_deploy_config(incoming_config)
        if self._is_admin_principal_role(principal_role):
            return normalized_incoming

        normalized_current = _normalize_deploy_config(current_config)
        provided_fields = (
            {str(field).strip() for field in deploy_config_field_names if str(field).strip()}
            if deploy_config_field_names is not None
            else set(normalized_incoming.keys())
        )
        restricted_fields = set(_DEPLOY_RESTRICTED_CONFIG_FIELDS)

        changed_restricted_fields: list[str] = []
        for field_name in sorted(restricted_fields.intersection(provided_fields)):
            if field_name == "inputs":
                current_inputs = (
                    dict(normalized_current.get("inputs", {}))
                    if isinstance(normalized_current.get("inputs"), dict)
                    else {}
                )
                incoming_inputs = (
                    dict(normalized_incoming.get("inputs", {}))
                    if isinstance(normalized_incoming.get("inputs"), dict)
                    else {}
                )
                if current_inputs != incoming_inputs:
                    changed_restricted_fields.append(field_name)
                continue
            current_value = str(normalized_current.get(field_name) or "").strip()
            incoming_value = str(normalized_incoming.get(field_name) or "").strip()
            if current_value != incoming_value:
                changed_restricted_fields.append(field_name)

        if changed_restricted_fields:
            raise SEOMigrationValidationError("Only admin principals can update deploy repository/workflow controls.")

        merged_config = dict(normalized_current)
        if "enabled" in provided_fields:
            merged_config["enabled"] = bool(normalized_incoming.get("enabled"))
        return merged_config

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
            (
                effective_publish_config,
                admin_publish_prerequisites,
                _,
            ) = self._build_effective_publish_config(
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
        duplicate_publish_attempt = False
        if not dry_run:
            duplicate_publish_attempt = _is_duplicate_publish_attempt(
                history=workspace.publish_history_json,
                artifact_version_id=artifact.id,
                target=target,
            )
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
        workflow_provisioning_status: str | None = None
        workflow_provisioning_remediation_mode: str | None = None
        workflow_remediation_attempted = False
        workflow_remediation_outcome = _WORKFLOW_REMEDIATION_OUTCOME_NOT_ATTEMPTED
        deploy_secret_propagation_attempted = False
        deploy_secret_propagation_status = _DEPLOY_SECRET_PROPAGATION_STATUS_NOT_ATTEMPTED
        deploy_secret_propagation_reason: str | None = None
        deploy_secret_propagation_source: str | None = None
        workflow_provisioning_verified = False
        workflow_resolution_for_provision: dict[str, object] | None = None
        expected_publish_url: str | None = None
        expected_publish_url_source = _MIGRATION_URL_SOURCE_UNKNOWN
        expected_publish_url_source_detail: str | None = None
        duplicate_publish_repaired = False
        publish_result: SEOMigrationGitHubPublishResult | None = None
        admin_deploy_metadata = self._resolve_admin_deploy_template_metadata()
        deploy_workflow_mode = (
            _normalize_string(
                admin_deploy_metadata.get("deploy_workflow_mode"),
                max_length=60,
            )
            or _DEPLOY_WORKFLOW_MODE_SITE_REPO_TEMPLATE_V1
        )
        target_environment_key = (
            _normalize_string(
                admin_deploy_metadata.get("target_environment_key"),
                max_length=80,
            )
            or _DEPLOY_DEFAULT_TARGET_ENVIRONMENT_KEY
        )
        target_environment_source = (
            _normalize_string(
                admin_deploy_metadata.get("target_environment_source"),
                max_length=60,
            )
            or _DEPLOY_TARGET_ENVIRONMENT_SOURCE_ADMIN
        )
        try:
            deploy_target_for_workflow: dict[str, object] | None = None
            try:
                (
                    deploy_target_for_workflow,
                    workflow_resolution_for_provision,
                ) = self._resolve_deploy_target_with_workflow_precedence(
                    workspace=workspace,
                    effective_publish_config=effective_publish_config,
                    artifact_version_id=artifact.id,
                    validate_workflow_candidates=True,
                )
            except ValueError:
                deploy_target_for_workflow = {
                    "enabled": False,
                    "repo_owner": target["repo_owner"],
                    "repo_name": target["repo_name"],
                    "workflow_id": self.deploy_default_workflow_id,
                    "ref": target["branch"] or self.deploy_default_ref,
                    "inputs": {},
                }

            (
                expected_publish_url,
                expected_publish_url_source,
                expected_publish_url_source_detail,
            ) = self._resolve_expected_publish_url(
                deploy_target=deploy_target_for_workflow,
                deploy_config=workspace.deploy_config_json,
            )

            if not dry_run and isinstance(deploy_target_for_workflow, dict):
                workflow_provisioning_remediation_mode = (
                    "duplicate_publish_repair" if duplicate_publish_attempt else "bootstrap"
                )
                workflow_remediation_attempted = bool(duplicate_publish_attempt)
                workflow_owner = str(deploy_target_for_workflow.get("repo_owner") or target["repo_owner"])
                workflow_repo = str(deploy_target_for_workflow.get("repo_name") or target["repo_name"])
                workflow_ref = str(deploy_target_for_workflow.get("ref") or target["branch"])
                workflow_identifier = str(
                    deploy_target_for_workflow.get("workflow_id") or self.deploy_default_workflow_id
                )
                workflow_path = f".github/workflows/{workflow_identifier}"
                self._emit_structured_service_log(
                    payload={
                        "event": "seo_migration_publish_workflow_resolution",
                        "business_id": business_id,
                        "site_id": site_id,
                        "workspace_id": workspace.id,
                        "artifact_version_id": artifact.id,
                        "repo_owner": workflow_owner,
                        "repo_name": workflow_repo,
                        "ref": workflow_ref,
                        "workflow_id": workflow_identifier,
                        "workflow_path": (
                            _normalize_workflow_path_for_deploy(
                                (workflow_resolution_for_provision or {}).get("workflow_path")
                            )
                            or _normalize_workflow_path_for_deploy(workflow_path)
                        ),
                        "resolved_workflow_source": _normalize_string(
                            (workflow_resolution_for_provision or {}).get("source"),
                            max_length=60,
                        ),
                        "site_workflow_file_path": _normalize_workflow_path_for_deploy(
                            (workflow_resolution_for_provision or {}).get("site_specific_workflow_path")
                        ),
                        "deploy_workflow_mode": _normalize_string(
                            (workflow_resolution_for_provision or {}).get("deploy_workflow_mode"),
                            max_length=60,
                        )
                        or deploy_workflow_mode,
                    },
                    fallback_message="seo_migration_publish_workflow_resolution",
                    level=logging.INFO,
                )
                deploy_workflow_provision_result = self.github_publisher.ensure_deploy_workflow(
                    repo_owner=workflow_owner,
                    repo_name=workflow_repo,
                    branch=workflow_ref,
                    workflow_id=workflow_identifier,
                    dry_run=False,
                    deploy_workflow_mode=deploy_workflow_mode,
                    target_environment_key=target_environment_key,
                    target_environment_source=target_environment_source,
                    managed_gke_config=_normalize_json_dict(admin_deploy_metadata.get("managed_gke_config")),
                    namespace_isolation_defaults=admin_deploy_metadata.get("namespace_isolation_defaults"),
                    site_id=site.id,
                )
                workflow_provisioning_verified = True
                workflow_remediation_outcome = _derive_workflow_remediation_outcome(
                    remediation_attempted=workflow_remediation_attempted,
                    managed_workflow_outcome=deploy_workflow_provision_result.managed_workflow_outcome,
                    write_failed=False,
                )
                workflow_path = deploy_workflow_provision_result.workflow_path
                workflow_provisioning_status = (
                    "created" if deploy_workflow_provision_result.provisioned else "already_exists"
                )
                if not deploy_workflow_provision_result.provisioned:
                    workflow_provisioning_remediation_mode = "already_present"
                self._log_workflow_provisioning(
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    principal_id=principal_id,
                    artifact_version_id=artifact.id,
                    repo_owner=workflow_owner,
                    repo_name=workflow_repo,
                    ref=workflow_ref,
                    workflow_id=workflow_identifier,
                    workflow_path=workflow_path,
                    status=workflow_provisioning_status,
                    remediation_mode=workflow_provisioning_remediation_mode,
                    deploy_workflow_mode=deploy_workflow_mode,
                    target_environment_key=target_environment_key,
                    target_environment_source=target_environment_source,
                    kubernetes_namespace=deploy_workflow_provision_result.kubernetes_namespace,
                    namespace_source=deploy_workflow_provision_result.namespace_source,
                    namespace_model_status=deploy_workflow_provision_result.namespace_model_status,
                    managed_manifest_paths=deploy_workflow_provision_result.managed_manifest_paths,
                    managed_resource_quota_expected=deploy_workflow_provision_result.managed_resource_quota_expected,
                    managed_resource_quota_present=deploy_workflow_provision_result.managed_resource_quota_present,
                    managed_limit_range_expected=deploy_workflow_provision_result.managed_limit_range_expected,
                    managed_limit_range_present=deploy_workflow_provision_result.managed_limit_range_present,
                    managed_network_policy_expected=deploy_workflow_provision_result.managed_network_policy_expected,
                    managed_network_policy_present=deploy_workflow_provision_result.managed_network_policy_present,
                    managed_namespace_policies_aligned=deploy_workflow_provision_result.managed_namespace_policies_aligned,
                    workflow_remediation_outcome=workflow_remediation_outcome,
                    commit_sha=deploy_workflow_provision_result.commit_sha,
                    verified=True,
                )
                self._log_workflow_provisioning(
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    principal_id=principal_id,
                    artifact_version_id=artifact.id,
                    repo_owner=workflow_owner,
                    repo_name=workflow_repo,
                    ref=workflow_ref,
                    workflow_id=workflow_identifier,
                    workflow_path=workflow_path,
                    status="verified",
                    remediation_mode=workflow_provisioning_remediation_mode,
                    deploy_workflow_mode=deploy_workflow_mode,
                    target_environment_key=target_environment_key,
                    target_environment_source=target_environment_source,
                    kubernetes_namespace=deploy_workflow_provision_result.kubernetes_namespace,
                    namespace_source=deploy_workflow_provision_result.namespace_source,
                    namespace_model_status=deploy_workflow_provision_result.namespace_model_status,
                    managed_manifest_paths=deploy_workflow_provision_result.managed_manifest_paths,
                    managed_resource_quota_expected=deploy_workflow_provision_result.managed_resource_quota_expected,
                    managed_resource_quota_present=deploy_workflow_provision_result.managed_resource_quota_present,
                    managed_limit_range_expected=deploy_workflow_provision_result.managed_limit_range_expected,
                    managed_limit_range_present=deploy_workflow_provision_result.managed_limit_range_present,
                    managed_network_policy_expected=deploy_workflow_provision_result.managed_network_policy_expected,
                    managed_network_policy_present=deploy_workflow_provision_result.managed_network_policy_present,
                    managed_namespace_policies_aligned=deploy_workflow_provision_result.managed_namespace_policies_aligned,
                    workflow_remediation_outcome=workflow_remediation_outcome,
                    commit_sha=deploy_workflow_provision_result.commit_sha,
                    verified=True,
                )
                if deploy_workflow_provision_result.provisioned:
                    self._log_workflow_provisioned(
                        business_id=business_id,
                        site_id=site_id,
                        workspace_id=workspace.id,
                        principal_id=principal_id,
                        provision_result=deploy_workflow_provision_result,
                    )
                (
                    deploy_secret_propagation_attempted,
                    deploy_secret_propagation_status,
                    deploy_secret_propagation_reason,
                    deploy_secret_propagation_source,
                ) = self._attempt_deploy_secret_propagation(
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    artifact_version_id=artifact.id,
                    principal_id=principal_id,
                    workflow_owner=workflow_owner,
                    workflow_repo=workflow_repo,
                    workflow_ref=workflow_ref,
                    publish_target=target,
                    deploy_target=deploy_target_for_workflow,
                    admin_prerequisites=admin_publish_prerequisites,
                )
            if duplicate_publish_attempt:
                if deploy_workflow_provision_result is not None and deploy_workflow_provision_result.provisioned:
                    duplicate_publish_repaired = True
                    publish_result = SEOMigrationGitHubPublishResult(
                        dry_run=False,
                        repo_owner=target["repo_owner"],
                        repo_name=target["repo_name"],
                        branch=target["branch"],
                        artifact_root=target["artifact_root"],
                        files_published=0,
                        total_bytes=0,
                        commit_shas=(),
                        committed_paths=(),
                        published_at=utc_now().isoformat(),
                    )
                else:
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
                        target_summary={
                            **target,
                            "workflow_provisioning_status": workflow_provisioning_status,
                            "workflow_provisioning_remediation_mode": workflow_provisioning_remediation_mode,
                            "workflow_remediation_attempted": workflow_remediation_attempted,
                            "workflow_remediation_outcome": workflow_remediation_outcome,
                            "deploy_secret_propagation_attempted": deploy_secret_propagation_attempted,
                            "deploy_secret_propagation_status": deploy_secret_propagation_status,
                            "deploy_secret_propagation_reason": deploy_secret_propagation_reason,
                            "deploy_secret_propagation_source": deploy_secret_propagation_source,
                        },
                        failure_category="duplicate_request",
                        failure_reason=failure_message,
                        duration_ms=self._duration_ms(started_at),
                    )
                    raise SEOMigrationValidationError(failure_message)
            else:
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
            if workflow_provisioning_remediation_mode:
                workflow_remediation_outcome = _derive_workflow_remediation_outcome(
                    remediation_attempted=workflow_remediation_attempted,
                    managed_workflow_outcome=(
                        deploy_workflow_provision_result.managed_workflow_outcome
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    write_failed=True,
                )
                workflow_identifier = (
                    deploy_workflow_provision_result.workflow_id
                    if deploy_workflow_provision_result is not None
                    else str(
                        (
                            deploy_target_for_workflow.get("workflow_id")
                            if isinstance(deploy_target_for_workflow, dict)
                            else self.deploy_default_workflow_id
                        )
                        or self.deploy_default_workflow_id
                    )
                )
                workflow_path = (
                    deploy_workflow_provision_result.workflow_path
                    if deploy_workflow_provision_result is not None
                    else f".github/workflows/{workflow_identifier}"
                )
                workflow_owner = str(
                    (
                        deploy_target_for_workflow.get("repo_owner")
                        if isinstance(deploy_target_for_workflow, dict)
                        else target.get("repo_owner")
                    )
                    or target["repo_owner"]
                )
                workflow_repo = str(
                    (
                        deploy_target_for_workflow.get("repo_name")
                        if isinstance(deploy_target_for_workflow, dict)
                        else target.get("repo_name")
                    )
                    or target["repo_name"]
                )
                workflow_ref = str(
                    (
                        deploy_target_for_workflow.get("ref")
                        if isinstance(deploy_target_for_workflow, dict)
                        else target.get("branch")
                    )
                    or target["branch"]
                )
                self._log_workflow_provisioning(
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    principal_id=principal_id,
                    artifact_version_id=artifact.id,
                    repo_owner=workflow_owner,
                    repo_name=workflow_repo,
                    ref=workflow_ref,
                    workflow_id=workflow_identifier,
                    workflow_path=workflow_path,
                    status="failed",
                    remediation_mode=workflow_provisioning_remediation_mode,
                    deploy_workflow_mode=deploy_workflow_mode,
                    target_environment_key=target_environment_key,
                    target_environment_source=target_environment_source,
                    kubernetes_namespace=(
                        deploy_workflow_provision_result.kubernetes_namespace
                        if deploy_workflow_provision_result is not None
                        else _safe_derive_kubernetes_namespace_for_summary(repo_name=workflow_repo)[0]
                    ),
                    namespace_source=(
                        deploy_workflow_provision_result.namespace_source
                        if deploy_workflow_provision_result is not None
                        else _safe_derive_kubernetes_namespace_for_summary(repo_name=workflow_repo)[1]
                    ),
                    namespace_model_status=(
                        deploy_workflow_provision_result.namespace_model_status
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_manifest_paths=(
                        deploy_workflow_provision_result.managed_manifest_paths
                        if deploy_workflow_provision_result is not None
                        else ()
                    ),
                    managed_resource_quota_expected=(
                        deploy_workflow_provision_result.managed_resource_quota_expected
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_resource_quota_present=(
                        deploy_workflow_provision_result.managed_resource_quota_present
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_limit_range_expected=(
                        deploy_workflow_provision_result.managed_limit_range_expected
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_limit_range_present=(
                        deploy_workflow_provision_result.managed_limit_range_present
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_network_policy_expected=(
                        deploy_workflow_provision_result.managed_network_policy_expected
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_network_policy_present=(
                        deploy_workflow_provision_result.managed_network_policy_present
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    managed_namespace_policies_aligned=(
                        deploy_workflow_provision_result.managed_namespace_policies_aligned
                        if deploy_workflow_provision_result is not None
                        else None
                    ),
                    workflow_remediation_outcome=workflow_remediation_outcome,
                    verified=workflow_provisioning_verified,
                    error_code=exc.code,
                    error_message=exc.safe_message,
                )
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
                    "expected_publish_url": expected_publish_url,
                    "url_source": expected_publish_url_source,
                    "url_source_detail": expected_publish_url_source_detail,
                    "deploy_secret_propagation_attempted": deploy_secret_propagation_attempted,
                    "deploy_secret_propagation_status": deploy_secret_propagation_status,
                    "deploy_secret_propagation_reason": deploy_secret_propagation_reason,
                    "deploy_secret_propagation_source": deploy_secret_propagation_source,
                    "failure_reason": _normalize_string(exc.code, max_length=80),
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
                target_summary={
                    **target,
                    "failure_reason_code": _normalize_string(exc.code, max_length=80),
                    "workflow_provisioning_status": workflow_provisioning_status,
                    "workflow_provisioning_remediation_mode": workflow_provisioning_remediation_mode,
                    "workflow_remediation_attempted": workflow_remediation_attempted,
                    "workflow_remediation_outcome": workflow_remediation_outcome,
                    "deploy_secret_propagation_attempted": deploy_secret_propagation_attempted,
                    "deploy_secret_propagation_status": deploy_secret_propagation_status,
                    "deploy_secret_propagation_reason": deploy_secret_propagation_reason,
                    "deploy_secret_propagation_source": deploy_secret_propagation_source,
                    "kubernetes_namespace": (
                        deploy_workflow_provision_result.kubernetes_namespace
                        if deploy_workflow_provision_result is not None
                        else _safe_derive_kubernetes_namespace_for_summary(
                            repo_name=(
                                deploy_target_for_workflow.get("repo_name")
                                if isinstance(deploy_target_for_workflow, dict)
                                else target.get("repo_name")
                            )
                        )[0]
                    ),
                },
                failure_category=failure_category,
                failure_reason=exc.safe_message,
                duration_ms=self._duration_ms(started_at),
            )
            raise SEOMigrationValidationError(exc.safe_message) from exc

        if publish_result is None:
            raise SEOMigrationValidationError("Migration publish result was unavailable.")

        now = utc_now()
        status_label = "dry_run" if dry_run else "published"
        if not dry_run:
            artifact.publish_status = "published"
            if not duplicate_publish_repaired:
                artifact.last_published_at = now
            elif artifact.last_published_at is None:
                artifact.last_published_at = now
            artifact.last_publish_error_summary = None
            if not duplicate_publish_repaired:
                artifact.last_published_commit_sha = (
                    publish_result.commit_shas[-1] if publish_result.commit_shas else None
                )
            workspace.last_published_artifact_version_id = artifact.id
            workspace.last_published_artifact_version_number = artifact.version
            if not duplicate_publish_repaired or workspace.last_published_commit_sha is None:
                workspace.last_published_commit_sha = artifact.last_published_commit_sha
            if not duplicate_publish_repaired:
                workspace.last_published_at = now
            elif workspace.last_published_at is None:
                workspace.last_published_at = artifact.last_published_at or now
            if not duplicate_publish_repaired or workspace.last_published_by_principal_id is None:
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
            "expected_publish_url": expected_publish_url,
            "url_source": expected_publish_url_source,
            "url_source_detail": expected_publish_url_source_detail,
            "duplicate_artifact_skipped": bool(duplicate_publish_repaired),
            "workflow_provisioning_status": workflow_provisioning_status,
            "workflow_provisioning_remediation_mode": workflow_provisioning_remediation_mode,
            "workflow_remediation_attempted": workflow_remediation_attempted,
            "workflow_remediation_outcome": workflow_remediation_outcome,
            "deploy_secret_propagation_attempted": deploy_secret_propagation_attempted,
            "deploy_secret_propagation_status": deploy_secret_propagation_status,
            "deploy_secret_propagation_reason": deploy_secret_propagation_reason,
            "deploy_secret_propagation_source": deploy_secret_propagation_source,
            "workflow_provisioning_verified": workflow_provisioning_verified,
            "deploy_workflow_mode": deploy_workflow_mode,
            "target_environment_key": target_environment_key,
            "target_environment_source": target_environment_source,
            "kubernetes_namespace": (
                deploy_workflow_provision_result.kubernetes_namespace
                if deploy_workflow_provision_result is not None
                else _safe_derive_kubernetes_namespace_for_summary(repo_name=publish_result.repo_name)[0]
            ),
            "namespace_source": (
                deploy_workflow_provision_result.namespace_source
                if deploy_workflow_provision_result is not None
                else _safe_derive_kubernetes_namespace_for_summary(repo_name=publish_result.repo_name)[1]
            ),
            "namespace_model_status": (
                deploy_workflow_provision_result.namespace_model_status
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_manifest_paths": list(
                deploy_workflow_provision_result.managed_manifest_paths
                if deploy_workflow_provision_result is not None
                else ()
            ),
            "managed_resource_quota_expected": (
                deploy_workflow_provision_result.managed_resource_quota_expected
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_resource_quota_present": (
                deploy_workflow_provision_result.managed_resource_quota_present
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_limit_range_expected": (
                deploy_workflow_provision_result.managed_limit_range_expected
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_limit_range_present": (
                deploy_workflow_provision_result.managed_limit_range_present
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_network_policy_expected": (
                deploy_workflow_provision_result.managed_network_policy_expected
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_network_policy_present": (
                deploy_workflow_provision_result.managed_network_policy_present
                if deploy_workflow_provision_result is not None
                else None
            ),
            "managed_namespace_policies_aligned": (
                deploy_workflow_provision_result.managed_namespace_policies_aligned
                if deploy_workflow_provision_result is not None
                else None
            ),
            "deploy_workflow_provisioned": bool(
                not dry_run
                and deploy_workflow_provision_result is not None
                and deploy_workflow_provision_result.provisioned
            ),
        }
        if not dry_run and deploy_workflow_provision_result is not None:
            history_payload["deploy_workflow_id"] = deploy_workflow_provision_result.workflow_id
            history_payload["deploy_workflow_path"] = deploy_workflow_provision_result.workflow_path
            history_payload["site_workflow_file_path"] = deploy_workflow_provision_result.workflow_path
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
                "expected_publish_url": expected_publish_url,
                "url_source": expected_publish_url_source,
                "url_source_detail": expected_publish_url_source_detail,
                "duplicate_artifact_skipped": bool(duplicate_publish_repaired),
                "workflow_provisioning_status": workflow_provisioning_status,
                "workflow_provisioning_remediation_mode": workflow_provisioning_remediation_mode,
                "workflow_remediation_attempted": workflow_remediation_attempted,
                "workflow_remediation_outcome": workflow_remediation_outcome,
                "deploy_secret_propagation_attempted": deploy_secret_propagation_attempted,
                "deploy_secret_propagation_status": deploy_secret_propagation_status,
                "deploy_secret_propagation_reason": deploy_secret_propagation_reason,
                "deploy_secret_propagation_source": deploy_secret_propagation_source,
                "workflow_provisioning_verified": workflow_provisioning_verified,
                "deploy_workflow_mode": deploy_workflow_mode,
                "target_environment_key": target_environment_key,
                "target_environment_source": target_environment_source,
                "kubernetes_namespace": history_payload.get("kubernetes_namespace"),
                "namespace_source": history_payload.get("namespace_source"),
                "namespace_model_status": history_payload.get("namespace_model_status"),
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
        deploy_trace_id = str(uuid4())
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
            correlation_id=deploy_trace_id,
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
                target_summary={
                    **_normalize_json_dict(readiness.get("target")),
                    "dispatch_service_availability": readiness.get("dispatch_service_availability"),
                    "dispatch_service_reason_code": readiness.get("dispatch_service_reason_code"),
                },
                failure_category=failure_category,
                failure_reason=reason_text,
                duration_ms=self._duration_ms(started_at),
                correlation_id=deploy_trace_id,
            )
            raise SEOMigrationValidationError(reason_text)

        try:
            effective_publish_config, _, _ = self._build_effective_publish_config(
                workspace_publish_config=workspace.publish_config_json,
                require_admin=True,
            )
            deploy_target, workflow_resolution = self._resolve_deploy_target_with_workflow_precedence(
                workspace=workspace,
                effective_publish_config=effective_publish_config,
                artifact_version_id=artifact.id,
                validate_workflow_candidates=True,
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
                target_summary={
                    **self._safe_deploy_target_summary(workspace=workspace),
                    "resolved_workflow_source": _DEPLOY_WORKFLOW_SOURCE_WORKSPACE_CONFIG,
                    "deploy_trace_id": deploy_trace_id,
                },
                failure_category="target_invalid",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
                correlation_id=deploy_trace_id,
            )
            raise SEOMigrationValidationError(failure_message) from exc
        namespace_isolation_defaults = _normalize_json_dict(workflow_resolution.get("namespace_isolation_defaults"))
        workflow_resolution_path = _normalize_workflow_path_for_deploy(workflow_resolution.get("workflow_path"))
        dispatch_identifier_diagnostics = _resolve_workflow_dispatch_identifier(
            workflow_id=deploy_target.get("workflow_id"),
            workflow_path=workflow_resolution_path,
        )
        workflow_identifier_requested = _normalize_string(
            dispatch_identifier_diagnostics.get("workflow_identifier_requested"),
            max_length=200,
        )
        workflow_identifier_used = _normalize_string(
            dispatch_identifier_diagnostics.get("workflow_identifier_used"),
            max_length=200,
        )
        workflow_identifier_type_requested = _normalize_string(
            dispatch_identifier_diagnostics.get("workflow_identifier_type_requested"),
            max_length=80,
        )
        workflow_identifier_type_used = _normalize_string(
            dispatch_identifier_diagnostics.get("workflow_identifier_type_used"),
            max_length=80,
        )
        workflow_dispatch_resolution_source = _normalize_string(
            dispatch_identifier_diagnostics.get("workflow_dispatch_resolution_source"),
            max_length=60,
        )
        workflow_file_path = (
            _normalize_workflow_path_for_deploy(dispatch_identifier_diagnostics.get("workflow_file_path"))
            or workflow_resolution_path
        )
        workflow_name = _normalize_string(dispatch_identifier_diagnostics.get("workflow_name"), max_length=160)
        if workflow_identifier_used is None:
            workflow_identifier_used = _normalize_workflow_id_for_deploy(
                deploy_target.get("workflow_id")
            ) or _normalize_string(
                deploy_target.get("workflow_id"),
                max_length=160,
            )
        workflow_identifier = _derive_workflow_identifier(
            workflow_id=workflow_identifier_used or deploy_target.get("workflow_id"),
            workflow_path=workflow_file_path,
        )
        if workflow_resolution.get("source") in {
            _DEPLOY_WORKFLOW_SOURCE_PUBLISH_HISTORY,
            _DEPLOY_WORKFLOW_SOURCE_SITE_SPECIFIC,
        }:
            self._emit_structured_service_log(
                payload={
                    "event": "seo_migration_deploy_workflow_resolution",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "resolved_workflow_source": workflow_resolution.get("source"),
                    "workflow_id": deploy_target.get("workflow_id"),
                    "workflow_path": workflow_file_path,
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_name": workflow_name,
                    "deploy_trace_id": deploy_trace_id,
                },
                fallback_message="seo_migration_deploy_workflow_resolution",
                level=logging.INFO,
            )
        (
            expected_publish_url,
            expected_publish_url_source,
            expected_publish_url_source_detail,
        ) = self._resolve_expected_publish_url_for_deploy(
            workspace=workspace,
            artifact_version_id=artifact.id,
            deploy_target=deploy_target,
        )
        resolved_live_url: str | None = None
        resolved_live_url_source = _MIGRATION_URL_SOURCE_UNKNOWN
        resolved_live_url_source_detail: str | None = None
        requested_ref = str(deploy_target["ref"] or "").strip()
        resolved_ref = requested_ref
        ref_source = "requested"
        target_readiness: SEOMigrationGitHubTargetReadinessResult | None = None
        workflow_dispatch_supported: bool | None = None
        workflow_trigger_types: tuple[str, ...] | list[str] = ()
        dispatch_service_availability: bool | None = None
        dispatch_service_reason_code: str | None = None
        workflow_conformance_checked: bool | None = None
        workflow_conformance_status: str | None = None
        workflow_conformance_reasons: list[str] = []
        workflow_conformance_evidence_summary: str | None = None
        dispatch_identifier_type: str | None = workflow_identifier_type_used or _infer_dispatch_identifier_type(
            workflow_identifier_used or deploy_target.get("workflow_id")
        )
        actual_dispatch_identifier_sent: str | None = None
        actual_dispatch_identifier_type_sent: str | None = None
        dispatch_ref_sent: str | None = None
        workflow_inputs_configured_keys = _normalize_dispatch_input_keys(deploy_target.get("inputs"))
        workflow_inputs_sent_keys: list[str] = []
        workflow_run_lookup_attempted: bool | None = None
        workflow_run_found: bool | None = None
        workflow_job_failure_detected: bool | None = None
        workflow_run_failure_reason_code: str | None = None
        workflow_run_failure_stage: str | None = None
        workflow_run_failure_step: str | None = None
        workflow_run_failure_hint: str | None = None
        post_dispatch_state: str | None = None
        post_conformance_stage: str | None = None
        post_conformance_reason_text: str | None = None
        post_conformance_remediation_message: str | None = None
        expected_workflow_outputs = list(_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS)
        deploy_evidence_contract_status = _DEPLOY_EVIDENCE_CONTRACT_STATUS_UNKNOWN
        deploy_evidence_contract_reasons: list[str] = []
        workflow_contract_advisory: str | None = None
        dispatch_attempted = False
        dispatch_result_stage: str | None = None
        # Keep workflow_dispatch payload contract bounded to explicitly configured deploy inputs.
        # Implicit runtime metadata (site_id/artifact_version/ga_measurement_id/etc.) should not
        # be auto-injected because GitHub rejects undeclared workflow_dispatch inputs.
        deploy_inputs = dict(deploy_target["inputs"])
        workflow_inputs_sent_keys = _normalize_dispatch_input_keys(deploy_inputs)
        analytics_config = _normalize_analytics_config(workspace.analytics_config_json)
        analytics_insertion_mode = str(analytics_config.get("insertion_mode") or "publish_and_deploy")
        effective_ga_measurement_id = _resolve_effective_ga_measurement_id(
            site=site,
            workspace=workspace,
            override_measurement_id=None,
            phase="deploy",
        )
        duplicate_active_record = None
        stale_unverified_dispatch_record = None
        stale_active_dispatch_record = None
        if not dry_run:
            (
                duplicate_active_record,
                stale_unverified_dispatch_record,
                stale_active_dispatch_record,
            ) = _find_active_duplicate_deploy_attempt(
                history=workspace.deploy_history_json,
                artifact_version_id=artifact.id,
                target={
                    **deploy_target,
                    "inputs": deploy_inputs,
                },
            )
        if duplicate_active_record is not None:
            duplicate_post_dispatch_state = _normalize_string(
                duplicate_active_record.get("post_dispatch_state"), max_length=80
            ) or _derive_post_dispatch_state(
                dispatch_attempted=duplicate_active_record.get("dispatch_attempted"),
                dispatch_result_stage=duplicate_active_record.get("dispatch_result_stage"),
                workflow_run_id=duplicate_active_record.get("workflow_run_id"),
                workflow_run_status=duplicate_active_record.get("workflow_run_status"),
                workflow_run_conclusion=duplicate_active_record.get("workflow_run_conclusion"),
                resolved_live_url=duplicate_active_record.get("resolved_live_url"),
                workflow_run_lookup_attempted=duplicate_active_record.get("workflow_run_lookup_attempted"),
                workflow_run_found=duplicate_active_record.get("workflow_run_found"),
            )
            duplicate_dispatch_result_stage = _normalize_deploy_failure_stage(
                duplicate_active_record.get("dispatch_result_stage")
            )
            duplicate_workflow_run_status = _normalize_string(
                duplicate_active_record.get("workflow_run_status"),
                max_length=40,
            )
            duplicate_workflow_run_conclusion = _normalize_string(
                duplicate_active_record.get("workflow_run_conclusion"),
                max_length=40,
            )
            duplicate_workflow_run_id = _coerce_int(duplicate_active_record.get("workflow_run_id"))
            duplicate_deploy_trace_id = _normalize_string(
                duplicate_active_record.get("deploy_trace_id"),
                max_length=80,
            )
            stale_threshold_seconds = _derive_duplicate_blocker_stale_threshold_seconds(item=duplicate_active_record)
            duplicate_stale_observability = _build_deploy_history_stale_observability(
                item=duplicate_active_record,
                now=utc_now(),
                stale_after_seconds=stale_threshold_seconds,
            )
            duplicate_stale_observability["blocking_treated_as_stale"] = False
            failure_message = _build_active_duplicate_deploy_message(
                post_dispatch_state=duplicate_post_dispatch_state,
                dispatch_result_stage=duplicate_dispatch_result_stage,
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
                target_summary={
                    **deploy_target,
                    "inputs": _normalize_history_inputs(deploy_inputs),
                    "resolved_workflow_source": workflow_resolution.get("source"),
                    "workflow_identifier": workflow_identifier,
                    "deploy_trace_id": deploy_trace_id,
                    "blocking_post_dispatch_state": duplicate_post_dispatch_state,
                    "blocking_dispatch_result_stage": duplicate_dispatch_result_stage,
                    "blocking_workflow_run_id": duplicate_workflow_run_id,
                    "blocking_workflow_run_status": duplicate_workflow_run_status,
                    "blocking_workflow_run_conclusion": duplicate_workflow_run_conclusion,
                    "blocking_deploy_trace_id": duplicate_deploy_trace_id,
                    "blocking_timestamp": _normalize_string(
                        duplicate_active_record.get("timestamp"),
                        max_length=64,
                    ),
                    "blocking_dispatched_at": _normalize_string(
                        duplicate_active_record.get("dispatched_at"),
                        max_length=64,
                    ),
                    "blocking_refreshed_at": _normalize_string(
                        duplicate_active_record.get("refreshed_at"),
                        max_length=64,
                    ),
                    **duplicate_stale_observability,
                },
                failure_category="duplicate_request",
                failure_reason=failure_message,
                duration_ms=self._duration_ms(started_at),
                correlation_id=deploy_trace_id,
            )
            raise SEOMigrationValidationError(failure_message)
        if stale_active_dispatch_record is not None:
            stale_reference_field, stale_reference_at = _resolve_deploy_history_activity_reference(
                item=stale_active_dispatch_record
            )
            stale_active_observability = _build_deploy_history_stale_observability(
                item=stale_active_dispatch_record,
                now=utc_now(),
                stale_after_seconds=_DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS,
            )
            self._emit_structured_service_log(
                payload={
                    "event": "downgrade_to_stale_active_deploy_blocker",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "artifact_version": artifact.version,
                    "deploy_trace_id": deploy_trace_id,
                    "blocking_deploy_trace_id": _normalize_string(
                        stale_active_dispatch_record.get("deploy_trace_id"),
                        max_length=80,
                    ),
                    "repo_owner": deploy_target["repo_owner"],
                    "repo_name": deploy_target["repo_name"],
                    "workflow_id": deploy_target["workflow_id"],
                    "ref": deploy_target["ref"],
                    "blocking_post_dispatch_state": _normalize_string(
                        stale_active_dispatch_record.get("post_dispatch_state"),
                        max_length=80,
                    ),
                    "stale_reference_field": stale_reference_field,
                    "stale_reference_at": stale_reference_at.isoformat() if stale_reference_at is not None else None,
                    "stale_threshold_seconds": _DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS,
                    "stale_age_seconds": stale_active_observability.get("blocking_stale_age_seconds"),
                    "stale_evaluated": stale_active_observability.get("blocking_stale_evaluated"),
                    "stale_is_stale": stale_active_observability.get("blocking_stale_is_stale"),
                    "blocking_treated_as_stale": True,
                },
                fallback_message="downgrade_to_stale_active_deploy_blocker",
                level=logging.INFO,
            )
        if stale_unverified_dispatch_record is not None:
            stale_reference_field, stale_reference_at = _resolve_deploy_history_activity_reference(
                item=stale_unverified_dispatch_record
            )
            stale_unverified_observability = _build_deploy_history_stale_observability(
                item=stale_unverified_dispatch_record,
                now=utc_now(),
                stale_after_seconds=_DUPLICATE_DEPLOY_UNVERIFIED_DISPATCH_STALE_SECONDS,
            )
            self._emit_structured_service_log(
                payload={
                    "event": "downgrade_to_stale_unverified_dispatch",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "artifact_version": artifact.version,
                    "deploy_trace_id": deploy_trace_id,
                    "blocking_deploy_trace_id": _normalize_string(
                        stale_unverified_dispatch_record.get("deploy_trace_id"),
                        max_length=80,
                    ),
                    "repo_owner": deploy_target["repo_owner"],
                    "repo_name": deploy_target["repo_name"],
                    "workflow_id": deploy_target["workflow_id"],
                    "ref": deploy_target["ref"],
                    "stale_reference_field": stale_reference_field,
                    "stale_reference_at": stale_reference_at.isoformat() if stale_reference_at is not None else None,
                    "stale_threshold_seconds": _DUPLICATE_DEPLOY_UNVERIFIED_DISPATCH_STALE_SECONDS,
                    "stale_age_seconds": stale_unverified_observability.get("blocking_stale_age_seconds"),
                    "stale_evaluated": stale_unverified_observability.get("blocking_stale_evaluated"),
                    "stale_is_stale": stale_unverified_observability.get("blocking_stale_is_stale"),
                    "blocking_treated_as_stale": True,
                },
                fallback_message="downgrade_to_stale_unverified_dispatch",
                level=logging.INFO,
            )

        try:
            deploy_target_for_dispatch = SEOMigrationGitHubDeployTarget(
                repo_owner=deploy_target["repo_owner"],
                repo_name=deploy_target["repo_name"],
                workflow_id=(workflow_identifier_used or deploy_target["workflow_id"]),
                ref=deploy_target["ref"],
                inputs=deploy_inputs,
            )
            managed_gke_config_for_dispatch = _normalize_json_dict(workflow_resolution.get("managed_gke_config"))
            if not dry_run:
                target_readiness = self.github_publisher.check_deploy_target_readiness(
                    target=deploy_target_for_dispatch,
                    allow_ref_repair=False,
                    allow_workflow_repair=False,
                    dry_run=False,
                    remediation_mode="none",
                    managed_gke_config=managed_gke_config_for_dispatch,
                    namespace_isolation_defaults=namespace_isolation_defaults,
                )
                requested_ref = target_readiness.requested_ref
                resolved_ref = target_readiness.resolved_ref
                ref_source = target_readiness.ref_source
                workflow_dispatch_supported = target_readiness.workflow_dispatch_supported
                workflow_trigger_types = target_readiness.workflow_trigger_types
                dispatch_service_availability = target_readiness.dispatch_service_availability
                dispatch_service_reason_code = target_readiness.dispatch_service_reason_code
                workflow_conformance_checked = target_readiness.workflow_conformance_checked
                workflow_conformance_status = target_readiness.workflow_conformance_status
                workflow_conformance_reasons = list(target_readiness.workflow_conformance_reasons or ())
                workflow_conformance_evidence_summary = target_readiness.workflow_conformance_evidence_summary
                dispatch_identifier_type = target_readiness.dispatch_identifier_type
                workflow_identifier_used = _normalize_string(target_readiness.workflow_id, max_length=160)
                if workflow_identifier_type_used is None:
                    workflow_identifier_type_used = _normalize_string(
                        target_readiness.dispatch_identifier_type,
                        max_length=80,
                    )
                workflow_file_path = (
                    _normalize_workflow_path_for_deploy(target_readiness.workflow_path) or workflow_file_path
                )
                workflow_name = _workflow_id_from_path_for_deploy(workflow_file_path) or workflow_name
                if workflow_identifier_requested and workflow_identifier_used:
                    if workflow_identifier_requested != workflow_identifier_used:
                        workflow_dispatch_resolution_source = "workflow_file_path"
                    elif workflow_dispatch_resolution_source is None:
                        workflow_dispatch_resolution_source = "workflow_id"
                workflow_identifier = _derive_workflow_identifier(
                    workflow_id=workflow_identifier_used or target_readiness.workflow_id,
                    workflow_path=workflow_file_path or target_readiness.workflow_path,
                )
                self._log_target_readiness_check(
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    artifact_version_id=artifact.id,
                    repo_owner=target_readiness.repo_owner,
                    repo_name=target_readiness.repo_name,
                    requested_ref=target_readiness.requested_ref,
                    resolved_ref=target_readiness.resolved_ref,
                    ref_source=target_readiness.ref_source,
                    workflow_id=workflow_identifier_used or target_readiness.workflow_id,
                    workflow_path=workflow_file_path or target_readiness.workflow_path,
                    repo_exists=target_readiness.repo_exists,
                    ref_exists=target_readiness.ref_exists,
                    workflow_exists=target_readiness.workflow_exists,
                    workflow_dispatch_ready=target_readiness.workflow_dispatch_ready,
                    workflow_dispatch_supported=target_readiness.workflow_dispatch_supported,
                    workflow_trigger_types=target_readiness.workflow_trigger_types,
                    dispatch_service_availability=target_readiness.dispatch_service_availability,
                    dispatch_service_reason_code=target_readiness.dispatch_service_reason_code,
                    dispatch_identifier_type=target_readiness.dispatch_identifier_type,
                    workflow_identifier_requested=workflow_identifier_requested,
                    workflow_identifier_used=workflow_identifier_used,
                    workflow_identifier_type_requested=workflow_identifier_type_requested,
                    workflow_identifier_type_used=workflow_identifier_type_used,
                    workflow_dispatch_resolution_source=workflow_dispatch_resolution_source,
                    workflow_name=workflow_name,
                    workflow_conformance_checked=target_readiness.workflow_conformance_checked,
                    workflow_conformance_status=target_readiness.workflow_conformance_status,
                    workflow_conformance_reasons=target_readiness.workflow_conformance_reasons,
                    workflow_conformance_evidence_summary=target_readiness.workflow_conformance_evidence_summary,
                    kubernetes_namespace=target_readiness.kubernetes_namespace,
                    namespace_source=target_readiness.namespace_source,
                    namespace_model_status=target_readiness.namespace_model_status,
                    workflow_namespace_aligned=target_readiness.workflow_namespace_aligned,
                    manifest_namespace_aligned=target_readiness.manifest_namespace_aligned,
                    managed_resource_quota_expected=target_readiness.managed_resource_quota_expected,
                    managed_resource_quota_present=target_readiness.managed_resource_quota_present,
                    managed_limit_range_expected=target_readiness.managed_limit_range_expected,
                    managed_limit_range_present=target_readiness.managed_limit_range_present,
                    managed_network_policy_expected=target_readiness.managed_network_policy_expected,
                    managed_network_policy_present=target_readiness.managed_network_policy_present,
                    managed_namespace_policies_aligned=target_readiness.managed_namespace_policies_aligned,
                    deploy_trace_id=deploy_trace_id,
                    remediation_mode=target_readiness.remediation_mode,
                )
                publish_resolved_workflow_path = _normalize_workflow_path_for_deploy(
                    workflow_resolution.get("workflow_path")
                )
                publish_resolved_workflow_id = _workflow_id_from_path_for_deploy(
                    publish_resolved_workflow_path
                ) or _normalize_workflow_id_for_deploy(
                    workflow_resolution.get("workflow_id")
                )
                if publish_resolved_workflow_path is None:
                    publish_resolved_workflow_path = _normalize_workflow_path_for_deploy(
                        f".github/workflows/{str(publish_resolved_workflow_id or '').strip()}"
                    )
                publish_resolved_ref = _normalize_string(
                    workflow_resolution.get("resolved_ref"),
                    max_length=120,
                ) or _normalize_string(
                    deploy_target.get("ref"),
                    max_length=120,
                )
                readiness_resolved_workflow_path = _normalize_workflow_path_for_deploy(
                    target_readiness.workflow_path
                )
                readiness_resolved_workflow_id = _workflow_id_from_path_for_deploy(
                    readiness_resolved_workflow_path
                ) or _normalize_workflow_id_for_deploy(
                    target_readiness.workflow_id
                )
                if readiness_resolved_workflow_path is None:
                    readiness_resolved_workflow_path = _normalize_workflow_path_for_deploy(
                        f".github/workflows/{str(readiness_resolved_workflow_id or '').strip()}"
                    )
                readiness_resolved_ref = _normalize_string(
                    target_readiness.resolved_ref,
                    max_length=120,
                ) or _normalize_string(
                    target_readiness.requested_ref,
                    max_length=120,
                )
                workflow_candidate_alignment_exact = (
                    (publish_resolved_workflow_id or "") == (readiness_resolved_workflow_id or "")
                    and (publish_resolved_workflow_path or "") == (readiness_resolved_workflow_path or "")
                    and (publish_resolved_ref or "") == (readiness_resolved_ref or "")
                )
                self._emit_structured_service_log(
                    payload={
                        "event": "seo_migration_workflow_candidate_alignment",
                        "business_id": business_id,
                        "site_id": site_id,
                        "workspace_id": workspace.id,
                        "artifact_version_id": artifact.id,
                        "resolved_workflow_source": _normalize_string(
                            workflow_resolution.get("source"),
                            max_length=60,
                        ),
                        "publish_resolved_workflow_id": publish_resolved_workflow_id,
                        "publish_resolved_workflow_path": publish_resolved_workflow_path,
                        "publish_resolved_ref": publish_resolved_ref,
                        "publish_history_workflow_id": _normalize_workflow_id_for_deploy(
                            workflow_resolution.get("history_workflow_id")
                        ),
                        "publish_history_workflow_path": _normalize_workflow_path_for_deploy(
                            workflow_resolution.get("history_workflow_path")
                        ),
                        "readiness_resolved_workflow_id": readiness_resolved_workflow_id,
                        "readiness_resolved_workflow_path": readiness_resolved_workflow_path,
                        "readiness_resolved_ref": readiness_resolved_ref,
                        "workflow_candidate_alignment_exact": workflow_candidate_alignment_exact,
                        "deploy_trace_id": deploy_trace_id,
                    },
                    fallback_message="seo_migration_workflow_candidate_alignment",
                    level=logging.INFO,
                )
                deploy_target_for_dispatch = SEOMigrationGitHubDeployTarget(
                    repo_owner=deploy_target_for_dispatch.repo_owner,
                    repo_name=deploy_target_for_dispatch.repo_name,
                    workflow_id=(workflow_identifier_used or deploy_target_for_dispatch.workflow_id),
                    ref=deploy_target_for_dispatch.ref,
                    inputs=deploy_inputs,
                )
            actual_dispatch_identifier_sent = _normalize_string(
                normalize_workflow_dispatch_identifier_for_api(deploy_target_for_dispatch.workflow_id),
                max_length=200,
            ) or _normalize_string(deploy_target_for_dispatch.workflow_id, max_length=200)
            actual_dispatch_identifier_type_sent = _infer_dispatch_identifier_type(actual_dispatch_identifier_sent)
            if not actual_dispatch_identifier_type_sent:
                actual_dispatch_identifier_type_sent = _normalize_string(dispatch_identifier_type, max_length=80)
            dispatch_ref_sent = _normalize_string(deploy_target_for_dispatch.ref, max_length=120)
            self._emit_structured_service_log(
                payload={
                    "event": "seo_migration_deploy_dispatch_preflight",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "repo_owner": deploy_target_for_dispatch.repo_owner,
                    "repo_name": deploy_target_for_dispatch.repo_name,
                    "requested_ref": requested_ref,
                    "resolved_ref": resolved_ref,
                    "ref_source": ref_source,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_file_path": workflow_file_path,
                    "workflow_name": workflow_name,
                    "workflow_conformance_checked": workflow_conformance_checked,
                    "workflow_conformance_status": workflow_conformance_status,
                    "workflow_conformance_reasons": list(workflow_conformance_reasons),
                    "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                    "dispatch_identifier_type": dispatch_identifier_type,
                    "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                    "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                    "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                    "post_conformance_stage": _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED,
                    "post_conformance_reason_text": "Workflow dispatch was attempted; awaiting run evidence.",
                    "deploy_trace_id": deploy_trace_id,
                },
                fallback_message="seo_migration_deploy_dispatch_preflight",
                level=logging.INFO,
            )
            deploy_result = self.github_publisher.dispatch_deploy(
                target=deploy_target_for_dispatch,
                dry_run=dry_run,
                managed_gke_config=managed_gke_config_for_dispatch,
            )
            dispatch_attempted = not dry_run
            dispatch_result_stage = "workflow_dispatch" if not dry_run else "dry_run"
            workflow_run_lookup_attempted = not dry_run
            workflow_run_found = _coerce_int(getattr(deploy_result, "workflow_run_id", None)) is not None
            workflow_job_failure_detected = _derive_workflow_job_failure_detected(
                workflow_run_status=getattr(deploy_result, "workflow_run_status", None),
                workflow_run_conclusion=getattr(deploy_result, "workflow_run_conclusion", None),
            )
            workflow_run_failure_reason_code = _normalize_workflow_run_failure_reason_code(
                getattr(deploy_result, "workflow_run_failure_reason_code", None)
            )
            workflow_run_failure_stage = _normalize_workflow_run_failure_stage(
                getattr(deploy_result, "workflow_run_failure_stage", None)
            )
            workflow_run_failure_step = _normalize_string(
                getattr(deploy_result, "workflow_run_failure_step", None),
                max_length=200,
            )
            if workflow_job_failure_detected and workflow_run_failure_reason_code is None:
                workflow_run_failure_reason_code = _DEPLOY_RUN_FAILURE_REASON_GENERIC
            if workflow_job_failure_detected and workflow_run_failure_stage is None:
                workflow_run_failure_stage = _DEPLOY_RUN_FAILURE_STAGE_WORKFLOW_EXECUTION
            if dispatch_service_availability is None:
                if dry_run:
                    runtime_diagnostics = self._runtime_publisher_diagnostics(action="deploy")
                    dispatch_service_availability = bool(runtime_diagnostics.get("configured"))
                    if dispatch_service_reason_code is None:
                        dispatch_service_reason_code = _derive_dispatch_service_reason_code(
                            runtime_reason_code=str(runtime_diagnostics.get("reason_code") or ""),
                            target_valid=True,
                            target_enabled=True,
                            dispatch_service_availability=dispatch_service_availability,
                        )
                else:
                    dispatch_service_availability = True
            if dispatch_service_reason_code is None:
                dispatch_service_reason_code = (
                    _DEPLOY_DISPATCH_SERVICE_REASON_AVAILABLE
                    if dispatch_service_availability
                    else _DEPLOY_DISPATCH_SERVICE_REASON_RUNTIME_UNAVAILABLE
                )
        except SEOMigrationGitHubPublisherError as exc:
            failure_category = self._categorize_publisher_failure(exc=exc, action="deploy")
            failure_reason_code = _normalize_deploy_failure_reason_code(exc.code)
            failure_stage = _normalize_deploy_failure_stage(exc.stage)
            dispatch_attempted = failure_stage == "workflow_dispatch"
            dispatch_result_stage = failure_stage or "workflow_dispatch"
            workflow_run_lookup_attempted = False
            workflow_run_found = False
            workflow_job_failure_detected = False
            if dispatch_ref_sent is None:
                dispatch_ref_sent = _normalize_string(deploy_target.get("ref"), max_length=120)
            if not dry_run:
                repo_exists = failure_stage not in {"repo_lookup"}
                ref_exists = failure_stage not in {"repo_lookup", "ref_lookup"}
                workflow_exists = failure_stage not in {"repo_lookup", "ref_lookup", "workflow_lookup"}
                workflow_dispatch_ready = failure_stage not in {"repo_lookup", "ref_lookup", "workflow_lookup"}
                if failure_stage == "workflow_lookup" and failure_reason_code in {
                    _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE,
                    _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED,
                    _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY,
                }:
                    # Workflow lookup completed against an existing workflow, but dispatch
                    # requirements were not met (for example non-dispatchable trigger/contract).
                    workflow_exists = True
                    workflow_dispatch_ready = False
                workflow_dispatch_supported = (
                    target_readiness.workflow_dispatch_supported
                    if target_readiness is not None
                    else failure_stage not in {"repo_lookup", "ref_lookup", "workflow_lookup", "workflow_dispatch"}
                )
                workflow_trigger_types = target_readiness.workflow_trigger_types if target_readiness is not None else ()
                workflow_conformance_checked = (
                    target_readiness.workflow_conformance_checked
                    if target_readiness is not None
                    else workflow_conformance_checked
                )
                workflow_conformance_status = (
                    target_readiness.workflow_conformance_status
                    if target_readiness is not None
                    else workflow_conformance_status
                )
                workflow_conformance_reasons = (
                    list(target_readiness.workflow_conformance_reasons or ())
                    if target_readiness is not None
                    else workflow_conformance_reasons
                )
                workflow_conformance_evidence_summary = (
                    target_readiness.workflow_conformance_evidence_summary
                    if target_readiness is not None
                    else workflow_conformance_evidence_summary
                )
                if (
                    failure_reason_code == _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY
                    and workflow_conformance_status is None
                ):
                    workflow_conformance_checked = True
                    workflow_conformance_status = "workflow_placeholder_detected"
                    if not workflow_conformance_reasons:
                        workflow_conformance_reasons = ["placeholder_workflow_content_detected"]
                dispatch_identifier_type = (
                    target_readiness.dispatch_identifier_type if target_readiness is not None else "workflow_id"
                )
                if dispatch_service_availability is None:
                    dispatch_service_availability = (
                        target_readiness.dispatch_service_availability if target_readiness is not None else False
                    )
                if dispatch_service_reason_code is None:
                    dispatch_service_reason_code = _normalize_dispatch_service_reason_code(
                        target_readiness.dispatch_service_reason_code if target_readiness is not None else None
                    ) or _derive_dispatch_service_reason_code(
                        runtime_reason_code="",
                        target_valid=repo_exists and ref_exists and workflow_exists,
                        target_enabled=True,
                        dispatch_service_availability=bool(dispatch_service_availability),
                        failure_reason_code=failure_reason_code,
                        failure_stage=failure_stage,
                    )
                self._log_target_readiness_check(
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    artifact_version_id=artifact.id,
                    repo_owner=deploy_target["repo_owner"],
                    repo_name=deploy_target["repo_name"],
                    requested_ref=requested_ref or str(deploy_target.get("ref") or ""),
                    resolved_ref=resolved_ref or str(deploy_target.get("ref") or ""),
                    ref_source=ref_source or "requested",
                    workflow_id=workflow_identifier_used or deploy_target["workflow_id"],
                    workflow_path=(
                        workflow_file_path
                        or (
                            target_readiness.workflow_path
                            if target_readiness is not None
                            else workflow_resolution.get("workflow_path")
                        )
                    ),
                    repo_exists=repo_exists,
                    ref_exists=ref_exists,
                    workflow_exists=workflow_exists,
                    workflow_dispatch_ready=workflow_dispatch_ready,
                    workflow_dispatch_supported=workflow_dispatch_supported,
                    workflow_trigger_types=workflow_trigger_types,
                    dispatch_service_availability=dispatch_service_availability,
                    dispatch_service_reason_code=dispatch_service_reason_code,
                    dispatch_identifier_type=dispatch_identifier_type,
                    workflow_identifier_requested=workflow_identifier_requested,
                    workflow_identifier_used=workflow_identifier_used,
                    workflow_identifier_type_requested=workflow_identifier_type_requested,
                    workflow_identifier_type_used=workflow_identifier_type_used,
                    workflow_dispatch_resolution_source=workflow_dispatch_resolution_source,
                    workflow_name=workflow_name,
                    workflow_conformance_checked=workflow_conformance_checked,
                    workflow_conformance_status=workflow_conformance_status,
                    workflow_conformance_reasons=workflow_conformance_reasons,
                    workflow_conformance_evidence_summary=workflow_conformance_evidence_summary,
                    kubernetes_namespace=(
                        target_readiness.kubernetes_namespace
                        if target_readiness is not None
                        else _normalize_string(workflow_resolution.get("kubernetes_namespace"), max_length=63)
                    ),
                    namespace_source=(
                        target_readiness.namespace_source
                        if target_readiness is not None
                        else _normalize_string(workflow_resolution.get("namespace_source"), max_length=60)
                    ),
                    namespace_model_status=(
                        target_readiness.namespace_model_status
                        if target_readiness is not None
                        else _normalize_string(workflow_resolution.get("namespace_model_status"), max_length=40)
                    ),
                    workflow_namespace_aligned=(
                        target_readiness.workflow_namespace_aligned
                        if target_readiness is not None
                        else None
                    ),
                    manifest_namespace_aligned=(
                        target_readiness.manifest_namespace_aligned
                        if target_readiness is not None
                        else None
                    ),
                    managed_resource_quota_expected=(
                        target_readiness.managed_resource_quota_expected
                        if target_readiness is not None
                        else None
                    ),
                    managed_resource_quota_present=(
                        target_readiness.managed_resource_quota_present
                        if target_readiness is not None
                        else None
                    ),
                    managed_limit_range_expected=(
                        target_readiness.managed_limit_range_expected
                        if target_readiness is not None
                        else None
                    ),
                    managed_limit_range_present=(
                        target_readiness.managed_limit_range_present
                        if target_readiness is not None
                        else None
                    ),
                    managed_network_policy_expected=(
                        target_readiness.managed_network_policy_expected
                        if target_readiness is not None
                        else None
                    ),
                    managed_network_policy_present=(
                        target_readiness.managed_network_policy_present
                        if target_readiness is not None
                        else None
                    ),
                    managed_namespace_policies_aligned=(
                        target_readiness.managed_namespace_policies_aligned
                        if target_readiness is not None
                        else None
                    ),
                    deploy_trace_id=deploy_trace_id,
                    remediation_mode="none",
                )
            if dispatch_service_reason_code is None:
                dispatch_service_reason_code = _derive_dispatch_service_reason_code(
                    runtime_reason_code=str(
                        self._runtime_publisher_diagnostics(action="deploy").get("reason_code") or ""
                    ),
                    target_valid=True,
                    target_enabled=True,
                    dispatch_service_availability=bool(dispatch_service_availability),
                    failure_reason_code=failure_reason_code,
                    failure_stage=failure_stage,
                )
            failure_reason_for_log = (
                f"{failure_reason_code}: {exc.safe_message}" if failure_reason_code else exc.safe_message
            )
            failure_remediation_hint = _derive_deploy_failure_remediation_hint(
                failure_reason=failure_reason_code,
                failure_stage=failure_stage,
                workflow_exists=workflow_exists if not dry_run else None,
                dispatch_service_reason_code=dispatch_service_reason_code,
            )
            post_dispatch_state = _derive_post_dispatch_state(
                dispatch_attempted=dispatch_attempted,
                dispatch_result_stage=dispatch_result_stage,
                workflow_run_id=None,
                workflow_run_status=None,
                workflow_run_conclusion=None,
                resolved_live_url=None,
                workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                workflow_run_found=workflow_run_found,
            )
            (
                deploy_evidence_contract_status,
                deploy_evidence_contract_reasons,
                workflow_contract_advisory,
            ) = _derive_deploy_evidence_contract(
                workflow_conformance_status=workflow_conformance_status,
                post_dispatch_state=post_dispatch_state,
                resolved_live_url=None,
                url_source=expected_publish_url_source,
            )
            post_conformance_stage = _derive_post_conformance_stage(
                workflow_conformance_status=workflow_conformance_status,
                dispatch_attempted=dispatch_attempted,
                dispatch_result_stage=dispatch_result_stage,
                failure_stage=failure_stage,
                post_dispatch_state=post_dispatch_state,
                workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                workflow_run_failure_stage=workflow_run_failure_stage,
                deploy_evidence_contract_status=deploy_evidence_contract_status,
            )
            post_conformance_reason_text = _derive_post_conformance_reason_text(
                post_conformance_stage=post_conformance_stage,
                workflow_run_failure_reason_code=workflow_run_failure_reason_code,
                workflow_run_failure_stage=workflow_run_failure_stage,
                post_dispatch_state=post_dispatch_state,
            )
            post_conformance_remediation_message = _derive_post_conformance_remediation_message(
                post_conformance_stage=post_conformance_stage
            )
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
                    "workflow_id": workflow_identifier_used or deploy_target["workflow_id"],
                    "configured_workflow_id": deploy_target["workflow_id"],
                    "workflow_path": workflow_file_path or workflow_resolution.get("workflow_path"),
                    "workflow_file_path": workflow_file_path or workflow_resolution.get("workflow_path"),
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_name": workflow_name,
                    "workflow_conformance_checked": workflow_conformance_checked,
                    "workflow_conformance_status": workflow_conformance_status,
                    "workflow_conformance_reasons": list(workflow_conformance_reasons),
                    "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                    "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                    "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                    "ref": deploy_target["ref"],
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "requested_ref": requested_ref,
                    "resolved_ref": resolved_ref,
                    "ref_source": ref_source,
                    "inputs": deploy_inputs,
                    "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                    "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                    "analytics_measurement_id": effective_ga_measurement_id,
                    "analytics_insertion_mode": analytics_insertion_mode,
                    "expected_publish_url": expected_publish_url,
                    "resolved_live_url": resolved_live_url,
                    "url_source": expected_publish_url_source,
                    "url_source_detail": expected_publish_url_source_detail,
                    "deploy_trace_id": deploy_trace_id,
                    "workflow_dispatch_supported": workflow_dispatch_supported,
                    "workflow_trigger_types": list(workflow_trigger_types),
                    "dispatch_service_availability": dispatch_service_availability,
                    "dispatch_service_reason_code": dispatch_service_reason_code,
                    "dispatch_identifier_type": dispatch_identifier_type,
                    "dispatch_attempted": dispatch_attempted,
                    "dispatch_result_stage": dispatch_result_stage,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "workflow_job_failure_detected": workflow_job_failure_detected,
                    "post_dispatch_state": post_dispatch_state,
                    "post_conformance_stage": post_conformance_stage,
                    "post_conformance_reason_text": post_conformance_reason_text,
                    "post_conformance_remediation_message": post_conformance_remediation_message,
                    "expected_workflow_outputs": expected_workflow_outputs,
                    "deploy_evidence_contract_status": deploy_evidence_contract_status,
                    "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                    "workflow_contract_advisory": workflow_contract_advisory,
                    "repo_exists": repo_exists if not dry_run else None,
                    "ref_exists": ref_exists if not dry_run else None,
                    "workflow_exists": workflow_exists if not dry_run else None,
                    "workflow_dispatch_ready": workflow_dispatch_ready if not dry_run else None,
                    "failure_category": failure_category,
                    "failure_reason": failure_reason_code,
                    "failure_stage": failure_stage,
                    "failure_remediation_hint": failure_remediation_hint,
                    "error": exc.safe_message,
                    "error_summary": exc.safe_message,
                    "resolved_workflow_source": workflow_resolution.get("source"),
                    "deploy_workflow_mode": workflow_resolution.get("deploy_workflow_mode"),
                    "target_environment_key": workflow_resolution.get("target_environment_key"),
                    "target_environment_source": workflow_resolution.get("target_environment_source"),
                    "site_workflow_file_path": workflow_resolution.get("site_specific_workflow_path"),
                    "kubernetes_namespace": (
                        target_readiness.kubernetes_namespace
                        if target_readiness is not None
                        else workflow_resolution.get("kubernetes_namespace")
                    ),
                    "namespace_source": (
                        target_readiness.namespace_source
                        if target_readiness is not None
                        else workflow_resolution.get("namespace_source")
                    ),
                    "namespace_model_status": (
                        target_readiness.namespace_model_status
                        if target_readiness is not None
                        else workflow_resolution.get("namespace_model_status")
                    ),
                    "workflow_namespace_aligned": (
                        target_readiness.workflow_namespace_aligned if target_readiness is not None else None
                    ),
                    "manifest_namespace_aligned": (
                        target_readiness.manifest_namespace_aligned if target_readiness is not None else None
                    ),
                    "managed_resource_quota_expected": (
                        target_readiness.managed_resource_quota_expected if target_readiness is not None else None
                    ),
                    "managed_resource_quota_present": (
                        target_readiness.managed_resource_quota_present if target_readiness is not None else None
                    ),
                    "managed_limit_range_expected": (
                        target_readiness.managed_limit_range_expected if target_readiness is not None else None
                    ),
                    "managed_limit_range_present": (
                        target_readiness.managed_limit_range_present if target_readiness is not None else None
                    ),
                    "managed_network_policy_expected": (
                        target_readiness.managed_network_policy_expected if target_readiness is not None else None
                    ),
                    "managed_network_policy_present": (
                        target_readiness.managed_network_policy_present if target_readiness is not None else None
                    ),
                    "managed_namespace_policies_aligned": (
                        target_readiness.managed_namespace_policies_aligned if target_readiness is not None else None
                    ),
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
                    "workflow_id": workflow_identifier_used or deploy_target["workflow_id"],
                    "workflow_path": (
                        workflow_file_path
                        or (
                            target_readiness.workflow_path
                            if target_readiness is not None
                            else workflow_resolution.get("workflow_path")
                        )
                    ),
                    "workflow_file_path": (
                        workflow_file_path
                        or (
                            target_readiness.workflow_path
                            if target_readiness is not None
                            else workflow_resolution.get("workflow_path")
                        )
                    ),
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_name": workflow_name,
                    "workflow_conformance_checked": workflow_conformance_checked,
                    "workflow_conformance_status": workflow_conformance_status,
                    "workflow_conformance_reasons": list(workflow_conformance_reasons),
                    "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                    "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                    "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                    "ref": deploy_target["ref"],
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "requested_ref": requested_ref,
                    "resolved_ref": resolved_ref,
                    "ref_source": ref_source,
                    "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                    "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                    "resolved_workflow_source": workflow_resolution.get("source"),
                    "deploy_workflow_mode": workflow_resolution.get("deploy_workflow_mode"),
                    "target_environment_key": workflow_resolution.get("target_environment_key"),
                    "target_environment_source": workflow_resolution.get("target_environment_source"),
                    "site_workflow_file_path": workflow_resolution.get("site_specific_workflow_path"),
                    "kubernetes_namespace": (
                        target_readiness.kubernetes_namespace
                        if target_readiness is not None
                        else workflow_resolution.get("kubernetes_namespace")
                    ),
                    "namespace_source": (
                        target_readiness.namespace_source
                        if target_readiness is not None
                        else workflow_resolution.get("namespace_source")
                    ),
                    "namespace_model_status": (
                        target_readiness.namespace_model_status
                        if target_readiness is not None
                        else workflow_resolution.get("namespace_model_status")
                    ),
                    "workflow_namespace_aligned": (
                        target_readiness.workflow_namespace_aligned if target_readiness is not None else None
                    ),
                    "manifest_namespace_aligned": (
                        target_readiness.manifest_namespace_aligned if target_readiness is not None else None
                    ),
                    "managed_resource_quota_expected": (
                        target_readiness.managed_resource_quota_expected if target_readiness is not None else None
                    ),
                    "managed_resource_quota_present": (
                        target_readiness.managed_resource_quota_present if target_readiness is not None else None
                    ),
                    "managed_limit_range_expected": (
                        target_readiness.managed_limit_range_expected if target_readiness is not None else None
                    ),
                    "managed_limit_range_present": (
                        target_readiness.managed_limit_range_present if target_readiness is not None else None
                    ),
                    "managed_network_policy_expected": (
                        target_readiness.managed_network_policy_expected if target_readiness is not None else None
                    ),
                    "managed_network_policy_present": (
                        target_readiness.managed_network_policy_present if target_readiness is not None else None
                    ),
                    "managed_namespace_policies_aligned": (
                        target_readiness.managed_namespace_policies_aligned if target_readiness is not None else None
                    ),
                    "deploy_trace_id": deploy_trace_id,
                    "workflow_dispatch_supported": workflow_dispatch_supported,
                    "workflow_trigger_types": list(workflow_trigger_types),
                    "dispatch_service_availability": dispatch_service_availability,
                    "dispatch_service_reason_code": dispatch_service_reason_code,
                    "dispatch_identifier_type": dispatch_identifier_type,
                    "dispatch_attempted": dispatch_attempted,
                    "dispatch_result_stage": dispatch_result_stage,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "workflow_job_failure_detected": workflow_job_failure_detected,
                    "post_dispatch_state": post_dispatch_state,
                    "post_conformance_stage": post_conformance_stage,
                    "post_conformance_reason_text": post_conformance_reason_text,
                    "post_conformance_remediation_message": post_conformance_remediation_message,
                    "expected_workflow_outputs": expected_workflow_outputs,
                    "deploy_evidence_contract_status": deploy_evidence_contract_status,
                    "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                    "workflow_contract_advisory": workflow_contract_advisory,
                    "failure_reason_code": failure_reason_code,
                    "failure_stage": failure_stage,
                    "failure_remediation_hint": failure_remediation_hint,
                    "expected_publish_url": expected_publish_url,
                    "resolved_live_url": resolved_live_url,
                    "url_source": expected_publish_url_source,
                    "url_source_detail": expected_publish_url_source_detail,
                },
                failure_category=failure_category,
                failure_reason=failure_reason_for_log,
                duration_ms=self._duration_ms(started_at),
                correlation_id=deploy_trace_id,
            )
            self._emit_structured_service_log(
                payload={
                    "event": "seo_migration_deploy_dispatch_failed",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "repo_owner": deploy_target["repo_owner"],
                    "repo_name": deploy_target["repo_name"],
                    "workflow_id": workflow_identifier_used or deploy_target["workflow_id"],
                    "workflow_path": (
                        workflow_file_path
                        or (
                            target_readiness.workflow_path
                            if target_readiness is not None
                            else workflow_resolution.get("workflow_path")
                        )
                    ),
                    "workflow_file_path": (
                        workflow_file_path
                        or (
                            target_readiness.workflow_path
                            if target_readiness is not None
                            else workflow_resolution.get("workflow_path")
                        )
                    ),
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_name": workflow_name,
                    "workflow_conformance_checked": workflow_conformance_checked,
                    "workflow_conformance_status": workflow_conformance_status,
                    "workflow_conformance_reasons": list(workflow_conformance_reasons),
                    "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                    "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                    "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                    "ref": deploy_target["ref"],
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "requested_ref": requested_ref,
                    "resolved_ref": resolved_ref,
                    "ref_source": ref_source,
                    "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                    "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                    "resolved_workflow_source": workflow_resolution.get("source"),
                    "deploy_workflow_mode": workflow_resolution.get("deploy_workflow_mode"),
                    "target_environment_key": workflow_resolution.get("target_environment_key"),
                    "target_environment_source": workflow_resolution.get("target_environment_source"),
                    "site_workflow_file_path": workflow_resolution.get("site_specific_workflow_path"),
                    "kubernetes_namespace": (
                        target_readiness.kubernetes_namespace
                        if target_readiness is not None
                        else workflow_resolution.get("kubernetes_namespace")
                    ),
                    "namespace_source": (
                        target_readiness.namespace_source
                        if target_readiness is not None
                        else workflow_resolution.get("namespace_source")
                    ),
                    "namespace_model_status": (
                        target_readiness.namespace_model_status
                        if target_readiness is not None
                        else workflow_resolution.get("namespace_model_status")
                    ),
                    "workflow_namespace_aligned": (
                        target_readiness.workflow_namespace_aligned if target_readiness is not None else None
                    ),
                    "manifest_namespace_aligned": (
                        target_readiness.manifest_namespace_aligned if target_readiness is not None else None
                    ),
                    "deploy_trace_id": deploy_trace_id,
                    "workflow_dispatch_supported": workflow_dispatch_supported,
                    "workflow_trigger_types": list(workflow_trigger_types),
                    "dispatch_service_availability": dispatch_service_availability,
                    "dispatch_service_reason_code": dispatch_service_reason_code,
                    "dispatch_identifier_type": dispatch_identifier_type,
                    "dispatch_attempted": dispatch_attempted,
                    "dispatch_result_stage": dispatch_result_stage,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "workflow_job_failure_detected": workflow_job_failure_detected,
                    "post_dispatch_state": post_dispatch_state,
                    "post_conformance_stage": post_conformance_stage,
                    "post_conformance_reason_text": post_conformance_reason_text,
                    "post_conformance_remediation_message": post_conformance_remediation_message,
                    "expected_workflow_outputs": expected_workflow_outputs,
                    "deploy_evidence_contract_status": deploy_evidence_contract_status,
                    "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                    "workflow_contract_advisory": workflow_contract_advisory,
                    "failure_reason_code": failure_reason_code,
                    "failure_stage": failure_stage,
                    "failure_category": failure_category,
                    "failure_message": exc.safe_message,
                    "failure_remediation_hint": failure_remediation_hint,
                    "expected_publish_url": expected_publish_url,
                    "resolved_live_url": resolved_live_url,
                    "url_source": expected_publish_url_source,
                    "url_source_detail": expected_publish_url_source_detail,
                },
                fallback_message="seo_migration_deploy_dispatch_failed",
                level=logging.WARNING,
            )
            raise SEOMigrationValidationError(exc.safe_message) from exc

        (
            resolved_live_url,
            resolved_live_url_source,
            resolved_live_url_source_detail,
        ) = self._resolve_deploy_live_url(
            deploy_result=deploy_result,
            expected_publish_url=expected_publish_url,
            expected_publish_url_source=expected_publish_url_source,
            expected_publish_url_source_detail=expected_publish_url_source_detail,
        )
        post_dispatch_state = _derive_post_dispatch_state(
            dispatch_attempted=dispatch_attempted,
            dispatch_result_stage=dispatch_result_stage,
            workflow_run_id=getattr(deploy_result, "workflow_run_id", None),
            workflow_run_status=getattr(deploy_result, "workflow_run_status", None),
            workflow_run_conclusion=getattr(deploy_result, "workflow_run_conclusion", None),
            resolved_live_url=resolved_live_url,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_found=workflow_run_found,
        )
        (
            deploy_evidence_contract_status,
            deploy_evidence_contract_reasons,
            workflow_contract_advisory,
        ) = _derive_deploy_evidence_contract(
            workflow_conformance_status=workflow_conformance_status,
            post_dispatch_state=post_dispatch_state,
            resolved_live_url=resolved_live_url,
            url_source=resolved_live_url_source,
        )
        workflow_run_failure_hint = _derive_workflow_run_failure_hint(
            failure_reason=workflow_run_failure_reason_code,
            post_dispatch_state=post_dispatch_state,
        )
        post_conformance_stage = _derive_post_conformance_stage(
            workflow_conformance_status=workflow_conformance_status,
            dispatch_attempted=dispatch_attempted,
            dispatch_result_stage=dispatch_result_stage,
            failure_stage=None,
            post_dispatch_state=post_dispatch_state,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_failure_stage=workflow_run_failure_stage,
            deploy_evidence_contract_status=deploy_evidence_contract_status,
        )
        post_conformance_reason_text = _derive_post_conformance_reason_text(
            post_conformance_stage=post_conformance_stage,
            workflow_run_failure_reason_code=workflow_run_failure_reason_code,
            workflow_run_failure_stage=workflow_run_failure_stage,
            post_dispatch_state=post_dispatch_state,
        )
        post_conformance_remediation_message = _derive_post_conformance_remediation_message(
            post_conformance_stage=post_conformance_stage
        )
        dispatch_verification_state = _derive_dispatch_verification_state(
            dispatch_attempted=dispatch_attempted,
            workflow_run_id=getattr(deploy_result, "workflow_run_id", None),
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_found=workflow_run_found,
        )
        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_deploy_dispatch_accepted",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "repo_owner": deploy_result.repo_owner,
                "repo_name": deploy_result.repo_name,
                "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
                "workflow_identifier": workflow_identifier,
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": workflow_identifier_type_requested,
                "workflow_identifier_type_used": workflow_identifier_type_used,
                "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                "workflow_name": workflow_name,
                "workflow_conformance_checked": workflow_conformance_checked,
                "workflow_conformance_status": workflow_conformance_status,
                "workflow_conformance_reasons": list(workflow_conformance_reasons),
                "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                "ref": deploy_result.ref,
                "dispatch_ref_sent": dispatch_ref_sent,
                "requested_ref": requested_ref,
                "resolved_ref": resolved_ref,
                "ref_source": ref_source,
                "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                "deploy_trace_id": deploy_trace_id,
                "workflow_dispatch_supported": workflow_dispatch_supported,
                "workflow_trigger_types": list(workflow_trigger_types),
                "dispatch_service_availability": dispatch_service_availability,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "dispatch_identifier_type": dispatch_identifier_type,
                "dispatch_attempted": dispatch_attempted,
                "dispatch_result_stage": dispatch_result_stage,
                "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                "workflow_run_found": workflow_run_found,
                "dispatch_verification_state": dispatch_verification_state,
                "workflow_job_failure_detected": workflow_job_failure_detected,
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "expected_workflow_outputs": expected_workflow_outputs,
                "deploy_evidence_contract_status": deploy_evidence_contract_status,
                "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                "workflow_contract_advisory": workflow_contract_advisory,
                "dispatched_at": deploy_result.dispatched_at,
                "workflow_run_id": getattr(deploy_result, "workflow_run_id", None),
                "workflow_run_status": getattr(deploy_result, "workflow_run_status", None),
                "workflow_run_conclusion": getattr(deploy_result, "workflow_run_conclusion", None),
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
            },
            fallback_message="seo_migration_deploy_dispatch_accepted",
            level=logging.INFO,
        )
        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_workflow_run_lookup_attempted",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "repo_owner": deploy_result.repo_owner,
                "repo_name": deploy_result.repo_name,
                "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
                "workflow_identifier": workflow_identifier,
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": workflow_identifier_type_requested,
                "workflow_identifier_type_used": workflow_identifier_type_used,
                "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                "workflow_name": workflow_name,
                "workflow_conformance_checked": workflow_conformance_checked,
                "workflow_conformance_status": workflow_conformance_status,
                "workflow_conformance_reasons": list(workflow_conformance_reasons),
                "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                "ref": deploy_result.ref,
                "dispatch_ref_sent": dispatch_ref_sent,
                "requested_ref": requested_ref,
                "resolved_ref": resolved_ref,
                "ref_source": ref_source,
                "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                "deploy_trace_id": deploy_trace_id,
                "dispatch_attempted": dispatch_attempted,
                "dispatch_result_stage": dispatch_result_stage,
                "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                "workflow_run_found": workflow_run_found,
                "dispatch_verification_state": dispatch_verification_state,
                "workflow_job_failure_detected": workflow_job_failure_detected,
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "expected_workflow_outputs": expected_workflow_outputs,
                "deploy_evidence_contract_status": deploy_evidence_contract_status,
                "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                "workflow_contract_advisory": workflow_contract_advisory,
                "workflow_run_id": getattr(deploy_result, "workflow_run_id", None),
                "workflow_run_status": getattr(deploy_result, "workflow_run_status", None),
                "workflow_run_conclusion": getattr(deploy_result, "workflow_run_conclusion", None),
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
            },
            fallback_message="seo_migration_workflow_run_lookup_attempted",
            level=logging.INFO,
        )
        if dispatch_attempted and getattr(deploy_result, "workflow_run_id", None) is None:
            self._emit_structured_service_log(
                payload={
                    "event": "dispatch_attempted_without_run",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "repo_owner": deploy_result.repo_owner,
                    "repo_name": deploy_result.repo_name,
                    "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "ref": deploy_result.ref,
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "deploy_trace_id": deploy_trace_id,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "post_dispatch_state": post_dispatch_state,
                    "post_conformance_stage": post_conformance_stage,
                    "post_conformance_reason_text": post_conformance_reason_text,
                    "post_conformance_remediation_message": post_conformance_remediation_message,
                    "dispatch_verification_state": _derive_dispatch_verification_state(
                        dispatch_attempted=dispatch_attempted,
                        workflow_run_id=getattr(deploy_result, "workflow_run_id", None),
                        workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                        workflow_run_found=workflow_run_found,
                    ),
                },
                fallback_message="dispatch_attempted_without_run",
                level=logging.INFO,
            )
        if getattr(deploy_result, "workflow_run_id", None) is not None:
            self._emit_structured_service_log(
                payload={
                    "event": "seo_migration_workflow_run_result_captured",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "repo_owner": deploy_result.repo_owner,
                    "repo_name": deploy_result.repo_name,
                    "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_name": workflow_name,
                    "workflow_conformance_checked": workflow_conformance_checked,
                    "workflow_conformance_status": workflow_conformance_status,
                    "workflow_conformance_reasons": list(workflow_conformance_reasons),
                    "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                    "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                    "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                    "ref": deploy_result.ref,
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "requested_ref": requested_ref,
                    "resolved_ref": resolved_ref,
                    "ref_source": ref_source,
                    "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                    "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                    "deploy_trace_id": deploy_trace_id,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "dispatch_verification_state": dispatch_verification_state,
                    "workflow_job_failure_detected": workflow_job_failure_detected,
                    "post_dispatch_state": post_dispatch_state,
                    "post_conformance_stage": post_conformance_stage,
                    "post_conformance_reason_text": post_conformance_reason_text,
                    "post_conformance_remediation_message": post_conformance_remediation_message,
                    "expected_workflow_outputs": expected_workflow_outputs,
                    "deploy_evidence_contract_status": deploy_evidence_contract_status,
                    "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                    "workflow_contract_advisory": workflow_contract_advisory,
                    "workflow_run_id": getattr(deploy_result, "workflow_run_id", None),
                    "workflow_run_status": getattr(deploy_result, "workflow_run_status", None),
                    "workflow_run_conclusion": getattr(deploy_result, "workflow_run_conclusion", None),
                    "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                    "workflow_run_failure_stage": workflow_run_failure_stage,
                    "workflow_run_failure_step": workflow_run_failure_step,
                    "workflow_run_failure_hint": workflow_run_failure_hint,
                },
                fallback_message="seo_migration_workflow_run_result_captured",
                level=logging.INFO,
            )
        if resolved_live_url and resolved_live_url_source == _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT:
            self._emit_structured_service_log(
                payload={
                    "event": "seo_migration_workflow_output_url_captured",
                    "business_id": business_id,
                    "site_id": site_id,
                    "workspace_id": workspace.id,
                    "artifact_version_id": artifact.id,
                    "repo_owner": deploy_result.repo_owner,
                    "repo_name": deploy_result.repo_name,
                    "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
                    "workflow_identifier": workflow_identifier,
                    "workflow_identifier_requested": workflow_identifier_requested,
                    "workflow_identifier_used": workflow_identifier_used,
                    "workflow_identifier_type_requested": workflow_identifier_type_requested,
                    "workflow_identifier_type_used": workflow_identifier_type_used,
                    "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                    "workflow_name": workflow_name,
                    "workflow_conformance_checked": workflow_conformance_checked,
                    "workflow_conformance_status": workflow_conformance_status,
                    "workflow_conformance_reasons": list(workflow_conformance_reasons),
                    "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                    "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                    "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                    "ref": deploy_result.ref,
                    "dispatch_ref_sent": dispatch_ref_sent,
                    "requested_ref": requested_ref,
                    "resolved_ref": resolved_ref,
                    "ref_source": ref_source,
                    "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                    "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                    "deploy_trace_id": deploy_trace_id,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "dispatch_verification_state": dispatch_verification_state,
                    "workflow_job_failure_detected": workflow_job_failure_detected,
                    "post_dispatch_state": post_dispatch_state,
                    "post_conformance_stage": post_conformance_stage,
                    "post_conformance_reason_text": post_conformance_reason_text,
                    "post_conformance_remediation_message": post_conformance_remediation_message,
                    "expected_workflow_outputs": expected_workflow_outputs,
                    "deploy_evidence_contract_status": deploy_evidence_contract_status,
                    "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                    "workflow_contract_advisory": workflow_contract_advisory,
                    "workflow_run_id": getattr(deploy_result, "workflow_run_id", None),
                    "workflow_run_status": getattr(deploy_result, "workflow_run_status", None),
                    "workflow_run_conclusion": getattr(deploy_result, "workflow_run_conclusion", None),
                    "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                    "workflow_run_failure_stage": workflow_run_failure_stage,
                    "workflow_run_failure_step": workflow_run_failure_step,
                    "workflow_run_failure_hint": workflow_run_failure_hint,
                    "resolved_live_url": resolved_live_url,
                    "url_source": resolved_live_url_source,
                    "url_source_detail": resolved_live_url_source_detail,
                },
                fallback_message="seo_migration_workflow_output_url_captured",
                level=logging.INFO,
            )
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
            "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
            "configured_workflow_id": deploy_target["workflow_id"],
            "workflow_identifier": workflow_identifier,
            "workflow_identifier_requested": workflow_identifier_requested,
            "workflow_identifier_used": workflow_identifier_used,
            "workflow_identifier_type_requested": workflow_identifier_type_requested,
            "workflow_identifier_type_used": workflow_identifier_type_used,
            "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
            "workflow_name": workflow_name,
            "workflow_conformance_checked": workflow_conformance_checked,
            "workflow_conformance_status": workflow_conformance_status,
            "workflow_conformance_reasons": list(workflow_conformance_reasons),
            "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
            "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
            "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
            "workflow_path": (
                workflow_file_path
                or (
                    target_readiness.workflow_path
                    if target_readiness is not None
                    else workflow_resolution.get("workflow_path")
                )
            ),
            "workflow_file_path": (
                workflow_file_path
                or (
                    target_readiness.workflow_path
                    if target_readiness is not None
                    else workflow_resolution.get("workflow_path")
                )
            ),
            "ref": deploy_result.ref,
            "dispatch_ref_sent": dispatch_ref_sent,
            "requested_ref": requested_ref,
            "resolved_ref": resolved_ref,
            "ref_source": ref_source,
            "inputs": deploy_result.inputs,
            "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
            "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
            "deploy_trace_id": deploy_trace_id,
            "workflow_dispatch_supported": workflow_dispatch_supported,
            "workflow_trigger_types": list(workflow_trigger_types),
            "dispatch_service_availability": dispatch_service_availability,
            "dispatch_service_reason_code": dispatch_service_reason_code,
            "dispatch_identifier_type": dispatch_identifier_type,
            "dispatch_attempted": dispatch_attempted,
            "dispatch_result_stage": dispatch_result_stage,
            "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
            "workflow_run_found": workflow_run_found,
            "workflow_job_failure_detected": workflow_job_failure_detected,
            "dispatch_verification_state": dispatch_verification_state,
            "post_dispatch_state": post_dispatch_state,
            "post_conformance_stage": post_conformance_stage,
            "post_conformance_reason_text": post_conformance_reason_text,
            "post_conformance_remediation_message": post_conformance_remediation_message,
            "expected_workflow_outputs": expected_workflow_outputs,
            "deploy_evidence_contract_status": deploy_evidence_contract_status,
            "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
            "workflow_contract_advisory": workflow_contract_advisory,
            "repo_exists": target_readiness.repo_exists if target_readiness is not None else None,
            "ref_exists": target_readiness.ref_exists if target_readiness is not None else None,
            "workflow_exists": target_readiness.workflow_exists if target_readiness is not None else None,
            "workflow_dispatch_ready": (
                target_readiness.workflow_dispatch_ready if target_readiness is not None else None
            ),
            "analytics_measurement_id": effective_ga_measurement_id,
            "analytics_insertion_mode": analytics_insertion_mode,
            "analytics_applied": bool(effective_ga_measurement_id),
            "dispatched_at": deploy_result.dispatched_at,
            "resolved_workflow_source": workflow_resolution.get("source"),
            "deploy_workflow_mode": workflow_resolution.get("deploy_workflow_mode"),
            "target_environment_key": workflow_resolution.get("target_environment_key"),
            "target_environment_source": workflow_resolution.get("target_environment_source"),
            "site_workflow_file_path": workflow_resolution.get("site_specific_workflow_path"),
            "kubernetes_namespace": (
                target_readiness.kubernetes_namespace
                if target_readiness is not None
                else workflow_resolution.get("kubernetes_namespace")
            ),
            "namespace_source": (
                target_readiness.namespace_source
                if target_readiness is not None
                else workflow_resolution.get("namespace_source")
            ),
            "namespace_model_status": (
                target_readiness.namespace_model_status
                if target_readiness is not None
                else workflow_resolution.get("namespace_model_status")
            ),
            "workflow_namespace_aligned": (
                target_readiness.workflow_namespace_aligned if target_readiness is not None else None
            ),
            "manifest_namespace_aligned": (
                target_readiness.manifest_namespace_aligned if target_readiness is not None else None
            ),
            "managed_resource_quota_expected": (
                target_readiness.managed_resource_quota_expected if target_readiness is not None else None
            ),
            "managed_resource_quota_present": (
                target_readiness.managed_resource_quota_present if target_readiness is not None else None
            ),
            "managed_limit_range_expected": (
                target_readiness.managed_limit_range_expected if target_readiness is not None else None
            ),
            "managed_limit_range_present": (
                target_readiness.managed_limit_range_present if target_readiness is not None else None
            ),
            "managed_network_policy_expected": (
                target_readiness.managed_network_policy_expected if target_readiness is not None else None
            ),
            "managed_network_policy_present": (
                target_readiness.managed_network_policy_present if target_readiness is not None else None
            ),
            "managed_namespace_policies_aligned": (
                target_readiness.managed_namespace_policies_aligned if target_readiness is not None else None
            ),
            "workflow_run_id": getattr(deploy_result, "workflow_run_id", None),
            "workflow_run_status": getattr(deploy_result, "workflow_run_status", None),
            "workflow_run_conclusion": getattr(deploy_result, "workflow_run_conclusion", None),
            "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
            "workflow_run_failure_stage": workflow_run_failure_stage,
            "workflow_run_failure_step": workflow_run_failure_step,
            "workflow_run_failure_hint": workflow_run_failure_hint,
            "expected_publish_url": expected_publish_url,
            "resolved_live_url": resolved_live_url,
            "url_source": resolved_live_url_source,
            "url_source_detail": resolved_live_url_source_detail,
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
                "workflow_id": workflow_identifier_used or deploy_result.workflow_id,
                "workflow_identifier": workflow_identifier,
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": workflow_identifier_type_requested,
                "workflow_identifier_type_used": workflow_identifier_type_used,
                "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                "workflow_name": workflow_name,
                "workflow_conformance_checked": workflow_conformance_checked,
                "workflow_conformance_status": workflow_conformance_status,
                "workflow_conformance_reasons": list(workflow_conformance_reasons),
                "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
                "actual_dispatch_identifier_sent": actual_dispatch_identifier_sent,
                "actual_dispatch_identifier_type_sent": actual_dispatch_identifier_type_sent,
                "workflow_path": (
                    workflow_file_path
                    or (
                        target_readiness.workflow_path
                        if target_readiness is not None
                        else workflow_resolution.get("workflow_path")
                    )
                ),
                "workflow_file_path": (
                    workflow_file_path
                    or (
                        target_readiness.workflow_path
                        if target_readiness is not None
                        else workflow_resolution.get("workflow_path")
                    )
                ),
                "ref": deploy_result.ref,
                "dispatch_ref_sent": dispatch_ref_sent,
                "requested_ref": requested_ref,
                "resolved_ref": resolved_ref,
                "ref_source": ref_source,
                "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                "resolved_workflow_source": workflow_resolution.get("source"),
                "deploy_workflow_mode": workflow_resolution.get("deploy_workflow_mode"),
                "target_environment_key": workflow_resolution.get("target_environment_key"),
                "target_environment_source": workflow_resolution.get("target_environment_source"),
                "site_workflow_file_path": workflow_resolution.get("site_specific_workflow_path"),
                "kubernetes_namespace": (
                    target_readiness.kubernetes_namespace
                    if target_readiness is not None
                    else workflow_resolution.get("kubernetes_namespace")
                ),
                "namespace_source": (
                    target_readiness.namespace_source
                    if target_readiness is not None
                    else workflow_resolution.get("namespace_source")
                ),
                "namespace_model_status": (
                    target_readiness.namespace_model_status
                    if target_readiness is not None
                    else workflow_resolution.get("namespace_model_status")
                ),
                "workflow_namespace_aligned": (
                    target_readiness.workflow_namespace_aligned if target_readiness is not None else None
                ),
                "manifest_namespace_aligned": (
                    target_readiness.manifest_namespace_aligned if target_readiness is not None else None
                ),
                "managed_resource_quota_expected": (
                    target_readiness.managed_resource_quota_expected if target_readiness is not None else None
                ),
                "managed_resource_quota_present": (
                    target_readiness.managed_resource_quota_present if target_readiness is not None else None
                ),
                "managed_limit_range_expected": (
                    target_readiness.managed_limit_range_expected if target_readiness is not None else None
                ),
                "managed_limit_range_present": (
                    target_readiness.managed_limit_range_present if target_readiness is not None else None
                ),
                "managed_network_policy_expected": (
                    target_readiness.managed_network_policy_expected if target_readiness is not None else None
                ),
                "managed_network_policy_present": (
                    target_readiness.managed_network_policy_present if target_readiness is not None else None
                ),
                "managed_namespace_policies_aligned": (
                    target_readiness.managed_namespace_policies_aligned if target_readiness is not None else None
                ),
                "deploy_trace_id": deploy_trace_id,
                "workflow_dispatch_supported": workflow_dispatch_supported,
                "workflow_trigger_types": list(workflow_trigger_types),
                "dispatch_service_availability": dispatch_service_availability,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "dispatch_identifier_type": dispatch_identifier_type,
                "dispatch_attempted": dispatch_attempted,
                "dispatch_result_stage": dispatch_result_stage,
                    "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                    "workflow_run_found": workflow_run_found,
                    "dispatch_verification_state": dispatch_verification_state,
                "workflow_job_failure_detected": workflow_job_failure_detected,
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "expected_workflow_outputs": expected_workflow_outputs,
                "deploy_evidence_contract_status": deploy_evidence_contract_status,
                "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
                "workflow_contract_advisory": workflow_contract_advisory,
                "workflow_run_id": getattr(deploy_result, "workflow_run_id", None),
                "workflow_run_status": getattr(deploy_result, "workflow_run_status", None),
                "workflow_run_conclusion": getattr(deploy_result, "workflow_run_conclusion", None),
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
                "expected_publish_url": expected_publish_url,
                "resolved_live_url": resolved_live_url,
                "url_source": resolved_live_url_source,
                "url_source_detail": resolved_live_url_source_detail,
            },
            duration_ms=self._duration_ms(started_at),
            correlation_id=deploy_trace_id,
        )
        return SEOMigrationDeployActionResult(
            workspace=workspace,
            artifact=artifact,
            readiness=readiness,
            result=history_payload,
        )

    def refresh_deploy_run_status(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
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
            action="deploy_status_refresh",
            status="requested",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            target_summary={"artifact_version_id": artifact.id},
        )
        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_deploy_status_refresh_requested",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "artifact_version": artifact.version,
                "principal_id": principal_id,
            },
            fallback_message="seo_migration_deploy_status_refresh_requested",
            level=logging.INFO,
        )

        readiness = self._build_deploy_readiness(
            site=site,
            workspace=workspace,
            artifact=artifact,
        )
        normalized_history = _normalize_history_list(workspace.deploy_history_json)
        history_index = _find_latest_deploy_history_index_for_refresh(
            history=normalized_history,
            artifact_version_id=artifact.id,
        )
        if history_index is None:
            return self._build_deploy_refresh_no_change_result(
                business_id=business_id,
                site_id=site_id,
                workspace=workspace,
                artifact=artifact,
                readiness=readiness,
                started_at=started_at,
                reason_code="deploy_record_missing",
                reason_message="No deploy request record was found for this artifact.",
                principal_id=principal_id,
            )

        target_history_item = _normalize_json_dict(normalized_history[history_index])
        deploy_trace_id = _normalize_string(target_history_item.get("deploy_trace_id"), max_length=80)
        workflow_identifier = _derive_workflow_identifier(
            workflow_id=target_history_item.get("workflow_id"),
            workflow_path=target_history_item.get("workflow_path"),
        )
        workflow_identifier_requested = _normalize_string(
            target_history_item.get("workflow_identifier_requested"),
            max_length=200,
        ) or _normalize_string(target_history_item.get("workflow_id"), max_length=160)
        workflow_identifier_used = _normalize_string(
            target_history_item.get("workflow_identifier_used"),
            max_length=200,
        ) or _normalize_string(target_history_item.get("workflow_id"), max_length=160)
        workflow_identifier_type_requested = _normalize_string(
            target_history_item.get("workflow_identifier_type_requested"),
            max_length=80,
        ) or _infer_dispatch_identifier_type(workflow_identifier_requested)
        workflow_identifier_type_used = _normalize_string(
            target_history_item.get("workflow_identifier_type_used"),
            max_length=80,
        ) or _normalize_string(target_history_item.get("dispatch_identifier_type"), max_length=80)
        workflow_dispatch_resolution_source = _normalize_string(
            target_history_item.get("workflow_dispatch_resolution_source"),
            max_length=80,
        )
        workflow_file_path = _normalize_workflow_path_for_deploy(
            target_history_item.get("workflow_file_path")
        ) or _normalize_workflow_path_for_deploy(target_history_item.get("workflow_path"))
        workflow_name = _normalize_string(
            target_history_item.get("workflow_name"), max_length=160
        ) or _workflow_id_from_path_for_deploy(workflow_file_path)
        dispatch_service_availability = (
            bool(target_history_item.get("dispatch_service_availability"))
            if isinstance(target_history_item.get("dispatch_service_availability"), bool)
            else None
        )
        dispatch_service_reason_code = _normalize_dispatch_service_reason_code(
            target_history_item.get("dispatch_service_reason_code")
        )
        dispatch_attempted = (
            bool(target_history_item.get("dispatch_attempted"))
            if isinstance(target_history_item.get("dispatch_attempted"), bool)
            else None
        )
        dispatch_result_stage = _normalize_string(target_history_item.get("dispatch_result_stage"), max_length=40)
        dispatch_ref_sent = _normalize_string(
            target_history_item.get("dispatch_ref_sent"), max_length=120
        ) or _normalize_string(
            target_history_item.get("ref"),
            max_length=120,
        )
        workflow_inputs_configured_keys = _normalize_dispatch_input_keys(
            target_history_item.get("workflow_inputs_configured_keys")
        ) or _normalize_dispatch_input_keys(target_history_item.get("inputs"))
        workflow_inputs_sent_keys = _normalize_dispatch_input_keys(
            target_history_item.get("workflow_inputs_sent_keys")
        ) or _normalize_dispatch_input_keys(target_history_item.get("inputs"))
        workflow_run_lookup_attempted = (
            bool(target_history_item.get("workflow_run_lookup_attempted"))
            if isinstance(target_history_item.get("workflow_run_lookup_attempted"), bool)
            else None
        )
        workflow_run_found = (
            bool(target_history_item.get("workflow_run_found"))
            if isinstance(target_history_item.get("workflow_run_found"), bool)
            else None
        )
        workflow_job_failure_detected = (
            bool(target_history_item.get("workflow_job_failure_detected"))
            if isinstance(target_history_item.get("workflow_job_failure_detected"), bool)
            else None
        )
        post_dispatch_state = _normalize_string(target_history_item.get("post_dispatch_state"), max_length=80)
        workflow_dispatch_supported = (
            bool(target_history_item.get("workflow_dispatch_supported"))
            if isinstance(target_history_item.get("workflow_dispatch_supported"), bool)
            else None
        )
        workflow_trigger_types = _normalize_workflow_trigger_types_for_summary(
            target_history_item.get("workflow_trigger_types")
        )
        dispatch_identifier_type = _normalize_string(target_history_item.get("dispatch_identifier_type"), max_length=80)
        workflow_run_id = _coerce_int(target_history_item.get("workflow_run_id"))
        dispatch_verification_state = _derive_dispatch_verification_state(
            dispatch_attempted=dispatch_attempted,
            workflow_run_id=workflow_run_id,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_found=workflow_run_found,
        )
        post_conformance_stage = _normalize_post_conformance_stage(
            target_history_item.get("post_conformance_stage")
        ) or _derive_post_conformance_stage(
            workflow_conformance_status=target_history_item.get("workflow_conformance_status"),
            dispatch_attempted=dispatch_attempted,
            dispatch_result_stage=dispatch_result_stage,
            failure_stage=target_history_item.get("failure_stage"),
            post_dispatch_state=post_dispatch_state,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_failure_stage=target_history_item.get("workflow_run_failure_stage"),
            deploy_evidence_contract_status=target_history_item.get("deploy_evidence_contract_status"),
        )
        post_conformance_reason_text = _normalize_string(
            target_history_item.get("post_conformance_reason_text"),
            max_length=240,
        ) or _derive_post_conformance_reason_text(
            post_conformance_stage=post_conformance_stage,
            workflow_run_failure_reason_code=target_history_item.get("workflow_run_failure_reason_code"),
            workflow_run_failure_stage=target_history_item.get("workflow_run_failure_stage"),
            post_dispatch_state=post_dispatch_state,
        )
        post_conformance_remediation_message = _normalize_string(
            target_history_item.get("post_conformance_remediation_message"),
            max_length=280,
        ) or _derive_post_conformance_remediation_message(
            post_conformance_stage=post_conformance_stage
        )

        repo_owner = _normalize_string(target_history_item.get("repo_owner"), max_length=80)
        repo_name = _normalize_string(target_history_item.get("repo_name"), max_length=120)
        workflow_id = (
            _normalize_workflow_path_for_deploy(target_history_item.get("actual_dispatch_identifier_sent"))
            or _normalize_workflow_path_for_deploy(target_history_item.get("workflow_identifier_used"))
            or _normalize_workflow_path_for_deploy(target_history_item.get("workflow_id"))
            or _normalize_workflow_id_for_deploy(target_history_item.get("actual_dispatch_identifier_sent"))
            or _normalize_workflow_id_for_deploy(target_history_item.get("workflow_identifier_used"))
            or _normalize_workflow_id_for_deploy(target_history_item.get("workflow_id"))
        )
        ref = _normalize_string(target_history_item.get("ref"), max_length=120)
        if not repo_owner or not repo_name or not workflow_id or not ref:
            return self._build_deploy_refresh_no_change_result(
                business_id=business_id,
                site_id=site_id,
                workspace=workspace,
                artifact=artifact,
                readiness=readiness,
                started_at=started_at,
                reason_code="deploy_target_metadata_missing",
                reason_message="Deploy status refresh requires stored deploy target metadata.",
                principal_id=principal_id,
                history_item=target_history_item,
            )

        dispatched_at = _normalize_string(target_history_item.get("dispatched_at"), max_length=64)
        target_inputs = _normalize_history_inputs(target_history_item.get("inputs"))
        deploy_target = SEOMigrationGitHubDeployTarget(
            repo_owner=repo_owner,
            repo_name=repo_name,
            workflow_id=workflow_id,
            ref=ref,
            inputs=target_inputs,
        )
        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_workflow_run_refresh_lookup_attempted",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "workflow_id": workflow_id,
                "workflow_identifier": workflow_identifier,
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": workflow_identifier_type_requested,
                "workflow_identifier_type_used": workflow_identifier_type_used,
                "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                "workflow_file_path": workflow_file_path,
                "workflow_name": workflow_name,
                "ref": ref,
                "dispatch_ref_sent": dispatch_ref_sent,
                "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                "deploy_trace_id": deploy_trace_id,
                "workflow_dispatch_supported": workflow_dispatch_supported,
                "workflow_trigger_types": workflow_trigger_types,
                "dispatch_service_availability": dispatch_service_availability,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "dispatch_identifier_type": dispatch_identifier_type,
                "dispatch_attempted": dispatch_attempted,
                "dispatch_result_stage": dispatch_result_stage,
                "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                "workflow_run_found": workflow_run_found,
                "dispatch_verification_state": dispatch_verification_state,
                "workflow_job_failure_detected": workflow_job_failure_detected,
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "workflow_run_id": workflow_run_id,
            },
            fallback_message="seo_migration_workflow_run_refresh_lookup_attempted",
            level=logging.INFO,
        )
        refresh_result: SEOMigrationGitHubDeployRunStatusResult | None = None
        if workflow_run_id is None:
            lookup_result: SEOMigrationGitHubDeployRunStatusResult | None = None
            try:
                lookup_result = self.github_publisher.lookup_deploy_run_status_after_dispatch(
                    target=deploy_target,
                    dispatched_at=dispatched_at,
                )
            except SEOMigrationGitHubPublisherError as exc:
                self._emit_structured_service_log(
                    payload={
                        "event": "no_run_observed_after_refresh",
                        "business_id": business_id,
                        "site_id": site_id,
                        "workspace_id": workspace.id,
                        "artifact_version_id": artifact.id,
                        "repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "workflow_id": workflow_id,
                        "workflow_identifier": workflow_identifier,
                        "workflow_identifier_requested": workflow_identifier_requested,
                        "workflow_identifier_used": workflow_identifier_used,
                        "ref": ref,
                        "dispatch_ref_sent": dispatch_ref_sent,
                        "post_conformance_stage": _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN,
                        "post_conformance_reason_text": "Workflow dispatch succeeded but run evidence is still pending.",
                        "deploy_trace_id": deploy_trace_id,
                        "failure_reason_code": _normalize_deploy_failure_reason_code(exc.code),
                        "failure_stage": _normalize_deploy_failure_stage(exc.stage),
                        "failure_message": exc.safe_message,
                    },
                    fallback_message="no_run_observed_after_refresh",
                    level=logging.WARNING,
                )
                return self._build_deploy_refresh_no_change_result(
                    business_id=business_id,
                    site_id=site_id,
                    workspace=workspace,
                    artifact=artifact,
                    readiness=readiness,
                    started_at=started_at,
                    reason_code="workflow_run_lookup_failed",
                    reason_message=exc.safe_message,
                    principal_id=principal_id,
                    history_item=target_history_item,
                )

            if lookup_result is None:
                refreshed_at = utc_now().isoformat()
                next_item = dict(target_history_item)
                updated = False
                expected_updates: dict[str, object] = {
                    "workflow_run_lookup_attempted": True,
                    "workflow_run_found": False,
                    "dispatch_verification_state": "unverified_dispatch_no_run_observed",
                    "post_dispatch_state": "dispatch_unverified_no_run",
                    "post_conformance_stage": _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN,
                    "post_conformance_reason_text": "Workflow dispatch succeeded but run evidence is still pending.",
                    "post_conformance_remediation_message": _derive_post_conformance_remediation_message(
                        post_conformance_stage=_POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN
                    ),
                    "refreshed_at": refreshed_at,
                }
                for field_name, field_value in expected_updates.items():
                    if next_item.get(field_name) != field_value:
                        next_item[field_name] = field_value
                        updated = True
                if updated:
                    normalized_history[history_index] = _normalize_json_dict(next_item)
                    workspace.deploy_history_json = normalized_history
                    workspace.updated_by_principal_id = principal_id
                    self._update_workspace_readiness_statuses(workspace=workspace, site=site)
                    self.seo_migration_repository.save_workspace(workspace)
                    self.session.commit()
                    self.session.refresh(workspace)
                self._emit_structured_service_log(
                    payload={
                        "event": "no_run_observed_after_refresh",
                        "business_id": business_id,
                        "site_id": site_id,
                        "workspace_id": workspace.id,
                        "artifact_version_id": artifact.id,
                        "repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "workflow_id": workflow_id,
                        "workflow_identifier": workflow_identifier,
                        "workflow_identifier_requested": workflow_identifier_requested,
                        "workflow_identifier_used": workflow_identifier_used,
                        "workflow_identifier_type_requested": workflow_identifier_type_requested,
                        "workflow_identifier_type_used": workflow_identifier_type_used,
                        "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                        "workflow_file_path": workflow_file_path,
                        "workflow_name": workflow_name,
                        "ref": ref,
                        "dispatch_ref_sent": dispatch_ref_sent,
                        "deploy_trace_id": deploy_trace_id,
                        "dispatch_attempted": dispatch_attempted,
                        "workflow_run_lookup_attempted": True,
                        "workflow_run_found": False,
                        "post_dispatch_state": "dispatch_unverified_no_run",
                    },
                    fallback_message="no_run_observed_after_refresh",
                    level=logging.INFO,
                )
                return self._build_deploy_refresh_no_change_result(
                    business_id=business_id,
                    site_id=site_id,
                    workspace=workspace,
                    artifact=artifact,
                    readiness=readiness,
                    started_at=started_at,
                    reason_code="no_run_observed_after_refresh",
                    reason_message=(
                        "Deploy dispatch was recorded, but no workflow run was observed during refresh."
                    ),
                    principal_id=principal_id,
                    history_item=next_item,
                )

            refresh_result = lookup_result
            workflow_run_id = _coerce_int(lookup_result.workflow_run_id)
            workflow_run_lookup_attempted = True
            workflow_run_found = workflow_run_id is not None

        if refresh_result is None:
            try:
                refresh_result = self.github_publisher.refresh_deploy_run_status(
                    target=deploy_target,
                    workflow_run_id=workflow_run_id,
                    dispatched_at=dispatched_at,
                )
            except SEOMigrationGitHubPublisherError as exc:
                failure_category = self._categorize_publisher_failure(exc=exc, action="deploy")
                failure_reason_code = _normalize_deploy_failure_reason_code(exc.code)
                failure_stage = _normalize_deploy_failure_stage(exc.stage)
                self._log_control_plane_action(
                    action="deploy_status_refresh",
                    status="failed",
                    business_id=business_id,
                    site_id=site_id,
                    workspace_id=workspace.id,
                    artifact_version_id=artifact.id,
                    artifact_version=artifact.version,
                    principal_id=principal_id,
                    target_summary={
                        "repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "workflow_id": workflow_id,
                        "workflow_identifier": workflow_identifier,
                        "workflow_identifier_requested": workflow_identifier_requested,
                        "workflow_identifier_used": workflow_identifier_used,
                        "workflow_identifier_type_requested": workflow_identifier_type_requested,
                        "workflow_identifier_type_used": workflow_identifier_type_used,
                        "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                        "workflow_file_path": workflow_file_path,
                        "workflow_name": workflow_name,
                        "ref": ref,
                        "dispatch_ref_sent": dispatch_ref_sent,
                        "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                        "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                        "deploy_trace_id": deploy_trace_id,
                        "workflow_dispatch_supported": workflow_dispatch_supported,
                        "workflow_trigger_types": workflow_trigger_types,
                        "dispatch_service_availability": dispatch_service_availability,
                        "dispatch_service_reason_code": dispatch_service_reason_code,
                        "dispatch_identifier_type": dispatch_identifier_type,
                        "dispatch_attempted": dispatch_attempted,
                        "dispatch_result_stage": dispatch_result_stage,
                        "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                        "workflow_run_found": workflow_run_found,
                        "workflow_job_failure_detected": workflow_job_failure_detected,
                        "post_dispatch_state": post_dispatch_state,
                        "workflow_run_id": workflow_run_id,
                        "resolved_workflow_source": target_history_item.get("resolved_workflow_source"),
                        "failure_reason_code": failure_reason_code,
                        "failure_stage": failure_stage,
                    },
                    failure_category=failure_category,
                    failure_reason=exc.safe_message,
                    duration_ms=self._duration_ms(started_at),
                    correlation_id=deploy_trace_id,
                )
                self._emit_structured_service_log(
                    payload={
                        "event": "seo_migration_deploy_status_refresh_failed",
                        "business_id": business_id,
                        "site_id": site_id,
                        "workspace_id": workspace.id,
                        "artifact_version_id": artifact.id,
                        "repo_owner": repo_owner,
                        "repo_name": repo_name,
                        "workflow_id": workflow_id,
                        "workflow_identifier": workflow_identifier,
                        "workflow_identifier_requested": workflow_identifier_requested,
                        "workflow_identifier_used": workflow_identifier_used,
                        "workflow_identifier_type_requested": workflow_identifier_type_requested,
                        "workflow_identifier_type_used": workflow_identifier_type_used,
                        "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                        "workflow_file_path": workflow_file_path,
                        "workflow_name": workflow_name,
                        "ref": ref,
                        "dispatch_ref_sent": dispatch_ref_sent,
                        "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                        "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                        "deploy_trace_id": deploy_trace_id,
                        "workflow_dispatch_supported": workflow_dispatch_supported,
                        "workflow_trigger_types": workflow_trigger_types,
                        "dispatch_service_availability": dispatch_service_availability,
                        "dispatch_service_reason_code": dispatch_service_reason_code,
                        "dispatch_identifier_type": dispatch_identifier_type,
                        "dispatch_attempted": dispatch_attempted,
                        "dispatch_result_stage": dispatch_result_stage,
                        "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                        "workflow_run_found": workflow_run_found,
                        "workflow_job_failure_detected": workflow_job_failure_detected,
                        "post_dispatch_state": post_dispatch_state,
                        "workflow_run_id": workflow_run_id,
                        "failure_category": failure_category,
                        "failure_reason_code": failure_reason_code,
                        "failure_stage": failure_stage,
                        "failure_message": exc.safe_message,
                    },
                    fallback_message="seo_migration_deploy_status_refresh_failed",
                    level=logging.WARNING,
                )
                raise SEOMigrationValidationError(exc.safe_message) from exc

        next_item = dict(target_history_item)
        updated = False
        workflow_run_lookup_attempted = True
        workflow_run_found = _coerce_int(refresh_result.workflow_run_id) is not None
        workflow_job_failure_detected = _derive_workflow_job_failure_detected(
            workflow_run_status=refresh_result.workflow_run_status,
            workflow_run_conclusion=refresh_result.workflow_run_conclusion,
        )
        workflow_run_failure_reason_code = _normalize_workflow_run_failure_reason_code(
            getattr(refresh_result, "workflow_run_failure_reason_code", None)
        )
        workflow_run_failure_stage = _normalize_workflow_run_failure_stage(
            getattr(refresh_result, "workflow_run_failure_stage", None)
        )
        workflow_run_failure_step = _normalize_string(
            getattr(refresh_result, "workflow_run_failure_step", None),
            max_length=200,
        )
        if workflow_job_failure_detected and workflow_run_failure_reason_code is None:
            workflow_run_failure_reason_code = _DEPLOY_RUN_FAILURE_REASON_GENERIC
        if workflow_job_failure_detected and workflow_run_failure_stage is None:
            workflow_run_failure_stage = _DEPLOY_RUN_FAILURE_STAGE_WORKFLOW_EXECUTION
        workflow_run_failure_hint = _derive_workflow_run_failure_hint(
            failure_reason=workflow_run_failure_reason_code,
            post_dispatch_state=post_dispatch_state,
        )
        post_conformance_stage = _derive_post_conformance_stage(
            workflow_conformance_status=next_item.get("workflow_conformance_status"),
            dispatch_attempted=dispatch_attempted,
            dispatch_result_stage=dispatch_result_stage,
            failure_stage=next_item.get("failure_stage"),
            post_dispatch_state=post_dispatch_state,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_failure_stage=workflow_run_failure_stage,
            deploy_evidence_contract_status=next_item.get("deploy_evidence_contract_status"),
        )
        post_conformance_reason_text = _derive_post_conformance_reason_text(
            post_conformance_stage=post_conformance_stage,
            workflow_run_failure_reason_code=workflow_run_failure_reason_code,
            workflow_run_failure_stage=workflow_run_failure_stage,
            post_dispatch_state=post_dispatch_state,
        )
        post_conformance_remediation_message = _derive_post_conformance_remediation_message(
            post_conformance_stage=post_conformance_stage
        )
        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_workflow_run_refresh_result_captured",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "workflow_id": workflow_id,
                "workflow_identifier": workflow_identifier,
                "ref": ref,
                "deploy_trace_id": deploy_trace_id,
                "workflow_run_id": refresh_result.workflow_run_id,
                "workflow_run_status": refresh_result.workflow_run_status,
                "workflow_run_conclusion": refresh_result.workflow_run_conclusion,
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
            },
            fallback_message="seo_migration_workflow_run_refresh_result_captured",
            level=logging.INFO,
        )
        for field_name, field_value in (
            ("workflow_run_id", refresh_result.workflow_run_id),
            ("workflow_run_status", _normalize_string(refresh_result.workflow_run_status, max_length=40)),
            ("workflow_run_conclusion", _normalize_string(refresh_result.workflow_run_conclusion, max_length=40)),
            ("workflow_run_failure_reason_code", workflow_run_failure_reason_code),
            ("workflow_run_failure_stage", workflow_run_failure_stage),
            ("workflow_run_failure_step", workflow_run_failure_step),
            ("workflow_run_failure_hint", workflow_run_failure_hint),
            ("dispatch_ref_sent", dispatch_ref_sent),
            ("workflow_inputs_configured_keys", workflow_inputs_configured_keys),
            ("workflow_inputs_sent_keys", workflow_inputs_sent_keys),
            ("workflow_run_lookup_attempted", workflow_run_lookup_attempted),
            ("workflow_run_found", workflow_run_found),
            (
                "dispatch_verification_state",
                _derive_dispatch_verification_state(
                    dispatch_attempted=dispatch_attempted,
                    workflow_run_id=refresh_result.workflow_run_id,
                    workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                    workflow_run_found=workflow_run_found,
                ),
            ),
            ("workflow_job_failure_detected", workflow_job_failure_detected),
            ("post_conformance_stage", post_conformance_stage),
            ("post_conformance_reason_text", post_conformance_reason_text),
            ("post_conformance_remediation_message", post_conformance_remediation_message),
        ):
            if next_item.get(field_name) != field_value:
                next_item[field_name] = field_value
                updated = True

        candidate_live_url, candidate_url_source, candidate_url_source_detail = self._resolve_deploy_live_url(
            deploy_result=refresh_result,
            expected_publish_url=None,
            expected_publish_url_source=_MIGRATION_URL_SOURCE_UNKNOWN,
            expected_publish_url_source_detail=None,
        )
        if candidate_url_source not in {_MIGRATION_URL_SOURCE_DEPLOY_RESULT, _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT}:
            candidate_live_url = None
            candidate_url_source = _MIGRATION_URL_SOURCE_UNKNOWN
            candidate_url_source_detail = None

        existing_live_url = _normalize_url_candidate(next_item.get("resolved_live_url"))
        existing_url_source = _normalize_migration_url_source(next_item.get("url_source"))
        existing_url_source_detail = _normalize_string(next_item.get("url_source_detail"), max_length=120)
        if candidate_live_url:
            existing_rank = _confirmed_live_url_source_rank(existing_url_source)
            candidate_rank = _confirmed_live_url_source_rank(candidate_url_source)
            if (
                existing_live_url is None
                or candidate_rank > existing_rank
                or (candidate_rank == existing_rank and existing_live_url != candidate_live_url)
            ):
                next_item["resolved_live_url"] = candidate_live_url
                next_item["url_source"] = candidate_url_source
                next_item["url_source_detail"] = candidate_url_source_detail
                existing_live_url = candidate_live_url
                existing_url_source = candidate_url_source
                existing_url_source_detail = candidate_url_source_detail
                updated = True
                if candidate_url_source == _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT:
                    self._emit_structured_service_log(
                        payload={
                            "event": "seo_migration_workflow_output_url_captured_via_refresh",
                            "business_id": business_id,
                            "site_id": site_id,
                            "workspace_id": workspace.id,
                            "artifact_version_id": artifact.id,
                            "repo_owner": repo_owner,
                            "repo_name": repo_name,
                            "workflow_id": workflow_id,
                            "workflow_identifier": workflow_identifier,
                            "ref": ref,
                            "deploy_trace_id": deploy_trace_id,
                            "workflow_run_id": refresh_result.workflow_run_id,
                            "workflow_run_status": refresh_result.workflow_run_status,
                            "workflow_run_conclusion": refresh_result.workflow_run_conclusion,
                            "resolved_live_url": candidate_live_url,
                            "url_source": candidate_url_source,
                            "url_source_detail": candidate_url_source_detail,
                        },
                        fallback_message="seo_migration_workflow_output_url_captured_via_refresh",
                        level=logging.INFO,
                    )

        post_dispatch_state = _derive_post_dispatch_state(
            dispatch_attempted=dispatch_attempted,
            dispatch_result_stage=dispatch_result_stage,
            workflow_run_id=refresh_result.workflow_run_id,
            workflow_run_status=refresh_result.workflow_run_status,
            workflow_run_conclusion=refresh_result.workflow_run_conclusion,
            resolved_live_url=existing_live_url,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_found=workflow_run_found,
        )
        if next_item.get("post_dispatch_state") != post_dispatch_state:
            next_item["post_dispatch_state"] = post_dispatch_state
            updated = True
        workflow_run_failure_hint = _derive_workflow_run_failure_hint(
            failure_reason=workflow_run_failure_reason_code,
            post_dispatch_state=post_dispatch_state,
        )
        if next_item.get("workflow_run_failure_hint") != workflow_run_failure_hint:
            next_item["workflow_run_failure_hint"] = workflow_run_failure_hint
            updated = True
        (
            deploy_evidence_contract_status,
            deploy_evidence_contract_reasons,
            workflow_contract_advisory,
        ) = _derive_deploy_evidence_contract(
            workflow_conformance_status=next_item.get("workflow_conformance_status"),
            post_dispatch_state=post_dispatch_state,
            resolved_live_url=existing_live_url,
            url_source=existing_url_source,
        )
        if next_item.get("deploy_evidence_contract_status") != deploy_evidence_contract_status:
            next_item["deploy_evidence_contract_status"] = deploy_evidence_contract_status
            updated = True
        if next_item.get("deploy_evidence_contract_reasons") != deploy_evidence_contract_reasons:
            next_item["deploy_evidence_contract_reasons"] = list(deploy_evidence_contract_reasons)
            updated = True
        if next_item.get("workflow_contract_advisory") != workflow_contract_advisory:
            next_item["workflow_contract_advisory"] = workflow_contract_advisory
            updated = True
        post_conformance_stage = _derive_post_conformance_stage(
            workflow_conformance_status=next_item.get("workflow_conformance_status"),
            dispatch_attempted=dispatch_attempted,
            dispatch_result_stage=dispatch_result_stage,
            failure_stage=next_item.get("failure_stage"),
            post_dispatch_state=post_dispatch_state,
            workflow_run_lookup_attempted=workflow_run_lookup_attempted,
            workflow_run_failure_stage=workflow_run_failure_stage,
            deploy_evidence_contract_status=deploy_evidence_contract_status,
        )
        post_conformance_reason_text = _derive_post_conformance_reason_text(
            post_conformance_stage=post_conformance_stage,
            workflow_run_failure_reason_code=workflow_run_failure_reason_code,
            workflow_run_failure_stage=workflow_run_failure_stage,
            post_dispatch_state=post_dispatch_state,
        )
        post_conformance_remediation_message = _derive_post_conformance_remediation_message(
            post_conformance_stage=post_conformance_stage
        )
        if next_item.get("post_conformance_stage") != post_conformance_stage:
            next_item["post_conformance_stage"] = post_conformance_stage
            updated = True
        if next_item.get("post_conformance_reason_text") != post_conformance_reason_text:
            next_item["post_conformance_reason_text"] = post_conformance_reason_text
            updated = True
        if next_item.get("post_conformance_remediation_message") != post_conformance_remediation_message:
            next_item["post_conformance_remediation_message"] = post_conformance_remediation_message
            updated = True

        refresh_status = "updated" if updated else "no_change"
        no_change_reason = None
        if refresh_status == "no_change":
            run_status = str(refresh_result.workflow_run_status or "").strip().lower()
            run_conclusion = str(refresh_result.workflow_run_conclusion or "").strip().lower()
            if run_status in {"queued", "waiting", "requested"}:
                no_change_reason = "workflow_run_pending"
            elif run_status in {"in_progress", "running"}:
                no_change_reason = "workflow_run_in_progress"
            elif run_status == "completed" and run_conclusion == "success":
                no_change_reason = "workflow_output_missing_url"
            elif run_status == "completed" and run_conclusion and run_conclusion != "success":
                no_change_reason = "workflow_run_completed_without_success"
            else:
                no_change_reason = "no_new_workflow_evidence"

        if updated:
            normalized_history[history_index] = _normalize_json_dict(next_item)
            workspace.deploy_history_json = normalized_history
            workspace.updated_by_principal_id = principal_id
            self._update_workspace_readiness_statuses(workspace=workspace, site=site)
            self.seo_migration_repository.save_workspace(workspace)
            self.session.commit()
            self.session.refresh(workspace)

        refreshed_at = _normalize_string(getattr(refresh_result, "refreshed_at", None), max_length=64)
        result_payload: dict[str, object] = {
            "action": "deploy_status_refresh",
            "status": refresh_status,
            "artifact_version_id": artifact.id,
            "artifact_version": artifact.version,
            "timestamp": utc_now().isoformat(),
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "workflow_id": workflow_id,
            "workflow_identifier": workflow_identifier,
            "workflow_identifier_requested": workflow_identifier_requested,
            "workflow_identifier_used": workflow_identifier_used,
            "workflow_identifier_type_requested": workflow_identifier_type_requested,
            "workflow_identifier_type_used": workflow_identifier_type_used,
            "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
            "workflow_file_path": workflow_file_path,
            "workflow_name": workflow_name,
            "workflow_conformance_checked": (
                bool(next_item.get("workflow_conformance_checked"))
                if isinstance(next_item.get("workflow_conformance_checked"), bool)
                else None
            ),
            "workflow_conformance_status": _normalize_string(
                next_item.get("workflow_conformance_status"),
                max_length=80,
            ),
            "workflow_conformance_reasons": _normalize_string_list(
                next_item.get("workflow_conformance_reasons"),
                max_items=10,
                max_item_length=120,
            ),
            "workflow_conformance_evidence_summary": _normalize_string(
                next_item.get("workflow_conformance_evidence_summary"),
                max_length=240,
            ),
            "ref": ref,
            "dispatch_ref_sent": dispatch_ref_sent,
            "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
            "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
            "deploy_trace_id": deploy_trace_id,
            "resolved_workflow_source": next_item.get("resolved_workflow_source"),
            "deploy_workflow_mode": _normalize_string(next_item.get("deploy_workflow_mode"), max_length=60),
            "target_environment_key": _normalize_string(next_item.get("target_environment_key"), max_length=80),
            "target_environment_source": _normalize_string(
                next_item.get("target_environment_source"),
                max_length=80,
            ),
            "site_workflow_file_path": _normalize_workflow_path_for_deploy(next_item.get("site_workflow_file_path")),
            "kubernetes_namespace": _normalize_string(next_item.get("kubernetes_namespace"), max_length=63),
            "namespace_source": _normalize_string(next_item.get("namespace_source"), max_length=60),
            "namespace_model_status": _normalize_string(next_item.get("namespace_model_status"), max_length=40),
            "workflow_namespace_aligned": (
                bool(next_item.get("workflow_namespace_aligned"))
                if isinstance(next_item.get("workflow_namespace_aligned"), bool)
                else None
            ),
            "manifest_namespace_aligned": (
                bool(next_item.get("manifest_namespace_aligned"))
                if isinstance(next_item.get("manifest_namespace_aligned"), bool)
                else None
            ),
            "workflow_dispatch_supported": workflow_dispatch_supported,
            "workflow_trigger_types": workflow_trigger_types,
            "dispatch_service_availability": dispatch_service_availability,
            "dispatch_service_reason_code": dispatch_service_reason_code,
            "dispatch_identifier_type": dispatch_identifier_type,
            "dispatch_attempted": dispatch_attempted,
            "dispatch_result_stage": dispatch_result_stage,
            "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
            "workflow_run_found": workflow_run_found,
            "dispatch_verification_state": _derive_dispatch_verification_state(
                dispatch_attempted=dispatch_attempted,
                workflow_run_id=refresh_result.workflow_run_id,
                workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                workflow_run_found=workflow_run_found,
            ),
            "workflow_job_failure_detected": workflow_job_failure_detected,
            "post_dispatch_state": post_dispatch_state,
            "post_conformance_stage": post_conformance_stage,
            "post_conformance_reason_text": post_conformance_reason_text,
            "post_conformance_remediation_message": post_conformance_remediation_message,
            "expected_workflow_outputs": _normalize_string_list(
                next_item.get("expected_workflow_outputs"),
                max_items=8,
                max_item_length=80,
            )
            or list(_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS),
            "deploy_evidence_contract_status": deploy_evidence_contract_status,
            "deploy_evidence_contract_reasons": list(deploy_evidence_contract_reasons),
            "workflow_contract_advisory": workflow_contract_advisory,
            "workflow_run_id": refresh_result.workflow_run_id,
            "workflow_run_status": refresh_result.workflow_run_status,
            "workflow_run_conclusion": refresh_result.workflow_run_conclusion,
            "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
            "workflow_run_failure_stage": workflow_run_failure_stage,
            "workflow_run_failure_step": workflow_run_failure_step,
            "workflow_run_failure_hint": workflow_run_failure_hint,
            "resolved_live_url": existing_live_url,
            "url_source": existing_url_source,
            "url_source_detail": existing_url_source_detail,
            "updated": updated,
        }
        if refreshed_at:
            result_payload["refreshed_at"] = refreshed_at
        if no_change_reason:
            result_payload["no_change_reason"] = no_change_reason

        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_deploy_status_refresh_completed",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "workflow_id": workflow_id,
                "workflow_identifier": workflow_identifier,
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": workflow_identifier_type_requested,
                "workflow_identifier_type_used": workflow_identifier_type_used,
                "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                "workflow_file_path": workflow_file_path,
                "workflow_name": workflow_name,
                "workflow_conformance_checked": result_payload.get("workflow_conformance_checked"),
                "workflow_conformance_status": result_payload.get("workflow_conformance_status"),
                "workflow_conformance_reasons": result_payload.get("workflow_conformance_reasons"),
                "workflow_conformance_evidence_summary": result_payload.get("workflow_conformance_evidence_summary"),
                "ref": ref,
                "dispatch_ref_sent": dispatch_ref_sent,
                "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                "deploy_trace_id": deploy_trace_id,
                "workflow_dispatch_supported": workflow_dispatch_supported,
                "workflow_trigger_types": workflow_trigger_types,
                "dispatch_service_availability": dispatch_service_availability,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "dispatch_identifier_type": dispatch_identifier_type,
                "dispatch_attempted": dispatch_attempted,
                "dispatch_result_stage": dispatch_result_stage,
                "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                "workflow_run_found": workflow_run_found,
                "dispatch_verification_state": result_payload.get("dispatch_verification_state"),
                "workflow_job_failure_detected": workflow_job_failure_detected,
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "expected_workflow_outputs": result_payload.get("expected_workflow_outputs"),
                "deploy_evidence_contract_status": result_payload.get("deploy_evidence_contract_status"),
                "deploy_evidence_contract_reasons": result_payload.get("deploy_evidence_contract_reasons"),
                "workflow_contract_advisory": result_payload.get("workflow_contract_advisory"),
                "workflow_run_id": refresh_result.workflow_run_id,
                "workflow_run_status": refresh_result.workflow_run_status,
                "workflow_run_conclusion": refresh_result.workflow_run_conclusion,
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
                "resolved_live_url": existing_live_url,
                "url_source": existing_url_source,
                "url_source_detail": existing_url_source_detail,
                "refresh_status": refresh_status,
                "no_change_reason": no_change_reason,
            },
            fallback_message="seo_migration_deploy_status_refresh_completed",
            level=logging.INFO,
        )
        self._log_control_plane_action(
            action="deploy_status_refresh",
            status="completed",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            target_summary={
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "workflow_id": workflow_id,
                "workflow_identifier": workflow_identifier,
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": workflow_identifier_type_requested,
                "workflow_identifier_type_used": workflow_identifier_type_used,
                "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
                "workflow_file_path": workflow_file_path,
                "workflow_name": workflow_name,
                "workflow_conformance_checked": result_payload.get("workflow_conformance_checked"),
                "workflow_conformance_status": result_payload.get("workflow_conformance_status"),
                "workflow_conformance_reasons": result_payload.get("workflow_conformance_reasons"),
                "workflow_conformance_evidence_summary": result_payload.get("workflow_conformance_evidence_summary"),
                "ref": ref,
                "dispatch_ref_sent": dispatch_ref_sent,
                "workflow_inputs_configured_keys": workflow_inputs_configured_keys,
                "workflow_inputs_sent_keys": workflow_inputs_sent_keys,
                "deploy_trace_id": deploy_trace_id,
                "workflow_dispatch_supported": workflow_dispatch_supported,
                "workflow_trigger_types": workflow_trigger_types,
                "dispatch_service_availability": dispatch_service_availability,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "dispatch_identifier_type": dispatch_identifier_type,
                "dispatch_attempted": dispatch_attempted,
                "dispatch_result_stage": dispatch_result_stage,
                "workflow_run_lookup_attempted": workflow_run_lookup_attempted,
                "workflow_run_found": workflow_run_found,
                "dispatch_verification_state": result_payload.get("dispatch_verification_state"),
                "workflow_job_failure_detected": workflow_job_failure_detected,
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "expected_workflow_outputs": result_payload.get("expected_workflow_outputs"),
                "deploy_evidence_contract_status": result_payload.get("deploy_evidence_contract_status"),
                "deploy_evidence_contract_reasons": result_payload.get("deploy_evidence_contract_reasons"),
                "workflow_contract_advisory": result_payload.get("workflow_contract_advisory"),
                "resolved_workflow_source": next_item.get("resolved_workflow_source"),
                "workflow_run_id": refresh_result.workflow_run_id,
                "workflow_run_status": refresh_result.workflow_run_status,
                "workflow_run_conclusion": refresh_result.workflow_run_conclusion,
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
                "resolved_live_url": existing_live_url,
                "url_source": existing_url_source,
                "url_source_detail": existing_url_source_detail,
                "refresh_status": refresh_status,
                "no_change_reason": no_change_reason,
            },
            duration_ms=self._duration_ms(started_at),
            correlation_id=deploy_trace_id,
        )
        refreshed_readiness = self._build_deploy_readiness(
            site=site,
            workspace=workspace,
            artifact=artifact,
        )
        return SEOMigrationDeployActionResult(
            workspace=workspace,
            artifact=artifact,
            readiness=refreshed_readiness,
            result=result_payload,
        )

    def _build_deploy_refresh_no_change_result(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace: SEOMigrationWorkspace,
        artifact: SEOMigrationArtifactVersion,
        readiness: dict[str, object],
        started_at: float,
        reason_code: str,
        reason_message: str,
        principal_id: str | None,
        history_item: dict[str, object] | None = None,
    ) -> SEOMigrationDeployActionResult:
        history_item = history_item or {}
        now = utc_now().isoformat()
        result_payload: dict[str, object] = {
            "action": "deploy_status_refresh",
            "status": "no_change",
            "artifact_version_id": artifact.id,
            "artifact_version": artifact.version,
            "timestamp": now,
            "no_change_reason": reason_code,
            "message": reason_message,
            "updated": False,
            "repo_owner": _normalize_string(history_item.get("repo_owner"), max_length=80),
            "repo_name": _normalize_string(history_item.get("repo_name"), max_length=120),
            "workflow_id": _normalize_string(history_item.get("workflow_id"), max_length=160),
            "workflow_identifier": _derive_workflow_identifier(
                workflow_id=history_item.get("workflow_id"),
                workflow_path=history_item.get("workflow_path"),
            ),
            "workflow_identifier_requested": _normalize_string(
                history_item.get("workflow_identifier_requested"),
                max_length=200,
            )
            or _normalize_string(history_item.get("workflow_id"), max_length=160),
            "workflow_identifier_used": _normalize_string(
                history_item.get("workflow_identifier_used"),
                max_length=200,
            )
            or _normalize_string(history_item.get("workflow_id"), max_length=160),
            "workflow_identifier_type_requested": _normalize_string(
                history_item.get("workflow_identifier_type_requested"),
                max_length=80,
            ),
            "workflow_identifier_type_used": _normalize_string(
                history_item.get("workflow_identifier_type_used"),
                max_length=80,
            )
            or _normalize_string(history_item.get("dispatch_identifier_type"), max_length=80),
            "workflow_dispatch_resolution_source": _normalize_string(
                history_item.get("workflow_dispatch_resolution_source"),
                max_length=80,
            ),
            "workflow_file_path": _normalize_workflow_path_for_deploy(history_item.get("workflow_file_path"))
            or _normalize_workflow_path_for_deploy(history_item.get("workflow_path")),
            "workflow_name": _normalize_string(history_item.get("workflow_name"), max_length=160)
            or _workflow_id_from_path_for_deploy(
                _normalize_workflow_path_for_deploy(history_item.get("workflow_file_path"))
                or _normalize_workflow_path_for_deploy(history_item.get("workflow_path"))
            ),
            "workflow_conformance_checked": (
                bool(history_item.get("workflow_conformance_checked"))
                if isinstance(history_item.get("workflow_conformance_checked"), bool)
                else None
            ),
            "workflow_conformance_status": _normalize_string(
                history_item.get("workflow_conformance_status"),
                max_length=80,
            ),
            "workflow_conformance_reasons": _normalize_string_list(
                history_item.get("workflow_conformance_reasons"),
                max_items=10,
                max_item_length=120,
            ),
            "workflow_conformance_evidence_summary": _normalize_string(
                history_item.get("workflow_conformance_evidence_summary"),
                max_length=240,
            ),
            "ref": _normalize_string(history_item.get("ref"), max_length=120),
            "dispatch_ref_sent": _normalize_string(history_item.get("dispatch_ref_sent"), max_length=120)
            or _normalize_string(history_item.get("ref"), max_length=120),
            "workflow_inputs_configured_keys": _normalize_dispatch_input_keys(
                history_item.get("workflow_inputs_configured_keys")
            )
            or _normalize_dispatch_input_keys(history_item.get("inputs")),
            "workflow_inputs_sent_keys": _normalize_dispatch_input_keys(history_item.get("workflow_inputs_sent_keys"))
            or _normalize_dispatch_input_keys(history_item.get("inputs")),
            "deploy_trace_id": _normalize_string(history_item.get("deploy_trace_id"), max_length=80),
            "resolved_workflow_source": _normalize_string(history_item.get("resolved_workflow_source"), max_length=40),
            "deploy_workflow_mode": _normalize_string(history_item.get("deploy_workflow_mode"), max_length=60),
            "target_environment_key": _normalize_string(history_item.get("target_environment_key"), max_length=80),
            "target_environment_source": _normalize_string(
                history_item.get("target_environment_source"),
                max_length=80,
            ),
            "site_workflow_file_path": _normalize_workflow_path_for_deploy(
                history_item.get("site_workflow_file_path")
            ),
            "kubernetes_namespace": _normalize_string(history_item.get("kubernetes_namespace"), max_length=63),
            "namespace_source": _normalize_string(history_item.get("namespace_source"), max_length=60),
            "namespace_model_status": _normalize_string(history_item.get("namespace_model_status"), max_length=40),
            "workflow_namespace_aligned": (
                bool(history_item.get("workflow_namespace_aligned"))
                if isinstance(history_item.get("workflow_namespace_aligned"), bool)
                else None
            ),
            "manifest_namespace_aligned": (
                bool(history_item.get("manifest_namespace_aligned"))
                if isinstance(history_item.get("manifest_namespace_aligned"), bool)
                else None
            ),
            "managed_resource_quota_expected": (
                bool(history_item.get("managed_resource_quota_expected"))
                if isinstance(history_item.get("managed_resource_quota_expected"), bool)
                else None
            ),
            "managed_resource_quota_present": (
                bool(history_item.get("managed_resource_quota_present"))
                if isinstance(history_item.get("managed_resource_quota_present"), bool)
                else None
            ),
            "managed_limit_range_expected": (
                bool(history_item.get("managed_limit_range_expected"))
                if isinstance(history_item.get("managed_limit_range_expected"), bool)
                else None
            ),
            "managed_limit_range_present": (
                bool(history_item.get("managed_limit_range_present"))
                if isinstance(history_item.get("managed_limit_range_present"), bool)
                else None
            ),
            "managed_network_policy_expected": (
                bool(history_item.get("managed_network_policy_expected"))
                if isinstance(history_item.get("managed_network_policy_expected"), bool)
                else None
            ),
            "managed_network_policy_present": (
                bool(history_item.get("managed_network_policy_present"))
                if isinstance(history_item.get("managed_network_policy_present"), bool)
                else None
            ),
            "managed_namespace_policies_aligned": (
                bool(history_item.get("managed_namespace_policies_aligned"))
                if isinstance(history_item.get("managed_namespace_policies_aligned"), bool)
                else None
            ),
            "workflow_dispatch_supported": (
                bool(history_item.get("workflow_dispatch_supported"))
                if isinstance(history_item.get("workflow_dispatch_supported"), bool)
                else None
            ),
            "workflow_trigger_types": _normalize_workflow_trigger_types_for_summary(
                history_item.get("workflow_trigger_types")
            ),
            "dispatch_service_availability": (
                bool(history_item.get("dispatch_service_availability"))
                if isinstance(history_item.get("dispatch_service_availability"), bool)
                else None
            ),
            "dispatch_service_reason_code": _normalize_dispatch_service_reason_code(
                history_item.get("dispatch_service_reason_code")
            ),
            "dispatch_identifier_type": _normalize_string(history_item.get("dispatch_identifier_type"), max_length=80),
            "dispatch_attempted": (
                bool(history_item.get("dispatch_attempted"))
                if isinstance(history_item.get("dispatch_attempted"), bool)
                else None
            ),
            "dispatch_result_stage": _normalize_string(history_item.get("dispatch_result_stage"), max_length=40),
            "workflow_run_lookup_attempted": (
                bool(history_item.get("workflow_run_lookup_attempted"))
                if isinstance(history_item.get("workflow_run_lookup_attempted"), bool)
                else None
            ),
            "workflow_run_found": (
                bool(history_item.get("workflow_run_found"))
                if isinstance(history_item.get("workflow_run_found"), bool)
                else None
            ),
            "dispatch_verification_state": _normalize_string(
                history_item.get("dispatch_verification_state"),
                max_length=80,
            )
            or _derive_dispatch_verification_state(
                dispatch_attempted=history_item.get("dispatch_attempted"),
                workflow_run_id=history_item.get("workflow_run_id"),
                workflow_run_lookup_attempted=history_item.get("workflow_run_lookup_attempted"),
                workflow_run_found=history_item.get("workflow_run_found"),
            ),
            "workflow_job_failure_detected": (
                bool(history_item.get("workflow_job_failure_detected"))
                if isinstance(history_item.get("workflow_job_failure_detected"), bool)
                else _derive_workflow_job_failure_detected(
                    workflow_run_status=history_item.get("workflow_run_status"),
                    workflow_run_conclusion=history_item.get("workflow_run_conclusion"),
                )
            ),
            "workflow_run_id": _coerce_int(history_item.get("workflow_run_id")),
            "workflow_run_status": _normalize_string(history_item.get("workflow_run_status"), max_length=40),
            "workflow_run_conclusion": _normalize_string(history_item.get("workflow_run_conclusion"), max_length=40),
            "workflow_run_failure_reason_code": _normalize_workflow_run_failure_reason_code(
                history_item.get("workflow_run_failure_reason_code")
            ),
            "workflow_run_failure_stage": _normalize_workflow_run_failure_stage(
                history_item.get("workflow_run_failure_stage")
            ),
            "workflow_run_failure_step": _normalize_string(history_item.get("workflow_run_failure_step"), max_length=200),
            "workflow_run_failure_hint": _normalize_string(history_item.get("workflow_run_failure_hint"), max_length=240)
            or _derive_workflow_run_failure_hint(
                failure_reason=history_item.get("workflow_run_failure_reason_code"),
                post_dispatch_state=history_item.get("post_dispatch_state"),
            ),
            "resolved_live_url": _normalize_url_candidate(history_item.get("resolved_live_url")),
            "url_source": _normalize_migration_url_source(history_item.get("url_source")),
            "url_source_detail": _normalize_string(history_item.get("url_source_detail"), max_length=120),
            "post_dispatch_state": _normalize_string(history_item.get("post_dispatch_state"), max_length=80)
            or _derive_post_dispatch_state(
                dispatch_attempted=history_item.get("dispatch_attempted"),
                dispatch_result_stage=history_item.get("dispatch_result_stage"),
                workflow_run_id=history_item.get("workflow_run_id"),
                workflow_run_status=history_item.get("workflow_run_status"),
                workflow_run_conclusion=history_item.get("workflow_run_conclusion"),
                resolved_live_url=history_item.get("resolved_live_url"),
                workflow_run_lookup_attempted=history_item.get("workflow_run_lookup_attempted"),
                workflow_run_found=history_item.get("workflow_run_found"),
            ),
        }
        deploy_evidence_contract_status = _normalize_deploy_evidence_contract_status(
            history_item.get("deploy_evidence_contract_status")
        )
        deploy_evidence_contract_reasons = _normalize_string_list(
            history_item.get("deploy_evidence_contract_reasons"),
            max_items=8,
            max_item_length=120,
        )
        workflow_contract_advisory = _normalize_string(
            history_item.get("workflow_contract_advisory"),
            max_length=240,
        )
        if deploy_evidence_contract_status is None:
            (
                deploy_evidence_contract_status,
                derived_reasons,
                derived_advisory,
            ) = _derive_deploy_evidence_contract(
                workflow_conformance_status=result_payload.get("workflow_conformance_status"),
                post_dispatch_state=result_payload.get("post_dispatch_state"),
                resolved_live_url=result_payload.get("resolved_live_url"),
                url_source=result_payload.get("url_source"),
            )
            if not deploy_evidence_contract_reasons:
                deploy_evidence_contract_reasons = derived_reasons
            if workflow_contract_advisory is None:
                workflow_contract_advisory = derived_advisory
        result_payload["expected_workflow_outputs"] = _normalize_string_list(
            history_item.get("expected_workflow_outputs"),
            max_items=8,
            max_item_length=80,
        ) or list(_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS)
        result_payload["deploy_evidence_contract_status"] = (
            deploy_evidence_contract_status or _DEPLOY_EVIDENCE_CONTRACT_STATUS_UNKNOWN
        )
        result_payload["deploy_evidence_contract_reasons"] = deploy_evidence_contract_reasons
        result_payload["workflow_contract_advisory"] = workflow_contract_advisory
        post_conformance_stage = _normalize_post_conformance_stage(history_item.get("post_conformance_stage")) or (
            _derive_post_conformance_stage(
                workflow_conformance_status=result_payload.get("workflow_conformance_status"),
                dispatch_attempted=result_payload.get("dispatch_attempted"),
                dispatch_result_stage=result_payload.get("dispatch_result_stage"),
                failure_stage=history_item.get("failure_stage"),
                post_dispatch_state=result_payload.get("post_dispatch_state"),
                workflow_run_lookup_attempted=result_payload.get("workflow_run_lookup_attempted"),
                workflow_run_failure_stage=result_payload.get("workflow_run_failure_stage"),
                deploy_evidence_contract_status=result_payload.get("deploy_evidence_contract_status"),
            )
        )
        post_conformance_reason_text = _normalize_string(
            history_item.get("post_conformance_reason_text"),
            max_length=240,
        ) or _derive_post_conformance_reason_text(
            post_conformance_stage=post_conformance_stage,
            workflow_run_failure_reason_code=result_payload.get("workflow_run_failure_reason_code"),
            workflow_run_failure_stage=result_payload.get("workflow_run_failure_stage"),
            post_dispatch_state=result_payload.get("post_dispatch_state"),
        )
        post_conformance_remediation_message = _normalize_string(
            history_item.get("post_conformance_remediation_message"),
            max_length=280,
        ) or _derive_post_conformance_remediation_message(
            post_conformance_stage=post_conformance_stage
        )
        result_payload["post_conformance_stage"] = post_conformance_stage
        result_payload["post_conformance_reason_text"] = post_conformance_reason_text
        result_payload["post_conformance_remediation_message"] = post_conformance_remediation_message
        self._emit_structured_service_log(
            payload={
                "event": "seo_migration_deploy_status_refresh_no_change",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": artifact.id,
                "refresh_status": "no_change",
                "no_change_reason": reason_code,
                "reason_message": reason_message,
                "repo_owner": result_payload.get("repo_owner"),
                "repo_name": result_payload.get("repo_name"),
                "workflow_id": result_payload.get("workflow_id"),
                "workflow_identifier": result_payload.get("workflow_identifier"),
                "workflow_identifier_requested": result_payload.get("workflow_identifier_requested"),
                "workflow_identifier_used": result_payload.get("workflow_identifier_used"),
                "workflow_identifier_type_requested": result_payload.get("workflow_identifier_type_requested"),
                "workflow_identifier_type_used": result_payload.get("workflow_identifier_type_used"),
                "workflow_dispatch_resolution_source": result_payload.get("workflow_dispatch_resolution_source"),
                "workflow_file_path": result_payload.get("workflow_file_path"),
                "workflow_name": result_payload.get("workflow_name"),
                "workflow_conformance_checked": result_payload.get("workflow_conformance_checked"),
                "workflow_conformance_status": result_payload.get("workflow_conformance_status"),
                "workflow_conformance_reasons": result_payload.get("workflow_conformance_reasons"),
                "workflow_conformance_evidence_summary": result_payload.get("workflow_conformance_evidence_summary"),
                "ref": result_payload.get("ref"),
                "dispatch_ref_sent": result_payload.get("dispatch_ref_sent"),
                "workflow_inputs_configured_keys": result_payload.get("workflow_inputs_configured_keys"),
                "workflow_inputs_sent_keys": result_payload.get("workflow_inputs_sent_keys"),
                "deploy_trace_id": result_payload.get("deploy_trace_id"),
                "workflow_dispatch_supported": result_payload.get("workflow_dispatch_supported"),
                "workflow_trigger_types": result_payload.get("workflow_trigger_types"),
                "dispatch_service_availability": result_payload.get("dispatch_service_availability"),
                "dispatch_service_reason_code": result_payload.get("dispatch_service_reason_code"),
                "dispatch_identifier_type": result_payload.get("dispatch_identifier_type"),
                "dispatch_attempted": result_payload.get("dispatch_attempted"),
                "dispatch_result_stage": result_payload.get("dispatch_result_stage"),
                "workflow_run_lookup_attempted": result_payload.get("workflow_run_lookup_attempted"),
                "workflow_run_found": result_payload.get("workflow_run_found"),
                "dispatch_verification_state": result_payload.get("dispatch_verification_state"),
                "workflow_job_failure_detected": result_payload.get("workflow_job_failure_detected"),
                "post_dispatch_state": result_payload.get("post_dispatch_state"),
                "post_conformance_stage": result_payload.get("post_conformance_stage"),
                "post_conformance_reason_text": result_payload.get("post_conformance_reason_text"),
                "post_conformance_remediation_message": result_payload.get("post_conformance_remediation_message"),
                "expected_workflow_outputs": result_payload.get("expected_workflow_outputs"),
                "deploy_evidence_contract_status": result_payload.get("deploy_evidence_contract_status"),
                "deploy_evidence_contract_reasons": result_payload.get("deploy_evidence_contract_reasons"),
                "workflow_contract_advisory": result_payload.get("workflow_contract_advisory"),
                "workflow_run_id": result_payload.get("workflow_run_id"),
                "workflow_run_status": result_payload.get("workflow_run_status"),
                "workflow_run_conclusion": result_payload.get("workflow_run_conclusion"),
                "workflow_run_failure_reason_code": result_payload.get("workflow_run_failure_reason_code"),
                "workflow_run_failure_stage": result_payload.get("workflow_run_failure_stage"),
                "workflow_run_failure_step": result_payload.get("workflow_run_failure_step"),
                "workflow_run_failure_hint": result_payload.get("workflow_run_failure_hint"),
            },
            fallback_message="seo_migration_deploy_status_refresh_no_change",
            level=logging.INFO,
        )
        self._log_control_plane_action(
            action="deploy_status_refresh",
            status="completed",
            business_id=business_id,
            site_id=site_id,
            workspace_id=workspace.id,
            artifact_version_id=artifact.id,
            artifact_version=artifact.version,
            principal_id=principal_id,
            target_summary={
                "refresh_status": "no_change",
                "no_change_reason": reason_code,
                "repo_owner": result_payload.get("repo_owner"),
                "repo_name": result_payload.get("repo_name"),
                "workflow_id": result_payload.get("workflow_id"),
                "workflow_identifier": result_payload.get("workflow_identifier"),
                "workflow_identifier_requested": result_payload.get("workflow_identifier_requested"),
                "workflow_identifier_used": result_payload.get("workflow_identifier_used"),
                "workflow_identifier_type_requested": result_payload.get("workflow_identifier_type_requested"),
                "workflow_identifier_type_used": result_payload.get("workflow_identifier_type_used"),
                "workflow_dispatch_resolution_source": result_payload.get("workflow_dispatch_resolution_source"),
                "workflow_file_path": result_payload.get("workflow_file_path"),
                "workflow_name": result_payload.get("workflow_name"),
                "workflow_conformance_checked": result_payload.get("workflow_conformance_checked"),
                "workflow_conformance_status": result_payload.get("workflow_conformance_status"),
                "workflow_conformance_reasons": result_payload.get("workflow_conformance_reasons"),
                "workflow_conformance_evidence_summary": result_payload.get("workflow_conformance_evidence_summary"),
                "ref": result_payload.get("ref"),
                "dispatch_ref_sent": result_payload.get("dispatch_ref_sent"),
                "workflow_inputs_configured_keys": result_payload.get("workflow_inputs_configured_keys"),
                "workflow_inputs_sent_keys": result_payload.get("workflow_inputs_sent_keys"),
                "deploy_trace_id": result_payload.get("deploy_trace_id"),
                "workflow_dispatch_supported": result_payload.get("workflow_dispatch_supported"),
                "workflow_trigger_types": result_payload.get("workflow_trigger_types"),
                "dispatch_service_availability": result_payload.get("dispatch_service_availability"),
                "dispatch_service_reason_code": result_payload.get("dispatch_service_reason_code"),
                "dispatch_identifier_type": result_payload.get("dispatch_identifier_type"),
                "dispatch_attempted": result_payload.get("dispatch_attempted"),
                "dispatch_result_stage": result_payload.get("dispatch_result_stage"),
                "workflow_run_lookup_attempted": result_payload.get("workflow_run_lookup_attempted"),
                "workflow_run_found": result_payload.get("workflow_run_found"),
                "dispatch_verification_state": result_payload.get("dispatch_verification_state"),
                "workflow_job_failure_detected": result_payload.get("workflow_job_failure_detected"),
                "post_dispatch_state": result_payload.get("post_dispatch_state"),
                "post_conformance_stage": result_payload.get("post_conformance_stage"),
                "post_conformance_reason_text": result_payload.get("post_conformance_reason_text"),
                "post_conformance_remediation_message": result_payload.get("post_conformance_remediation_message"),
                "expected_workflow_outputs": result_payload.get("expected_workflow_outputs"),
                "deploy_evidence_contract_status": result_payload.get("deploy_evidence_contract_status"),
                "deploy_evidence_contract_reasons": result_payload.get("deploy_evidence_contract_reasons"),
                "workflow_contract_advisory": result_payload.get("workflow_contract_advisory"),
                "workflow_run_id": result_payload.get("workflow_run_id"),
                "workflow_run_status": result_payload.get("workflow_run_status"),
                "workflow_run_conclusion": result_payload.get("workflow_run_conclusion"),
                "workflow_run_failure_reason_code": result_payload.get("workflow_run_failure_reason_code"),
                "workflow_run_failure_stage": result_payload.get("workflow_run_failure_stage"),
                "workflow_run_failure_step": result_payload.get("workflow_run_failure_step"),
                "workflow_run_failure_hint": result_payload.get("workflow_run_failure_hint"),
            },
            duration_ms=self._duration_ms(started_at),
            correlation_id=_normalize_string(result_payload.get("deploy_trace_id"), max_length=80),
        )
        return SEOMigrationDeployActionResult(
            workspace=workspace,
            artifact=artifact,
            readiness=readiness,
            result=result_payload,
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

        normalized_files, file_warnings, file_validation_diagnostics = self._validate_and_normalize_files(
            provider_output.generated_files
        )
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
            file_validation_diagnostics=file_validation_diagnostics,
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
            draft_contract_diagnostics = self._build_draft_contract_diagnostics(
                evaluation=draft_contract_evaluation,
                file_validation_diagnostics=file_validation_diagnostics,
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
                draft_contract_diagnostics=draft_contract_diagnostics,
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
                draft_failure.endpoint_path if draft_failure and generation_status == "partial" else draft_endpoint_path
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
            request_body_mode=(
                draft_failure.request_body_mode if draft_failure and generation_status == "partial" else None
            ),
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

    def delete_artifact_version(
        self,
        *,
        business_id: str,
        site_id: str,
        artifact_version_id: str,
        principal_id: str | None = None,
    ) -> SEOMigrationArtifactDeleteResult:
        workspace = self.get_workspace(business_id=business_id, site_id=site_id)
        site = self._require_site(business_id=business_id, site_id=site_id)
        artifact = self.get_artifact_version(
            business_id=business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )

        if artifact.publish_status == "published":
            raise SEOMigrationValidationError(
                "Published artifacts cannot be deleted.",
                failure_category="artifact_invalid",
                failure_reason="validation_failed",
                error_code="artifact_already_published",
                artifact_version_id=artifact.id,
                workspace_id=workspace.id,
            )

        if (
            artifact.id == workspace.last_published_artifact_version_id
            or artifact.id == workspace.last_deployed_artifact_version_id
        ):
            raise SEOMigrationValidationError(
                "Artifacts referenced by publish/deploy pointers cannot be deleted.",
                failure_category="artifact_invalid",
                failure_reason="validation_failed",
                error_code="artifact_delete_integrity_blocked",
                artifact_version_id=artifact.id,
                workspace_id=workspace.id,
            )

        if _history_references_artifact(
            history=workspace.publish_history_json,
            artifact_version_id=artifact.id,
            action="publish",
        ):
            raise SEOMigrationValidationError(
                "Artifacts referenced by publish history cannot be deleted.",
                failure_category="artifact_invalid",
                failure_reason="validation_failed",
                error_code="artifact_referenced_by_publish_history",
                artifact_version_id=artifact.id,
                workspace_id=workspace.id,
            )

        if _history_references_artifact(
            history=workspace.deploy_history_json,
            artifact_version_id=artifact.id,
            action="deploy",
        ):
            raise SEOMigrationValidationError(
                "Artifacts referenced by deploy history cannot be deleted.",
                failure_category="artifact_invalid",
                failure_reason="validation_failed",
                error_code="artifact_delete_integrity_blocked",
                artifact_version_id=artifact.id,
                workspace_id=workspace.id,
            )

        deleted_artifact_id = artifact.id
        deleted_artifact_version = int(artifact.version)
        self.seo_migration_repository.delete_artifact_version(artifact)

        remaining_versions = self.seo_migration_repository.list_artifact_versions_for_business_site(
            business_id,
            site_id,
            limit=100,
        )
        latest_generated = remaining_versions[0] if remaining_versions else None
        latest_approved = next((item for item in remaining_versions if item.approval_status == "approved"), None)

        workspace.latest_generated_artifact_version_id = latest_generated.id if latest_generated else None
        workspace.latest_generated_artifact_version_number = latest_generated.version if latest_generated else None
        workspace.latest_approved_artifact_version_id = latest_approved.id if latest_approved else None
        workspace.latest_approved_artifact_version_number = latest_approved.version if latest_approved else None
        if latest_generated is None:
            workspace.migration_status = "draft"
        elif latest_approved is not None:
            workspace.migration_status = "draft_approved"
        else:
            workspace.migration_status = "draft_generated"
        workspace.updated_by_principal_id = principal_id
        self._update_workspace_readiness_statuses(workspace=workspace, site=site)
        self.seo_migration_repository.save_workspace(workspace)
        self.session.commit()
        self.session.refresh(workspace)
        logger.info(
            "seo_migration_artifact_deleted",
            extra={
                "event": "seo_migration_artifact_deleted",
                "business_id": business_id,
                "site_id": site_id,
                "workspace_id": workspace.id,
                "artifact_version_id": deleted_artifact_id,
                "artifact_version_number": deleted_artifact_version,
                "principal_id": _normalize_string(principal_id, max_length=64),
            },
        )
        return SEOMigrationArtifactDeleteResult(
            workspace=workspace,
            deleted_artifact_version_id=deleted_artifact_id,
            deleted_artifact_version_number=deleted_artifact_version,
        )

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
        latest_deploy_failure_detail = self._derive_latest_deploy_failure_detail(history=workspace.deploy_history_json)
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
            "last_failure_reason": publish_diagnostics.get("last_failure_reason"),
            "last_failure_stage": publish_diagnostics.get("last_failure_stage"),
            "last_failure_message": publish_diagnostics.get("last_failure_message"),
            "last_workflow_remediation_attempted": publish_diagnostics.get(
                "last_workflow_remediation_attempted"
            ),
            "last_workflow_remediation_outcome": publish_diagnostics.get(
                "last_workflow_remediation_outcome"
            ),
            "last_deploy_secret_propagation_attempted": publish_diagnostics.get(
                "last_deploy_secret_propagation_attempted"
            ),
            "last_deploy_secret_propagation_status": publish_diagnostics.get(
                "last_deploy_secret_propagation_status"
            ),
            "last_deploy_secret_propagation_reason": publish_diagnostics.get(
                "last_deploy_secret_propagation_reason"
            ),
            "last_deploy_secret_propagation_source": publish_diagnostics.get(
                "last_deploy_secret_propagation_source"
            ),
        }
        deploy_readiness = {
            **deploy_readiness,
            "last_status": deploy_diagnostics.get("last_status"),
            "last_failure_category": deploy_diagnostics.get("last_failure_category"),
            "last_failure_reason": deploy_diagnostics.get("last_failure_reason"),
            "last_failure_stage": deploy_diagnostics.get("last_failure_stage"),
            "last_failure_message": deploy_diagnostics.get("last_failure_message"),
            "last_failure_remediation_hint": deploy_diagnostics.get("last_failure_remediation_hint"),
            "last_failure_workflow_identifier_requested": latest_deploy_failure_detail.get(
                "workflow_identifier_requested"
            ),
            "last_failure_workflow_identifier_used": latest_deploy_failure_detail.get("workflow_identifier_used"),
            "last_failure_workflow_file_path": latest_deploy_failure_detail.get("workflow_file_path"),
            "last_failure_workflow_exists": latest_deploy_failure_detail.get("workflow_exists"),
            "last_failure_workflow_dispatch_resolution_source": latest_deploy_failure_detail.get(
                "workflow_dispatch_resolution_source"
            ),
            "last_failure_dispatch_service_reason_code": latest_deploy_failure_detail.get(
                "dispatch_service_reason_code"
            ),
            "last_failure_workflow_conformance_status": latest_deploy_failure_detail.get("workflow_conformance_status"),
            "last_failure_workflow_conformance_reasons": latest_deploy_failure_detail.get(
                "workflow_conformance_reasons"
            ),
            "last_failure_resolved_workflow_source": latest_deploy_failure_detail.get("resolved_workflow_source"),
            "last_failure_target_environment_key": latest_deploy_failure_detail.get("target_environment_key"),
            "last_failure_target_environment_source": latest_deploy_failure_detail.get("target_environment_source"),
        }
        context_summary = {
            **context_summary,
            "migration_diagnostics": {
                "last_publish_status": publish_diagnostics.get("last_status"),
                "last_publish_failure_category": publish_diagnostics.get("last_failure_category"),
                "last_publish_failure_reason": publish_diagnostics.get("last_failure_reason"),
                "last_publish_failure_stage": publish_diagnostics.get("last_failure_stage"),
                "last_publish_failure_message": publish_diagnostics.get("last_failure_message"),
                "last_publish_workflow_remediation_attempted": publish_diagnostics.get(
                    "last_workflow_remediation_attempted"
                ),
                "last_publish_workflow_remediation_outcome": publish_diagnostics.get(
                    "last_workflow_remediation_outcome"
                ),
                "last_publish_deploy_secret_propagation_attempted": publish_diagnostics.get(
                    "last_deploy_secret_propagation_attempted"
                ),
                "last_publish_deploy_secret_propagation_status": publish_diagnostics.get(
                    "last_deploy_secret_propagation_status"
                ),
                "last_publish_deploy_secret_propagation_reason": publish_diagnostics.get(
                    "last_deploy_secret_propagation_reason"
                ),
                "last_publish_deploy_secret_propagation_source": publish_diagnostics.get(
                    "last_deploy_secret_propagation_source"
                ),
                "last_deploy_status": deploy_diagnostics.get("last_status"),
                "last_deploy_failure_category": deploy_diagnostics.get("last_failure_category"),
                "last_deploy_failure_reason": deploy_diagnostics.get("last_failure_reason"),
                "last_deploy_failure_stage": deploy_diagnostics.get("last_failure_stage"),
                "last_deploy_failure_message": deploy_diagnostics.get("last_failure_message"),
                "last_deploy_failure_remediation_hint": deploy_diagnostics.get("last_failure_remediation_hint"),
                "last_deploy_failure_workflow_identifier_requested": latest_deploy_failure_detail.get(
                    "workflow_identifier_requested"
                ),
                "last_deploy_failure_workflow_identifier_used": latest_deploy_failure_detail.get(
                    "workflow_identifier_used"
                ),
                "last_deploy_failure_workflow_file_path": latest_deploy_failure_detail.get("workflow_file_path"),
                "last_deploy_failure_workflow_exists": latest_deploy_failure_detail.get("workflow_exists"),
                "last_deploy_failure_workflow_dispatch_resolution_source": latest_deploy_failure_detail.get(
                    "workflow_dispatch_resolution_source"
                ),
                "last_deploy_failure_dispatch_service_reason_code": latest_deploy_failure_detail.get(
                    "dispatch_service_reason_code"
                ),
                "last_deploy_failure_workflow_conformance_status": latest_deploy_failure_detail.get(
                    "workflow_conformance_status"
                ),
                "last_deploy_failure_workflow_conformance_reasons": latest_deploy_failure_detail.get(
                    "workflow_conformance_reasons"
                ),
                "last_deploy_failure_resolved_workflow_source": latest_deploy_failure_detail.get(
                    "resolved_workflow_source"
                ),
                "last_deploy_failure_target_environment_key": latest_deploy_failure_detail.get(
                    "target_environment_key"
                ),
                "last_deploy_failure_target_environment_source": latest_deploy_failure_detail.get(
                    "target_environment_source"
                ),
                "last_deploy_post_conformance_stage": deploy_readiness.get("last_post_conformance_stage"),
                "last_deploy_post_conformance_reason_text": deploy_readiness.get(
                    "last_post_conformance_reason_text"
                ),
                "last_deploy_post_conformance_remediation_message": deploy_readiness.get(
                    "last_post_conformance_remediation_message"
                ),
                "last_draft_generation_status": draft_diagnostics.get("last_status"),
                "last_draft_failure_category": draft_diagnostics.get("last_failure_category"),
                "last_draft_failure_reason": draft_diagnostics.get("last_failure_reason"),
                "last_draft_failure_message": draft_diagnostics.get("last_failure_message"),
                "last_draft_failure_retryable": draft_diagnostics.get("last_failure_retryable"),
                "last_draft_failure_code": draft_diagnostics.get("last_failure_code"),
                "last_draft_failure_normalized_category": draft_diagnostics.get("last_failure_normalized_category"),
                "last_draft_failure_normalized_reason": draft_diagnostics.get("last_failure_normalized_reason"),
                "last_draft_failure_normalized_source": draft_diagnostics.get("last_failure_normalized_source"),
                "last_draft_failure_normalized_retryable": draft_diagnostics.get("last_failure_normalized_retryable"),
                "last_draft_failure_provider_attempt_count": draft_diagnostics.get(
                    "last_failure_provider_attempt_count"
                ),
                # Keep legacy aliases for existing diagnostics consumers while draft-prefixed
                # keys remain the canonical migration_diagnostics fields.
                "last_failure_normalized_category": draft_diagnostics.get("last_failure_normalized_category"),
                "last_failure_normalized_reason": draft_diagnostics.get("last_failure_normalized_reason"),
                "last_failure_normalized_source": draft_diagnostics.get("last_failure_normalized_source"),
                "last_failure_normalized_retryable": draft_diagnostics.get("last_failure_normalized_retryable"),
                "last_failure_provider_attempt_count": draft_diagnostics.get("last_failure_provider_attempt_count"),
                "last_draft_failure_correlation_id": draft_diagnostics.get("last_failure_correlation_id"),
                "last_draft_failure_artifact_version_id": draft_diagnostics.get("last_failure_artifact_version_id"),
                "last_draft_failure_source": draft_diagnostics.get("last_failure_source"),
                "last_draft_failure_endpoint_path": draft_diagnostics.get("last_failure_endpoint_path"),
                "last_draft_failure_execution_mode": draft_diagnostics.get("last_failure_execution_mode"),
                "last_draft_failure_response_format_mode": draft_diagnostics.get("last_failure_response_format_mode"),
                "last_draft_failure_request_body_mode": draft_diagnostics.get("last_failure_request_body_mode"),
                "last_draft_failure_model_requested": draft_diagnostics.get("last_failure_model_requested"),
                "last_draft_failure_model_resolved": draft_diagnostics.get("last_failure_model_resolved"),
                "last_draft_failure_model_used": draft_diagnostics.get("last_failure_model_used"),
                "last_draft_failure_hint": draft_diagnostics.get("last_failure_hint"),
                "last_draft_failure_timeout_seconds": draft_diagnostics.get("last_failure_timeout_seconds"),
                "last_draft_failure_timeout_source": draft_diagnostics.get("last_failure_timeout_source"),
                "last_draft_ai_diagnostics_summary": draft_diagnostics.get("last_draft_ai_diagnostics_summary"),
                "last_draft_contract_status": draft_diagnostics.get("last_contract_status"),
                "last_draft_contract_reason_codes": draft_diagnostics.get("last_contract_reason_codes"),
                "last_draft_contract_warning_codes": draft_diagnostics.get("last_contract_warning_codes"),
                "last_draft_contract_retry_likelihood": draft_diagnostics.get("last_contract_retry_likelihood"),
                "last_draft_contract_candidate_item_count": draft_diagnostics.get("last_contract_candidate_item_count"),
                "last_draft_contract_normalized_item_count": draft_diagnostics.get(
                    "last_contract_normalized_item_count"
                ),
                "last_draft_contract_dropped_item_count": draft_diagnostics.get("last_contract_dropped_item_count"),
                "last_draft_contract_required_artifact_files_expected": draft_diagnostics.get(
                    "last_contract_required_artifact_files_expected"
                ),
                "last_draft_contract_required_artifact_files_present": draft_diagnostics.get(
                    "last_contract_required_artifact_files_present"
                ),
                "last_draft_contract_missing_required_artifact_files": draft_diagnostics.get(
                    "last_contract_missing_required_artifact_files"
                ),
                "last_draft_contract_content_density_failures_by_file": draft_diagnostics.get(
                    "last_contract_content_density_failures_by_file"
                ),
                "last_draft_contract_parser_rejection_reason_counts": draft_diagnostics.get(
                    "last_contract_parser_rejection_reason_counts"
                ),
                "last_draft_contract_artifact_primary_file_detected": draft_diagnostics.get(
                    "last_contract_artifact_primary_file_detected"
                ),
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
                "last_failure_normalized_category": None,
                "last_failure_normalized_reason": None,
                "last_failure_normalized_source": None,
                "last_failure_normalized_retryable": None,
                "last_failure_provider_attempt_count": None,
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
                "last_failure_hint": None,
                "last_failure_timeout_seconds": None,
                "last_failure_timeout_source": None,
                "last_failure_original_input_size": None,
                "last_failure_final_input_size": None,
                "last_failure_trimmed_bytes": None,
                "last_failure_trimming_pass_count": None,
                "last_failure_difficulty_score": None,
                "last_failure_budget_outcome": None,
                "last_failure_retry_suppressed": None,
                "last_failure_degraded_state": None,
                "last_draft_ai_diagnostics_summary": None,
                "last_contract_status": None,
                "last_contract_reason_codes": [],
                "last_contract_warning_codes": [],
                "last_contract_retry_likelihood": None,
                "last_contract_candidate_item_count": None,
                "last_contract_normalized_item_count": None,
                "last_contract_dropped_item_count": None,
                "last_contract_required_artifact_files_expected": [],
                "last_contract_required_artifact_files_present": [],
                "last_contract_missing_required_artifact_files": [],
                "last_contract_content_density_failures_by_file": [],
                "last_contract_parser_rejection_reason_counts": {},
                "last_contract_artifact_primary_file_detected": None,
            }

        diagnostics_payload = {}
        if isinstance(artifact.context_json, dict):
            diagnostics_payload = _normalize_json_dict(artifact.context_json.get("draft_generation_failure"))
        contract_payload = {}
        if isinstance(artifact.context_json, dict):
            contract_payload = _normalize_json_dict(artifact.context_json.get("draft_contract_evaluation"))
        status_value = _normalize_string(artifact.status, max_length=40)
        failure_category = _normalize_string(diagnostics_payload.get("failure_category"), max_length=40)
        if failure_category not in _MIGRATION_FAILURE_CATEGORY_VALUES:
            failure_category = "artifact_invalid" if status_value == "failed" else None
        failure_reason = _normalize_string(diagnostics_payload.get("failure_reason"), max_length=80)
        if failure_reason not in _DRAFT_FAILURE_REASON_VALUES:
            failure_reason = None
        failure_code = _normalize_string(diagnostics_payload.get("error_code"), max_length=80)
        normalized_failure_category = _normalize_string(
            diagnostics_payload.get("normalized_failure_category"),
            max_length=80,
        )
        normalized_failure_reason = _normalize_string(
            diagnostics_payload.get("normalized_failure_reason"),
            max_length=120,
        )
        normalized_failure_source = _normalize_string(
            diagnostics_payload.get("normalized_failure_source"),
            max_length=80,
        )
        normalized_failure_retryable = (
            bool(diagnostics_payload.get("normalized_retryable"))
            if isinstance(diagnostics_payload.get("normalized_retryable"), bool)
            else None
        )
        provider_attempt_count_raw = diagnostics_payload.get("provider_attempt_count")
        provider_attempt_count = (
            max(1, int(provider_attempt_count_raw)) if isinstance(provider_attempt_count_raw, int) else None
        )
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
        failure_hint = _normalize_string(diagnostics_payload.get("failure_hint"), max_length=120)
        timeout_seconds_raw = diagnostics_payload.get("timeout_seconds")
        timeout_seconds = max(1, int(timeout_seconds_raw)) if isinstance(timeout_seconds_raw, int) else None
        timeout_source = _normalize_string(diagnostics_payload.get("timeout_source"), max_length=20)
        if timeout_source not in {"admin", "default"}:
            timeout_source = None
        original_input_size_raw = diagnostics_payload.get("original_input_size")
        original_input_size = max(0, int(original_input_size_raw)) if isinstance(original_input_size_raw, int) else None
        final_input_size_raw = diagnostics_payload.get("final_input_size")
        final_input_size = max(0, int(final_input_size_raw)) if isinstance(final_input_size_raw, int) else None
        trimmed_bytes_raw = diagnostics_payload.get("trimmed_bytes")
        trimmed_bytes = max(0, int(trimmed_bytes_raw)) if isinstance(trimmed_bytes_raw, int) else None
        trimming_pass_count_raw = diagnostics_payload.get("trimming_pass_count")
        trimming_pass_count = (
            max(0, int(trimming_pass_count_raw)) if isinstance(trimming_pass_count_raw, int) else None
        )
        difficulty_score_raw = diagnostics_payload.get("difficulty_score")
        difficulty_score = (
            max(0, min(100, int(difficulty_score_raw))) if isinstance(difficulty_score_raw, int) else None
        )
        budget_outcome = _normalize_string(diagnostics_payload.get("budget_outcome"), max_length=80)
        retry_suppressed = (
            bool(diagnostics_payload.get("retry_suppressed"))
            if isinstance(diagnostics_payload.get("retry_suppressed"), bool)
            else None
        )
        degraded_state = _normalize_string(diagnostics_payload.get("degraded_state"), max_length=120)
        contract_status = _normalize_string(contract_payload.get("evaluation_status"), max_length=40)
        contract_reason_codes = _normalize_string_list(
            contract_payload.get("reason_codes"), max_items=12, max_item_length=80
        )
        contract_warning_codes = _normalize_string_list(
            contract_payload.get("warning_codes"), max_items=12, max_item_length=80
        )
        contract_retry_likelihood = _normalize_string(
            contract_payload.get("retry_likelihood"),
            max_length=80,
        )
        candidate_item_count_raw = contract_payload.get("candidate_item_count")
        candidate_item_count = (
            max(0, int(candidate_item_count_raw)) if isinstance(candidate_item_count_raw, int) else None
        )
        normalized_item_count_raw = contract_payload.get("normalized_item_count")
        normalized_item_count = (
            max(0, int(normalized_item_count_raw)) if isinstance(normalized_item_count_raw, int) else None
        )
        dropped_item_count_raw = contract_payload.get("dropped_item_count")
        dropped_item_count = max(0, int(dropped_item_count_raw)) if isinstance(dropped_item_count_raw, int) else None
        required_files_expected = _normalize_string_list(
            contract_payload.get("required_artifact_files_expected"),
            max_items=12,
            max_item_length=160,
        )
        required_files_present = _normalize_string_list(
            contract_payload.get("required_artifact_files_present"),
            max_items=12,
            max_item_length=160,
        )
        missing_required_files = _normalize_string_list(
            contract_payload.get("missing_required_artifact_files"),
            max_items=12,
            max_item_length=160,
        )
        content_density_failures_by_file = _normalize_string_list(
            contract_payload.get("content_density_failures_by_file"),
            max_items=20,
            max_item_length=200,
        )
        parser_rejection_reason_counts_raw = contract_payload.get("parser_rejection_reason_counts")
        parser_rejection_reason_counts: dict[str, int] = {}
        if isinstance(parser_rejection_reason_counts_raw, dict):
            for raw_key, raw_value in parser_rejection_reason_counts_raw.items():
                key = _normalize_string(raw_key, max_length=80)
                if key is None or not isinstance(raw_value, int):
                    continue
                parser_rejection_reason_counts[key] = max(0, int(raw_value))
        artifact_primary_file_detected = (
            bool(contract_payload.get("artifact_primary_file_detected"))
            if isinstance(contract_payload.get("artifact_primary_file_detected"), bool)
            else None
        )
        ai_diagnostics_summary = build_ai_diagnostics_summary(
            failure_category=normalized_failure_category or failure_category,
            failure_reason=normalized_failure_reason or failure_reason,
            failure_source=normalized_failure_source or failure_source,
            retryable=normalized_failure_retryable if isinstance(normalized_failure_retryable, bool) else retryable_flag,
            hint=failure_hint,
            budget_outcome=budget_outcome,
            retry_suppressed=retry_suppressed,
            trimming_pass_count=trimming_pass_count,
            difficulty_score=difficulty_score,
            original_input_size=original_input_size,
            final_input_size=final_input_size,
            trimmed_bytes=trimmed_bytes,
            degraded_state=degraded_state,
        )
        if not any(value is not None for value in ai_diagnostics_summary.values()):
            ai_diagnostics_summary = None
        return {
            "last_status": status_value,
            "last_failure_category": failure_category,
            "last_failure_reason": failure_reason,
            "last_failure_message": _normalize_string(artifact.error_summary, max_length=400),
            "last_failure_retryable": retryable_flag,
            "last_failure_code": failure_code,
            "last_failure_normalized_category": normalized_failure_category,
            "last_failure_normalized_reason": normalized_failure_reason,
            "last_failure_normalized_source": normalized_failure_source,
            "last_failure_normalized_retryable": normalized_failure_retryable,
            "last_failure_provider_attempt_count": provider_attempt_count,
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
            "last_failure_hint": failure_hint,
            "last_failure_timeout_seconds": timeout_seconds,
            "last_failure_timeout_source": timeout_source,
            "last_failure_original_input_size": original_input_size,
            "last_failure_final_input_size": final_input_size,
            "last_failure_trimmed_bytes": trimmed_bytes,
            "last_failure_trimming_pass_count": trimming_pass_count,
            "last_failure_difficulty_score": difficulty_score,
            "last_failure_budget_outcome": budget_outcome,
            "last_failure_retry_suppressed": retry_suppressed,
            "last_failure_degraded_state": degraded_state,
            "last_draft_ai_diagnostics_summary": ai_diagnostics_summary,
            "last_contract_status": contract_status,
            "last_contract_reason_codes": contract_reason_codes,
            "last_contract_warning_codes": contract_warning_codes,
            "last_contract_retry_likelihood": contract_retry_likelihood,
            "last_contract_candidate_item_count": candidate_item_count,
            "last_contract_normalized_item_count": normalized_item_count,
            "last_contract_dropped_item_count": dropped_item_count,
            "last_contract_required_artifact_files_expected": required_files_expected,
            "last_contract_required_artifact_files_present": required_files_present,
            "last_contract_missing_required_artifact_files": missing_required_files,
            "last_contract_content_density_failures_by_file": content_density_failures_by_file,
            "last_contract_parser_rejection_reason_counts": parser_rejection_reason_counts,
            "last_contract_artifact_primary_file_detected": artifact_primary_file_detected,
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
        draft_contract_diagnostics: dict[str, object] | None = None,
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
            draft_contract_diagnostics=draft_contract_diagnostics,
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
        draft_contract_diagnostics: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_failure_source = _normalize_string(failure_source, max_length=40)
        if normalized_failure_source not in {"local_preflight", "remote_provider", "local_validation", "unknown"}:
            normalized_failure_source = None
        compatibility_decision = (
            "blocked_local_preflight" if normalized_failure_source == "local_preflight" else "allowed"
        )
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
            "normalized_failure_category": _normalize_string(failure.normalized_failure_category, max_length=80),
            "normalized_failure_reason": _normalize_string(failure.normalized_failure_reason, max_length=120),
            "normalized_failure_source": _normalize_string(failure.normalized_failure_source, max_length=80),
            "error_code": failure.error_code,
            "message": failure.message_for_operator,
            "retryable": failure.retryable,
            "normalized_retryable": (
                failure.normalized_retryable if isinstance(failure.normalized_retryable, bool) else None
            ),
            "provider_attempt_count": (
                max(1, int(failure.provider_attempt_count)) if isinstance(failure.provider_attempt_count, int) else None
            ),
            "failure_source": normalized_failure_source,
            "correlation_id": failure.correlation_id or draft_run_id,
            "provider_name": failure.provider_name,
            "model_name": failure.model_name,
            "prompt_version": failure.prompt_version,
            "failure_hint": self._draft_failure_hint(
                failure_reason=failure.failure_reason,
                normalized_failure_category=failure.normalized_failure_category,
                normalized_failure_reason=failure.normalized_failure_reason,
            ),
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
            "original_input_size": (
                max(0, int(failure.original_input_size)) if isinstance(failure.original_input_size, int) else None
            ),
            "final_input_size": (
                max(0, int(failure.final_input_size)) if isinstance(failure.final_input_size, int) else None
            ),
            "trimmed_bytes": max(0, int(failure.trimmed_bytes)) if isinstance(failure.trimmed_bytes, int) else None,
            "trimming_pass_count": (
                max(0, int(failure.trimming_pass_count)) if isinstance(failure.trimming_pass_count, int) else None
            ),
            "difficulty_score": (
                max(0, min(100, int(failure.difficulty_score))) if isinstance(failure.difficulty_score, int) else None
            ),
            "budget_outcome": _normalize_string(failure.budget_outcome, max_length=80),
            "retry_suppressed": (
                bool(failure.retry_suppressed) if isinstance(failure.retry_suppressed, bool) else None
            ),
            "degraded_state": _normalize_string(failure.degraded_state, max_length=120),
            "recorded_at": utc_now().isoformat(),
        }
        normalized_contract_diagnostics = _normalize_json_dict(draft_contract_diagnostics)
        if normalized_contract_diagnostics:
            payload["draft_contract_evaluation"] = normalized_contract_diagnostics
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
            normalized_failure_category=_normalize_string(
                error.normalized_failure_category or details.get("normalized_failure_category"),
                max_length=80,
            ),
            normalized_failure_reason=_normalize_string(
                error.normalized_failure_reason or details.get("normalized_failure_reason"),
                max_length=120,
            ),
            normalized_failure_source=_normalize_string(
                error.normalized_failure_source or details.get("normalized_failure_source"),
                max_length=80,
            ),
            normalized_retryable=(
                error.normalized_retryable
                if isinstance(error.normalized_retryable, bool)
                else (
                    details.get("normalized_retryable")
                    if isinstance(details.get("normalized_retryable"), bool)
                    else None
                )
            ),
            provider_attempt_count=(
                max(1, int(error.attempt_count))
                if isinstance(error.attempt_count, int)
                else (
                    max(1, int(details.get("attempt_count"))) if isinstance(details.get("attempt_count"), int) else None
                )
            ),
            original_input_size=(
                max(0, int(error.original_input_size))
                if isinstance(error.original_input_size, int)
                else (
                    max(0, int(details.get("original_input_size")))
                    if isinstance(details.get("original_input_size"), int)
                    else None
                )
            ),
            final_input_size=(
                max(0, int(error.final_input_size))
                if isinstance(error.final_input_size, int)
                else (
                    max(0, int(details.get("final_input_size")))
                    if isinstance(details.get("final_input_size"), int)
                    else None
                )
            ),
            trimmed_bytes=(
                max(0, int(error.trimmed_bytes))
                if isinstance(error.trimmed_bytes, int)
                else (
                    max(0, int(details.get("trimmed_bytes")))
                    if isinstance(details.get("trimmed_bytes"), int)
                    else None
                )
            ),
            trimming_pass_count=(
                max(0, int(error.trimming_pass_count))
                if isinstance(error.trimming_pass_count, int)
                else (
                    max(0, int(details.get("trimming_pass_count")))
                    if isinstance(details.get("trimming_pass_count"), int)
                    else None
                )
            ),
            difficulty_score=(
                max(0, min(100, int(error.difficulty_score)))
                if isinstance(error.difficulty_score, int)
                else (
                    max(0, min(100, int(details.get("difficulty_score"))))
                    if isinstance(details.get("difficulty_score"), int)
                    else None
                )
            ),
            budget_outcome=_normalize_string(
                error.budget_outcome or details.get("budget_outcome"),
                max_length=80,
            ),
            retry_suppressed=(
                error.retry_suppressed
                if isinstance(error.retry_suppressed, bool)
                else (
                    details.get("retry_suppressed")
                    if isinstance(details.get("retry_suppressed"), bool)
                    else None
                )
            ),
            degraded_state=_normalize_string(
                error.degraded_state or details.get("degraded_state"),
                max_length=120,
            ),
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

    @staticmethod
    def _draft_failure_hint(
        *,
        failure_reason: str | None,
        normalized_failure_category: str | None,
        normalized_failure_reason: str | None,
    ) -> str | None:
        normalized_reason = _normalize_string(normalized_failure_reason, max_length=120)
        fallback_reason = _normalize_string(failure_reason, max_length=80)
        return build_ai_failure_hint(
            failure_category=_normalize_string(normalized_failure_category, max_length=80),
            failure_reason=normalized_reason or fallback_reason,
        )

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
        file_validation_diagnostics: dict[str, object] | None = None,
    ) -> None:
        merged_diagnostics = self._build_draft_contract_diagnostics(
            evaluation=evaluation,
            file_validation_diagnostics=file_validation_diagnostics,
        )
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
            "retry_likelihood": _normalize_string(evaluation.retry_likelihood, max_length=80),
            "candidate_item_count": max(0, int(evaluation.candidate_item_count)),
            "normalized_item_count": max(0, int(evaluation.normalized_item_count)),
            "required_artifact_files_expected": list(evaluation.required_artifact_files_expected),
            "required_artifact_files_present": list(evaluation.required_artifact_files_present),
            "missing_required_artifact_files": list(evaluation.missing_required_artifact_files),
            "content_density_failures_by_file": list(evaluation.content_density_failures_by_file),
            "artifact_primary_file_detected": bool(evaluation.artifact_primary_file_detected),
            "parser_rejection_reason_counts": _normalize_json_dict(
                merged_diagnostics.get("parser_rejection_reason_counts")
            ),
        }
        level = logging.INFO if evaluation.status != "rejected" else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_DRAFT_CONTRACT_EVALUATION_LOG_EVENT,
            level=level,
        )

    @staticmethod
    def _build_draft_contract_diagnostics(
        *,
        evaluation: AIResponseContractEvaluation,
        file_validation_diagnostics: dict[str, object] | None = None,
    ) -> dict[str, object]:
        parser_rejection_reason_counts_raw: object = (
            _normalize_json_dict(file_validation_diagnostics).get("parser_rejection_reason_counts")
            if isinstance(file_validation_diagnostics, dict)
            else {}
        )
        parser_rejection_reason_counts: dict[str, int] = {}
        if isinstance(parser_rejection_reason_counts_raw, dict):
            for raw_key, raw_value in parser_rejection_reason_counts_raw.items():
                key = _normalize_string(raw_key, max_length=80)
                if key is None or not isinstance(raw_value, int):
                    continue
                parser_rejection_reason_counts[key] = max(0, int(raw_value))
        return {
            "evaluation_status": _normalize_string(evaluation.status, max_length=40),
            "evaluation_score": max(0, int(evaluation.score)),
            "reason_codes": list(evaluation.reasons),
            "warning_codes": list(evaluation.warnings),
            "retryable": evaluation.retryable if isinstance(evaluation.retryable, bool) else None,
            "retry_likelihood": _normalize_string(evaluation.retry_likelihood, max_length=80),
            "candidate_item_count": max(0, int(evaluation.candidate_item_count)),
            "normalized_item_count": max(0, int(evaluation.normalized_item_count)),
            "dropped_item_count": max(0, int(evaluation.dropped_item_count)),
            "required_artifact_files_expected": list(evaluation.required_artifact_files_expected),
            "required_artifact_files_present": list(evaluation.required_artifact_files_present),
            "missing_required_artifact_files": list(evaluation.missing_required_artifact_files),
            "content_density_failures_by_file": list(evaluation.content_density_failures_by_file),
            "artifact_primary_file_detected": bool(evaluation.artifact_primary_file_detected),
            "parser_rejection_reason_counts": parser_rejection_reason_counts,
        }

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
        correlation_id: str | None = None,
    ) -> None:
        safe_failure_category = failure_category if failure_category in _MIGRATION_FAILURE_CATEGORY_VALUES else None
        safe_failure_reason = _normalize_string(failure_reason, max_length=300)
        safe_correlation_id = _normalize_string(correlation_id, max_length=120)
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
        if safe_correlation_id:
            payload["correlation_id"] = safe_correlation_id
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
            "deploy_workflow_mode": provision_result.deploy_workflow_mode,
            "target_environment_key": provision_result.target_environment_key,
            "target_environment_source": provision_result.target_environment_source,
            "kubernetes_namespace": provision_result.kubernetes_namespace,
            "namespace_source": provision_result.namespace_source,
            "managed_manifest_paths": list(provision_result.managed_manifest_paths or ()),
            "namespace_model_status": provision_result.namespace_model_status,
            "managed_resource_quota_expected": provision_result.managed_resource_quota_expected,
            "managed_resource_quota_present": provision_result.managed_resource_quota_present,
            "managed_limit_range_expected": provision_result.managed_limit_range_expected,
            "managed_limit_range_present": provision_result.managed_limit_range_present,
            "managed_network_policy_expected": provision_result.managed_network_policy_expected,
            "managed_network_policy_present": provision_result.managed_network_policy_present,
            "managed_namespace_policies_aligned": provision_result.managed_namespace_policies_aligned,
            "managed_workflow_outcome": _normalize_string(
                provision_result.managed_workflow_outcome,
                max_length=80,
            ),
        }
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_MIGRATION_WORKFLOW_PROVISIONED_LOG_EVENT,
            level=logging.INFO,
        )

    def _log_workflow_provisioning(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        principal_id: str | None,
        artifact_version_id: str | None,
        repo_owner: str,
        repo_name: str,
        ref: str,
        workflow_id: str,
        workflow_path: str,
        status: str,
        remediation_mode: str,
        deploy_workflow_mode: str | None = None,
        target_environment_key: str | None = None,
        target_environment_source: str | None = None,
        kubernetes_namespace: str | None = None,
        namespace_source: str | None = None,
        namespace_model_status: str | None = None,
        managed_manifest_paths: tuple[str, ...] | list[str] | None = None,
        managed_resource_quota_expected: bool | None = None,
        managed_resource_quota_present: bool | None = None,
        managed_limit_range_expected: bool | None = None,
        managed_limit_range_present: bool | None = None,
        managed_network_policy_expected: bool | None = None,
        managed_network_policy_present: bool | None = None,
        managed_namespace_policies_aligned: bool | None = None,
        workflow_remediation_outcome: str | None = None,
        commit_sha: str | None = None,
        verified: bool | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "event": _MIGRATION_WORKFLOW_PROVISIONING_LOG_EVENT,
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "principal_id": principal_id,
            "artifact_version_id": artifact_version_id,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "ref": ref,
            "workflow_id": workflow_id,
            "workflow_path": workflow_path,
            "status": _normalize_string(status, max_length=40) or "unknown",
            "remediation_mode": _normalize_string(remediation_mode, max_length=60) or "unknown",
        }
        normalized_workflow_mode = _normalize_string(deploy_workflow_mode, max_length=60)
        if normalized_workflow_mode:
            payload["deploy_workflow_mode"] = normalized_workflow_mode
        normalized_target_environment_key = _normalize_string(target_environment_key, max_length=80)
        if normalized_target_environment_key:
            payload["target_environment_key"] = normalized_target_environment_key
        normalized_target_environment_source = _normalize_string(target_environment_source, max_length=60)
        if normalized_target_environment_source:
            payload["target_environment_source"] = normalized_target_environment_source
        normalized_kubernetes_namespace = _normalize_string(kubernetes_namespace, max_length=63)
        if normalized_kubernetes_namespace:
            payload["kubernetes_namespace"] = normalized_kubernetes_namespace
        normalized_namespace_source = _normalize_string(namespace_source, max_length=60)
        if normalized_namespace_source:
            payload["namespace_source"] = normalized_namespace_source
        normalized_namespace_model_status = _normalize_string(namespace_model_status, max_length=40)
        if normalized_namespace_model_status:
            payload["namespace_model_status"] = normalized_namespace_model_status
        normalized_manifest_paths: list[str] = []
        if isinstance(managed_manifest_paths, (tuple, list)):
            for item in managed_manifest_paths:
                normalized = _normalize_string(item, max_length=180)
                if normalized:
                    normalized_manifest_paths.append(normalized)
        if normalized_manifest_paths:
            payload["managed_manifest_paths"] = normalized_manifest_paths
        if managed_resource_quota_expected is not None:
            payload["managed_resource_quota_expected"] = bool(managed_resource_quota_expected)
        if managed_resource_quota_present is not None:
            payload["managed_resource_quota_present"] = bool(managed_resource_quota_present)
        if managed_limit_range_expected is not None:
            payload["managed_limit_range_expected"] = bool(managed_limit_range_expected)
        if managed_limit_range_present is not None:
            payload["managed_limit_range_present"] = bool(managed_limit_range_present)
        if managed_network_policy_expected is not None:
            payload["managed_network_policy_expected"] = bool(managed_network_policy_expected)
        if managed_network_policy_present is not None:
            payload["managed_network_policy_present"] = bool(managed_network_policy_present)
        if managed_namespace_policies_aligned is not None:
            payload["managed_namespace_policies_aligned"] = bool(managed_namespace_policies_aligned)
        normalized_workflow_remediation_outcome = _normalize_string(
            workflow_remediation_outcome,
            max_length=80,
        )
        if normalized_workflow_remediation_outcome:
            payload["workflow_remediation_outcome"] = normalized_workflow_remediation_outcome
        normalized_sha = _normalize_string(commit_sha, max_length=80)
        if normalized_sha:
            payload["commit_sha"] = normalized_sha
        if verified is not None:
            payload["verified"] = bool(verified)
        normalized_error_code = _normalize_string(error_code, max_length=80)
        if normalized_error_code:
            payload["error_code"] = normalized_error_code
        normalized_error_message = _normalize_string(error_message, max_length=300)
        if normalized_error_message:
            payload["error_message"] = normalized_error_message
        level = logging.INFO if payload["status"] != "failed" else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message=_MIGRATION_WORKFLOW_PROVISIONING_LOG_EVENT,
            level=level,
        )

    def _log_deploy_secret_propagation(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        artifact_version_id: str | None,
        principal_id: str | None,
        repo_owner: str,
        repo_name: str,
        ref: str,
        attempted: bool,
        status: str,
        reason: str | None = None,
        action: str | None = None,
        secret_source: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "event": "seo_migration_deploy_secret_propagation",
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "artifact_version_id": artifact_version_id,
            "principal_id": principal_id,
            "repo_owner": _normalize_string(repo_owner, max_length=120),
            "repo_name": _normalize_string(repo_name, max_length=120),
            "ref": _normalize_string(ref, max_length=120),
            "secret_name": _DEPLOY_SECRET_NAME_GCP_DEPLOY_KEY,
            "attempted": bool(attempted),
            "status": _normalize_string(status, max_length=60)
            or _DEPLOY_SECRET_PROPAGATION_STATUS_NOT_ATTEMPTED,
        }
        normalized_reason = _normalize_string(reason, max_length=120)
        if normalized_reason:
            payload["reason"] = normalized_reason
        normalized_action = _normalize_string(action, max_length=40)
        if normalized_action:
            payload["action"] = normalized_action
        normalized_secret_source = _normalize_string(secret_source, max_length=80)
        if normalized_secret_source:
            payload["secret_source"] = normalized_secret_source
        level = logging.INFO if payload.get("status") != _DEPLOY_SECRET_PROPAGATION_STATUS_FAILED else logging.WARNING
        self._emit_structured_service_log(
            payload=payload,
            fallback_message="seo_migration_deploy_secret_propagation",
            level=level,
        )

    def _attempt_deploy_secret_propagation(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        artifact_version_id: str,
        principal_id: str | None,
        workflow_owner: str,
        workflow_repo: str,
        workflow_ref: str,
        publish_target: dict[str, object],
        deploy_target: dict[str, object] | None,
        admin_prerequisites: dict[str, bool],
    ) -> tuple[bool, str, str | None, str | None]:
        deploy_secret_value, deploy_secret_source, deploy_secret_resolution_reason = (
            self._resolve_deploy_secret_for_propagation()
        )
        normalized_owner = _normalize_string(workflow_owner, max_length=120) or ""
        normalized_repo = _normalize_string(workflow_repo, max_length=120) or ""
        normalized_ref = _normalize_string(workflow_ref, max_length=120) or ""
        normalized_publish_owner = _normalize_string(publish_target.get("repo_owner"), max_length=120) or ""
        normalized_publish_repo = _normalize_string(publish_target.get("repo_name"), max_length=120) or ""
        normalized_publish_branch = _normalize_string(publish_target.get("branch"), max_length=120) or ""

        guardrail_reason: str | None = None
        if not bool((deploy_target or {}).get("enabled")):
            guardrail_reason = "deploy_target_not_enabled"
        elif not bool(admin_prerequisites.get("admin_publish_configured")):
            guardrail_reason = "admin_publish_target_not_configured"
        elif not bool(admin_prerequisites.get("admin_publish_config_enabled")):
            guardrail_reason = "admin_publish_target_disabled"
        elif normalized_owner != normalized_publish_owner:
            guardrail_reason = "repo_owner_not_approved"
        elif (
            normalized_owner != normalized_publish_owner
            or normalized_repo != normalized_publish_repo
            or normalized_ref != normalized_publish_branch
        ):
            guardrail_reason = "target_tuple_mismatch"

        if guardrail_reason is not None:
            self._log_deploy_secret_propagation(
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace_id,
                artifact_version_id=artifact_version_id,
                principal_id=principal_id,
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                ref=normalized_ref,
                attempted=False,
                status=_DEPLOY_SECRET_PROPAGATION_STATUS_SKIPPED_GUARDRAIL,
                reason=guardrail_reason,
                secret_source=deploy_secret_source,
            )
            return (
                False,
                _DEPLOY_SECRET_PROPAGATION_STATUS_SKIPPED_GUARDRAIL,
                guardrail_reason,
                deploy_secret_source,
            )

        if not deploy_secret_value:
            reason = deploy_secret_resolution_reason or _GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING
            self._log_deploy_secret_propagation(
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace_id,
                artifact_version_id=artifact_version_id,
                principal_id=principal_id,
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                ref=normalized_ref,
                attempted=False,
                status=_DEPLOY_SECRET_PROPAGATION_STATUS_FAILED,
                reason=reason,
                secret_source=deploy_secret_source,
            )
            return (
                False,
                _DEPLOY_SECRET_PROPAGATION_STATUS_FAILED,
                reason,
                deploy_secret_source,
            )

        try:
            propagation_result: SEOMigrationGitHubActionsSecretUpsertResult = (
                self.github_publisher.upsert_actions_secret(
                    repo_owner=normalized_owner,
                    repo_name=normalized_repo,
                    secret_name=_DEPLOY_SECRET_NAME_GCP_DEPLOY_KEY,
                    secret_value=deploy_secret_value,
                )
            )
            normalized_action = (
                _normalize_string(getattr(propagation_result, "action", None), max_length=20) or ""
            ).lower()
            status = (
                _DEPLOY_SECRET_PROPAGATION_STATUS_UPDATED
                if normalized_action == _DEPLOY_SECRET_PROPAGATION_STATUS_UPDATED
                else _DEPLOY_SECRET_PROPAGATION_STATUS_CREATED
            )
            self._log_deploy_secret_propagation(
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace_id,
                artifact_version_id=artifact_version_id,
                principal_id=principal_id,
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                ref=normalized_ref,
                attempted=True,
                status=status,
                action=normalized_action or status,
                secret_source=deploy_secret_source,
            )
            return (
                True,
                status,
                None,
                deploy_secret_source,
            )
        except SEOMigrationGitHubPublisherError as exc:
            normalized_reason = _normalize_string(exc.code, max_length=120) or "secret_propagation_failed"
            self._log_deploy_secret_propagation(
                business_id=business_id,
                site_id=site_id,
                workspace_id=workspace_id,
                artifact_version_id=artifact_version_id,
                principal_id=principal_id,
                repo_owner=normalized_owner,
                repo_name=normalized_repo,
                ref=normalized_ref,
                attempted=True,
                status=_DEPLOY_SECRET_PROPAGATION_STATUS_FAILED,
                reason=normalized_reason,
                secret_source=deploy_secret_source,
            )
            return (
                True,
                _DEPLOY_SECRET_PROPAGATION_STATUS_FAILED,
                normalized_reason,
                deploy_secret_source,
            )

    def _resolve_deploy_secret_for_propagation(self) -> tuple[str | None, str | None, str | None]:
        admin_managed_status = (
            self.github_publish_config_service.get_managed_gcp_deploy_key_status()
            if self.github_publish_config_service is not None
            else {}
        )
        admin_secret_configured = bool(admin_managed_status.get("configured"))
        if admin_secret_configured and self.github_publish_config_service is not None:
            try:
                admin_secret_value = self.github_publish_config_service.get_managed_gcp_deploy_key_value()
            except GitHubPublishConfigSecretError:
                return (
                    None,
                    _DEPLOY_SECRET_SOURCE_ADMIN_MANAGED,
                    _GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID,
                )
            if admin_secret_value:
                return (
                    admin_secret_value,
                    _DEPLOY_SECRET_SOURCE_ADMIN_MANAGED,
                    None,
                )

        runtime_fallback_secret = (self.deploy_secret_gcp_key or "").strip()
        if runtime_fallback_secret:
            return (
                runtime_fallback_secret,
                _DEPLOY_SECRET_SOURCE_RUNTIME_FALLBACK,
                None,
            )
        return (
            None,
            _DEPLOY_SECRET_SOURCE_ADMIN_MANAGED if self.github_publish_config_service is not None else None,
            _GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING,
        )

    def _log_target_readiness_check(
        self,
        *,
        business_id: str,
        site_id: str,
        workspace_id: str | None,
        artifact_version_id: str | None,
        repo_owner: str,
        repo_name: str,
        requested_ref: str,
        resolved_ref: str,
        ref_source: str,
        workflow_id: str,
        workflow_path: str | None,
        repo_exists: bool,
        ref_exists: bool,
        workflow_exists: bool,
        workflow_dispatch_ready: bool,
        workflow_dispatch_supported: bool | None = None,
        workflow_trigger_types: tuple[str, ...] | list[str] | None = None,
        dispatch_service_availability: bool | None = None,
        dispatch_service_reason_code: str | None = None,
        dispatch_identifier_type: str | None = None,
        workflow_identifier_requested: str | None = None,
        workflow_identifier_used: str | None = None,
        workflow_identifier_type_requested: str | None = None,
        workflow_identifier_type_used: str | None = None,
        workflow_dispatch_resolution_source: str | None = None,
        workflow_name: str | None = None,
        workflow_conformance_checked: bool | None = None,
        workflow_conformance_status: str | None = None,
        workflow_conformance_reasons: tuple[str, ...] | list[str] | None = None,
        workflow_conformance_evidence_summary: str | None = None,
        kubernetes_namespace: str | None = None,
        namespace_source: str | None = None,
        namespace_model_status: str | None = None,
        workflow_namespace_aligned: bool | None = None,
        manifest_namespace_aligned: bool | None = None,
        managed_resource_quota_expected: bool | None = None,
        managed_resource_quota_present: bool | None = None,
        managed_limit_range_expected: bool | None = None,
        managed_limit_range_present: bool | None = None,
        managed_network_policy_expected: bool | None = None,
        managed_network_policy_present: bool | None = None,
        managed_namespace_policies_aligned: bool | None = None,
        deploy_trace_id: str | None = None,
        remediation_mode: str,
    ) -> None:
        payload: dict[str, object] = {
            "event": "seo_migration_target_readiness_check",
            "timestamp": utc_now().isoformat(),
            "business_id": business_id,
            "site_id": site_id,
            "workspace_id": workspace_id,
            "artifact_version_id": artifact_version_id,
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "requested_ref": requested_ref,
            "resolved_ref": resolved_ref,
            "ref_source": ref_source,
            "workflow_id": workflow_id,
            "repo_exists": bool(repo_exists),
            "ref_exists": bool(ref_exists),
            "workflow_exists": bool(workflow_exists),
            "workflow_dispatch_ready": bool(workflow_dispatch_ready),
            "remediation_mode": _normalize_string(remediation_mode, max_length=60) or "none",
        }
        if workflow_dispatch_supported is not None:
            payload["workflow_dispatch_supported"] = bool(workflow_dispatch_supported)
        normalized_trigger_types: list[str] = []
        if isinstance(workflow_trigger_types, (tuple, list)):
            for item in workflow_trigger_types:
                normalized = _normalize_string(item, max_length=60)
                if normalized:
                    normalized_trigger_types.append(normalized)
        if normalized_trigger_types:
            payload["workflow_trigger_types"] = normalized_trigger_types
        normalized_identifier_type = _normalize_string(dispatch_identifier_type, max_length=80)
        if normalized_identifier_type:
            payload["dispatch_identifier_type"] = normalized_identifier_type
        normalized_identifier_requested = _normalize_string(workflow_identifier_requested, max_length=200)
        if normalized_identifier_requested:
            payload["workflow_identifier_requested"] = normalized_identifier_requested
        normalized_identifier_used = _normalize_string(workflow_identifier_used, max_length=200)
        if normalized_identifier_used:
            payload["workflow_identifier_used"] = normalized_identifier_used
        normalized_identifier_type_requested = _normalize_string(workflow_identifier_type_requested, max_length=80)
        if normalized_identifier_type_requested:
            payload["workflow_identifier_type_requested"] = normalized_identifier_type_requested
        normalized_identifier_type_used = _normalize_string(workflow_identifier_type_used, max_length=80)
        if normalized_identifier_type_used:
            payload["workflow_identifier_type_used"] = normalized_identifier_type_used
        normalized_dispatch_resolution_source = _normalize_string(workflow_dispatch_resolution_source, max_length=80)
        if normalized_dispatch_resolution_source:
            payload["workflow_dispatch_resolution_source"] = normalized_dispatch_resolution_source
        normalized_workflow_name = _normalize_string(workflow_name, max_length=160)
        if normalized_workflow_name:
            payload["workflow_name"] = normalized_workflow_name
        if workflow_conformance_checked is not None:
            payload["workflow_conformance_checked"] = bool(workflow_conformance_checked)
        normalized_conformance_status = _normalize_string(workflow_conformance_status, max_length=80)
        if normalized_conformance_status:
            payload["workflow_conformance_status"] = normalized_conformance_status
        normalized_conformance_reasons: list[str] = []
        if isinstance(workflow_conformance_reasons, (tuple, list)):
            for item in workflow_conformance_reasons:
                normalized = _normalize_string(item, max_length=120)
                if normalized:
                    normalized_conformance_reasons.append(normalized)
        if normalized_conformance_reasons:
            payload["workflow_conformance_reasons"] = normalized_conformance_reasons
        normalized_conformance_evidence_summary = _normalize_string(
            workflow_conformance_evidence_summary,
            max_length=240,
        )
        if normalized_conformance_evidence_summary:
            payload["workflow_conformance_evidence_summary"] = normalized_conformance_evidence_summary
        normalized_kubernetes_namespace = _normalize_string(kubernetes_namespace, max_length=63)
        if normalized_kubernetes_namespace:
            payload["kubernetes_namespace"] = normalized_kubernetes_namespace
        normalized_namespace_source = _normalize_string(namespace_source, max_length=60)
        if normalized_namespace_source:
            payload["namespace_source"] = normalized_namespace_source
        normalized_namespace_model_status = _normalize_string(namespace_model_status, max_length=40)
        if normalized_namespace_model_status:
            payload["namespace_model_status"] = normalized_namespace_model_status
        if workflow_namespace_aligned is not None:
            payload["workflow_namespace_aligned"] = bool(workflow_namespace_aligned)
        if manifest_namespace_aligned is not None:
            payload["manifest_namespace_aligned"] = bool(manifest_namespace_aligned)
        if managed_resource_quota_expected is not None:
            payload["managed_resource_quota_expected"] = bool(managed_resource_quota_expected)
        if managed_resource_quota_present is not None:
            payload["managed_resource_quota_present"] = bool(managed_resource_quota_present)
        if managed_limit_range_expected is not None:
            payload["managed_limit_range_expected"] = bool(managed_limit_range_expected)
        if managed_limit_range_present is not None:
            payload["managed_limit_range_present"] = bool(managed_limit_range_present)
        if managed_network_policy_expected is not None:
            payload["managed_network_policy_expected"] = bool(managed_network_policy_expected)
        if managed_network_policy_present is not None:
            payload["managed_network_policy_present"] = bool(managed_network_policy_present)
        if managed_namespace_policies_aligned is not None:
            payload["managed_namespace_policies_aligned"] = bool(managed_namespace_policies_aligned)
        if dispatch_service_availability is not None:
            payload["dispatch_service_availability"] = bool(dispatch_service_availability)
        normalized_dispatch_service_reason = _normalize_dispatch_service_reason_code(dispatch_service_reason_code)
        if normalized_dispatch_service_reason:
            payload["dispatch_service_reason_code"] = normalized_dispatch_service_reason
        normalized_deploy_trace_id = _normalize_string(deploy_trace_id, max_length=80)
        if normalized_deploy_trace_id:
            payload["deploy_trace_id"] = normalized_deploy_trace_id
        normalized_workflow_path = _normalize_string(workflow_path, max_length=200)
        if normalized_workflow_path:
            payload["workflow_path"] = normalized_workflow_path
        level = (
            logging.INFO
            if payload["repo_exists"]
            and payload["ref_exists"]
            and payload["workflow_exists"]
            and payload["workflow_dispatch_ready"]
            and payload.get("dispatch_service_availability", True)
            else logging.WARNING
        )
        self._emit_structured_service_log(
            payload=payload,
            fallback_message="seo_migration_target_readiness_check",
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

    @staticmethod
    def _normalize_admin_repo_owner(value: object) -> str:
        normalized = _normalize_string(value, max_length=120) or ""
        # Backward compatibility: older admin config rows may still contain owner/repo.
        # Ownership split now treats admin config as owner-only.
        if "/" in normalized:
            normalized = normalized.split("/", 1)[0].strip()
        return normalized

    def _resolve_admin_deploy_template_metadata(self) -> dict[str, object]:
        deploy_workflow_mode = _DEPLOY_WORKFLOW_MODE_SITE_REPO_TEMPLATE_V1
        target_environment_key = _DEPLOY_DEFAULT_TARGET_ENVIRONMENT_KEY
        target_environment_source = _DEPLOY_TARGET_ENVIRONMENT_SOURCE_ADMIN
        managed_gke_cluster_name: str | None = None
        managed_gke_cluster_location: str | None = None
        managed_gke_project_id: str | None = None
        namespace_isolation_defaults = normalize_namespace_isolation_defaults(None).model_dump(mode="json")
        if self.github_publish_config_service is None:
            return {
                "deploy_workflow_mode": deploy_workflow_mode,
                "target_environment_key": target_environment_key,
                "target_environment_source": target_environment_source,
                "managed_gke_cluster_name": managed_gke_cluster_name,
                "managed_gke_cluster_location": managed_gke_cluster_location,
                "managed_gke_project_id": managed_gke_project_id,
                "namespace_isolation_defaults": namespace_isolation_defaults,
            }
        admin_config = self.github_publish_config_service.get()
        candidate_mode = _normalize_string(
            getattr(admin_config, "deploy_workflow_mode", None),
            max_length=60,
        )
        if candidate_mode == _DEPLOY_WORKFLOW_MODE_SITE_REPO_TEMPLATE_V1:
            deploy_workflow_mode = candidate_mode
        candidate_environment_key = _normalize_string(
            getattr(admin_config, "target_environment_key", None),
            max_length=80,
        )
        if candidate_environment_key:
            target_environment_key = candidate_environment_key
        candidate_source = _normalize_string(
            getattr(admin_config, "target_environment_source", None),
            max_length=60,
        )
        if candidate_source:
            target_environment_source = candidate_source
        managed_gke_cluster_name = _normalize_string(
            getattr(admin_config, "managed_gke_cluster_name", None),
            max_length=120,
        )
        managed_gke_cluster_location = _normalize_string(
            getattr(admin_config, "managed_gke_cluster_location", None),
            max_length=120,
        )
        managed_gke_project_id = _normalize_string(
            getattr(admin_config, "managed_gke_project_id", None),
            max_length=120,
        )
        candidate_namespace_defaults = normalize_namespace_isolation_defaults(
            getattr(admin_config, "namespace_isolation_defaults_json", None)
        ).model_dump(mode="json")
        if isinstance(candidate_namespace_defaults, dict):
            namespace_isolation_defaults = candidate_namespace_defaults
        return {
            "deploy_workflow_mode": deploy_workflow_mode,
            "target_environment_key": target_environment_key,
            "target_environment_source": target_environment_source,
            "managed_gke_cluster_name": managed_gke_cluster_name,
            "managed_gke_cluster_location": managed_gke_cluster_location,
            "managed_gke_project_id": managed_gke_project_id,
            "managed_gke_config": {
                "cluster_name": managed_gke_cluster_name,
                "cluster_location": managed_gke_cluster_location,
                "project_id": managed_gke_project_id,
            },
            "namespace_isolation_defaults": namespace_isolation_defaults,
        }

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
        admin_deploy_metadata = self._resolve_admin_deploy_template_metadata()
        workflow_id = str(normalized.get("workflow_id") or self.deploy_default_workflow_id).strip()
        workflow_path = _normalize_workflow_path_for_deploy(f".github/workflows/{workflow_id}")
        repo_name = str(normalized.get("repo_name") or fallback_publish.get("repo_name") or "").strip()
        kubernetes_namespace, namespace_source = _safe_derive_kubernetes_namespace_for_summary(
            repo_name=repo_name,
            site_id=workspace.site_id,
        )
        return {
            "enabled": bool(normalized.get("enabled")),
            "repo_owner": str(normalized.get("repo_owner") or fallback_publish.get("repo_owner") or "").strip(),
            "repo_name": repo_name,
            "workflow_id": workflow_id,
            "ref": str(normalized.get("ref") or self.deploy_default_ref).strip(),
            "deploy_workflow_mode": admin_deploy_metadata.get("deploy_workflow_mode"),
            "target_environment_key": admin_deploy_metadata.get("target_environment_key"),
            "target_environment_source": admin_deploy_metadata.get("target_environment_source"),
            "managed_gke_cluster_name": admin_deploy_metadata.get("managed_gke_cluster_name"),
            "managed_gke_cluster_location": admin_deploy_metadata.get("managed_gke_cluster_location"),
            "managed_gke_project_id": admin_deploy_metadata.get("managed_gke_project_id"),
            "site_workflow_file_path": workflow_path,
            "kubernetes_namespace": kubernetes_namespace,
            "namespace_source": namespace_source,
            "namespace_model_status": "unknown",
        }

    def _resolve_deploy_target_with_workflow_precedence(
        self,
        *,
        workspace: SEOMigrationWorkspace,
        effective_publish_config: dict[str, object],
        artifact_version_id: str | None,
        validate_workflow_candidates: bool = False,
    ) -> tuple[dict[str, object], dict[str, object]]:
        normalized_deploy_config = _normalize_deploy_config(workspace.deploy_config_json)
        configured_workflow_path = _normalize_workflow_path_for_deploy(normalized_deploy_config.get("workflow_id"))
        if configured_workflow_path:
            configured_workflow_id = _workflow_id_from_path_for_deploy(configured_workflow_path)
            if configured_workflow_id:
                normalized_deploy_config["workflow_id"] = configured_workflow_id
        publish_target = _resolve_publish_target(effective_publish_config)
        candidate_owner = str(
            normalized_deploy_config.get("repo_owner") or publish_target.get("repo_owner") or ""
        ).strip()
        candidate_repo = str(normalized_deploy_config.get("repo_name") or publish_target.get("repo_name") or "").strip()
        candidate_ref = str(normalized_deploy_config.get("ref") or self.deploy_default_ref or "").strip()
        history_workflow_id, history_workflow_path = _resolve_publish_history_workflow_identity(
            history=workspace.publish_history_json,
            artifact_version_id=artifact_version_id,
            repo_owner=candidate_owner,
            repo_name=candidate_repo,
            ref=candidate_ref,
        )
        site_specific_workflow_id = _derive_site_specific_workflow_id_for_repo_name(candidate_repo)
        site_specific_workflow_path = (
            _normalize_workflow_path_for_deploy(f".github/workflows/{site_specific_workflow_id}")
            if site_specific_workflow_id
            else None
        )

        fallback_source = _DEPLOY_WORKFLOW_SOURCE_DEFAULT
        if str(normalized_deploy_config.get("workflow_id") or "").strip():
            fallback_source = _DEPLOY_WORKFLOW_SOURCE_WORKSPACE_CONFIG

        resolved_target = _resolve_deploy_target(
            deploy_config=normalized_deploy_config,
            publish_config=effective_publish_config,
            default_workflow_id=self.deploy_default_workflow_id,
            default_ref=self.deploy_default_ref,
        )
        fallback_workflow_id = _normalize_workflow_id_for_deploy(resolved_target.get("workflow_id"))
        fallback_workflow_path = _normalize_workflow_path_for_deploy(
            f".github/workflows/{str(fallback_workflow_id or '').strip()}"
        )
        workflow_candidates: list[dict[str, str | None]] = []
        seen_candidate_keys: set[str] = set()

        def _append_candidate(*, source: str, workflow_id: object, workflow_path: object) -> None:
            normalized_path = _normalize_workflow_path_for_deploy(workflow_path)
            normalized_id = (
                _workflow_id_from_path_for_deploy(normalized_path)
                or _normalize_workflow_id_for_deploy(workflow_id)
                or _normalize_string(workflow_id, max_length=160)
            )
            if normalized_id is None:
                return
            if normalized_path is None:
                normalized_path = _normalize_workflow_path_for_deploy(f".github/workflows/{normalized_id}")
            candidate_key = normalized_path or normalized_id
            if not candidate_key or candidate_key in seen_candidate_keys:
                return
            seen_candidate_keys.add(candidate_key)
            workflow_candidates.append(
                {
                    "source": source,
                    "workflow_id": normalized_id,
                    "workflow_path": normalized_path,
                }
            )

        if validate_workflow_candidates:
            _append_candidate(
                source=_DEPLOY_WORKFLOW_SOURCE_SITE_SPECIFIC,
                workflow_id=site_specific_workflow_id,
                workflow_path=site_specific_workflow_path,
            )
        _append_candidate(
            source=_DEPLOY_WORKFLOW_SOURCE_PUBLISH_HISTORY,
            workflow_id=history_workflow_id,
            workflow_path=history_workflow_path,
        )
        _append_candidate(
            source=fallback_source,
            workflow_id=fallback_workflow_id,
            workflow_path=fallback_workflow_path,
        )

        selected_candidate = (
            workflow_candidates[0]
            if workflow_candidates
            else {
                "source": fallback_source,
                "workflow_id": fallback_workflow_id,
                "workflow_path": fallback_workflow_path,
            }
        )
        if validate_workflow_candidates and workflow_candidates:
            for candidate in workflow_candidates:
                candidate_valid, candidate_reason_code = self._is_dispatchable_workflow_candidate(
                    repo_owner=candidate_owner,
                    repo_name=candidate_repo,
                    ref=candidate_ref,
                    workflow_id=candidate.get("workflow_id"),
                )
                if candidate_valid:
                    selected_candidate = candidate
                    break
                if candidate_reason_code == _DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND:
                    continue
                if candidate_reason_code in {
                    _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE,
                    _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED,
                    _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY,
                }:
                    # Preserve higher-priority target truth when the workflow exists but is
                    # not dispatchable; do not silently fall through to lower-priority defaults.
                    selected_candidate = candidate
                    break
                # Preserve failure truth for non-workflow-specific preflight issues
                # (for example repo/ref/runtime authorization blockers).
                selected_candidate = candidate
                break

        selected_workflow_id = _normalize_workflow_id_for_deploy(selected_candidate.get("workflow_id"))
        selected_workflow_path = _normalize_workflow_path_for_deploy(selected_candidate.get("workflow_path"))
        if selected_workflow_id:
            resolved_target["workflow_id"] = selected_workflow_id
        resolved_namespace, resolved_namespace_source = _safe_derive_kubernetes_namespace_for_summary(
            repo_name=resolved_target.get("repo_name"),
            site_id=workspace.site_id,
        )
        admin_deploy_metadata = self._resolve_admin_deploy_template_metadata()
        resolution = {
            "source": str(selected_candidate.get("source") or fallback_source),
            "workflow_id": str(resolved_target.get("workflow_id") or "").strip(),
            "workflow_path": selected_workflow_path,
            "history_workflow_id": history_workflow_id,
            "history_workflow_path": history_workflow_path,
            "resolved_ref": candidate_ref,
            "site_specific_workflow_id": site_specific_workflow_id,
            "site_specific_workflow_path": site_specific_workflow_path,
            "deploy_workflow_mode": admin_deploy_metadata.get("deploy_workflow_mode"),
            "target_environment_key": admin_deploy_metadata.get("target_environment_key"),
            "target_environment_source": admin_deploy_metadata.get("target_environment_source"),
            "managed_gke_cluster_name": admin_deploy_metadata.get("managed_gke_cluster_name"),
            "managed_gke_cluster_location": admin_deploy_metadata.get("managed_gke_cluster_location"),
            "managed_gke_project_id": admin_deploy_metadata.get("managed_gke_project_id"),
            "managed_gke_config": _normalize_json_dict(admin_deploy_metadata.get("managed_gke_config")),
            "namespace_isolation_defaults": _normalize_json_dict(
                admin_deploy_metadata.get("namespace_isolation_defaults")
            ),
            "kubernetes_namespace": resolved_namespace,
            "namespace_source": resolved_namespace_source,
            "namespace_model_status": "unknown",
        }
        return resolved_target, resolution

    def _is_dispatchable_workflow_candidate(
        self,
        *,
        repo_owner: str,
        repo_name: str,
        ref: str,
        workflow_id: object,
    ) -> tuple[bool, str | None]:
        normalized_owner = _normalize_string(repo_owner, max_length=80)
        normalized_repo = _normalize_string(repo_name, max_length=120)
        normalized_ref = _normalize_string(ref, max_length=120)
        normalized_workflow_id = _normalize_workflow_id_for_deploy(workflow_id)
        if (
            not normalized_owner
            or not normalized_repo
            or not normalized_ref
            or not normalized_workflow_id
            or not self.github_publisher_configured
        ):
            return False, None
        target = SEOMigrationGitHubDeployTarget(
            repo_owner=normalized_owner,
            repo_name=normalized_repo,
            workflow_id=normalized_workflow_id,
            ref=normalized_ref,
            inputs={},
        )
        admin_deploy_metadata = self._resolve_admin_deploy_template_metadata()
        try:
            readiness = self.github_publisher.check_deploy_target_readiness(
                target=target,
                allow_ref_repair=False,
                allow_workflow_repair=False,
                dry_run=False,
                remediation_mode="none",
                managed_gke_config=_normalize_json_dict(admin_deploy_metadata.get("managed_gke_config")),
                namespace_isolation_defaults=_normalize_json_dict(
                    admin_deploy_metadata.get("namespace_isolation_defaults")
                ),
            )
        except SEOMigrationGitHubPublisherError as exc:
            return False, _normalize_deploy_failure_reason_code(exc.code)

        if not readiness.workflow_exists:
            return False, _DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND
        if not readiness.workflow_dispatch_ready:
            return False, _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE
        if not readiness.workflow_dispatch_supported:
            return False, _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED
        return True, None

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
        deploy_namespace = _normalize_string(
            deploy_target.get("kubernetes_namespace"),
            max_length=63,
        ) or _normalize_string(deploy_readiness.get("kubernetes_namespace"), max_length=63)
        deploy_namespace_source = _normalize_string(
            deploy_target.get("namespace_source"),
            max_length=60,
        ) or _normalize_string(deploy_readiness.get("namespace_source"), max_length=60)
        deploy_namespace_model_status = _normalize_string(
            deploy_target.get("namespace_model_status"),
            max_length=40,
        ) or _normalize_string(deploy_readiness.get("namespace_model_status"), max_length=40)
        deploy_workflow_namespace_aligned = (
            bool(deploy_target.get("workflow_namespace_aligned"))
            if isinstance(deploy_target.get("workflow_namespace_aligned"), bool)
            else (
                bool(deploy_readiness.get("workflow_namespace_aligned"))
                if isinstance(deploy_readiness.get("workflow_namespace_aligned"), bool)
                else None
            )
        )
        deploy_manifest_namespace_aligned = (
            bool(deploy_target.get("manifest_namespace_aligned"))
            if isinstance(deploy_target.get("manifest_namespace_aligned"), bool)
            else (
                bool(deploy_readiness.get("manifest_namespace_aligned"))
                if isinstance(deploy_readiness.get("manifest_namespace_aligned"), bool)
                else None
            )
        )
        managed_resource_quota_expected = (
            bool(deploy_target.get("managed_resource_quota_expected"))
            if isinstance(deploy_target.get("managed_resource_quota_expected"), bool)
            else (
                bool(deploy_readiness.get("managed_resource_quota_expected"))
                if isinstance(deploy_readiness.get("managed_resource_quota_expected"), bool)
                else None
            )
        )
        managed_resource_quota_present = (
            bool(deploy_target.get("managed_resource_quota_present"))
            if isinstance(deploy_target.get("managed_resource_quota_present"), bool)
            else (
                bool(deploy_readiness.get("managed_resource_quota_present"))
                if isinstance(deploy_readiness.get("managed_resource_quota_present"), bool)
                else None
            )
        )
        managed_limit_range_expected = (
            bool(deploy_target.get("managed_limit_range_expected"))
            if isinstance(deploy_target.get("managed_limit_range_expected"), bool)
            else (
                bool(deploy_readiness.get("managed_limit_range_expected"))
                if isinstance(deploy_readiness.get("managed_limit_range_expected"), bool)
                else None
            )
        )
        managed_limit_range_present = (
            bool(deploy_target.get("managed_limit_range_present"))
            if isinstance(deploy_target.get("managed_limit_range_present"), bool)
            else (
                bool(deploy_readiness.get("managed_limit_range_present"))
                if isinstance(deploy_readiness.get("managed_limit_range_present"), bool)
                else None
            )
        )
        managed_network_policy_expected = (
            bool(deploy_target.get("managed_network_policy_expected"))
            if isinstance(deploy_target.get("managed_network_policy_expected"), bool)
            else (
                bool(deploy_readiness.get("managed_network_policy_expected"))
                if isinstance(deploy_readiness.get("managed_network_policy_expected"), bool)
                else None
            )
        )
        managed_network_policy_present = (
            bool(deploy_target.get("managed_network_policy_present"))
            if isinstance(deploy_target.get("managed_network_policy_present"), bool)
            else (
                bool(deploy_readiness.get("managed_network_policy_present"))
                if isinstance(deploy_readiness.get("managed_network_policy_present"), bool)
                else None
            )
        )
        managed_namespace_policies_aligned = (
            bool(deploy_target.get("managed_namespace_policies_aligned"))
            if isinstance(deploy_target.get("managed_namespace_policies_aligned"), bool)
            else (
                bool(deploy_readiness.get("managed_namespace_policies_aligned"))
                if isinstance(deploy_readiness.get("managed_namespace_policies_aligned"), bool)
                else None
            )
        )
        publish_owner = _normalize_string(publish_target.get("repo_owner"), max_length=80)
        publish_repo = _normalize_string(publish_target.get("repo_name"), max_length=120)
        publish_branch = _normalize_string(publish_target.get("branch"), max_length=120) or "main"
        publish_root = (_normalize_string(publish_target.get("artifact_root"), max_length=120) or "").strip("/")
        publish_repository = f"{publish_owner}/{publish_repo}" if publish_owner and publish_repo else None
        publish_tree_url = self._derive_publish_tree_url(
            repo_owner=publish_owner,
            repo_name=publish_repo,
            branch=publish_branch,
            artifact_root=publish_root,
        )
        publish_root_display = f"/{publish_root}" if publish_root else "/"
        expected_publish_location = (
            f"{publish_repository}@{publish_branch}:{publish_root_display}" if publish_repository else None
        )

        expected_publish_url, expected_publish_url_source, expected_publish_url_source_detail = (
            self._resolve_expected_publish_url_for_deploy(
                workspace=workspace,
                artifact_version_id=workspace.last_published_artifact_version_id,
                deploy_target=deploy_target,
            )
        )
        resolved_live_url, resolved_live_url_source, resolved_live_url_source_detail = (
            self._resolve_latest_deploy_live_url(
                workspace=workspace,
                artifact_version_id=workspace.last_deployed_artifact_version_id,
                repo_owner=_normalize_string(deploy_target.get("repo_owner"), max_length=80) or "",
                repo_name=_normalize_string(deploy_target.get("repo_name"), max_length=120) or "",
                ref=_normalize_string(deploy_target.get("ref"), max_length=120) or "",
            )
        )
        confirmed_live_url = (
            resolved_live_url
            if resolved_live_url_source in {_MIGRATION_URL_SOURCE_DEPLOY_RESULT, _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT}
            else None
        )
        deployed_live = bool(workspace.last_deployed_at)
        deploy_state = "unknown"
        if confirmed_live_url and deployed_live:
            deploy_state = "active_live"
        elif expected_publish_url:
            deploy_state = "expected_after_deploy"
        elif resolved_live_url:
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
                "expected_publish_url": expected_publish_url,
                "url_source": expected_publish_url_source,
                "url_source_detail": expected_publish_url_source_detail,
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
                "expected_publish_url": expected_publish_url,
                "resolved_live_url": resolved_live_url,
                "expected_url": expected_publish_url,
                "active_url": confirmed_live_url if deployed_live else None,
                "url_source": (
                    resolved_live_url_source
                    if resolved_live_url_source != _MIGRATION_URL_SOURCE_UNKNOWN
                    else expected_publish_url_source
                ),
                "url_source_detail": (
                    resolved_live_url_source_detail
                    if resolved_live_url_source_detail is not None
                    else expected_publish_url_source_detail
                ),
                "is_deployed": deployed_live,
                "last_deployed_at": (
                    workspace.last_deployed_at.isoformat() if hasattr(workspace.last_deployed_at, "isoformat") else None
                ),
                "target_repository": (
                    f"{_normalize_string(deploy_target.get('repo_owner'), max_length=80) or ''}/"
                    f"{_normalize_string(deploy_target.get('repo_name'), max_length=120) or ''}"
                ).strip("/")
                or None,
                "workflow_id": _normalize_string(deploy_target.get("workflow_id"), max_length=160),
                "resolved_workflow_path": _normalize_workflow_path_for_deploy(
                    deploy_target.get("resolved_workflow_path")
                ),
                "deploy_workflow_mode": _normalize_string(deploy_target.get("deploy_workflow_mode"), max_length=60),
                "target_environment_key": _normalize_string(
                    deploy_target.get("target_environment_key"),
                    max_length=80,
                ),
                "target_environment_source": _normalize_string(
                    deploy_target.get("target_environment_source"),
                    max_length=60,
                ),
                "site_workflow_file_path": _normalize_workflow_path_for_deploy(
                    deploy_target.get("site_workflow_file_path")
                ),
                "kubernetes_namespace": deploy_namespace,
                "namespace_source": deploy_namespace_source,
                "namespace_model_status": deploy_namespace_model_status,
                "workflow_namespace_aligned": deploy_workflow_namespace_aligned,
                "manifest_namespace_aligned": deploy_manifest_namespace_aligned,
                "managed_resource_quota_expected": managed_resource_quota_expected,
                "managed_resource_quota_present": managed_resource_quota_present,
                "managed_limit_range_expected": managed_limit_range_expected,
                "managed_limit_range_present": managed_limit_range_present,
                "managed_network_policy_expected": managed_network_policy_expected,
                "managed_network_policy_present": managed_network_policy_present,
                "managed_namespace_policies_aligned": managed_namespace_policies_aligned,
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

    def _resolve_expected_publish_url(
        self,
        *,
        deploy_target: dict[str, object] | None,
        deploy_config: object | None,
    ) -> tuple[str | None, str, str | None]:
        target_inputs = {}
        if isinstance(deploy_target, dict):
            target_inputs = _normalize_history_inputs(deploy_target.get("inputs"))
        if not target_inputs:
            target_inputs = _normalize_history_inputs(_normalize_json_dict(deploy_config).get("inputs"))
        candidate_url, source_detail = self._resolve_url_candidate_from_inputs(target_inputs)
        if candidate_url:
            return (
                candidate_url,
                _MIGRATION_URL_SOURCE_DETERMINISTIC_TARGET_CONFIG,
                source_detail,
            )
        return None, _MIGRATION_URL_SOURCE_UNKNOWN, None

    def _resolve_expected_publish_url_for_deploy(
        self,
        *,
        workspace: SEOMigrationWorkspace,
        artifact_version_id: str | None,
        deploy_target: dict[str, object],
    ) -> tuple[str | None, str, str | None]:
        target_owner = _normalize_string(deploy_target.get("repo_owner"), max_length=80) or ""
        target_repo = _normalize_string(deploy_target.get("repo_name"), max_length=120) or ""
        target_ref = _normalize_string(deploy_target.get("ref"), max_length=120) or ""
        history_url, history_url_source, history_url_source_detail = _resolve_publish_history_expected_publish_url(
            history=workspace.publish_history_json,
            artifact_version_id=artifact_version_id,
            repo_owner=target_owner,
            repo_name=target_repo,
            ref=target_ref,
        )
        if history_url:
            return history_url, history_url_source, history_url_source_detail
        return self._resolve_expected_publish_url(
            deploy_target=deploy_target,
            deploy_config=workspace.deploy_config_json,
        )

    def _resolve_deploy_live_url(
        self,
        *,
        deploy_result: object,
        expected_publish_url: str | None,
        expected_publish_url_source: str,
        expected_publish_url_source_detail: str | None,
    ) -> tuple[str | None, str, str | None]:
        workflow_output_payload = _normalize_history_inputs(getattr(deploy_result, "workflow_output", {}))
        if not workflow_output_payload:
            workflow_output_payload = _normalize_history_inputs(getattr(deploy_result, "workflow_outputs", {}))
        if not workflow_output_payload:
            workflow_output_payload = _normalize_history_inputs(getattr(deploy_result, "outputs", {}))
        metadata_live_url, metadata_source_detail = self._resolve_url_candidate_from_inputs(
            workflow_output_payload,
            preferred_keys=_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS,
        )
        if metadata_live_url:
            detail = metadata_source_detail or "workflow_output:live_url"
            if detail.startswith("deploy_input:"):
                detail = detail.replace("deploy_input:", "workflow_output:", 1)
            return metadata_live_url, _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT, detail

        explicit_live_url = _normalize_url_candidate(getattr(deploy_result, "live_url", None))
        if explicit_live_url:
            return explicit_live_url, _MIGRATION_URL_SOURCE_DEPLOY_RESULT, "deploy_result:live_url"

        return None, _MIGRATION_URL_SOURCE_UNKNOWN, None

    def _resolve_latest_deploy_live_url(
        self,
        *,
        workspace: SEOMigrationWorkspace,
        artifact_version_id: str | None,
        repo_owner: str,
        repo_name: str,
        ref: str,
    ) -> tuple[str | None, str, str | None]:
        return _resolve_deploy_history_live_url(
            history=workspace.deploy_history_json,
            artifact_version_id=artifact_version_id,
            repo_owner=repo_owner,
            repo_name=repo_name,
            ref=ref,
        )

    @staticmethod
    def _resolve_url_candidate_from_inputs(
        inputs: dict[str, str],
        *,
        preferred_keys: tuple[str, ...] = ("deploy_url", "public_url", "site_url", "url"),
    ) -> tuple[str | None, str | None]:
        for key in preferred_keys:
            candidate = _normalize_url_candidate(inputs.get(key))
            if candidate:
                return candidate, f"deploy_input:{key}"
        for key in ("host", "domain"):
            candidate = _normalize_host_candidate(inputs.get(key))
            if candidate:
                return candidate, f"deploy_input:{key}"
        return None, None

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
        normalized_blockers = [
            str(item or "").strip().lower() for item in blocker_codes or [] if str(item or "").strip()
        ]
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
            _DEPLOY_TARGET_REASON_TOKEN_UNAUTHORIZED,
        }:
            return "config_missing"
        if code in {
            "github_target_not_found",
            "github_workflow_invalid",
            "workflow_provisioning_failed",
            "workflow_provision_failed",
            _DEPLOY_TARGET_REASON_REPO_NOT_FOUND,
            _DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND,
            _DEPLOY_TARGET_REASON_REF_INVALID,
            _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED,
            _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE,
            _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY,
        }:
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
        last_failure_reason: str | None = None
        last_failure_stage: str | None = None
        last_failure_remediation_hint: str | None = None
        last_workflow_remediation_attempted: bool | None = None
        last_workflow_remediation_outcome: str | None = None
        last_deploy_secret_propagation_attempted: bool | None = None
        last_deploy_secret_propagation_status: str | None = None
        last_deploy_secret_propagation_reason: str | None = None
        last_deploy_secret_propagation_source: str | None = None
        for item in reversed(normalized_history):
            if str(item.get("action") or "").strip().lower() != target_action:
                continue
            if last_status is None:
                status_value = _normalize_string(item.get("status"), max_length=40)
                if status_value:
                    last_status = status_value
                remediation_attempted_value = item.get("workflow_remediation_attempted")
                if isinstance(remediation_attempted_value, bool):
                    last_workflow_remediation_attempted = remediation_attempted_value
                last_workflow_remediation_outcome = _normalize_string(
                    item.get("workflow_remediation_outcome"),
                    max_length=80,
                )
                deploy_secret_attempted_value = item.get("deploy_secret_propagation_attempted")
                if isinstance(deploy_secret_attempted_value, bool):
                    last_deploy_secret_propagation_attempted = deploy_secret_attempted_value
                last_deploy_secret_propagation_status = _normalize_string(
                    item.get("deploy_secret_propagation_status"),
                    max_length=80,
                )
                last_deploy_secret_propagation_reason = _normalize_string(
                    item.get("deploy_secret_propagation_reason"),
                    max_length=120,
                )
                last_deploy_secret_propagation_source = _normalize_string(
                    item.get("deploy_secret_propagation_source"),
                    max_length=120,
                )
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
                last_failure_reason = _normalize_deploy_failure_reason_code(item.get("failure_reason"))
                last_failure_stage = _normalize_deploy_failure_stage(item.get("failure_stage"))
                last_failure_remediation_hint = _normalize_string(
                    item.get("failure_remediation_hint"),
                    max_length=240,
                )
                if last_failure_remediation_hint is None:
                    last_failure_remediation_hint = _derive_deploy_failure_remediation_hint(
                        failure_reason=last_failure_reason,
                        failure_stage=last_failure_stage,
                        workflow_exists=item.get("workflow_exists"),
                        dispatch_service_reason_code=item.get("dispatch_service_reason_code"),
                    )
                break
        return {
            "last_status": last_status,
            "last_failure_category": last_failure_category,
            "last_failure_message": last_failure_message,
            "last_failure_reason": last_failure_reason,
            "last_failure_stage": last_failure_stage,
            "last_failure_remediation_hint": last_failure_remediation_hint,
            "last_workflow_remediation_attempted": last_workflow_remediation_attempted,
            "last_workflow_remediation_outcome": last_workflow_remediation_outcome,
            "last_deploy_secret_propagation_attempted": last_deploy_secret_propagation_attempted,
            "last_deploy_secret_propagation_status": last_deploy_secret_propagation_status,
            "last_deploy_secret_propagation_reason": last_deploy_secret_propagation_reason,
            "last_deploy_secret_propagation_source": last_deploy_secret_propagation_source,
        }

    @staticmethod
    def _derive_latest_deploy_failure_detail(*, history: object) -> dict[str, object]:
        normalized_history = _normalize_history_list(history)
        for item in reversed(normalized_history):
            if str(item.get("action") or "").strip().lower() != "deploy":
                continue
            if str(item.get("status") or "").strip().lower() != "failed":
                continue
            workflow_file_path = _normalize_workflow_path_for_deploy(
                item.get("workflow_file_path")
            ) or _normalize_workflow_path_for_deploy(item.get("workflow_path"))
            workflow_identifier_requested = _normalize_string(
                item.get("workflow_identifier_requested"),
                max_length=200,
            ) or _normalize_string(item.get("workflow_id"), max_length=160)
            workflow_identifier_used = _normalize_string(
                item.get("workflow_identifier_used"),
                max_length=200,
            ) or _normalize_string(item.get("workflow_id"), max_length=160)
            workflow_conformance_reasons = _normalize_string_list(
                item.get("workflow_conformance_reasons"),
                max_items=10,
                max_item_length=120,
            )
            failure_reason = _normalize_deploy_failure_reason_code(item.get("failure_reason"))
            failure_stage = _normalize_deploy_failure_stage(item.get("failure_stage"))
            failure_remediation_hint = _normalize_string(
                item.get("failure_remediation_hint"),
                max_length=240,
            ) or _derive_deploy_failure_remediation_hint(
                failure_reason=failure_reason,
                failure_stage=failure_stage,
                workflow_exists=item.get("workflow_exists"),
                dispatch_service_reason_code=item.get("dispatch_service_reason_code"),
            )
            return {
                "failure_category": _normalize_string(item.get("failure_category"), max_length=40),
                "failure_reason": failure_reason,
                "failure_stage": failure_stage,
                "failure_message": _normalize_string(
                    item.get("error_summary"),
                    max_length=300,
                )
                or _normalize_string(item.get("error"), max_length=300),
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_file_path": workflow_file_path,
                "workflow_dispatch_resolution_source": _normalize_string(
                    item.get("workflow_dispatch_resolution_source"),
                    max_length=80,
                ),
                "workflow_exists": (
                    bool(item.get("workflow_exists")) if isinstance(item.get("workflow_exists"), bool) else None
                ),
                "dispatch_service_reason_code": _normalize_dispatch_service_reason_code(
                    item.get("dispatch_service_reason_code")
                ),
                "workflow_conformance_status": _normalize_string(
                    item.get("workflow_conformance_status"),
                    max_length=80,
                ),
                "workflow_conformance_reasons": workflow_conformance_reasons,
                "resolved_workflow_source": _normalize_string(
                    item.get("resolved_workflow_source"),
                    max_length=40,
                ),
                "target_environment_key": _normalize_string(
                    item.get("target_environment_key"),
                    max_length=80,
                ),
                "target_environment_source": _normalize_string(
                    item.get("target_environment_source"),
                    max_length=80,
                ),
                "kubernetes_namespace": _normalize_string(item.get("kubernetes_namespace"), max_length=63),
                "namespace_source": _normalize_string(item.get("namespace_source"), max_length=60),
                "namespace_model_status": _normalize_string(item.get("namespace_model_status"), max_length=40),
                "workflow_namespace_aligned": (
                    bool(item.get("workflow_namespace_aligned"))
                    if isinstance(item.get("workflow_namespace_aligned"), bool)
                    else None
                ),
                "manifest_namespace_aligned": (
                    bool(item.get("manifest_namespace_aligned"))
                    if isinstance(item.get("manifest_namespace_aligned"), bool)
                    else None
                ),
                "managed_resource_quota_expected": (
                    bool(item.get("managed_resource_quota_expected"))
                    if isinstance(item.get("managed_resource_quota_expected"), bool)
                    else None
                ),
                "managed_resource_quota_present": (
                    bool(item.get("managed_resource_quota_present"))
                    if isinstance(item.get("managed_resource_quota_present"), bool)
                    else None
                ),
                "managed_limit_range_expected": (
                    bool(item.get("managed_limit_range_expected"))
                    if isinstance(item.get("managed_limit_range_expected"), bool)
                    else None
                ),
                "managed_limit_range_present": (
                    bool(item.get("managed_limit_range_present"))
                    if isinstance(item.get("managed_limit_range_present"), bool)
                    else None
                ),
                "managed_network_policy_expected": (
                    bool(item.get("managed_network_policy_expected"))
                    if isinstance(item.get("managed_network_policy_expected"), bool)
                    else None
                ),
                "managed_network_policy_present": (
                    bool(item.get("managed_network_policy_present"))
                    if isinstance(item.get("managed_network_policy_present"), bool)
                    else None
                ),
                "managed_namespace_policies_aligned": (
                    bool(item.get("managed_namespace_policies_aligned"))
                    if isinstance(item.get("managed_namespace_policies_aligned"), bool)
                    else None
                ),
                "failure_remediation_hint": failure_remediation_hint,
            }
        return {}

    @staticmethod
    def _derive_latest_deploy_traceability(
        *,
        history: object,
        artifact_version_id: str | None,
    ) -> dict[str, object]:
        normalized_history = _normalize_history_list(history)
        artifact_id = str(artifact_version_id or "").strip()
        for item in reversed(normalized_history):
            if str(item.get("action") or "").strip().lower() != "deploy":
                continue
            item_artifact_id = str(item.get("artifact_version_id") or "").strip()
            if artifact_id and item_artifact_id and item_artifact_id != artifact_id:
                continue
            workflow_dispatch_supported = item.get("workflow_dispatch_supported")
            dispatch_service_availability = item.get("dispatch_service_availability")
            workflow_conformance_checked = item.get("workflow_conformance_checked")
            workflow_conformance_reasons = item.get("workflow_conformance_reasons")
            dispatch_attempted = item.get("dispatch_attempted")
            workflow_run_lookup_attempted = item.get("workflow_run_lookup_attempted")
            workflow_run_found = item.get("workflow_run_found")
            workflow_job_failure_detected = item.get("workflow_job_failure_detected")
            workflow_file_path = _normalize_workflow_path_for_deploy(
                item.get("workflow_file_path")
            ) or _normalize_workflow_path_for_deploy(item.get("workflow_path"))
            workflow_name = _normalize_string(
                item.get("workflow_name"), max_length=160
            ) or _workflow_id_from_path_for_deploy(workflow_file_path)
            workflow_identifier_requested = _normalize_string(item.get("workflow_identifier_requested"), max_length=200)
            workflow_identifier_used = _normalize_string(item.get("workflow_identifier_used"), max_length=200)
            if workflow_identifier_requested is None:
                workflow_identifier_requested = _normalize_string(item.get("workflow_id"), max_length=160)
            if workflow_identifier_used is None:
                workflow_identifier_used = _normalize_string(item.get("workflow_id"), max_length=160)
            workflow_run_id = _coerce_int(item.get("workflow_run_id"))
            workflow_run_status = _normalize_string(item.get("workflow_run_status"), max_length=40)
            workflow_run_conclusion = _normalize_string(item.get("workflow_run_conclusion"), max_length=40)
            workflow_run_failure_reason_code = _normalize_workflow_run_failure_reason_code(
                item.get("workflow_run_failure_reason_code")
            )
            workflow_run_failure_stage = _normalize_workflow_run_failure_stage(
                item.get("workflow_run_failure_stage")
            )
            workflow_run_failure_step = _normalize_string(item.get("workflow_run_failure_step"), max_length=200)
            workflow_run_failure_hint = _normalize_string(item.get("workflow_run_failure_hint"), max_length=240)
            resolved_live_url = _normalize_url_candidate(item.get("resolved_live_url"))
            post_dispatch_state = _normalize_string(
                item.get("post_dispatch_state"), max_length=80
            ) or _derive_post_dispatch_state(
                dispatch_attempted=dispatch_attempted,
                dispatch_result_stage=item.get("dispatch_result_stage"),
                workflow_run_id=workflow_run_id,
                workflow_run_status=workflow_run_status,
                workflow_run_conclusion=workflow_run_conclusion,
                resolved_live_url=resolved_live_url,
                workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                workflow_run_found=workflow_run_found,
            )
            deploy_evidence_contract_status = _normalize_deploy_evidence_contract_status(
                item.get("deploy_evidence_contract_status")
            )
            deploy_evidence_contract_reasons = _normalize_string_list(
                item.get("deploy_evidence_contract_reasons"),
                max_items=8,
                max_item_length=120,
            )
            workflow_contract_advisory = _normalize_string(
                item.get("workflow_contract_advisory"),
                max_length=240,
            )
            if deploy_evidence_contract_status is None:
                (
                    deploy_evidence_contract_status,
                    derived_reasons,
                    derived_advisory,
                ) = _derive_deploy_evidence_contract(
                    workflow_conformance_status=item.get("workflow_conformance_status"),
                    post_dispatch_state=post_dispatch_state,
                    resolved_live_url=resolved_live_url,
                    url_source=item.get("url_source"),
                )
                if not deploy_evidence_contract_reasons:
                    deploy_evidence_contract_reasons = derived_reasons
                if workflow_contract_advisory is None:
                    workflow_contract_advisory = derived_advisory
            post_conformance_stage = _normalize_post_conformance_stage(
                item.get("post_conformance_stage")
            ) or _derive_post_conformance_stage(
                workflow_conformance_status=item.get("workflow_conformance_status"),
                dispatch_attempted=dispatch_attempted,
                dispatch_result_stage=item.get("dispatch_result_stage"),
                failure_stage=item.get("failure_stage"),
                post_dispatch_state=post_dispatch_state,
                workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                workflow_run_failure_stage=workflow_run_failure_stage,
                deploy_evidence_contract_status=deploy_evidence_contract_status,
            )
            post_conformance_reason_text = _normalize_string(
                item.get("post_conformance_reason_text"),
                max_length=240,
            ) or _derive_post_conformance_reason_text(
                post_conformance_stage=post_conformance_stage,
                workflow_run_failure_reason_code=workflow_run_failure_reason_code,
                workflow_run_failure_stage=workflow_run_failure_stage,
                post_dispatch_state=post_dispatch_state,
            )
            post_conformance_remediation_message = _normalize_string(
                item.get("post_conformance_remediation_message"),
                max_length=280,
            ) or _derive_post_conformance_remediation_message(
                post_conformance_stage=post_conformance_stage
            )
            return {
                "deploy_trace_id": _normalize_string(item.get("deploy_trace_id"), max_length=80),
                "workflow_identifier": _derive_workflow_identifier(
                    workflow_id=item.get("workflow_id"),
                    workflow_path=item.get("workflow_path"),
                ),
                "workflow_identifier_requested": workflow_identifier_requested,
                "workflow_identifier_used": workflow_identifier_used,
                "workflow_identifier_type_requested": _normalize_string(
                    item.get("workflow_identifier_type_requested"),
                    max_length=80,
                )
                or _infer_dispatch_identifier_type(workflow_identifier_requested),
                "workflow_identifier_type_used": _normalize_string(
                    item.get("workflow_identifier_type_used"),
                    max_length=80,
                )
                or _normalize_string(item.get("dispatch_identifier_type"), max_length=80)
                or _infer_dispatch_identifier_type(workflow_identifier_used),
                "workflow_dispatch_resolution_source": _normalize_string(
                    item.get("workflow_dispatch_resolution_source"),
                    max_length=80,
                ),
                "workflow_file_path": workflow_file_path,
                "workflow_name": workflow_name,
                "workflow_dispatch_supported": (
                    bool(workflow_dispatch_supported) if isinstance(workflow_dispatch_supported, bool) else None
                ),
                "workflow_trigger_types": _normalize_workflow_trigger_types_for_summary(
                    item.get("workflow_trigger_types")
                ),
                "dispatch_service_availability": (
                    bool(dispatch_service_availability) if isinstance(dispatch_service_availability, bool) else None
                ),
                "dispatch_service_reason_code": _normalize_dispatch_service_reason_code(
                    item.get("dispatch_service_reason_code")
                ),
                "workflow_conformance_checked": (
                    bool(workflow_conformance_checked) if isinstance(workflow_conformance_checked, bool) else None
                ),
                "workflow_conformance_status": _normalize_string(
                    item.get("workflow_conformance_status"),
                    max_length=80,
                ),
                "workflow_conformance_reasons": _normalize_string_list(
                    workflow_conformance_reasons,
                    max_items=10,
                    max_item_length=120,
                ),
                "workflow_conformance_evidence_summary": _normalize_string(
                    item.get("workflow_conformance_evidence_summary"),
                    max_length=240,
                ),
                "dispatch_identifier_type": _normalize_string(item.get("dispatch_identifier_type"), max_length=80),
                "dispatch_attempted": bool(dispatch_attempted) if isinstance(dispatch_attempted, bool) else None,
                "dispatch_result_stage": _normalize_string(item.get("dispatch_result_stage"), max_length=40),
                "dispatch_ref_sent": _normalize_string(item.get("dispatch_ref_sent"), max_length=120)
                or _normalize_string(item.get("ref"), max_length=120),
                "workflow_inputs_configured_keys": _normalize_dispatch_input_keys(
                    item.get("workflow_inputs_configured_keys")
                )
                or _normalize_dispatch_input_keys(item.get("inputs")),
                "workflow_inputs_sent_keys": _normalize_dispatch_input_keys(item.get("workflow_inputs_sent_keys"))
                or _normalize_dispatch_input_keys(item.get("inputs")),
                "workflow_run_lookup_attempted": (
                    bool(workflow_run_lookup_attempted) if isinstance(workflow_run_lookup_attempted, bool) else None
                ),
                "workflow_run_found": (bool(workflow_run_found) if isinstance(workflow_run_found, bool) else None),
                "dispatch_verification_state": _normalize_string(
                    item.get("dispatch_verification_state"),
                    max_length=80,
                )
                or _derive_dispatch_verification_state(
                    dispatch_attempted=dispatch_attempted,
                    workflow_run_id=workflow_run_id,
                    workflow_run_lookup_attempted=workflow_run_lookup_attempted,
                    workflow_run_found=workflow_run_found,
                ),
                "workflow_job_failure_detected": (
                    bool(workflow_job_failure_detected)
                    if isinstance(workflow_job_failure_detected, bool)
                    else _derive_workflow_job_failure_detected(
                        workflow_run_status=workflow_run_status,
                        workflow_run_conclusion=workflow_run_conclusion,
                    )
                ),
                "post_dispatch_state": post_dispatch_state,
                "post_conformance_stage": post_conformance_stage,
                "post_conformance_reason_text": post_conformance_reason_text,
                "post_conformance_remediation_message": post_conformance_remediation_message,
                "expected_workflow_outputs": _normalize_string_list(
                    item.get("expected_workflow_outputs"),
                    max_items=8,
                    max_item_length=80,
                )
                or list(_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS),
                "deploy_evidence_contract_status": (
                    deploy_evidence_contract_status or _DEPLOY_EVIDENCE_CONTRACT_STATUS_UNKNOWN
                ),
                "deploy_evidence_contract_reasons": deploy_evidence_contract_reasons,
                "workflow_contract_advisory": workflow_contract_advisory,
                "repo_exists": (bool(item.get("repo_exists")) if isinstance(item.get("repo_exists"), bool) else None),
                "ref_exists": (bool(item.get("ref_exists")) if isinstance(item.get("ref_exists"), bool) else None),
                "workflow_exists": (
                    bool(item.get("workflow_exists")) if isinstance(item.get("workflow_exists"), bool) else None
                ),
                "workflow_dispatch_ready": (
                    bool(item.get("workflow_dispatch_ready"))
                    if isinstance(item.get("workflow_dispatch_ready"), bool)
                    else None
                ),
                "workflow_run_id": workflow_run_id,
                "workflow_run_status": workflow_run_status,
                "workflow_run_conclusion": workflow_run_conclusion,
                "workflow_run_failure_reason_code": workflow_run_failure_reason_code,
                "workflow_run_failure_stage": workflow_run_failure_stage,
                "workflow_run_failure_step": workflow_run_failure_step,
                "workflow_run_failure_hint": workflow_run_failure_hint,
                "kubernetes_namespace": _normalize_string(item.get("kubernetes_namespace"), max_length=63),
                "namespace_source": _normalize_string(item.get("namespace_source"), max_length=60),
                "namespace_model_status": _normalize_string(item.get("namespace_model_status"), max_length=40),
                "workflow_namespace_aligned": (
                    bool(item.get("workflow_namespace_aligned"))
                    if isinstance(item.get("workflow_namespace_aligned"), bool)
                    else None
                ),
                "manifest_namespace_aligned": (
                    bool(item.get("manifest_namespace_aligned"))
                    if isinstance(item.get("manifest_namespace_aligned"), bool)
                    else None
                ),
                "managed_resource_quota_expected": (
                    bool(item.get("managed_resource_quota_expected"))
                    if isinstance(item.get("managed_resource_quota_expected"), bool)
                    else None
                ),
                "managed_resource_quota_present": (
                    bool(item.get("managed_resource_quota_present"))
                    if isinstance(item.get("managed_resource_quota_present"), bool)
                    else None
                ),
                "managed_limit_range_expected": (
                    bool(item.get("managed_limit_range_expected"))
                    if isinstance(item.get("managed_limit_range_expected"), bool)
                    else None
                ),
                "managed_limit_range_present": (
                    bool(item.get("managed_limit_range_present"))
                    if isinstance(item.get("managed_limit_range_present"), bool)
                    else None
                ),
                "managed_network_policy_expected": (
                    bool(item.get("managed_network_policy_expected"))
                    if isinstance(item.get("managed_network_policy_expected"), bool)
                    else None
                ),
                "managed_network_policy_present": (
                    bool(item.get("managed_network_policy_present"))
                    if isinstance(item.get("managed_network_policy_present"), bool)
                    else None
                ),
                "managed_namespace_policies_aligned": (
                    bool(item.get("managed_namespace_policies_aligned"))
                    if isinstance(item.get("managed_namespace_policies_aligned"), bool)
                    else None
                ),
            }
        return {}

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
            reasons.append(
                str(runtime_diagnostics.get("status_message") or "GitHub migration publisher is not configured.")
            )
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
        workflow_identifier: str | None = None
        dispatch_identifier_type = "workflow_id"
        target_readiness: SEOMigrationGitHubTargetReadinessResult | None = None
        managed_deploy_secret_available: bool | None = None
        managed_deploy_secret_source: str | None = None
        managed_deploy_secret_reason: str | None = None
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
                target, workflow_resolution = self._resolve_deploy_target_with_workflow_precedence(
                    workspace=workspace,
                    effective_publish_config=effective_publish_config,
                    artifact_version_id=(
                        artifact.id if artifact is not None else workspace.last_published_artifact_version_id
                    ),
                    validate_workflow_candidates=False,
                )
                target_valid = True
                target_summary = {
                    "enabled": target["enabled"],
                    "repo_owner": target["repo_owner"],
                    "repo_name": target["repo_name"],
                    "workflow_id": target["workflow_id"],
                    "ref": target["ref"],
                    "inputs": target["inputs"],
                    "resolved_workflow_source": workflow_resolution.get("source"),
                    "deploy_workflow_mode": workflow_resolution.get("deploy_workflow_mode"),
                    "target_environment_key": workflow_resolution.get("target_environment_key"),
                    "target_environment_source": workflow_resolution.get("target_environment_source"),
                    "site_workflow_file_path": workflow_resolution.get("site_specific_workflow_path"),
                    "kubernetes_namespace": workflow_resolution.get("kubernetes_namespace"),
                    "namespace_source": workflow_resolution.get("namespace_source"),
                    "namespace_model_status": workflow_resolution.get("namespace_model_status"),
                }
                if workflow_resolution.get("workflow_path"):
                    target_summary["resolved_workflow_path"] = workflow_resolution.get("workflow_path")
                dispatch_identifier_diagnostics = _resolve_workflow_dispatch_identifier(
                    workflow_id=target.get("workflow_id"),
                    workflow_path=workflow_resolution.get("workflow_path"),
                )
                workflow_identifier = _derive_workflow_identifier(
                    workflow_id=dispatch_identifier_diagnostics.get("workflow_identifier_used")
                    or target.get("workflow_id"),
                    workflow_path=workflow_resolution.get("workflow_path"),
                )
                dispatch_identifier_type = _normalize_string(
                    dispatch_identifier_diagnostics.get("workflow_identifier_type_used"),
                    max_length=80,
                ) or _infer_dispatch_identifier_type(target.get("workflow_id"))
                target_summary["workflow_identifier_requested"] = dispatch_identifier_diagnostics.get(
                    "workflow_identifier_requested"
                )
                target_summary["workflow_identifier_used"] = dispatch_identifier_diagnostics.get(
                    "workflow_identifier_used"
                )
                target_summary["workflow_identifier_type_requested"] = dispatch_identifier_diagnostics.get(
                    "workflow_identifier_type_requested"
                )
                target_summary["workflow_identifier_type_used"] = dispatch_identifier_diagnostics.get(
                    "workflow_identifier_type_used"
                )
                target_summary["workflow_dispatch_resolution_source"] = dispatch_identifier_diagnostics.get(
                    "workflow_dispatch_resolution_source"
                )
                target_summary["workflow_file_path"] = dispatch_identifier_diagnostics.get("workflow_file_path")
                target_summary["workflow_name"] = dispatch_identifier_diagnostics.get("workflow_name")
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
            reasons.append(
                str(runtime_diagnostics.get("status_message") or "GitHub migration publisher is not configured.")
            )
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
        (
            deploy_secret_for_propagation,
            managed_deploy_secret_source,
            managed_deploy_secret_reason,
        ) = self._resolve_deploy_secret_for_propagation()
        managed_deploy_secret_available = bool(deploy_secret_for_propagation)
        target_summary["managed_deploy_secret_available"] = managed_deploy_secret_available
        target_summary["managed_deploy_secret_source"] = managed_deploy_secret_source
        if managed_deploy_secret_reason:
            target_summary["managed_deploy_secret_reason"] = managed_deploy_secret_reason
        if (
            target_valid
            and _normalize_string(target_summary.get("deploy_workflow_mode"), max_length=60)
            == _DEPLOY_WORKFLOW_MODE_SITE_REPO_TEMPLATE_V1
            and not managed_deploy_secret_available
        ):
            reasons.append(
                _derive_managed_deploy_secret_readiness_message(
                    reason_code=managed_deploy_secret_reason,
                )
            )
            blocker_codes.append(_DEPLOY_BLOCKER_CONFIGURATION_MISSING)
        if not workspace.last_published_artifact_version_id:
            reasons.append("A published artifact is required before deploy.")
            blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
        elif artifact is not None and workspace.last_published_artifact_version_id != artifact.id:
            reasons.append("The selected artifact is not the latest published artifact.")
            blocker_codes.append(_DEPLOY_BLOCKER_PUBLISHED_ARTIFACT_MISSING)
        blocker_codes = _dedupe_strings(blocker_codes)
        dispatch_service_availability = (
            bool(runtime_diagnostics.get("configured")) and target_valid and bool(target_summary.get("enabled"))
        )
        dispatch_service_reason_code = _derive_dispatch_service_reason_code(
            runtime_reason_code=str(runtime_diagnostics.get("reason_code") or ""),
            target_valid=target_valid,
            target_enabled=bool(target_summary.get("enabled")),
            dispatch_service_availability=dispatch_service_availability,
        )
        if dispatch_service_availability:
            namespace_isolation_defaults = normalize_namespace_isolation_defaults(
                _normalize_json_dict(workflow_resolution.get("namespace_isolation_defaults"))
            )
            workflow_identifier_for_readiness = _normalize_string(
                target_summary.get("workflow_identifier_used"),
                max_length=160,
            ) or _normalize_string(target_summary.get("workflow_id"), max_length=160)
            if workflow_identifier_for_readiness:
                deploy_target_for_readiness = SEOMigrationGitHubDeployTarget(
                    repo_owner=str(target_summary.get("repo_owner") or "").strip(),
                    repo_name=str(target_summary.get("repo_name") or "").strip(),
                    workflow_id=workflow_identifier_for_readiness,
                    ref=str(target_summary.get("ref") or "").strip(),
                    inputs={},
                )
                try:
                    target_readiness = self.github_publisher.check_deploy_target_readiness(
                        target=deploy_target_for_readiness,
                        allow_ref_repair=False,
                        allow_workflow_repair=False,
                        dry_run=False,
                        remediation_mode="none",
                        managed_gke_config=_normalize_json_dict(workflow_resolution.get("managed_gke_config")),
                        namespace_isolation_defaults=namespace_isolation_defaults,
                    )
                except SEOMigrationGitHubPublisherError as exc:
                    dispatch_service_availability = False
                    dispatch_service_reason_code = _derive_dispatch_service_reason_code(
                        runtime_reason_code=str(runtime_diagnostics.get("reason_code") or ""),
                        target_valid=target_valid,
                        target_enabled=bool(target_summary.get("enabled")),
                        dispatch_service_availability=False,
                        failure_reason_code=_normalize_deploy_failure_reason_code(exc.code),
                        failure_stage=_normalize_deploy_failure_stage(exc.stage),
                    )
                    self._emit_structured_service_log(
                        payload={
                            "event": "seo_migration_deploy_readiness_target_check_failed",
                            "business_id": workspace.business_id,
                            "site_id": workspace.site_id,
                            "workspace_id": workspace.id,
                            "repo_owner": deploy_target_for_readiness.repo_owner,
                            "repo_name": deploy_target_for_readiness.repo_name,
                            "requested_ref": deploy_target_for_readiness.ref,
                            "workflow_id": deploy_target_for_readiness.workflow_id,
                            "failure_reason_code": _normalize_deploy_failure_reason_code(exc.code),
                            "failure_stage": _normalize_deploy_failure_stage(exc.stage),
                            "dispatch_service_reason_code": dispatch_service_reason_code,
                        },
                        fallback_message="seo_migration_deploy_readiness_target_check_failed",
                        level=logging.INFO,
                    )
                else:
                    dispatch_service_availability = bool(target_readiness.dispatch_service_availability)
                    dispatch_service_reason_code = _normalize_dispatch_service_reason_code(
                        target_readiness.dispatch_service_reason_code
                    ) or dispatch_service_reason_code
                    dispatch_identifier_type = _normalize_string(
                        target_readiness.dispatch_identifier_type,
                        max_length=80,
                    ) or dispatch_identifier_type
                    target_summary.update(
                        {
                            "repo_exists": target_readiness.repo_exists,
                            "ref_exists": target_readiness.ref_exists,
                            "workflow_exists": target_readiness.workflow_exists,
                            "workflow_dispatch_ready": target_readiness.workflow_dispatch_ready,
                            "workflow_dispatch_supported": target_readiness.workflow_dispatch_supported,
                            "workflow_trigger_types": list(target_readiness.workflow_trigger_types or ()),
                            "dispatch_service_availability": target_readiness.dispatch_service_availability,
                            "dispatch_service_reason_code": target_readiness.dispatch_service_reason_code,
                            "dispatch_identifier_type": target_readiness.dispatch_identifier_type,
                            "workflow_conformance_checked": target_readiness.workflow_conformance_checked,
                            "workflow_conformance_status": target_readiness.workflow_conformance_status,
                            "workflow_conformance_reasons": list(target_readiness.workflow_conformance_reasons or ()),
                            "workflow_conformance_evidence_summary": target_readiness.workflow_conformance_evidence_summary,
                            "kubernetes_namespace": target_readiness.kubernetes_namespace,
                            "namespace_source": target_readiness.namespace_source,
                            "namespace_model_status": target_readiness.namespace_model_status,
                            "workflow_namespace_aligned": target_readiness.workflow_namespace_aligned,
                            "manifest_namespace_aligned": target_readiness.manifest_namespace_aligned,
                            "managed_resource_quota_expected": target_readiness.managed_resource_quota_expected,
                            "managed_resource_quota_present": target_readiness.managed_resource_quota_present,
                            "managed_limit_range_expected": target_readiness.managed_limit_range_expected,
                            "managed_limit_range_present": target_readiness.managed_limit_range_present,
                            "managed_network_policy_expected": target_readiness.managed_network_policy_expected,
                            "managed_network_policy_present": target_readiness.managed_network_policy_present,
                            "managed_namespace_policies_aligned": target_readiness.managed_namespace_policies_aligned,
                            "managed_gke_config_details": _normalize_json_dict(
                                target_readiness.managed_gke_config_details
                            ),
                        }
                    )

        managed_gke_dispatch_message = _derive_managed_gke_dispatch_readiness_message(
            dispatch_service_reason_code=dispatch_service_reason_code
        )
        if managed_gke_dispatch_message:
            reasons.append(managed_gke_dispatch_message)
            blocker_codes.append(_DEPLOY_BLOCKER_CONFIGURATION_MISSING)
        blocker_codes = _dedupe_strings(blocker_codes)
        reasons = _dedupe_strings(reasons)
        latest_traceability = self._derive_latest_deploy_traceability(
            history=workspace.deploy_history_json,
            artifact_version_id=artifact.id if artifact is not None else None,
        )
        latest_failure_detail = self._derive_latest_deploy_failure_detail(
            history=workspace.deploy_history_json,
        )
        if workflow_identifier is None:
            workflow_identifier = _derive_workflow_identifier(
                workflow_id=target_summary.get("workflow_id"),
                workflow_path=target_summary.get("resolved_workflow_path"),
            )
        workflow_identifier_requested = _normalize_string(
            latest_traceability.get("workflow_identifier_requested"),
            max_length=200,
        ) or _normalize_string(target_summary.get("workflow_identifier_requested"), max_length=200)
        workflow_identifier_used = _normalize_string(
            latest_traceability.get("workflow_identifier_used"),
            max_length=200,
        ) or _normalize_string(target_summary.get("workflow_identifier_used"), max_length=200)
        workflow_identifier_type_requested = _normalize_string(
            latest_traceability.get("workflow_identifier_type_requested"),
            max_length=80,
        ) or _normalize_string(target_summary.get("workflow_identifier_type_requested"), max_length=80)
        workflow_identifier_type_used = _normalize_string(
            latest_traceability.get("workflow_identifier_type_used"),
            max_length=80,
        ) or _normalize_string(target_summary.get("workflow_identifier_type_used"), max_length=80)
        workflow_dispatch_resolution_source = _normalize_string(
            latest_traceability.get("workflow_dispatch_resolution_source"),
            max_length=80,
        ) or _normalize_string(target_summary.get("workflow_dispatch_resolution_source"), max_length=80)
        workflow_file_path = _normalize_workflow_path_for_deploy(
            latest_traceability.get("workflow_file_path")
        ) or _normalize_workflow_path_for_deploy(target_summary.get("workflow_file_path"))
        workflow_name = _normalize_string(
            latest_traceability.get("workflow_name"), max_length=160
        ) or _normalize_string(
            target_summary.get("workflow_name"),
            max_length=160,
        )
        if workflow_file_path and not workflow_name:
            workflow_name = _workflow_id_from_path_for_deploy(workflow_file_path)
        workflow_conformance_checked = (
            bool(latest_traceability.get("workflow_conformance_checked"))
            if isinstance(latest_traceability.get("workflow_conformance_checked"), bool)
            else (
                bool(target_summary.get("workflow_conformance_checked"))
                if isinstance(target_summary.get("workflow_conformance_checked"), bool)
                else None
            )
        )
        workflow_conformance_status = _normalize_string(
            latest_traceability.get("workflow_conformance_status"),
            max_length=80,
        ) or _normalize_string(target_summary.get("workflow_conformance_status"), max_length=80)
        workflow_conformance_reasons = _normalize_string_list(
            latest_traceability.get("workflow_conformance_reasons")
        ) or _normalize_string_list(target_summary.get("workflow_conformance_reasons"))
        workflow_conformance_evidence_summary = _normalize_string(
            latest_traceability.get("workflow_conformance_evidence_summary"),
            max_length=240,
        ) or _normalize_string(target_summary.get("workflow_conformance_evidence_summary"), max_length=240)
        last_failure_category = _normalize_string(
            latest_failure_detail.get("failure_category"),
            max_length=40,
        )
        last_failure_reason = _normalize_deploy_failure_reason_code(latest_failure_detail.get("failure_reason"))
        last_failure_stage = _normalize_deploy_failure_stage(latest_failure_detail.get("failure_stage"))
        last_failure_message = _normalize_string(
            latest_failure_detail.get("failure_message"),
            max_length=300,
        )
        last_failure_remediation_hint = _normalize_string(
            latest_failure_detail.get("failure_remediation_hint"),
            max_length=240,
        )
        last_failure_workflow_identifier_requested = _normalize_string(
            latest_failure_detail.get("workflow_identifier_requested"),
            max_length=200,
        )
        last_failure_workflow_identifier_used = _normalize_string(
            latest_failure_detail.get("workflow_identifier_used"),
            max_length=200,
        )
        last_failure_workflow_file_path = _normalize_workflow_path_for_deploy(
            latest_failure_detail.get("workflow_file_path")
        )
        last_failure_workflow_dispatch_resolution_source = _normalize_string(
            latest_failure_detail.get("workflow_dispatch_resolution_source"),
            max_length=80,
        )
        last_failure_dispatch_service_reason_code = _normalize_dispatch_service_reason_code(
            latest_failure_detail.get("dispatch_service_reason_code")
        )
        last_failure_workflow_conformance_status = _normalize_string(
            latest_failure_detail.get("workflow_conformance_status"),
            max_length=80,
        )
        last_failure_workflow_conformance_reasons = _normalize_string_list(
            latest_failure_detail.get("workflow_conformance_reasons")
        )
        last_failure_resolved_workflow_source = _normalize_string(
            latest_failure_detail.get("resolved_workflow_source"),
            max_length=40,
        )
        last_failure_target_environment_key = _normalize_string(
            latest_failure_detail.get("target_environment_key"),
            max_length=80,
        )
        last_failure_target_environment_source = _normalize_string(
            latest_failure_detail.get("target_environment_source"),
            max_length=80,
        )
        kubernetes_namespace = _normalize_string(
            latest_traceability.get("kubernetes_namespace"),
            max_length=63,
        ) or _normalize_string(target_summary.get("kubernetes_namespace"), max_length=63)
        namespace_source = _normalize_string(
            latest_traceability.get("namespace_source"),
            max_length=60,
        ) or _normalize_string(target_summary.get("namespace_source"), max_length=60)
        namespace_model_status = _normalize_string(
            latest_traceability.get("namespace_model_status"),
            max_length=40,
        ) or _normalize_string(target_summary.get("namespace_model_status"), max_length=40)
        workflow_namespace_aligned = (
            bool(latest_traceability.get("workflow_namespace_aligned"))
            if isinstance(latest_traceability.get("workflow_namespace_aligned"), bool)
            else (
                bool(target_summary.get("workflow_namespace_aligned"))
                if isinstance(target_summary.get("workflow_namespace_aligned"), bool)
                else None
            )
        )
        manifest_namespace_aligned = (
            bool(latest_traceability.get("manifest_namespace_aligned"))
            if isinstance(latest_traceability.get("manifest_namespace_aligned"), bool)
            else (
                bool(target_summary.get("manifest_namespace_aligned"))
                if isinstance(target_summary.get("manifest_namespace_aligned"), bool)
                else None
            )
        )
        managed_resource_quota_expected = (
            bool(latest_traceability.get("managed_resource_quota_expected"))
            if isinstance(latest_traceability.get("managed_resource_quota_expected"), bool)
            else (
                bool(target_summary.get("managed_resource_quota_expected"))
                if isinstance(target_summary.get("managed_resource_quota_expected"), bool)
                else None
            )
        )
        managed_resource_quota_present = (
            bool(latest_traceability.get("managed_resource_quota_present"))
            if isinstance(latest_traceability.get("managed_resource_quota_present"), bool)
            else (
                bool(target_summary.get("managed_resource_quota_present"))
                if isinstance(target_summary.get("managed_resource_quota_present"), bool)
                else None
            )
        )
        managed_limit_range_expected = (
            bool(latest_traceability.get("managed_limit_range_expected"))
            if isinstance(latest_traceability.get("managed_limit_range_expected"), bool)
            else (
                bool(target_summary.get("managed_limit_range_expected"))
                if isinstance(target_summary.get("managed_limit_range_expected"), bool)
                else None
            )
        )
        managed_limit_range_present = (
            bool(latest_traceability.get("managed_limit_range_present"))
            if isinstance(latest_traceability.get("managed_limit_range_present"), bool)
            else (
                bool(target_summary.get("managed_limit_range_present"))
                if isinstance(target_summary.get("managed_limit_range_present"), bool)
                else None
            )
        )
        managed_network_policy_expected = (
            bool(latest_traceability.get("managed_network_policy_expected"))
            if isinstance(latest_traceability.get("managed_network_policy_expected"), bool)
            else (
                bool(target_summary.get("managed_network_policy_expected"))
                if isinstance(target_summary.get("managed_network_policy_expected"), bool)
                else None
            )
        )
        managed_network_policy_present = (
            bool(latest_traceability.get("managed_network_policy_present"))
            if isinstance(latest_traceability.get("managed_network_policy_present"), bool)
            else (
                bool(target_summary.get("managed_network_policy_present"))
                if isinstance(target_summary.get("managed_network_policy_present"), bool)
                else None
            )
        )
        managed_namespace_policies_aligned = (
            bool(latest_traceability.get("managed_namespace_policies_aligned"))
            if isinstance(latest_traceability.get("managed_namespace_policies_aligned"), bool)
            else (
                bool(target_summary.get("managed_namespace_policies_aligned"))
                if isinstance(target_summary.get("managed_namespace_policies_aligned"), bool)
                else None
            )
        )
        if kubernetes_namespace and not _normalize_string(target_summary.get("kubernetes_namespace"), max_length=63):
            target_summary["kubernetes_namespace"] = kubernetes_namespace
        if namespace_source and not _normalize_string(target_summary.get("namespace_source"), max_length=60):
            target_summary["namespace_source"] = namespace_source
        if namespace_model_status and not _normalize_string(target_summary.get("namespace_model_status"), max_length=40):
            target_summary["namespace_model_status"] = namespace_model_status
        if (
            workflow_namespace_aligned is not None
            and not isinstance(target_summary.get("workflow_namespace_aligned"), bool)
        ):
            target_summary["workflow_namespace_aligned"] = workflow_namespace_aligned
        if (
            manifest_namespace_aligned is not None
            and not isinstance(target_summary.get("manifest_namespace_aligned"), bool)
        ):
            target_summary["manifest_namespace_aligned"] = manifest_namespace_aligned
        if (
            managed_resource_quota_expected is not None
            and not isinstance(target_summary.get("managed_resource_quota_expected"), bool)
        ):
            target_summary["managed_resource_quota_expected"] = managed_resource_quota_expected
        if (
            managed_resource_quota_present is not None
            and not isinstance(target_summary.get("managed_resource_quota_present"), bool)
        ):
            target_summary["managed_resource_quota_present"] = managed_resource_quota_present
        if (
            managed_limit_range_expected is not None
            and not isinstance(target_summary.get("managed_limit_range_expected"), bool)
        ):
            target_summary["managed_limit_range_expected"] = managed_limit_range_expected
        if (
            managed_limit_range_present is not None
            and not isinstance(target_summary.get("managed_limit_range_present"), bool)
        ):
            target_summary["managed_limit_range_present"] = managed_limit_range_present
        if (
            managed_network_policy_expected is not None
            and not isinstance(target_summary.get("managed_network_policy_expected"), bool)
        ):
            target_summary["managed_network_policy_expected"] = managed_network_policy_expected
        if (
            managed_network_policy_present is not None
            and not isinstance(target_summary.get("managed_network_policy_present"), bool)
        ):
            target_summary["managed_network_policy_present"] = managed_network_policy_present
        if (
            managed_namespace_policies_aligned is not None
            and not isinstance(target_summary.get("managed_namespace_policies_aligned"), bool)
        ):
            target_summary["managed_namespace_policies_aligned"] = managed_namespace_policies_aligned
        last_failure_workflow_exists = (
            bool(latest_failure_detail.get("workflow_exists"))
            if isinstance(latest_failure_detail.get("workflow_exists"), bool)
            else None
        )
        failure_category: str | None = None
        if reasons:
            failure_category = self._categorize_readiness_failure(
                reasons=reasons,
                action="deploy",
                blocker_codes=blocker_codes,
            )
        workflow_dispatch_supported = (
            bool(latest_traceability.get("workflow_dispatch_supported"))
            if isinstance(latest_traceability.get("workflow_dispatch_supported"), bool)
            else (
                bool(target_summary.get("workflow_dispatch_supported"))
                if isinstance(target_summary.get("workflow_dispatch_supported"), bool)
                else None
            )
        )
        workflow_trigger_types = _normalize_workflow_trigger_types_for_summary(
            latest_traceability.get("workflow_trigger_types")
        ) or _normalize_workflow_trigger_types_for_summary(target_summary.get("workflow_trigger_types"))

        return {
            "ready": not reasons,
            "reasons": reasons,
            "blocker_codes": blocker_codes,
            "failure_category": failure_category,
            "workflow_identifier": workflow_identifier,
            "workflow_identifier_requested": workflow_identifier_requested,
            "workflow_identifier_used": workflow_identifier_used,
            "workflow_identifier_type_requested": workflow_identifier_type_requested,
            "workflow_identifier_type_used": workflow_identifier_type_used,
            "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
            "workflow_file_path": workflow_file_path,
            "workflow_name": workflow_name,
            "dispatch_identifier_type": dispatch_identifier_type,
            "workflow_dispatch_supported": workflow_dispatch_supported,
            "workflow_trigger_types": workflow_trigger_types,
            "dispatch_service_availability": dispatch_service_availability,
            "dispatch_service_reason_code": dispatch_service_reason_code,
            "workflow_conformance_checked": workflow_conformance_checked,
            "workflow_conformance_status": workflow_conformance_status,
            "workflow_conformance_reasons": workflow_conformance_reasons,
            "workflow_conformance_evidence_summary": workflow_conformance_evidence_summary,
            "last_failure_category": last_failure_category,
            "last_failure_reason": last_failure_reason,
            "last_failure_stage": last_failure_stage,
            "last_failure_message": last_failure_message,
            "last_failure_remediation_hint": last_failure_remediation_hint,
            "last_failure_workflow_identifier_requested": last_failure_workflow_identifier_requested,
            "last_failure_workflow_identifier_used": last_failure_workflow_identifier_used,
            "last_failure_workflow_file_path": last_failure_workflow_file_path,
            "last_failure_workflow_exists": last_failure_workflow_exists,
            "last_failure_workflow_dispatch_resolution_source": last_failure_workflow_dispatch_resolution_source,
            "last_failure_dispatch_service_reason_code": last_failure_dispatch_service_reason_code,
            "last_failure_workflow_conformance_status": last_failure_workflow_conformance_status,
            "last_failure_workflow_conformance_reasons": last_failure_workflow_conformance_reasons,
            "last_failure_resolved_workflow_source": last_failure_resolved_workflow_source,
            "last_failure_target_environment_key": last_failure_target_environment_key,
            "last_failure_target_environment_source": last_failure_target_environment_source,
            "kubernetes_namespace": kubernetes_namespace,
            "namespace_source": namespace_source,
            "namespace_model_status": namespace_model_status,
            "workflow_namespace_aligned": workflow_namespace_aligned,
            "manifest_namespace_aligned": manifest_namespace_aligned,
            "managed_resource_quota_expected": managed_resource_quota_expected,
            "managed_resource_quota_present": managed_resource_quota_present,
            "managed_limit_range_expected": managed_limit_range_expected,
            "managed_limit_range_present": managed_limit_range_present,
            "managed_network_policy_expected": managed_network_policy_expected,
            "managed_network_policy_present": managed_network_policy_present,
            "managed_namespace_policies_aligned": managed_namespace_policies_aligned,
            "last_deploy_trace_id": latest_traceability.get("deploy_trace_id"),
            "last_dispatch_attempted": latest_traceability.get("dispatch_attempted"),
            "last_dispatch_result_stage": latest_traceability.get("dispatch_result_stage"),
            "last_dispatch_ref_sent": latest_traceability.get("dispatch_ref_sent"),
            "last_workflow_inputs_configured_keys": latest_traceability.get("workflow_inputs_configured_keys") or [],
            "last_workflow_inputs_sent_keys": latest_traceability.get("workflow_inputs_sent_keys") or [],
            "last_workflow_run_lookup_attempted": latest_traceability.get("workflow_run_lookup_attempted"),
            "last_workflow_run_found": latest_traceability.get("workflow_run_found"),
            "last_workflow_job_failure_detected": latest_traceability.get("workflow_job_failure_detected"),
            "last_post_dispatch_state": latest_traceability.get("post_dispatch_state"),
            "last_post_conformance_stage": latest_traceability.get("post_conformance_stage"),
            "last_post_conformance_reason_text": latest_traceability.get("post_conformance_reason_text"),
            "last_post_conformance_remediation_message": latest_traceability.get(
                "post_conformance_remediation_message"
            ),
            "expected_workflow_outputs": latest_traceability.get("expected_workflow_outputs")
            or list(_DEPLOY_EXPECTED_WORKFLOW_OUTPUT_KEYS),
            "last_deploy_evidence_contract_status": latest_traceability.get("deploy_evidence_contract_status"),
            "last_deploy_evidence_contract_reasons": latest_traceability.get("deploy_evidence_contract_reasons") or [],
            "last_workflow_contract_advisory": latest_traceability.get("workflow_contract_advisory"),
            "last_repo_exists": latest_traceability.get("repo_exists"),
            "last_ref_exists": latest_traceability.get("ref_exists"),
            "last_workflow_exists": latest_traceability.get("workflow_exists"),
            "last_workflow_dispatch_ready": latest_traceability.get("workflow_dispatch_ready"),
            "last_workflow_run_id": latest_traceability.get("workflow_run_id"),
            "last_workflow_run_status": latest_traceability.get("workflow_run_status"),
            "last_workflow_run_conclusion": latest_traceability.get("workflow_run_conclusion"),
            "last_workflow_run_failure_reason_code": latest_traceability.get("workflow_run_failure_reason_code"),
            "last_workflow_run_failure_stage": latest_traceability.get("workflow_run_failure_stage"),
            "last_workflow_run_failure_step": latest_traceability.get("workflow_run_failure_step"),
            "last_workflow_run_failure_hint": latest_traceability.get("workflow_run_failure_hint"),
            "target": target_summary,
            "config_prerequisites": {
                "github_publisher_configured": self.github_publisher_configured,
                "github_publisher_reason_code": str(runtime_diagnostics.get("reason_code") or ""),
                "github_publisher_status_message": str(runtime_diagnostics.get("status_message") or ""),
                "deploy_runtime_available": bool(runtime_diagnostics.get("configured")),
                "dispatch_service_availability": dispatch_service_availability,
                "dispatch_service_reason_code": dispatch_service_reason_code,
                "managed_deploy_secret_available": managed_deploy_secret_available,
                "managed_deploy_secret_source": managed_deploy_secret_source,
                "managed_deploy_secret_reason": managed_deploy_secret_reason,
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
    ) -> tuple[list[dict[str, object]], list[str], dict[str, object]]:
        warnings: list[str] = []
        parser_rejection_reason_counts: dict[str, int] = {}

        def _increment_reason(reason_code: str) -> None:
            parser_rejection_reason_counts[reason_code] = parser_rejection_reason_counts.get(reason_code, 0) + 1

        if len(files) > _MAX_GENERATED_FILES:
            warnings.append("Generated file list exceeded max count and was truncated.")
            _increment_reason("max_file_count_truncated")
        normalized: list[dict[str, object]] = []
        seen_paths: set[str] = set()
        total_bytes = 0
        candidate_item_count = max(0, int(len(files)))
        for raw_file in files[:_MAX_GENERATED_FILES]:
            path = _normalize_generated_path(getattr(raw_file, "path", None))
            if path is None:
                warnings.append("Dropped generated file with invalid path.")
                _increment_reason("invalid_path")
                continue
            if path in seen_paths:
                warnings.append(f"Dropped duplicate generated path '{path}'.")
                _increment_reason("duplicate_path")
                continue
            if _is_forbidden_path(path):
                warnings.append(f"Dropped forbidden generated path '{path}'.")
                _increment_reason("forbidden_path")
                continue
            if not path.endswith(_ALLOWED_FILE_EXTENSIONS):
                warnings.append(f"Dropped generated path outside static package boundary '{path}'.")
                _increment_reason("disallowed_extension")
                continue
            content = _normalize_generated_content(getattr(raw_file, "content", None))
            if content is None:
                warnings.append(f"Dropped generated path '{path}' due to empty content.")
                _increment_reason("empty_content")
                continue
            if len(content.encode("utf-8")) > _MAX_FILE_BYTES:
                warnings.append(f"Dropped generated path '{path}' due to file size limit.")
                _increment_reason("file_too_large")
                continue
            media_type = _normalize_media_type(path=path, value=getattr(raw_file, "media_type", None))
            normalized_content = _normalize_analytics_placeholders(path=path, content=content)
            content_bytes = len(normalized_content.encode("utf-8"))
            if total_bytes + content_bytes > _MAX_TOTAL_BYTES:
                warnings.append("Generated file payload exceeded aggregate size limit and was truncated.")
                _increment_reason("aggregate_size_limit")
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
        required_files_expected = ["index.html"]
        required_files_present = (
            ["index.html"]
            if any(str(item.get("path") or "").strip().lower() == "index.html" for item in normalized)
            else []
        )
        missing_required_files = [item for item in required_files_expected if item not in required_files_present]
        diagnostics = {
            "candidate_item_count": candidate_item_count,
            "normalized_item_count": max(0, int(len(normalized))),
            "dropped_item_count": max(0, int(candidate_item_count - len(normalized))),
            "required_artifact_files_expected": required_files_expected,
            "required_artifact_files_present": required_files_present,
            "missing_required_artifact_files": missing_required_files,
            "artifact_primary_file_detected": bool(required_files_present),
            "parser_rejection_reason_counts": parser_rejection_reason_counts,
        }
        return normalized, warnings, diagnostics

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


def _normalize_deploy_failure_reason_code(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=80)
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    allowed = {
        _DEPLOY_TARGET_REASON_REPO_NOT_FOUND,
        _DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND,
        _DEPLOY_TARGET_REASON_REF_INVALID,
        _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED,
        _DEPLOY_TARGET_REASON_TOKEN_UNAUTHORIZED,
        _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE,
        _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY,
        "github_target_not_found",
        "github_request_failed",
        "github_temporal_failure",
        "github_timeout",
        "github_network_error",
        "github_auth_failed",
        "publisher_not_configured",
    }
    if normalized_lower in allowed:
        return normalized_lower
    return None


def _normalize_deploy_failure_stage(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=40)
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    if normalized_lower in {"repo_lookup", "ref_lookup", "workflow_lookup", "workflow_dispatch"}:
        return normalized_lower
    return None


def _normalize_workflow_run_failure_reason_code(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=80)
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    allowed = {
        _DEPLOY_RUN_FAILURE_REASON_GCP_AUTH,
        _DEPLOY_RUN_FAILURE_REASON_CLUSTER_CREDENTIALS,
        _DEPLOY_RUN_FAILURE_REASON_MANIFEST_APPLY,
        _DEPLOY_RUN_FAILURE_REASON_ROLLOUT,
        _DEPLOY_RUN_FAILURE_REASON_INGRESS_VERIFY,
        _DEPLOY_RUN_FAILURE_REASON_INGRESS_EVIDENCE,
        _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_INVALID_STATE,
        _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_INSPECTION_FAILED,
        _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_EPHEMERAL_CERT,
        _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_CONNECTION,
        _DEPLOY_RUN_FAILURE_REASON_CANCELLED,
        _DEPLOY_RUN_FAILURE_REASON_TIMED_OUT,
        _DEPLOY_RUN_FAILURE_REASON_GENERIC,
    }
    if normalized_lower in allowed:
        return normalized_lower
    return None


def _normalize_workflow_run_failure_stage(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=80)
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    allowed = {
        _DEPLOY_RUN_FAILURE_STAGE_GCP_AUTH,
        _DEPLOY_RUN_FAILURE_STAGE_CLUSTER_CREDENTIALS,
        _DEPLOY_RUN_FAILURE_STAGE_MANIFEST_APPLY,
        _DEPLOY_RUN_FAILURE_STAGE_ROLLOUT,
        _DEPLOY_RUN_FAILURE_STAGE_INGRESS_VERIFY,
        _DEPLOY_RUN_FAILURE_STAGE_INGRESS_EVIDENCE,
        _DEPLOY_RUN_FAILURE_STAGE_WORKFLOW_EXECUTION,
    }
    if normalized_lower in allowed:
        return normalized_lower
    return None


def _normalize_dispatch_service_reason_code(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=80)
    if not normalized:
        return None
    normalized_lower = normalized.lower()
    if normalized_lower in {
        _DEPLOY_DISPATCH_SERVICE_REASON_AVAILABLE,
        _DEPLOY_DISPATCH_SERVICE_REASON_RUNTIME_UNAVAILABLE,
        _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_CONFIG_INVALID,
        _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_DISABLED,
        _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_METADATA_MISSING,
        _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME,
        _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION,
        _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID,
    }:
        return normalized_lower
    if normalized_lower in {
        _GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING,
        _GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID,
        _GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE,
        "github_auth_failed",
        "publisher_not_configured",
    }:
        return _DEPLOY_DISPATCH_SERVICE_REASON_RUNTIME_UNAVAILABLE
    return None


def _normalize_workflow_trigger_types_for_summary(value: object) -> list[str]:
    raw_values: list[object] = []
    if isinstance(value, str):
        raw_values = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    normalized: list[str] = []
    for item in raw_values:
        candidate = _normalize_string(item, max_length=60)
        if not candidate:
            continue
        normalized.append(candidate.lower())
    return _dedupe_strings(normalized)


def _normalize_dispatch_input_keys(value: object) -> list[str]:
    raw_values: list[object] = []
    if isinstance(value, dict):
        raw_values = list(value.keys())
    elif isinstance(value, (list, tuple, set)):
        raw_values = list(value)
    normalized: list[str] = []
    for item in raw_values:
        candidate = _normalize_string(item, max_length=80)
        if candidate:
            normalized.append(candidate)
    return _dedupe_strings(normalized)


def _derive_workflow_job_failure_detected(
    *,
    workflow_run_status: object,
    workflow_run_conclusion: object,
) -> bool | None:
    status = _normalize_string(workflow_run_status, max_length=40)
    conclusion = _normalize_string(workflow_run_conclusion, max_length=40)
    if status is None and conclusion is None:
        return None
    if (status or "").strip().lower() != "completed":
        return False
    normalized_conclusion = (conclusion or "").strip().lower()
    if not normalized_conclusion:
        return False
    return normalized_conclusion != "success"


def _derive_post_dispatch_state(
    *,
    dispatch_attempted: object,
    dispatch_result_stage: object,
    workflow_run_id: object,
    workflow_run_status: object,
    workflow_run_conclusion: object,
    resolved_live_url: object,
    workflow_run_lookup_attempted: object | None = None,
    workflow_run_found: object | None = None,
) -> str:
    attempted = dispatch_attempted if isinstance(dispatch_attempted, bool) else None
    result_stage = _normalize_deploy_failure_stage(dispatch_result_stage)
    run_id = _coerce_int(workflow_run_id)
    run_status = (_normalize_string(workflow_run_status, max_length=40) or "").strip().lower()
    run_conclusion = (_normalize_string(workflow_run_conclusion, max_length=40) or "").strip().lower()
    confirmed_live_url = _normalize_url_candidate(resolved_live_url)

    if attempted is False:
        return "dispatch_not_attempted"
    if run_id is None:
        if attempted is True:
            lookup_attempted = (
                bool(workflow_run_lookup_attempted)
                if isinstance(workflow_run_lookup_attempted, bool)
                else None
            )
            run_found = bool(workflow_run_found) if isinstance(workflow_run_found, bool) else None
            if lookup_attempted is True and run_found is False:
                return "dispatch_unverified_no_run"
            return "dispatch_accepted_no_run"
        if result_stage:
            return f"dispatch_blocked_{result_stage}"
        return "dispatch_not_attempted"
    if run_status in {"queued", "waiting", "requested", "pending"}:
        return "workflow_run_pending"
    if run_status in {"in_progress", "running"}:
        return "workflow_run_in_progress"
    if run_status == "completed":
        if run_conclusion == "success":
            if confirmed_live_url:
                return "workflow_run_succeeded_with_live_url"
            return "workflow_run_succeeded_without_live_url"
        if run_conclusion:
            return "workflow_run_failed"
        return "workflow_run_completed"
    if confirmed_live_url:
        return "workflow_run_succeeded_with_live_url"
    return "workflow_run_observed"


def _normalize_deploy_evidence_contract_status(value: object) -> str | None:
    normalized = (_normalize_string(value, max_length=80) or "").strip().lower()
    if normalized in {
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_CONFIRMED,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_PLACEHOLDER,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_CONTRACT_INCOMPLETE,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_SUCCEEDED_NO_EVIDENCE,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_RUN_FAILED,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_PENDING,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_NOT_ATTEMPTED,
        _DEPLOY_EVIDENCE_CONTRACT_STATUS_UNKNOWN,
    }:
        return normalized
    return None


def _normalize_post_conformance_stage(value: object) -> str | None:
    normalized = (_normalize_string(value, max_length=80) or "").strip().lower()
    if normalized in _POST_CONFORMANCE_STAGE_VALUES:
        return normalized
    return None


def _derive_post_conformance_stage(
    *,
    workflow_conformance_status: object,
    dispatch_attempted: object,
    dispatch_result_stage: object,
    failure_stage: object,
    post_dispatch_state: object,
    workflow_run_lookup_attempted: object,
    workflow_run_failure_stage: object,
    deploy_evidence_contract_status: object,
) -> str:
    conformance_status = (_normalize_string(workflow_conformance_status, max_length=80) or "").strip().lower()
    if conformance_status and conformance_status != "conformant":
        return _POST_CONFORMANCE_STAGE_WORKFLOW_CONFORMANCE_FAILED

    normalized_failure_stage = _normalize_deploy_failure_stage(failure_stage)
    if normalized_failure_stage == "workflow_dispatch":
        return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_FAILED

    post_state = _normalize_string(post_dispatch_state, max_length=80)
    if post_state == "workflow_run_succeeded_with_live_url":
        return _POST_CONFORMANCE_STAGE_DEPLOY_SUCCEEDED
    if post_state == "workflow_run_succeeded_without_live_url":
        return _POST_CONFORMANCE_STAGE_LIVE_URL_EVIDENCE_MISSING
    if post_state == "workflow_run_failed":
        normalized_run_failure_stage = _normalize_workflow_run_failure_stage(workflow_run_failure_stage)
        if normalized_run_failure_stage == _DEPLOY_RUN_FAILURE_STAGE_ROLLOUT:
            return _POST_CONFORMANCE_STAGE_ROLLOUT_FAILED
        return _POST_CONFORMANCE_STAGE_WORKFLOW_RUN_FAILED
    if post_state in {
        "dispatch_accepted_no_run",
        "dispatch_unverified_no_run",
        "workflow_run_pending",
        "workflow_run_in_progress",
        "workflow_run_observed",
        "workflow_run_completed",
    }:
        dispatch_was_attempted = bool(dispatch_attempted) if isinstance(dispatch_attempted, bool) else False
        lookup_attempted = bool(workflow_run_lookup_attempted) if isinstance(workflow_run_lookup_attempted, bool) else False
        if post_state == "dispatch_accepted_no_run" and dispatch_was_attempted and not lookup_attempted:
            return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED
        return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN
    if post_state and (post_state == "dispatch_not_attempted" or post_state.startswith("dispatch_blocked_")):
        return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED

    deploy_evidence_status = _normalize_deploy_evidence_contract_status(deploy_evidence_contract_status)
    if deploy_evidence_status == _DEPLOY_EVIDENCE_CONTRACT_STATUS_CONFIRMED:
        return _POST_CONFORMANCE_STAGE_DEPLOY_SUCCEEDED
    if deploy_evidence_status == _DEPLOY_EVIDENCE_CONTRACT_STATUS_SUCCEEDED_NO_EVIDENCE:
        return _POST_CONFORMANCE_STAGE_LIVE_URL_EVIDENCE_MISSING
    if deploy_evidence_status == _DEPLOY_EVIDENCE_CONTRACT_STATUS_RUN_FAILED:
        normalized_run_failure_stage = _normalize_workflow_run_failure_stage(workflow_run_failure_stage)
        if normalized_run_failure_stage == _DEPLOY_RUN_FAILURE_STAGE_ROLLOUT:
            return _POST_CONFORMANCE_STAGE_ROLLOUT_FAILED
        return _POST_CONFORMANCE_STAGE_WORKFLOW_RUN_FAILED
    if deploy_evidence_status == _DEPLOY_EVIDENCE_CONTRACT_STATUS_PENDING:
        return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN
    if deploy_evidence_status == _DEPLOY_EVIDENCE_CONTRACT_STATUS_NOT_ATTEMPTED:
        return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED

    dispatch_was_attempted = bool(dispatch_attempted) if isinstance(dispatch_attempted, bool) else False
    if dispatch_was_attempted:
        normalized_dispatch_stage = _normalize_deploy_failure_stage(dispatch_result_stage)
        if normalized_dispatch_stage == "workflow_dispatch":
            return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED
        return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN
    return _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED


def _derive_post_conformance_reason_text(
    *,
    post_conformance_stage: object,
    workflow_run_failure_reason_code: object,
    workflow_run_failure_stage: object,
    post_dispatch_state: object,
) -> str | None:
    normalized_stage = _normalize_post_conformance_stage(post_conformance_stage)
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_CONFORMANCE_FAILED:
        return "Workflow conformance validation failed before dispatch."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED:
        return "Workflow dispatch was blocked before dispatch execution."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED:
        return "Workflow dispatch was attempted; awaiting run evidence."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_FAILED:
        return "GitHub workflow dispatch rejected by API."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN:
        return "Workflow dispatch succeeded but run evidence is still pending."
    if normalized_stage in {
        _POST_CONFORMANCE_STAGE_WORKFLOW_RUN_FAILED,
        _POST_CONFORMANCE_STAGE_ROLLOUT_FAILED,
    }:
        hint = _derive_workflow_run_failure_hint(
            failure_reason=workflow_run_failure_reason_code,
            post_dispatch_state=post_dispatch_state,
        )
        if hint:
            return hint
        if _normalize_workflow_run_failure_stage(workflow_run_failure_stage) == _DEPLOY_RUN_FAILURE_STAGE_ROLLOUT:
            return "Workflow run started but rollout verification failed."
        return "Workflow run started but failed before explicit live URL evidence."
    if normalized_stage == _POST_CONFORMANCE_STAGE_LIVE_URL_EVIDENCE_MISSING:
        return "Workflow run completed without resolved_live_url evidence."
    if normalized_stage == _POST_CONFORMANCE_STAGE_DEPLOY_SUCCEEDED:
        return "Deploy succeeded with explicit live URL evidence."
    return None


def _derive_post_conformance_remediation_message(
    *,
    post_conformance_stage: object,
) -> str | None:
    normalized_stage = _normalize_post_conformance_stage(post_conformance_stage)
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_CONFORMANCE_FAILED:
        return "The repo workflow is not deploy-capable yet. Republish if managed; manually fix if custom."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_BLOCKED:
        return "Deploy prerequisites are still blocking dispatch. Review target readiness details."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_ATTEMPTED:
        return "Dispatch was attempted. Refresh deploy status to confirm workflow run evidence."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_FAILED:
        return "GitHub rejected the dispatch request. Check repo/workflow/ref access and dispatch support."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_DISPATCH_WAITING_FOR_RUN:
        return "Dispatch succeeded but run evidence is not visible yet. Refresh deploy status."
    if normalized_stage == _POST_CONFORMANCE_STAGE_WORKFLOW_RUN_FAILED:
        return "The workflow run failed before deployment completed. Review GitHub Actions logs."
    if normalized_stage == _POST_CONFORMANCE_STAGE_ROLLOUT_FAILED:
        return (
            "The workflow reached rollout but deployment did not become healthy. "
            "Review kubectl rollout output and GKE workload state."
        )
    if normalized_stage == _POST_CONFORMANCE_STAGE_LIVE_URL_EVIDENCE_MISSING:
        return (
            "Deployment may have completed, but no live URL evidence was captured. "
            "Confirm workflow outputs and deployment result reporting."
        )
    if normalized_stage == _POST_CONFORMANCE_STAGE_DEPLOY_SUCCEEDED:
        return "Deployment completed and live URL evidence was captured."
    return None


def _derive_workflow_remediation_outcome(
    *,
    remediation_attempted: bool,
    managed_workflow_outcome: object,
    write_failed: bool,
) -> str:
    if not remediation_attempted:
        return _WORKFLOW_REMEDIATION_OUTCOME_NOT_ATTEMPTED
    if write_failed:
        return _WORKFLOW_REMEDIATION_OUTCOME_WRITE_FAILED
    normalized_managed_outcome = _normalize_string(managed_workflow_outcome, max_length=80)
    if normalized_managed_outcome in {"managed_workflow_upgraded", "managed_workflow_created"}:
        return _WORKFLOW_REMEDIATION_OUTCOME_UPGRADED_MANAGED_PLACEHOLDER
    if normalized_managed_outcome == "managed_workflow_already_current":
        return _WORKFLOW_REMEDIATION_OUTCOME_ALREADY_CURRENT
    if normalized_managed_outcome == "managed_workflow_preserved_custom":
        return _WORKFLOW_REMEDIATION_OUTCOME_PRESERVED_CUSTOM
    return _WORKFLOW_REMEDIATION_OUTCOME_ALREADY_CURRENT


def _derive_deploy_evidence_contract(
    *,
    workflow_conformance_status: object,
    post_dispatch_state: object,
    resolved_live_url: object,
    url_source: object,
) -> tuple[str, list[str], str | None]:
    conformance_status = _normalize_string(workflow_conformance_status, max_length=80)
    post_state = _normalize_string(post_dispatch_state, max_length=80)
    resolved_live = _normalize_url_candidate(resolved_live_url)
    normalized_url_source = _normalize_migration_url_source(url_source)

    if resolved_live and normalized_url_source in {
        _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT,
        _MIGRATION_URL_SOURCE_DEPLOY_RESULT,
    }:
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_CONFIRMED,
            ["explicit_live_url_evidence_captured"],
            None,
        )
    if conformance_status == "workflow_placeholder_detected":
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_PLACEHOLDER,
            ["workflow_placeholder_detected"],
            "Selected workflow appears placeholder/non-deploying and may not emit explicit deploy evidence.",
        )
    if conformance_status == "workflow_contract_incomplete":
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_CONTRACT_INCOMPLETE,
            ["workflow_contract_incomplete"],
            "Selected workflow is dispatchable but missing managed deploy contract markers for explicit deploy evidence.",
        )
    if post_state == "workflow_run_succeeded_without_live_url":
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_SUCCEEDED_NO_EVIDENCE,
            ["workflow_run_succeeded_without_live_url"],
            "Workflow run completed but did not emit explicit live URL evidence.",
        )
    if post_state == "workflow_run_failed":
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_RUN_FAILED,
            ["workflow_run_failed"],
            "Workflow run failed before explicit live URL evidence was captured.",
        )
    if post_state in {
        "dispatch_accepted_no_run",
        "dispatch_unverified_no_run",
        "workflow_run_pending",
        "workflow_run_in_progress",
    }:
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_PENDING,
            [post_state],
            "Workflow run evidence is still pending; live deployment is not yet confirmed.",
        )
    if post_state == "dispatch_not_attempted" or (post_state and post_state.startswith("dispatch_blocked_")):
        return (
            _DEPLOY_EVIDENCE_CONTRACT_STATUS_NOT_ATTEMPTED,
            [post_state or "dispatch_not_attempted"],
            "Deploy dispatch was not completed; live deployment evidence cannot be confirmed yet.",
        )
    return (_DEPLOY_EVIDENCE_CONTRACT_STATUS_UNKNOWN, [], None)


def _infer_dispatch_identifier_type(workflow_id: object) -> str:
    normalized_workflow_path = _normalize_workflow_path_for_deploy(workflow_id)
    if normalized_workflow_path:
        return "workflow_file_path"
    normalized_workflow_id = _normalize_workflow_id_for_deploy(workflow_id)
    if normalized_workflow_id is None:
        normalized_workflow_id = _normalize_string(workflow_id, max_length=160) or ""
    if normalized_workflow_id.isdigit():
        return "workflow_numeric_id"
    return "workflow_id"


def _derive_dispatch_verification_state(
    *,
    dispatch_attempted: object,
    workflow_run_id: object,
    workflow_run_lookup_attempted: object,
    workflow_run_found: object,
) -> str:
    attempted = bool(dispatch_attempted) if isinstance(dispatch_attempted, bool) else False
    run_id = _coerce_int(workflow_run_id)
    lookup_attempted = (
        bool(workflow_run_lookup_attempted) if isinstance(workflow_run_lookup_attempted, bool) else False
    )
    run_found = bool(workflow_run_found) if isinstance(workflow_run_found, bool) else False
    if run_id is not None or run_found:
        return "confirmed_run_observed"
    if not attempted:
        return "dispatch_not_attempted"
    if lookup_attempted:
        return "unverified_dispatch_no_run_observed"
    return "unverified_dispatch_pending_observation"


def _derive_workflow_identifier(*, workflow_id: object, workflow_path: object) -> str | None:
    normalized_path = _normalize_workflow_path_for_deploy(workflow_path)
    if normalized_path:
        return normalized_path
    normalized_workflow_id = _normalize_workflow_id_for_deploy(workflow_id)
    if normalized_workflow_id:
        return normalized_workflow_id
    return _normalize_string(workflow_id, max_length=160)


def _resolve_workflow_dispatch_identifier(
    *,
    workflow_id: object,
    workflow_path: object,
) -> dict[str, str | None]:
    requested_identifier = _normalize_string(workflow_id, max_length=160)
    normalized_workflow_id = _normalize_workflow_id_for_deploy(workflow_id) or requested_identifier
    normalized_workflow_path = _normalize_workflow_path_for_deploy(workflow_path)
    normalized_requested_path = _normalize_workflow_path_for_deploy(requested_identifier)
    workflow_name_from_path = _workflow_id_from_path_for_deploy(normalized_workflow_path or normalized_requested_path)
    workflow_name_from_identifier = _workflow_id_from_path_for_deploy(normalized_workflow_id)

    used_identifier: str | None = None
    workflow_dispatch_resolution_source = "workflow_id"
    workflow_identifier_type_used = "workflow_id"
    if normalized_workflow_path:
        used_identifier = normalized_workflow_path
        workflow_dispatch_resolution_source = "workflow_file_path"
        workflow_identifier_type_used = "workflow_file_path"
    elif normalized_requested_path:
        used_identifier = normalized_requested_path
        workflow_dispatch_resolution_source = "workflow_file_path"
        workflow_identifier_type_used = "workflow_file_path"
    elif normalized_workflow_id:
        used_identifier = normalized_workflow_id
        workflow_dispatch_resolution_source = "workflow_id"
        workflow_identifier_type_used = _infer_dispatch_identifier_type(used_identifier)
    elif workflow_name_from_identifier:
        used_identifier = workflow_name_from_identifier
        workflow_dispatch_resolution_source = "workflow_id_path_normalized"
        workflow_identifier_type_used = _infer_dispatch_identifier_type(used_identifier)

    return {
        "workflow_identifier_requested": requested_identifier or normalized_workflow_id,
        "workflow_identifier_used": used_identifier,
        "workflow_identifier_type_requested": _infer_dispatch_identifier_type(requested_identifier),
        "workflow_identifier_type_used": workflow_identifier_type_used,
        "workflow_dispatch_resolution_source": workflow_dispatch_resolution_source,
        "workflow_file_path": normalized_workflow_path or normalized_requested_path,
        "workflow_name": workflow_name_from_path or workflow_name_from_identifier,
    }


def _derive_dispatch_service_reason_code(
    *,
    runtime_reason_code: str,
    target_valid: bool,
    target_enabled: bool,
    dispatch_service_availability: bool,
    failure_reason_code: str | None = None,
    failure_stage: str | None = None,
) -> str:
    if dispatch_service_availability:
        return _DEPLOY_DISPATCH_SERVICE_REASON_AVAILABLE
    runtime_reason = _normalize_string(runtime_reason_code, max_length=80)
    if runtime_reason:
        runtime_reason = runtime_reason.lower()
    if runtime_reason in {
        _GITHUB_PUBLISHER_REASON_RUNTIME_CREDENTIAL_MISSING,
        _GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID,
        _GITHUB_PUBLISHER_REASON_RUNTIME_INTEGRATION_UNAVAILABLE,
        "github_auth_failed",
        "publisher_not_configured",
    }:
        return _DEPLOY_DISPATCH_SERVICE_REASON_RUNTIME_UNAVAILABLE
    if runtime_reason in {
        _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME,
        _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION,
        _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID,
    }:
        return runtime_reason
    if not target_valid:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_CONFIG_INVALID
    if not target_enabled:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_DISABLED

    normalized_failure_reason = _normalize_deploy_failure_reason_code(failure_reason_code)
    normalized_failure_stage = _normalize_deploy_failure_stage(failure_stage)
    if normalized_failure_reason in {
        _DEPLOY_TARGET_REASON_REPO_NOT_FOUND,
        _DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND,
        _DEPLOY_TARGET_REASON_REF_INVALID,
    }:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_METADATA_MISSING
    if normalized_failure_reason in {
        _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE,
        _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED,
        _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY,
    }:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_CONFIG_INVALID
    if normalized_failure_stage in {"repo_lookup", "ref_lookup", "workflow_lookup"}:
        return _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_METADATA_MISSING
    return _DEPLOY_DISPATCH_SERVICE_REASON_RUNTIME_UNAVAILABLE


def _derive_managed_gke_dispatch_readiness_message(*, dispatch_service_reason_code: object) -> str | None:
    normalized_dispatch_reason = _normalize_dispatch_service_reason_code(dispatch_service_reason_code)
    if normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME:
        return (
            "Admin action required: managed deploy target is missing required admin GKE cluster name "
            "configuration. Update MBSRN admin deployment settings."
        )
    if normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION:
        return (
            "Admin action required: managed deploy target is missing required admin GKE cluster location "
            "configuration. Update MBSRN admin deployment settings."
        )
    if normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID:
        return (
            "Admin action required: managed deploy target is missing required admin GKE project id "
            "configuration. Update MBSRN admin deployment settings."
        )
    return None


def _derive_managed_deploy_secret_readiness_message(*, reason_code: object) -> str:
    normalized_reason = _normalize_string(reason_code, max_length=80)
    if normalized_reason == _GITHUB_PUBLISHER_REASON_RUNTIME_CONFIG_INVALID:
        return (
            "Admin action required: managed deploy secret GCP_DEPLOY_KEY is configured but unreadable. "
            "Rotate it in MBSRN admin deployment settings."
        )
    return (
        "Admin action required: managed deploy secret GCP_DEPLOY_KEY is missing. "
        "Configure it in MBSRN admin deployment settings."
    )


def _derive_deploy_failure_remediation_hint(
    *,
    failure_reason: object,
    failure_stage: object,
    workflow_exists: object,
    dispatch_service_reason_code: object,
) -> str | None:
    normalized_reason = _normalize_deploy_failure_reason_code(failure_reason)
    normalized_stage = _normalize_deploy_failure_stage(failure_stage)
    normalized_dispatch_reason = _normalize_dispatch_service_reason_code(dispatch_service_reason_code)
    workflow_exists_bool = bool(workflow_exists) if isinstance(workflow_exists, bool) else None

    if normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_NAME:
        return (
            "Managed deploy target is missing required admin GKE cluster name configuration. "
            "Update MBSRN admin deployment settings."
        )
    if normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_CLUSTER_LOCATION:
        return (
            "Managed deploy target is missing required admin GKE cluster location configuration. "
            "Update MBSRN admin deployment settings."
        )
    if normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_MISSING_GCP_PROJECT_ID:
        return (
            "Managed deploy target is missing required admin GKE project id configuration. "
            "Update MBSRN admin deployment settings."
        )
    if (
        normalized_reason == _DEPLOY_TARGET_REASON_WORKFLOW_NOT_DISPATCHABLE
        and normalized_stage == "workflow_lookup"
        and workflow_exists_bool is True
    ):
        return "Selected workflow exists but is not dispatchable for this deploy target."
    if normalized_reason == _DEPLOY_TARGET_REASON_WORKFLOW_NOT_PRODUCTION_READY:
        return (
            "Selected workflow is scaffold-only and not production-ready. "
            "Replace it with a deploy-capable workflow that emits explicit deploy evidence."
        )
    if normalized_reason == _DEPLOY_TARGET_REASON_WORKFLOW_NOT_FOUND and normalized_stage == "workflow_lookup":
        return "Selected workflow file could not be found in the target repository/ref."
    if normalized_reason == _DEPLOY_TARGET_REASON_DISPATCH_UNSUPPORTED:
        return "Selected workflow does not support workflow_dispatch for this target."
    if (
        normalized_dispatch_reason == _DEPLOY_DISPATCH_SERVICE_REASON_TARGET_CONFIG_INVALID
        and normalized_stage == "workflow_lookup"
    ):
        return "Deploy target configuration resolved to a workflow or target that is not usable."
    return None


def _derive_workflow_run_failure_hint(
    *,
    failure_reason: object,
    post_dispatch_state: object,
) -> str | None:
    normalized_reason = _normalize_workflow_run_failure_reason_code(failure_reason)
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_GCP_AUTH:
        return "GCP authentication failed in the deploy workflow run."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_CLUSTER_CREDENTIALS:
        return "GKE credential acquisition failed in the deploy workflow run."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_MANIFEST_APPLY:
        return "Applying Kubernetes manifests failed in the deploy workflow run."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_ROLLOUT:
        return "Deployment rollout verification failed or timed out in the deploy workflow run."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_INGRESS_VERIFY:
        return "Service or ingress verification failed in the deploy workflow run."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_INGRESS_EVIDENCE:
        return "Ingress endpoint was not available before workflow evidence timeout."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_INVALID_STATE:
        return (
            "Cloud SQL proxy could not fetch an ephemeral certificate because the instance reported invalidState. "
            "Confirm Cloud SQL instance state is RUNNABLE and retry deploy."
        )
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_INSPECTION_FAILED:
        return (
            "Cloud SQL instance inspection failed before migration startup. "
            "Verify instance name/project/permissions and retry deploy."
        )
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_EPHEMERAL_CERT:
        return (
            "Cloud SQL proxy failed to fetch an ephemeral certificate during migration startup. "
            "Verify instance connectivity/permissions and retry deploy."
        )
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_CLOUDSQL_CONNECTION:
        return (
            "Cloud SQL proxy accepted startup but the migration connection to localhost closed unexpectedly. "
            "Verify Cloud SQL instance readiness and proxy logs before retry."
        )
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_TIMED_OUT:
        return "Deploy workflow run timed out before completion."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_CANCELLED:
        return "Deploy workflow run was cancelled before completion."
    if normalized_reason == _DEPLOY_RUN_FAILURE_REASON_GENERIC:
        return "Deploy workflow run failed before explicit live URL evidence was captured."
    normalized_post_state = _normalize_string(post_dispatch_state, max_length=80)
    if normalized_post_state == "workflow_run_succeeded_without_live_url":
        return "Workflow run succeeded but did not emit explicit live URL evidence."
    return None


def _resolve_publish_history_workflow_identity(
    *,
    history: object,
    artifact_version_id: str | None,
    repo_owner: str,
    repo_name: str,
    ref: str,
) -> tuple[str | None, str | None]:
    normalized_history = _normalize_history_list(history)
    artifact_id = str(artifact_version_id or "").strip()
    normalized_owner = str(repo_owner or "").strip()
    normalized_repo = str(repo_name or "").strip()
    normalized_ref = str(ref or "").strip()
    for item in reversed(normalized_history):
        if str(item.get("action") or "").strip().lower() != "publish":
            continue
        if str(item.get("status") or "").strip().lower() != "published":
            continue
        if _coerce_bool(item.get("dry_run"), default=False):
            continue
        if artifact_id and str(item.get("artifact_version_id") or "").strip() != artifact_id:
            continue
        if normalized_owner and str(item.get("repo_owner") or "").strip() != normalized_owner:
            continue
        if normalized_repo and str(item.get("repo_name") or "").strip() != normalized_repo:
            continue
        publish_branch = str(item.get("branch") or "").strip()
        if normalized_ref and publish_branch and publish_branch != normalized_ref:
            continue

        workflow_id = _normalize_workflow_id_for_deploy(item.get("deploy_workflow_id"))
        workflow_path: str | None = None
        if not workflow_id:
            workflow_path = _normalize_workflow_path_for_deploy(item.get("deploy_workflow_path"))
            workflow_id = _workflow_id_from_path_for_deploy(workflow_path)
        elif _normalize_workflow_path_for_deploy(item.get("deploy_workflow_path")):
            workflow_path = _normalize_workflow_path_for_deploy(item.get("deploy_workflow_path"))
        if workflow_id:
            return workflow_id, workflow_path
    return None, None


def _resolve_publish_history_expected_publish_url(
    *,
    history: object,
    artifact_version_id: str | None,
    repo_owner: str,
    repo_name: str,
    ref: str,
) -> tuple[str | None, str, str | None]:
    normalized_history = _normalize_history_list(history)
    artifact_id = str(artifact_version_id or "").strip()
    normalized_owner = str(repo_owner or "").strip()
    normalized_repo = str(repo_name or "").strip()
    normalized_ref = str(ref or "").strip()
    for item in reversed(normalized_history):
        if str(item.get("action") or "").strip().lower() != "publish":
            continue
        if str(item.get("status") or "").strip().lower() != "published":
            continue
        if _coerce_bool(item.get("dry_run"), default=False):
            continue
        if artifact_id and str(item.get("artifact_version_id") or "").strip() != artifact_id:
            continue
        if normalized_owner and str(item.get("repo_owner") or "").strip() != normalized_owner:
            continue
        if normalized_repo and str(item.get("repo_name") or "").strip() != normalized_repo:
            continue
        publish_branch = str(item.get("branch") or "").strip()
        if normalized_ref and publish_branch and publish_branch != normalized_ref:
            continue

        expected_publish_url = _normalize_url_candidate(item.get("expected_publish_url"))
        if expected_publish_url:
            return (
                expected_publish_url,
                _normalize_migration_url_source(item.get("url_source")),
                _normalize_string(item.get("url_source_detail"), max_length=120),
            )
    return None, _MIGRATION_URL_SOURCE_UNKNOWN, None


def _resolve_deploy_history_live_url(
    *,
    history: object,
    artifact_version_id: str | None,
    repo_owner: str,
    repo_name: str,
    ref: str,
) -> tuple[str | None, str, str | None]:
    normalized_history = _normalize_history_list(history)
    artifact_id = str(artifact_version_id or "").strip()
    normalized_owner = str(repo_owner or "").strip()
    normalized_repo = str(repo_name or "").strip()
    normalized_ref = str(ref or "").strip()
    for item in reversed(normalized_history):
        if str(item.get("action") or "").strip().lower() != "deploy":
            continue
        status = str(item.get("status") or "").strip().lower()
        if status not in {"deploy_requested", "deployed"}:
            continue
        if _coerce_bool(item.get("dry_run"), default=False):
            continue
        if artifact_id and str(item.get("artifact_version_id") or "").strip() != artifact_id:
            continue
        if normalized_owner and str(item.get("repo_owner") or "").strip() != normalized_owner:
            continue
        if normalized_repo and str(item.get("repo_name") or "").strip() != normalized_repo:
            continue
        if normalized_ref and str(item.get("ref") or "").strip() != normalized_ref:
            continue

        resolved_live_url = _normalize_url_candidate(item.get("resolved_live_url"))
        if not resolved_live_url:
            resolved_live_url = _normalize_url_candidate(item.get("active_url"))
        if resolved_live_url:
            return (
                resolved_live_url,
                _normalize_migration_url_source(item.get("url_source")),
                _normalize_string(item.get("url_source_detail"), max_length=120),
            )
    return None, _MIGRATION_URL_SOURCE_UNKNOWN, None


def _derive_site_specific_workflow_id_for_repo_name(repo_name: object) -> str | None:
    normalized_repo_name = _normalize_string(repo_name, max_length=120)
    if not normalized_repo_name:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", normalized_repo_name.lower()).strip("-")
    if not slug:
        return None
    for suffix in ("-site", "-website"):
        if slug.endswith(suffix) and len(slug) > len(suffix):
            slug = slug[: -len(suffix)].rstrip("-")
            break
    if not slug:
        return None
    return _normalize_workflow_id_for_deploy(f"deploy-{slug}-www-prod.yml")


def _safe_derive_kubernetes_namespace_for_summary(
    *,
    repo_name: object,
    site_id: object | None = None,
) -> tuple[str | None, str | None]:
    try:
        namespace, source = derive_site_kubernetes_namespace(
            repo_name=repo_name,
            site_id=site_id,
        )
    except (SEOMigrationGitHubPublisherError, ValueError):
        return None, None
    normalized_namespace = _normalize_string(namespace, max_length=63)
    normalized_source = _normalize_string(source, max_length=60)
    return normalized_namespace, normalized_source


def _normalize_workflow_id_for_deploy(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=160)
    if not normalized:
        return None
    if not _VALID_WORKFLOW_ID_PATTERN.fullmatch(normalized) or ".." in normalized:
        return None
    if _has_reserved_git_segment(normalized):
        return None
    return normalized


def _normalize_workflow_path_for_deploy(value: object) -> str | None:
    normalized = _normalize_string(value, max_length=240)
    if not normalized:
        return None
    candidate = normalized.replace("\\", "/").lstrip("/")
    if not candidate.lower().startswith(".github/workflows/"):
        return None
    if ".." in candidate:
        return None
    return candidate


def _workflow_id_from_path_for_deploy(path: str | None) -> str | None:
    normalized_path = _normalize_workflow_path_for_deploy(path)
    if not normalized_path:
        return None
    workflow_id = normalized_path.split("/", 2)[-1].strip()
    return _normalize_workflow_id_for_deploy(workflow_id)


def _canonical_dispatch_workflow_identifier(value: object) -> str | None:
    normalized_path = _normalize_workflow_path_for_deploy(value)
    if normalized_path:
        return normalized_path
    normalized_workflow_id = _normalize_workflow_id_for_deploy(value)
    if normalized_workflow_id:
        return _normalize_workflow_path_for_deploy(f".github/workflows/{normalized_workflow_id}")
    return _normalize_string(value, max_length=200)


def _collect_canonical_workflow_identifiers(values: list[object]) -> set[str]:
    normalized: set[str] = set()
    for candidate in values:
        canonical = _canonical_dispatch_workflow_identifier(candidate)
        if canonical:
            normalized.add(canonical)
    return normalized


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


def _history_references_artifact(*, history: object, artifact_version_id: str, action: str) -> bool:
    artifact_id = str(artifact_version_id or "").strip()
    expected_action = str(action or "").strip().lower()
    if not artifact_id or not expected_action:
        return False
    normalized = _normalize_history_list(history)
    for item in normalized:
        if str(item.get("action") or "").strip().lower() != expected_action:
            continue
        if str(item.get("artifact_version_id") or "").strip() != artifact_id:
            continue
        return True
    return False


def _find_latest_deploy_history_index_for_refresh(
    *, history: list[dict[str, object]], artifact_version_id: str
) -> int | None:
    artifact_id = str(artifact_version_id or "").strip()
    if not artifact_id:
        return None
    for index in range(len(history) - 1, -1, -1):
        item = _normalize_json_dict(history[index])
        if str(item.get("action") or "").strip().lower() != "deploy":
            continue
        if _coerce_bool(item.get("dry_run"), default=False):
            continue
        if str(item.get("artifact_version_id") or "").strip() != artifact_id:
            continue
        return index
    return None


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


def _find_active_duplicate_deploy_attempt(
    *,
    history: object,
    artifact_version_id: str,
    target: dict[str, object],
) -> tuple[dict[str, object] | None, dict[str, object] | None, dict[str, object] | None]:
    normalized = _normalize_history_list(history)
    expected_inputs = _normalize_history_inputs(target.get("inputs"))
    target_workflow_identifiers = _collect_canonical_workflow_identifiers(
        [
            target.get("workflow_identifier_requested"),
            target.get("workflow_id"),
            target.get("workflow_path"),
            target.get("workflow_file_path"),
            target.get("workflow_identifier_used"),
            target.get("actual_dispatch_identifier_sent"),
        ]
    )
    now = utc_now()
    stale_unverified_record: dict[str, object] | None = None
    stale_active_record: dict[str, object] | None = None
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
        item_workflow_identifiers = _collect_canonical_workflow_identifiers(
            [
                item.get("configured_workflow_id"),
                item.get("workflow_identifier_requested"),
                item.get("workflow_id"),
                item.get("workflow_identifier_used"),
                item.get("actual_dispatch_identifier_sent"),
                item.get("workflow_path"),
                item.get("workflow_file_path"),
            ]
        )
        if not item_workflow_identifiers or not target_workflow_identifiers:
            continue
        if item_workflow_identifiers.isdisjoint(target_workflow_identifiers):
            continue
        if str(item.get("ref") or "").strip() != str(target.get("ref") or "").strip():
            continue
        if _normalize_history_inputs(item.get("inputs")) != expected_inputs:
            continue
        if _is_active_duplicate_deploy_history_entry(item=item, now=now):
            return item, stale_unverified_record, stale_active_record
        if (
            stale_unverified_record is None
            and _is_unverified_dispatch_history_entry(item=item)
            and _is_deploy_history_entry_stale(
                item=item,
                now=now,
                stale_after_seconds=_DUPLICATE_DEPLOY_UNVERIFIED_DISPATCH_STALE_SECONDS,
            )
        ):
            stale_unverified_record = item
        if (
            stale_active_record is None
            and _is_confirmed_active_run_history_entry(item=item)
            and _is_deploy_history_entry_stale(
                item=item,
                now=now,
                stale_after_seconds=_DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS,
            )
        ):
            stale_active_record = item
    return None, stale_unverified_record, stale_active_record


def _is_active_duplicate_deploy_history_entry(
    *,
    item: dict[str, object],
    now: datetime,
) -> bool:
    workflow_run_id = _coerce_int(item.get("workflow_run_id"))
    dispatch_attempted = _coerce_bool(item.get("dispatch_attempted"), default=False)
    workflow_run_lookup_attempted = (
        bool(item.get("workflow_run_lookup_attempted"))
        if isinstance(item.get("workflow_run_lookup_attempted"), bool)
        else None
    )
    workflow_run_found = (
        bool(item.get("workflow_run_found")) if isinstance(item.get("workflow_run_found"), bool) else None
    )
    post_dispatch_state = _normalize_string(item.get("post_dispatch_state"), max_length=80) or _derive_post_dispatch_state(
        dispatch_attempted=dispatch_attempted,
        dispatch_result_stage=item.get("dispatch_result_stage"),
        workflow_run_id=workflow_run_id,
        workflow_run_status=item.get("workflow_run_status"),
        workflow_run_conclusion=item.get("workflow_run_conclusion"),
        resolved_live_url=item.get("resolved_live_url"),
        workflow_run_lookup_attempted=workflow_run_lookup_attempted,
        workflow_run_found=workflow_run_found,
    )

    terminal_states = {
        "dispatch_not_attempted",
        "workflow_run_failed",
        "workflow_run_completed",
        "workflow_run_succeeded_without_live_url",
        "workflow_run_succeeded_with_live_url",
    }
    if post_dispatch_state in terminal_states:
        return False
    if post_dispatch_state.startswith("dispatch_blocked_"):
        return False

    workflow_run_status = (_normalize_string(item.get("workflow_run_status"), max_length=40) or "").strip().lower()
    if workflow_run_id is not None and workflow_run_status in {"queued", "waiting", "requested", "pending", "in_progress", "running"}:
        return _is_deploy_history_entry_fresh(
            item=item,
            now=now,
            stale_after_seconds=_DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS,
        )
    if workflow_run_id is not None and post_dispatch_state in {
        "workflow_run_pending",
        "workflow_run_in_progress",
        "workflow_run_observed",
    }:
        return _is_deploy_history_entry_fresh(
            item=item,
            now=now,
            stale_after_seconds=_DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS,
        )
    if workflow_run_status == "completed":
        return False

    if workflow_run_id is not None:
        # A run id with unknown/non-terminal status still requires active freshness evidence.
        return _is_deploy_history_entry_fresh(
            item=item,
            now=now,
            stale_after_seconds=_DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS,
        )

    if _is_unverified_dispatch_history_entry(item=item):
        reference_field, reference_at = _resolve_deploy_history_activity_reference(item=item)
        if reference_field is None or reference_at is None:
            # Do not let legacy/untracked records without activity timestamps block retries forever.
            return False
        age_seconds = (now - reference_at).total_seconds()
        return age_seconds < float(_DUPLICATE_DEPLOY_UNVERIFIED_DISPATCH_STALE_SECONDS)
    return False


def _is_unverified_dispatch_history_entry(*, item: dict[str, object]) -> bool:
    workflow_run_id = _coerce_int(item.get("workflow_run_id"))
    if workflow_run_id is not None:
        return False
    dispatch_attempted = _coerce_bool(item.get("dispatch_attempted"), default=False)
    if not dispatch_attempted:
        return False
    workflow_run_lookup_attempted = (
        bool(item.get("workflow_run_lookup_attempted"))
        if isinstance(item.get("workflow_run_lookup_attempted"), bool)
        else None
    )
    workflow_run_found = (
        bool(item.get("workflow_run_found")) if isinstance(item.get("workflow_run_found"), bool) else None
    )
    post_dispatch_state = _normalize_string(item.get("post_dispatch_state"), max_length=80) or _derive_post_dispatch_state(
        dispatch_attempted=dispatch_attempted,
        dispatch_result_stage=item.get("dispatch_result_stage"),
        workflow_run_id=workflow_run_id,
        workflow_run_status=item.get("workflow_run_status"),
        workflow_run_conclusion=item.get("workflow_run_conclusion"),
        resolved_live_url=item.get("resolved_live_url"),
        workflow_run_lookup_attempted=workflow_run_lookup_attempted,
        workflow_run_found=workflow_run_found,
    )
    if post_dispatch_state.startswith("dispatch_blocked_"):
        return False
    if post_dispatch_state in {
        "dispatch_not_attempted",
        "workflow_run_failed",
        "workflow_run_completed",
        "workflow_run_succeeded_without_live_url",
        "workflow_run_succeeded_with_live_url",
    }:
        return False
    return post_dispatch_state in {
        "dispatch_accepted_no_run",
        "dispatch_unverified_no_run",
        "workflow_run_pending",
        "workflow_run_in_progress",
        "workflow_run_observed",
    }


def _is_confirmed_active_run_history_entry(*, item: dict[str, object]) -> bool:
    workflow_run_id = _coerce_int(item.get("workflow_run_id"))
    if workflow_run_id is None:
        return False
    dispatch_attempted = _coerce_bool(item.get("dispatch_attempted"), default=False)
    workflow_run_lookup_attempted = (
        bool(item.get("workflow_run_lookup_attempted"))
        if isinstance(item.get("workflow_run_lookup_attempted"), bool)
        else None
    )
    workflow_run_found = (
        bool(item.get("workflow_run_found")) if isinstance(item.get("workflow_run_found"), bool) else None
    )
    post_dispatch_state = _normalize_string(item.get("post_dispatch_state"), max_length=80) or _derive_post_dispatch_state(
        dispatch_attempted=dispatch_attempted,
        dispatch_result_stage=item.get("dispatch_result_stage"),
        workflow_run_id=workflow_run_id,
        workflow_run_status=item.get("workflow_run_status"),
        workflow_run_conclusion=item.get("workflow_run_conclusion"),
        resolved_live_url=item.get("resolved_live_url"),
        workflow_run_lookup_attempted=workflow_run_lookup_attempted,
        workflow_run_found=workflow_run_found,
    )
    if post_dispatch_state.startswith("dispatch_blocked_"):
        return False
    if post_dispatch_state in {
        "dispatch_not_attempted",
        "workflow_run_failed",
        "workflow_run_completed",
        "workflow_run_succeeded_without_live_url",
        "workflow_run_succeeded_with_live_url",
    }:
        return False
    workflow_run_status = (_normalize_string(item.get("workflow_run_status"), max_length=40) or "").strip().lower()
    if workflow_run_status == "completed":
        return False
    return True


def _derive_duplicate_blocker_stale_threshold_seconds(*, item: dict[str, object]) -> int:
    if _is_unverified_dispatch_history_entry(item=item):
        return _DUPLICATE_DEPLOY_UNVERIFIED_DISPATCH_STALE_SECONDS
    return _DUPLICATE_DEPLOY_ACTIVE_BLOCKER_STALE_SECONDS


def _is_deploy_history_entry_fresh(
    *,
    item: dict[str, object],
    now: datetime,
    stale_after_seconds: int,
) -> bool:
    _, latest_activity = _resolve_deploy_history_activity_reference(item=item)
    if latest_activity is None:
        return False
    age_seconds = (now - latest_activity).total_seconds()
    return age_seconds < float(stale_after_seconds)


def _is_deploy_history_entry_stale(
    *,
    item: dict[str, object],
    now: datetime,
    stale_after_seconds: int,
) -> bool:
    _, latest_activity = _resolve_deploy_history_activity_reference(item=item)
    if latest_activity is None:
        return False
    age_seconds = (now - latest_activity).total_seconds()
    return age_seconds >= float(stale_after_seconds)


def _latest_deploy_history_activity_at(*, item: dict[str, object]) -> datetime | None:
    _, activity_at = _resolve_deploy_history_activity_reference(item=item)
    return activity_at


def _resolve_deploy_history_activity_reference(
    *,
    item: dict[str, object],
) -> tuple[str | None, datetime | None]:
    candidates: list[tuple[str, datetime]] = []
    for field_name in ("refreshed_at", "dispatched_at", "occurred_at", "timestamp"):
        parsed = _parse_iso8601_datetime(item.get(field_name))
        if parsed is not None:
            candidates.append((field_name, parsed))
    if not candidates:
        return None, None
    # Use the newest known activity timestamp to keep stale classification deterministic
    # across refresh/dispatch/history-write paths.
    return max(candidates, key=lambda candidate: candidate[1])


def _build_deploy_history_stale_observability(
    *,
    item: dict[str, object],
    now: datetime,
    stale_after_seconds: int,
) -> dict[str, object]:
    reference_field, reference_at = _resolve_deploy_history_activity_reference(item=item)
    if reference_at is None:
        return {
            "blocking_stale_reference_field": reference_field,
            "blocking_stale_reference_at": None,
            "blocking_stale_age_seconds": None,
            "blocking_stale_threshold_seconds": stale_after_seconds,
            "blocking_stale_evaluated": False,
            "blocking_stale_is_stale": None,
        }
    age_seconds = max(0, int((now - reference_at).total_seconds()))
    return {
        "blocking_stale_reference_field": reference_field,
        "blocking_stale_reference_at": reference_at.isoformat(),
        "blocking_stale_age_seconds": age_seconds,
        "blocking_stale_threshold_seconds": stale_after_seconds,
        "blocking_stale_evaluated": True,
        "blocking_stale_is_stale": age_seconds >= int(stale_after_seconds),
    }


def _parse_iso8601_datetime(value: object) -> datetime | None:
    normalized = _normalize_string(value, max_length=64)
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_active_duplicate_deploy_message(
    *,
    post_dispatch_state: str | None,
    dispatch_result_stage: str | None,
) -> str:
    normalized_state = _normalize_string(post_dispatch_state, max_length=80)
    if normalized_state in {"dispatch_accepted_no_run", "dispatch_unverified_no_run"}:
        return (
            "A deploy request for this artifact and target is already in progress "
            "(dispatch is unverified; workflow run evidence pending). "
            "Refresh deploy status and retry after the prior attempt reaches a terminal state."
        )
    if normalized_state in {"workflow_run_pending", "workflow_run_in_progress"}:
        return (
            "A deploy request for this artifact and target is already in progress. "
            "Refresh deploy status and retry after the prior attempt reaches a terminal state."
        )
    return (
        "A deploy request for this artifact and target is already active. "
        "Refresh deploy status and retry after the prior attempt reaches a terminal state."
    )


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
    raw_value = str(value).strip()
    if not raw_value:
        return None
    normalized = raw_value.replace("\\", "/")
    parsed_url = urlsplit(normalized)
    if parsed_url.scheme in {"http", "https"} and parsed_url.netloc:
        normalized = parsed_url.path.strip()
    if not normalized:
        return None
    if "?" in normalized:
        normalized = normalized.split("?", 1)[0]
    if "#" in normalized:
        normalized = normalized.split("#", 1)[0]
    normalized = normalized.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.lstrip("/")
    if not normalized:
        return None
    if "//" in normalized:
        while "//" in normalized:
            normalized = normalized.replace("//", "/")
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


def _normalize_string_list(value: object, *, max_items: int = 10, max_item_length: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized_items: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = _normalize_string(item, max_length=max_item_length)
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized_items.append(normalized)
        if len(normalized_items) >= max_items:
            break
    return normalized_items


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


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    normalized = str(value).strip()
    if not normalized:
        return None
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return None


def _normalize_migration_url_source(value: object) -> str:
    normalized = _normalize_string(value, max_length=80)
    if not normalized:
        return _MIGRATION_URL_SOURCE_UNKNOWN
    normalized_lower = normalized.lower()
    if normalized_lower in {
        _MIGRATION_URL_SOURCE_DETERMINISTIC_TARGET_CONFIG,
        _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT,
        _MIGRATION_URL_SOURCE_DEPLOY_RESULT,
    }:
        return normalized_lower
    return _MIGRATION_URL_SOURCE_UNKNOWN


def _confirmed_live_url_source_rank(source: object) -> int:
    normalized = _normalize_migration_url_source(source)
    if normalized == _MIGRATION_URL_SOURCE_DEPLOY_RESULT:
        return 2
    if normalized == _MIGRATION_URL_SOURCE_WORKFLOW_OUTPUT:
        return 1
    return 0


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
