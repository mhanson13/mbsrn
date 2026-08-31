from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


def _normalize_optional_text(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _normalize_base_path(value: object) -> str:
    normalized = _normalize_optional_text(value, max_length=160) or "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    normalized = normalized.replace("\\", "/")
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    if len(normalized) > 1 and normalized.endswith("/"):
        normalized = normalized.rstrip("/")
    return normalized or "/"


class GitHubPublishConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    owner: str | None = None
    repository: str | None = None
    default_branch: str = "main"
    base_path: str = "/"
    deploy_workflow_mode: str = "site_repo_template_v1"
    target_environment_key: str = "gke_prod"
    target_environment_source: str = "admin_config"
    github_repository_auto_create_enabled: bool = False
    managed_gke_cluster_name: str | None = None
    managed_gke_cluster_location: str | None = None
    managed_gke_project_id: str | None = None
    managed_gcp_deploy_key_configured: bool = False
    managed_gcp_deploy_key_updated_at: datetime | None = None
    namespace_isolation_defaults: "GitHubNamespaceIsolationDefaults"
    namespace_isolation_effective_defaults: "GitHubNamespaceIsolationDefaults | None" = None
    namespace_isolation_cap_reasons: dict[str, str] = Field(default_factory=dict)
    enabled: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GitHubPublishConfigUpdateRequest(BaseModel):
    owner: str | None = Field(default=None, max_length=120)
    repository: str | None = Field(default=None, max_length=255)
    default_branch: str | None = Field(default="main", max_length=120)
    base_path: str | None = Field(default="/", max_length=160)
    deploy_workflow_mode: str | None = Field(default="site_repo_template_v1", max_length=60)
    target_environment_key: str | None = Field(default="gke_prod", max_length=80)
    github_repository_auto_create_enabled: bool = False
    managed_gke_cluster_name: str | None = Field(default=None, max_length=120)
    managed_gke_cluster_location: str | None = Field(default=None, max_length=120)
    managed_gke_project_id: str | None = Field(default=None, max_length=120)
    managed_gcp_deploy_key_value: str | None = Field(default=None, max_length=20000)
    managed_gcp_deploy_key_clear: bool = False
    namespace_isolation_defaults: "GitHubNamespaceIsolationDefaults | None" = None
    enabled: bool = False

    @field_validator("owner", mode="before")
    @classmethod
    def _normalize_owner(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=120)

    @field_validator("repository", mode="before")
    @classmethod
    def _normalize_repository(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=255)

    @field_validator("default_branch", mode="before")
    @classmethod
    def _normalize_default_branch(cls, value: object) -> str | None:
        return _normalize_optional_text(value, max_length=120)

    @field_validator("base_path", mode="before")
    @classmethod
    def _normalize_base_path_value(cls, value: object) -> str:
        return _normalize_base_path(value)

    @field_validator("deploy_workflow_mode", mode="before")
    @classmethod
    def _normalize_deploy_workflow_mode(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=60)
        return normalized.lower() if normalized else None

    @field_validator("target_environment_key", mode="before")
    @classmethod
    def _normalize_target_environment_key(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=80)
        return normalized.lower() if normalized else None

    @field_validator("managed_gke_cluster_name", mode="before")
    @classmethod
    def _normalize_managed_gke_cluster_name(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=120)
        return normalized.lower() if normalized else None

    @field_validator("managed_gke_cluster_location", mode="before")
    @classmethod
    def _normalize_managed_gke_cluster_location(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=120)
        return normalized.lower() if normalized else None

    @field_validator("managed_gke_project_id", mode="before")
    @classmethod
    def _normalize_managed_gke_project_id(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=120)
        return normalized.lower() if normalized else None

    @field_validator("managed_gcp_deploy_key_value", mode="before")
    @classmethod
    def _normalize_managed_gcp_deploy_key_value(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


_VALID_CPU_PATTERN = r"^(?:[1-9]\d*m|[1-9]\d*(?:\.\d+)?)$"
_VALID_MEMORY_PATTERN = r"^(?:[1-9]\d*(?:Ei|Pi|Ti|Gi|Mi|Ki)|[1-9]\d*(?:\.\d+)?(?:E|P|T|G|M|K)i?)$"
_VALID_NONNEGATIVE_COUNT_PATTERN = r"^\d{1,6}$"
_DEFAULT_NETWORK_POLICY_MODE = "default_deny_ingress"
_ALLOWED_NETWORK_POLICY_MODES = {_DEFAULT_NETWORK_POLICY_MODE}
_DEFAULT_MANAGED_PREVIEW_ENDPOINT_MODE = "auto"
_ALLOWED_MANAGED_PREVIEW_ENDPOINT_MODES = {
    _DEFAULT_MANAGED_PREVIEW_ENDPOINT_MODE,
    "preview_shared_gateway",
    "dedicated_static_ip",
}


def _normalize_quantity(
    value: object,
    *,
    max_length: int,
) -> str | None:
    normalized = _normalize_optional_text(value, max_length=max_length)
    return normalized if normalized else None


def _normalize_nonnegative_count(
    value: object,
    *,
    default: int,
) -> int:
    if value is None or str(value).strip() == "":
        return default
    candidate = str(value).strip()
    if not candidate.isdigit():
        raise ValueError("must be a non-negative integer.")
    parsed = int(candidate)
    if parsed < 0:
        raise ValueError("must be a non-negative integer.")
    return parsed


class GitHubNamespaceResourceQuotaDefaults(BaseModel):
    enabled: bool = False
    requests_cpu: str = "1000m"
    requests_memory: str = "1Gi"
    limits_cpu: str = "2000m"
    limits_memory: str = "2Gi"
    pods: int = 20
    services: int = 10
    configmaps: int = 40
    secrets: int = 40
    persistentvolumeclaims: int = 10

    @field_validator(
        "requests_cpu",
        "limits_cpu",
        mode="before",
    )
    @classmethod
    def _normalize_cpu(cls, value: object) -> str:
        normalized = _normalize_quantity(value, max_length=32)
        if not normalized:
            raise ValueError("is required.")
        import re

        if not re.fullmatch(_VALID_CPU_PATTERN, normalized):
            raise ValueError("must be a valid Kubernetes CPU quantity (for example: 500m, 1, 2).")
        return normalized

    @field_validator(
        "requests_memory",
        "limits_memory",
        mode="before",
    )
    @classmethod
    def _normalize_memory(cls, value: object) -> str:
        normalized = _normalize_quantity(value, max_length=32)
        if not normalized:
            raise ValueError("is required.")
        import re

        if not re.fullmatch(_VALID_MEMORY_PATTERN, normalized):
            raise ValueError("must be a valid Kubernetes memory quantity (for example: 512Mi, 1Gi).")
        return normalized

    @field_validator(
        "pods",
        "services",
        "configmaps",
        "secrets",
        "persistentvolumeclaims",
        mode="before",
    )
    @classmethod
    def _normalize_counts(cls, value: object) -> int:
        parsed = _normalize_nonnegative_count(value, default=0)
        import re

        if not re.fullmatch(_VALID_NONNEGATIVE_COUNT_PATTERN, str(parsed)):
            raise ValueError("must be between 0 and 999999.")
        return parsed


class GitHubNamespaceLimitRangeDefaults(BaseModel):
    enabled: bool = False
    default_cpu: str = "500m"
    default_memory: str = "512Mi"
    default_request_cpu: str = "250m"
    default_request_memory: str = "256Mi"
    min_cpu: str = "100m"
    min_memory: str = "128Mi"
    max_cpu: str = "2000m"
    max_memory: str = "2Gi"

    @field_validator(
        "default_cpu",
        "default_request_cpu",
        "min_cpu",
        "max_cpu",
        mode="before",
    )
    @classmethod
    def _normalize_cpu(cls, value: object) -> str:
        normalized = _normalize_quantity(value, max_length=32)
        if not normalized:
            raise ValueError("is required.")
        import re

        if not re.fullmatch(_VALID_CPU_PATTERN, normalized):
            raise ValueError("must be a valid Kubernetes CPU quantity (for example: 500m, 1).")
        return normalized

    @field_validator(
        "default_memory",
        "default_request_memory",
        "min_memory",
        "max_memory",
        mode="before",
    )
    @classmethod
    def _normalize_memory(cls, value: object) -> str:
        normalized = _normalize_quantity(value, max_length=32)
        if not normalized:
            raise ValueError("is required.")
        import re

        if not re.fullmatch(_VALID_MEMORY_PATTERN, normalized):
            raise ValueError("must be a valid Kubernetes memory quantity (for example: 512Mi, 1Gi).")
        return normalized


class GitHubNamespaceNetworkPolicyDefaults(BaseModel):
    enabled: bool = False
    mode: str = _DEFAULT_NETWORK_POLICY_MODE

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=80) or _DEFAULT_NETWORK_POLICY_MODE
        normalized = normalized.lower()
        if normalized not in _ALLOWED_NETWORK_POLICY_MODES:
            raise ValueError("is invalid. Supported values: " + ", ".join(sorted(_ALLOWED_NETWORK_POLICY_MODES)) + ".")
        return normalized


_MIGRATION_GENERATION_DEPTH_VALUES = {"compact", "standard", "expanded"}
_MIGRATION_VARIATION_LEVEL_VALUES = {"conservative", "balanced", "differentiated"}
_MIGRATION_PREFLIGHT_MODE_VALUES = {"compact_fallback", "block_before_provider"}

_MIGRATION_REQUEST_MAX_CONTEXT_BUDGET_CHARS = 1_000_000
_MIGRATION_REQUEST_MAX_LIST_LIMIT = 1_000
_MIGRATION_REQUEST_MAX_TIMEOUT_SECONDS = 10_000
_MIGRATION_REQUEST_MAX_FINAL_INPUT_CHARS = 1_000_000
_MIGRATION_REQUEST_MAX_DIFFICULTY_SCORE = 100
_MIGRATION_REQUEST_MAX_COMPACT_LIMIT = 100

_MIGRATION_EFFECTIVE_BUDGET_LIMITS: dict[str, tuple[int, int]] = {
    "migration_context_budget_chars": (8000, 150000),
    "migration_recommendation_limit": (1, 24),
    "migration_competitor_limit": (1, 24),
    "migration_source_page_summary_limit": (3, 16),
    "migration_media_asset_limit": (4, 24),
    "migration_generated_page_limit": (4, 30),
    "migration_generated_file_limit": (4, 24),
}

_MIGRATION_EFFECTIVE_SAFETY_LIMITS: dict[str, tuple[int, int]] = {
    "migration_provider_timeout_seconds": (60, 600),
    "migration_max_final_input_chars": (3000, 64000),
    "migration_max_difficulty_score": (5, 24),
    "migration_compact_page_limit": (1, 10),
    "migration_compact_media_asset_limit": (0, 8),
    "migration_compact_recommendation_limit": (0, 12),
}


class MigrationGenerationBudgetDefaults(BaseModel):
    migration_context_budget_chars: int = Field(default=90000, ge=1, le=_MIGRATION_REQUEST_MAX_CONTEXT_BUDGET_CHARS)
    migration_recommendation_limit: int = Field(default=6, ge=0, le=_MIGRATION_REQUEST_MAX_LIST_LIMIT)
    migration_competitor_limit: int = Field(default=8, ge=0, le=_MIGRATION_REQUEST_MAX_LIST_LIMIT)
    migration_source_page_summary_limit: int = Field(default=8, ge=0, le=_MIGRATION_REQUEST_MAX_LIST_LIMIT)
    migration_media_asset_limit: int = Field(default=16, ge=0, le=_MIGRATION_REQUEST_MAX_LIST_LIMIT)
    migration_generated_page_limit: int = Field(default=20, ge=0, le=_MIGRATION_REQUEST_MAX_LIST_LIMIT)
    migration_generated_file_limit: int = Field(default=16, ge=0, le=_MIGRATION_REQUEST_MAX_LIST_LIMIT)
    migration_generation_depth: str = "standard"
    migration_variation_level: str = "balanced"
    migration_require_page_variety: bool = True
    migration_require_design_variation: bool = True

    @field_validator("migration_generation_depth", mode="before")
    @classmethod
    def _normalize_generation_depth(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=32) or "standard"
        lowered = normalized.lower()
        if lowered not in _MIGRATION_GENERATION_DEPTH_VALUES:
            raise ValueError(
                "is invalid. Supported values: " + ", ".join(sorted(_MIGRATION_GENERATION_DEPTH_VALUES)) + "."
            )
        return lowered

    @field_validator("migration_variation_level", mode="before")
    @classmethod
    def _normalize_variation_level(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=32) or "balanced"
        lowered = normalized.lower()
        if lowered not in _MIGRATION_VARIATION_LEVEL_VALUES:
            raise ValueError(
                "is invalid. Supported values: " + ", ".join(sorted(_MIGRATION_VARIATION_LEVEL_VALUES)) + "."
            )
        return lowered


class MigrationGenerationSafetyDefaults(BaseModel):
    # Synchronous migration generation timeout guardrail.
    # 600 seconds (10 minutes) is the hard maximum for this request/response path.
    # Longer generation must move to async/background execution architecture.
    migration_provider_timeout_seconds: int = Field(default=300, ge=1, le=_MIGRATION_REQUEST_MAX_TIMEOUT_SECONDS)
    migration_preflight_mode: str = "compact_fallback"
    migration_max_final_input_chars: int = Field(default=32000, ge=1, le=_MIGRATION_REQUEST_MAX_FINAL_INPUT_CHARS)
    migration_max_difficulty_score: int = Field(default=18, ge=1, le=_MIGRATION_REQUEST_MAX_DIFFICULTY_SCORE)
    migration_compact_fallback_enabled: bool = True
    migration_compact_page_limit: int = Field(default=6, ge=0, le=_MIGRATION_REQUEST_MAX_COMPACT_LIMIT)
    migration_compact_media_asset_limit: int = Field(default=5, ge=0, le=_MIGRATION_REQUEST_MAX_COMPACT_LIMIT)
    migration_compact_recommendation_limit: int = Field(default=8, ge=0, le=_MIGRATION_REQUEST_MAX_COMPACT_LIMIT)

    @field_validator("migration_preflight_mode", mode="before")
    @classmethod
    def _normalize_preflight_mode(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=40) or "compact_fallback"
        lowered = normalized.lower()
        if lowered not in _MIGRATION_PREFLIGHT_MODE_VALUES:
            raise ValueError(
                "is invalid. Supported values: " + ", ".join(sorted(_MIGRATION_PREFLIGHT_MODE_VALUES)) + "."
            )
        return lowered


class ManagedPreviewEndpointDefaults(BaseModel):
    mode: str = _DEFAULT_MANAGED_PREVIEW_ENDPOINT_MODE
    shared_preview_static_ip_name: str | None = Field(default=None, max_length=80)
    gateway_api_enabled: bool = False
    gateway_name: str | None = Field(default=None, max_length=63)
    gateway_namespace: str | None = Field(default=None, max_length=63)
    certificate_map_name: str | None = Field(default=None, max_length=63)
    certificate_map_entry_name: str | None = Field(default=None, max_length=63)
    certificate_name: str | None = Field(default=None, max_length=63)
    dns_authorization_name: str | None = Field(default=None, max_length=63)
    certificate_domain: str = "*.site.mbsrn.com"

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: object) -> str:
        normalized = _normalize_optional_text(value, max_length=40) or _DEFAULT_MANAGED_PREVIEW_ENDPOINT_MODE
        lowered = normalized.lower()
        if lowered not in _ALLOWED_MANAGED_PREVIEW_ENDPOINT_MODES:
            raise ValueError(
                "is invalid. Supported values: " + ", ".join(sorted(_ALLOWED_MANAGED_PREVIEW_ENDPOINT_MODES)) + "."
            )
        return lowered

    @field_validator("shared_preview_static_ip_name", mode="before")
    @classmethod
    def _normalize_shared_preview_static_ip_name(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=80)
        if not normalized:
            return None
        normalized = normalized.lower().replace("_", "-").replace(" ", "-")
        normalized = normalized.replace("/", "-").replace("\\", "-")
        while "--" in normalized:
            normalized = normalized.replace("--", "-")
        normalized = normalized.strip("-")
        return normalized or None

    @field_validator(
        "gateway_name",
        "gateway_namespace",
        "certificate_map_name",
        "certificate_map_entry_name",
        "certificate_name",
        "dns_authorization_name",
        mode="before",
    )
    @classmethod
    def _normalize_gateway_resource_name(cls, value: object) -> str | None:
        normalized = _normalize_optional_text(value, max_length=63)
        if not normalized:
            return None
        normalized = normalized.lower().replace("_", "-").replace(" ", "-")
        while "--" in normalized:
            normalized = normalized.replace("--", "-")
        return normalized.strip("-") or None

    @field_validator("certificate_domain", mode="before")
    @classmethod
    def _normalize_certificate_domain(cls, value: object) -> str:
        normalized = (_normalize_optional_text(value, max_length=253) or "*.site.mbsrn.com").lower().rstrip(".")
        if normalized != "*.site.mbsrn.com":
            raise ValueError("must be *.site.mbsrn.com for preview traffic.")
        return normalized

    @model_validator(mode="after")
    def _validate_enabled_gateway_configuration(self) -> "ManagedPreviewEndpointDefaults":
        if not self.gateway_api_enabled:
            return self
        required = {
            "shared_preview_static_ip_name": self.shared_preview_static_ip_name,
            "gateway_name": self.gateway_name,
            "gateway_namespace": self.gateway_namespace,
            "certificate_map_name": self.certificate_map_name,
            "certificate_map_entry_name": self.certificate_map_entry_name,
            "certificate_name": self.certificate_name,
            "dns_authorization_name": self.dns_authorization_name,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError("enabled Gateway API configuration requires: " + ", ".join(missing) + ".")
        import re

        resource_pattern = re.compile(r"^[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$")
        namespace_pattern = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
        for field_name in (
            "shared_preview_static_ip_name",
            "gateway_name",
            "certificate_map_name",
            "certificate_map_entry_name",
            "certificate_name",
            "dns_authorization_name",
        ):
            if not resource_pattern.fullmatch(str(required[field_name])):
                raise ValueError(f"{field_name} must be a lowercase Google/Kubernetes resource name.")
        if not namespace_pattern.fullmatch(str(self.gateway_namespace)):
            raise ValueError("gateway_namespace must be a lowercase Kubernetes namespace name.")
        return self


class GitHubNamespaceIsolationDefaults(BaseModel):
    resource_quota: GitHubNamespaceResourceQuotaDefaults = Field(default_factory=GitHubNamespaceResourceQuotaDefaults)
    limit_range: GitHubNamespaceLimitRangeDefaults = Field(default_factory=GitHubNamespaceLimitRangeDefaults)
    network_policy: GitHubNamespaceNetworkPolicyDefaults = Field(default_factory=GitHubNamespaceNetworkPolicyDefaults)
    managed_preview_endpoint: ManagedPreviewEndpointDefaults = Field(default_factory=ManagedPreviewEndpointDefaults)
    migration_generation_budget: MigrationGenerationBudgetDefaults = Field(
        default_factory=MigrationGenerationBudgetDefaults
    )
    migration_generation_safety: MigrationGenerationSafetyDefaults = Field(
        default_factory=MigrationGenerationSafetyDefaults
    )

    model_config = ConfigDict(extra="forbid")


def normalize_namespace_isolation_defaults(
    value: object | None,
) -> GitHubNamespaceIsolationDefaults:
    if isinstance(value, GitHubNamespaceIsolationDefaults):
        return value
    if value is None:
        return GitHubNamespaceIsolationDefaults()
    if isinstance(value, dict):
        return GitHubNamespaceIsolationDefaults.model_validate(value)
    raise ValidationError.from_exception_data(
        "GitHubNamespaceIsolationDefaults",
        [
            {
                "type": "value_error",
                "loc": ("namespace_isolation_defaults",),
                "msg": "must be an object.",
                "input": value,
            }
        ],
    )


def _clamp_migration_setting(
    *,
    setting_path: str,
    requested_value: int,
    min_value: int,
    max_value: int,
) -> tuple[int, str | None]:
    if requested_value < min_value:
        return (
            min_value,
            f"{setting_path} requested {requested_value} is below hard minimum {min_value}; effective value {min_value} is used.",
        )
    if requested_value > max_value:
        return (
            max_value,
            f"{setting_path} requested {requested_value} exceeds hard cap {max_value}; effective value {max_value} is used.",
        )
    return requested_value, None


def resolve_effective_namespace_isolation_defaults(
    value: object | None,
) -> tuple[GitHubNamespaceIsolationDefaults, dict[str, str]]:
    requested = normalize_namespace_isolation_defaults(value)
    effective_payload = requested.model_dump(mode="python")
    cap_reasons: dict[str, str] = {}

    budget_payload = effective_payload.get("migration_generation_budget")
    if isinstance(budget_payload, dict):
        for field_name, (min_value, max_value) in _MIGRATION_EFFECTIVE_BUDGET_LIMITS.items():
            requested_value_raw = budget_payload.get(field_name)
            if not isinstance(requested_value_raw, int):
                continue
            setting_path = f"migration_generation_budget.{field_name}"
            effective_value, reason = _clamp_migration_setting(
                setting_path=setting_path,
                requested_value=int(requested_value_raw),
                min_value=min_value,
                max_value=max_value,
            )
            budget_payload[field_name] = effective_value
            if reason:
                cap_reasons[setting_path] = reason

    safety_payload = effective_payload.get("migration_generation_safety")
    if isinstance(safety_payload, dict):
        for field_name, (min_value, max_value) in _MIGRATION_EFFECTIVE_SAFETY_LIMITS.items():
            requested_value_raw = safety_payload.get(field_name)
            if not isinstance(requested_value_raw, int):
                continue
            setting_path = f"migration_generation_safety.{field_name}"
            effective_value, reason = _clamp_migration_setting(
                setting_path=setting_path,
                requested_value=int(requested_value_raw),
                min_value=min_value,
                max_value=max_value,
            )
            safety_payload[field_name] = effective_value
            if reason:
                cap_reasons[setting_path] = reason

    return GitHubNamespaceIsolationDefaults.model_validate(effective_payload), cap_reasons


GitHubPublishConfigRead.model_rebuild()
