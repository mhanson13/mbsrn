from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.seo_recommendation import SEORecommendationGA4OutcomeSnapshotRead


_GA_MEASUREMENT_ID_PATTERN = re.compile(r"^G-[A-Z0-9]{4,32}$")


def _normalize_optional_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _normalize_string_list(value: object, *, max_items: int, max_item_length: int) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _normalize_optional_text(item, max_length=max_item_length)
        if text is None:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= max_items:
            break
    return normalized


def _normalize_ga_measurement_id(value: object) -> str | None:
    normalized = _normalize_optional_text(value, max_length=40)
    if normalized is None:
        return None
    normalized = normalized.upper()
    if not _GA_MEASUREMENT_ID_PATTERN.fullmatch(normalized):
        raise ValueError("ga_measurement_id must use GA4 format (for example G-ABCD1234).")
    return normalized


class SEOMigrationOperatorRequirements(BaseModel):
    business_objectives: list[str] = Field(default_factory=list)
    requested_pages: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    tone_preferences: list[str] = Field(default_factory=list)
    calls_to_action: list[str] = Field(default_factory=list)
    additional_notes: str | None = None

    @field_validator(
        "business_objectives",
        "requested_pages",
        "must_include",
        "must_avoid",
        "tone_preferences",
        "calls_to_action",
        mode="before",
    )
    @classmethod
    def _normalize_lists(cls, value: object) -> list[str]:
        return _normalize_string_list(value, max_items=20, max_item_length=220)

    @field_validator("additional_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=5000)


class SEOMigrationEnrichedContentNotes(BaseModel):
    replacement_summary: str | None = None
    homepage_value_proposition: str | None = None
    about_business: str | None = None
    service_highlights: list[str] = Field(default_factory=list)
    trust_signals: list[str] = Field(default_factory=list)
    faq_items: list[str] = Field(default_factory=list)
    contact_overrides: dict[str, str] = Field(default_factory=dict)
    additional_notes: str | None = None

    @field_validator(
        "replacement_summary",
        "homepage_value_proposition",
        "about_business",
        "additional_notes",
        mode="before",
    )
    @classmethod
    def _normalize_long_text(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=6000)

    @field_validator("service_highlights", "trust_signals", "faq_items", mode="before")
    @classmethod
    def _normalize_lists(cls, value: object) -> list[str]:
        return _normalize_string_list(value, max_items=30, max_item_length=240)

    @field_validator("contact_overrides", mode="before")
    @classmethod
    def _normalize_contact_overrides(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = _normalize_optional_text(raw_key, max_length=64)
            val = _normalize_optional_text(raw_value, max_length=240)
            if key is None or val is None:
                continue
            normalized[key] = val
            if len(normalized) >= 24:
                break
        return normalized


class SEOMigrationPublishConfig(BaseModel):
    enabled: bool = False
    repo_owner: str | None = Field(default=None, max_length=80)
    repo_name: str | None = Field(default=None, max_length=120)
    branch: str | None = Field(default=None, max_length=120)
    artifact_root: str | None = Field(default="", max_length=120)

    @field_validator("repo_owner", "repo_name", "branch", "artifact_root", mode="before")
    @classmethod
    def _normalize_paths(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=120)


class SEOMigrationDeployConfig(BaseModel):
    enabled: bool = False
    repo_owner: str | None = Field(default=None, max_length=80)
    repo_name: str | None = Field(default=None, max_length=120)
    workflow_id: str | None = Field(default="deploy-www-prod.yml", max_length=160)
    ref: str | None = Field(default="main", max_length=120)
    inputs: dict[str, str] = Field(default_factory=dict)

    @field_validator("repo_owner", "repo_name", "workflow_id", "ref", mode="before")
    @classmethod
    def _normalize_fields(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=160)

    @field_validator("inputs", mode="before")
    @classmethod
    def _normalize_inputs(cls, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: dict[str, str] = {}
        for raw_key, raw_value in value.items():
            key = _normalize_optional_text(raw_key, max_length=80)
            val = _normalize_optional_text(raw_value, max_length=240)
            if key is None or val is None:
                continue
            normalized[key] = val
            if len(normalized) >= 20:
                break
        return normalized


class SEOMigrationAnalyticsConfig(BaseModel):
    enabled: bool = True
    ga_measurement_id: str | None = None
    insertion_mode: str = "publish_and_deploy"

    @field_validator("ga_measurement_id", mode="before")
    @classmethod
    def _normalize_ga_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalize_ga_measurement_id(value)

    @field_validator("insertion_mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=40) or "publish_and_deploy"
        if normalized not in {"publish_only", "publish_and_deploy"}:
            raise ValueError("insertion_mode must be 'publish_only' or 'publish_and_deploy'.")
        return normalized


class SEOMigrationWorkspaceCreateOrUpdateRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=2048)
    operator_requirements: SEOMigrationOperatorRequirements | None = None
    enriched_content_notes: SEOMigrationEnrichedContentNotes | None = None
    publish_config: SEOMigrationPublishConfig | None = None
    deploy_config: SEOMigrationDeployConfig | None = None
    analytics_config: SEOMigrationAnalyticsConfig | None = None

    @field_validator("source_url", mode="before")
    @classmethod
    def _normalize_source_url(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=2048)
        if normalized is None:
            return None
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("source_url must use http or https")
        return normalized


class SEOMigrationSourceIngestRequest(BaseModel):
    source_url: str | None = Field(default=None, max_length=2048)

    @field_validator("source_url", mode="before")
    @classmethod
    def _normalize_source_url(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=2048)
        if normalized is None:
            return None
        if not (normalized.startswith("http://") or normalized.startswith("https://")):
            raise ValueError("source_url must use http or https")
        return normalized


class SEOMigrationRequirementsUpdateRequest(BaseModel):
    operator_requirements: SEOMigrationOperatorRequirements


class SEOMigrationRequirementsSuggestionRequest(BaseModel):
    field: str
    current_value: str | list[str] | None = None
    force_refresh: bool = False

    @field_validator("field", mode="before")
    @classmethod
    def _normalize_field(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=80)
        return (normalized or "").lower()

    @field_validator("current_value", mode="before")
    @classmethod
    def _normalize_current_value(cls, value: object) -> str | list[str] | None:
        if isinstance(value, list):
            return _normalize_string_list(value, max_items=20, max_item_length=240)
        return _normalize_optional_text(value, max_length=5000)


class SEOMigrationEnrichedContentUpdateRequest(BaseModel):
    enriched_content_notes: SEOMigrationEnrichedContentNotes


class SEOMigrationPublishConfigUpdateRequest(BaseModel):
    publish_config: SEOMigrationPublishConfig


class SEOMigrationDeployConfigUpdateRequest(BaseModel):
    deploy_config: SEOMigrationDeployConfig


class SEOMigrationAnalyticsConfigUpdateRequest(BaseModel):
    analytics_config: SEOMigrationAnalyticsConfig


class SEOMigrationDraftGenerateRequest(BaseModel):
    force_new_version: bool = False


class SEOMigrationDraftGenerationDiagnosticContext(BaseModel):
    failure_category: str | None = None
    failure_reason: str | None = None
    correlation_id: str | None = None
    workspace_id: str | None = None
    artifact_version_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    timeout_source: str | None = None


class SEOMigrationDraftGenerationErrorDetailRead(BaseModel):
    message: str
    reason_code: str
    error_code: str
    retryable: bool
    operator_action: str
    reconnect_target: str | None = None
    diagnostic_context: SEOMigrationDraftGenerationDiagnosticContext | None = None
    failure_category: str | None = None
    failure_reason: str | None = None
    correlation_id: str | None = None
    workspace_id: str | None = None
    artifact_version_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    timeout_source: str | None = None


class SEOMigrationDraftGenerationErrorEnvelopeRead(BaseModel):
    detail: SEOMigrationDraftGenerationErrorDetailRead


class SEOMigrationDraftReadinessRead(BaseModel):
    ready: bool
    blocking_reason_codes: list[str] = Field(default_factory=list)
    warning_reason_codes: list[str] = Field(default_factory=list)
    app_auth_ready: bool = True
    google_integration_ready: bool | None = None
    google_reconnect_required: bool = False
    live_google_data_required: bool = False
    draft_context_ready: bool = False
    recommendations_available_count: int = Field(default=0, ge=0)
    competitor_profiles_available_count: int = Field(default=0, ge=0)
    selected_media_assets_count: int = Field(default=0, ge=0)
    source_site_images_discovered_count: int = Field(default=0, ge=0)
    media_required_by_operator: bool = False
    media_requirement_sources: list[str] = Field(default_factory=list)
    usable_media_assets_count: int = Field(default=0, ge=0)
    useful_discovered_images_count: int = Field(default=0, ge=0)
    low_value_discovered_images_count: int = Field(default=0, ge=0)
    rejected_discovered_images_count: int = Field(default=0, ge=0)
    selected_usable_media_assets_count: int = Field(default=0, ge=0)
    media_requirement_satisfied: bool = True
    media_requirement_warning_reason: str | None = None
    operator_action: str


class SEOMigrationRequirementsSuggestionRead(BaseModel):
    field: str
    suggestion_status: str
    suggested_value: str | list[str] | None = None
    reason_code: str
    context_sources_used: list[str] = Field(default_factory=list)
    retryable: bool = False
    generated_at: str | None = None


class SEOMigrationMediaAssetUpdateRequest(BaseModel):
    selected_for_draft: bool | None = None
    apply_suggested_metadata: bool | None = None
    category: str | None = Field(default=None, max_length=64)
    alt_text: str | None = Field(default=None, max_length=240)
    description: str | None = Field(default=None, max_length=800)
    usage_note: str | None = Field(default=None, max_length=400)
    page_assignment: str | None = Field(default=None, max_length=120)

    @field_validator(
        "category",
        "alt_text",
        "description",
        "usage_note",
        "page_assignment",
        mode="before",
    )
    @classmethod
    def _normalize_optional_fields(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalize_optional_text(value, max_length=800)


class SEOMigrationMediaAssetLifecycleRequest(BaseModel):
    action: Literal["remove", "ignore"]


class SEOMigrationMediaSuggestionBatchRequest(BaseModel):
    asset_ids: list[str] = Field(default_factory=list)
    force_refresh: bool = False

    @field_validator("asset_ids", mode="before")
    @classmethod
    def _normalize_asset_ids(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            asset_id = _normalize_optional_text(item, max_length=80)
            if asset_id is None:
                continue
            key = asset_id.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(asset_id)
        return normalized


class SEOMigrationDiscoveredMediaImportRequest(BaseModel):
    discovered_image_ids: list[str] = Field(default_factory=list)
    normalized_urls: list[str] = Field(default_factory=list)
    selected_for_draft: bool | None = None
    allow_quality_override: bool = False

    @field_validator("discovered_image_ids", mode="before")
    @classmethod
    def _normalize_discovered_image_ids(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            asset_id = _normalize_optional_text(item, max_length=80)
            if asset_id is None:
                continue
            lowered = asset_id.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(asset_id)
        return normalized

    @field_validator("normalized_urls", mode="before")
    @classmethod
    def _normalize_discovered_urls(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            url_value = _normalize_optional_text(item, max_length=2048)
            if url_value is None:
                continue
            lowered = url_value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(url_value)
        return normalized


class SEOMigrationArtifactApproveRequest(BaseModel):
    approval_notes: str | None = Field(default=None, max_length=1200)

    @field_validator("approval_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=1200)


class SEOMigrationPublishRequest(BaseModel):
    artifact_version_id: str = Field(min_length=1, max_length=36)
    dry_run: bool = False
    commit_message: str | None = Field(default=None, max_length=180)
    analytics_measurement_id: str | None = Field(default=None, max_length=40)

    @field_validator("commit_message", mode="before")
    @classmethod
    def _normalize_commit_message(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=180)

    @field_validator("analytics_measurement_id", mode="before")
    @classmethod
    def _normalize_ga_id(cls, value: object) -> str | None:
        if value is None:
            return None
        return _normalize_ga_measurement_id(value)


class SEOMigrationDeployRequest(BaseModel):
    artifact_version_id: str = Field(min_length=1, max_length=36)
    dry_run: bool = False
    replace_existing_runtime: bool = False


class SEOMigrationDeployStatusRefreshRequest(BaseModel):
    artifact_version_id: str = Field(min_length=1, max_length=36)


class SEOMigrationSourceSnapshotRead(BaseModel):
    fetched_at: str | None = None
    final_url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    title: str | None = None
    meta_description: str | None = None
    canonical_url: str | None = None
    headings: list[str] = Field(default_factory=list)
    contact_signals: list[str] = Field(default_factory=list)
    phone_numbers: list[str] = Field(default_factory=list)
    emails: list[str] = Field(default_factory=list)
    addresses: list[str] = Field(default_factory=list)
    internal_links: list[str] = Field(default_factory=list)
    service_blocks: list[str] = Field(default_factory=list)
    pages_scanned_count: int = 0
    pages_scanned: list[str] = Field(default_factory=list)
    asset_references: dict[str, list[str]] = Field(default_factory=dict)
    discovered_images: list[dict[str, object]] = Field(default_factory=list)
    cleaned_text_blocks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SEOMigrationMediaMetadataSuggestionRead(BaseModel):
    suggested_category: str | None = None
    suggested_alt_text: str | None = None
    suggested_description: str | None = None
    suggested_usage_note: str | None = None
    suggested_page_assignment: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    suggestion_source: str | None = None
    suggestion_status: str | None = None
    reason_code: str | None = None
    generated_at: str | None = None


class SEOMigrationArtifactFileRead(BaseModel):
    path: str
    media_type: str
    size_bytes: int
    content: str | None = None


class SEOMigrationMediaAssetRead(BaseModel):
    asset_id: str | None = None
    artifact_path: str | None = None
    display_filename: str | None = None
    content_type: str | None = None
    fetch_status: str | None = None
    validation_checked_at: str | None = None
    size_bytes: int | None = None
    width: int | None = None
    height: int | None = None
    provenance: str | None = None
    selected_for_draft: bool = False
    import_status: str | None = None
    category: str | None = None
    alt_text: str | None = None
    description: str | None = None
    usage_note: str | None = None
    page_assignment: str | None = None
    normalized_url: str | None = None
    source_page_url: str | None = None
    preview_url: str | None = None
    created_at: str | None = None
    workspace_status: str | None = None
    metadata_suggestion: SEOMigrationMediaMetadataSuggestionRead | None = None
    metadata_suggestion_applied: bool = False
    metadata_suggestion_applied_at: str | None = None
    candidate_quality: str | None = None
    quality_reason: str | None = None


class SEOMigrationMediaAssetListRead(BaseModel):
    source_discovered: list[SEOMigrationMediaAssetRead] = Field(default_factory=list)
    operator_uploaded: list[SEOMigrationMediaAssetRead] = Field(default_factory=list)
    selected_assets: list[SEOMigrationMediaAssetRead] = Field(default_factory=list)
    source_discovered_count: int = 0
    pages_scanned_count: int = 0
    source_imported_count: int = 0
    operator_uploaded_count: int = 0
    selected_assets_count: int = 0
    media_asset_categories: list[str] = Field(default_factory=list)
    selected_assets_trimmed: bool = False
    diagnostics: list[str] = Field(default_factory=list)


class SEOMigrationMediaSuggestionBatchResultRead(BaseModel):
    asset_id: str
    suggestion_status: str
    reason_code: str | None = None
    retryable: bool = False
    metadata_suggestion: SEOMigrationMediaMetadataSuggestionRead | None = None


class SEOMigrationMediaSuggestionBatchRead(BaseModel):
    batch_status: str
    results: list[SEOMigrationMediaSuggestionBatchResultRead] = Field(default_factory=list)
    completed_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)


class SEOMigrationDiscoveredMediaImportResultRead(BaseModel):
    asset_id: str | None = None
    normalized_url: str | None = None
    status: str
    reason_code: str | None = None
    media_asset: SEOMigrationMediaAssetRead | None = None


class SEOMigrationDiscoveredMediaImportRead(BaseModel):
    batch_status: str
    results: list[SEOMigrationDiscoveredMediaImportResultRead] = Field(default_factory=list)
    imported_count: int = Field(default=0, ge=0)
    failed_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    disabled_count: int = Field(default=0, ge=0)


class SEOMigrationMediaAssetLifecycleActionRead(BaseModel):
    asset_id: str | None = None
    status: str
    reason_code: str | None = None
    media_asset: SEOMigrationMediaAssetRead | None = None


class SEOMigrationArtifactVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    workspace_id: str
    version: int
    status: str
    strategy_summary: str | None
    page_map_json: list[dict[str, object]] | None = None
    homepage_structure_json: list[dict[str, object]] | None = None
    service_page_suggestions_json: list[dict[str, object]] | None = None
    cta_contact_structure_json: dict[str, object] | None = None
    seo_meta_suggestions_json: dict[str, object] | None = None
    redirect_suggestions_json: list[dict[str, object]] | None = None
    analytics_placeholders_json: list[dict[str, object]] | None = None
    generated_files_json: list[dict[str, object]] | None = None
    artifact_quality_evaluation: dict[str, object] | None = None
    artifact_quality_evaluation_json: dict[str, object] | None = None
    file_count: int
    total_bytes: int
    provider_name: str
    model_name: str
    prompt_version: str
    parse_warnings_json: list[str] | None = None
    error_summary: str | None = None
    approval_status: str
    approved_by_principal_id: str | None = None
    approved_at: datetime | None = None
    approval_notes: str | None = None
    publish_status: str
    deploy_status: str
    last_published_commit_sha: str | None = None
    last_published_at: datetime | None = None
    last_publish_error_summary: str | None = None
    last_deployed_at: datetime | None = None
    last_deploy_error_summary: str | None = None
    created_by_principal_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SEOMigrationArtifactVersionListResponse(BaseModel):
    items: list[SEOMigrationArtifactVersionRead]
    total: int


class SEOMigrationPromptPreviewRead(BaseModel):
    provider_name: str
    model_name: str
    prompt_version: str
    context_json: dict[str, object]
    system_prompt: str
    user_prompt: str


class SEOMigrationWorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    business_id: str
    site_id: str
    source_url: str | None = None
    source_site_status: str
    migration_status: str
    operator_requirements_json: dict[str, object] | None = None
    enriched_content_notes_json: dict[str, object] | None = None
    brand_business_facts_snapshot_json: dict[str, object] | None = None
    imported_source_snapshot_json: dict[str, object] | None = None
    latest_generated_artifact_version_id: str | None = None
    latest_generated_artifact_version_number: int | None = None
    latest_approved_artifact_version_id: str | None = None
    latest_approved_artifact_version_number: int | None = None
    publish_config_json: dict[str, object] | None = None
    deploy_config_json: dict[str, object] | None = None
    analytics_config_json: dict[str, object] | None = None
    publish_status: str
    deploy_status: str
    last_published_artifact_version_id: str | None = None
    last_published_artifact_version_number: int | None = None
    last_published_commit_sha: str | None = None
    last_published_at: datetime | None = None
    last_published_by_principal_id: str | None = None
    last_deployed_artifact_version_id: str | None = None
    last_deployed_artifact_version_number: int | None = None
    last_deployed_at: datetime | None = None
    last_deployed_by_principal_id: str | None = None
    publish_history_json: list[dict[str, object]] | None = None
    deploy_history_json: list[dict[str, object]] | None = None
    created_by_principal_id: str | None = None
    updated_by_principal_id: str | None = None
    created_at: datetime
    updated_at: datetime


class SEOMigrationWorkspaceSummaryRead(BaseModel):
    workspace: SEOMigrationWorkspaceRead
    source_snapshot: SEOMigrationSourceSnapshotRead | None = None
    context_summary: dict[str, object]
    latest_artifact: SEOMigrationArtifactVersionRead | None = None
    publish_readiness: dict[str, object] = Field(default_factory=dict)
    deploy_readiness: dict[str, object] = Field(default_factory=dict)
    publish_history: list[dict[str, object]] = Field(default_factory=list)
    deploy_history: list[dict[str, object]] = Field(default_factory=list)
    ga4_outcome_snapshot: SEORecommendationGA4OutcomeSnapshotRead | None = None
    draft_only_notice: str


class SEOMigrationArtifactFilePreviewRead(BaseModel):
    artifact_version_id: str
    path: str
    media_type: str
    content: str


class SEOMigrationPublishActionRead(BaseModel):
    workspace: SEOMigrationWorkspaceRead
    artifact: SEOMigrationArtifactVersionRead
    readiness: dict[str, object]
    result: dict[str, object]


class SEOMigrationDeployActionRead(BaseModel):
    workspace: SEOMigrationWorkspaceRead
    artifact: SEOMigrationArtifactVersionRead
    readiness: dict[str, object]
    result: dict[str, object]


class SEOMigrationRepositoryAdoptActionRead(BaseModel):
    workspace: SEOMigrationWorkspaceRead
    readiness: dict[str, object]
    result: dict[str, object]


class SEOMigrationArtifactDeleteActionRead(BaseModel):
    workspace: SEOMigrationWorkspaceRead
    deleted_artifact_version_id: str
    deleted_artifact_version_number: int


class SEOMigrationHistoryListRead(BaseModel):
    items: list[dict[str, object]]
    total: int
