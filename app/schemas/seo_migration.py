from __future__ import annotations

from datetime import datetime
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    asset_references: dict[str, list[str]] = Field(default_factory=dict)
    cleaned_text_blocks: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SEOMigrationArtifactFileRead(BaseModel):
    path: str
    media_type: str
    size_bytes: int
    content: str | None = None


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


class SEOMigrationHistoryListRead(BaseModel):
    items: list[dict[str, object]]
    total: int
