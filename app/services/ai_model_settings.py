from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

ModelSource = Literal["explicit", "task_override", "business_default", "env_default", "provider_fallback"]
ResolvedModelSource = Literal[
    "explicit",
    "task_override",
    "business_default",
    "env_default",
    "provider_fallback",
    "deterministic",
]
AIModelValidationStatus = Literal["allowed", "compatibility_allowed", "deterministic"]
AITaskAlias = Literal[
    "requirements_helper",
    "media_metadata_helper",
    "recommendation_explanation",
    "competitor_analysis",
    "seo_audit_summary",
    "competitor_comparison_summary",
    "migration_site_plan",
    "migration_site_generation",
    "migration_section_repair",
    "validation_explainer",
    "moderation",
    "embeddings",
    "evaluation_harness",
    "migration_live_contract_validation",
    "maintenance_cleanup",
]
AIModelCapability = Literal[
    "text",
    "structured_json",
    "multimodal",
    "web_search",
    "code_generation",
    "moderation",
    "embeddings",
]
AIModelTier = Literal[
    "compatibility_shared",
    "nano",
    "mini",
    "mid_reasoning",
    "strongest_generation",
    "dedicated_moderation",
    "embedding",
    "deterministic",
]

_COMPATIBILITY_SHARED_MODEL_ALIAS: Final[str] = "compatibility_shared"
_BOOTSTRAP_FALLBACK_MODEL_NAME: Final[str] = "gpt-5.6-terra"
_DETERMINISTIC_MODEL_NAME: Final[str] = "deterministic"
_DEPRECATED_EXACT_MODELS: Final[tuple[str, ...]] = (
    "gpt-5.1",
    "gpt-4.1-mini",
    "gpt-4o-mini",
    "codex",
)
_DEPRECATED_PREFIX_MODELS: Final[tuple[str, ...]] = (
    "gpt-5.1-",
    "gpt-4.1-mini-",
    "gpt-4o-mini-",
    "codex-",
)
_GENERATIVE_MODEL_CAPABILITIES: Final[tuple[AIModelCapability, ...]] = (
    "text",
    "structured_json",
    "multimodal",
    "web_search",
    "code_generation",
)
_EMBEDDING_MODEL_CAPABILITIES: Final[tuple[AIModelCapability, ...]] = (
    "text",
    "embeddings",
)
_MODERATION_MODEL_CAPABILITIES: Final[tuple[AIModelCapability, ...]] = (
    "text",
    "moderation",
)


class AIModelValidationError(ValueError):
    def __init__(self, message: str, *, reason_code: str | None = None) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class UnknownAITaskAliasError(ValueError):
    def __init__(self, task_alias: str) -> None:
        self.task_alias = task_alias
        self.reason_code = "ai_model_task_alias_unknown"
        super().__init__(f"Unknown AI task alias '{task_alias}'.")


@dataclass(frozen=True)
class ResolvedAIModelName:
    model_name: str
    model_source: ModelSource


@dataclass(frozen=True)
class AITaskDefinition:
    task_alias: AITaskAlias
    admin_label: str
    description: str
    capability_note: str
    capabilities: tuple[AIModelCapability, ...]
    default_tier: AIModelTier
    allow_real_provider: bool
    structured_output_required: bool
    mock_only_for_now: bool
    admin_override_supported: bool
    uses_shared_fallback_by_default: bool
    deterministic_allowed: bool


@dataclass(frozen=True)
class AIModelValidationDecision:
    model_name: str
    deprecated_matched: bool
    blocked: bool
    compatibility_allowed: bool
    safe_message: str


@dataclass(frozen=True)
class ResolvedAIModelForTask:
    task_alias: AITaskAlias
    model_name: str | None
    model_source: ResolvedModelSource
    model_alias: str | None
    tier: AIModelTier
    capabilities: tuple[AIModelCapability, ...]
    allow_real_provider: bool
    structured_output_required: bool
    mock_only_for_now: bool
    deprecated_blocked: bool
    fallback_used: bool
    compatibility_mapped: bool
    legacy_compatibility_mode: bool
    validation_status: AIModelValidationStatus
    safe_diagnostic_message: str


@dataclass(frozen=True)
class AIModelSelectableValue:
    model_name: str
    label: str
    capability_note: str
    capabilities: tuple[AIModelCapability, ...]


@dataclass(frozen=True)
class OpenAINonToolStructuredOutputProfile:
    model_name: str
    endpoint_path: str
    response_format_mode: str
    request_body_mode: str
    supports_temperature_override: bool
    temperature_default_only: bool
    request_shape_adjusted: bool


_AI_TASK_REGISTRY: Final[dict[str, AITaskDefinition]] = {
    "requirements_helper": AITaskDefinition(
        task_alias="requirements_helper",
        admin_label="Requirements Helper",
        description="Short structured requirement helper and field-level suggestion tasks.",
        capability_note="Structured JSON helper tasks.",
        capabilities=("text", "structured_json"),
        default_tier="nano",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "media_metadata_helper": AITaskDefinition(
        task_alias="media_metadata_helper",
        admin_label="Media Metadata Helper",
        description="Structured image metadata suggestion tasks for migration media assets.",
        capability_note="Multimodal + structured JSON image tasks.",
        capabilities=("text", "structured_json", "multimodal"),
        default_tier="nano",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "recommendation_explanation": AITaskDefinition(
        task_alias="recommendation_explanation",
        admin_label="Recommendation Explanation",
        description="Recommendation narrative and bounded explanation tasks.",
        capability_note="Structured JSON recommendation narratives.",
        capabilities=("text", "structured_json"),
        default_tier="mini",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "competitor_analysis": AITaskDefinition(
        task_alias="competitor_analysis",
        admin_label="Competitor Analysis",
        description="Competitor discovery and synthesis tasks that may require web search.",
        capability_note="Structured JSON + web-search competitor analysis.",
        capabilities=("text", "structured_json", "web_search"),
        default_tier="mid_reasoning",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "seo_audit_summary": AITaskDefinition(
        task_alias="seo_audit_summary",
        admin_label="SEO Audit Summary",
        description="Deterministic SEO audit summary presentation.",
        capability_note="Deterministic summary presentation.",
        capabilities=("text",),
        default_tier="deterministic",
        allow_real_provider=False,
        structured_output_required=False,
        mock_only_for_now=True,
        admin_override_supported=False,
        uses_shared_fallback_by_default=False,
        deterministic_allowed=True,
    ),
    "competitor_comparison_summary": AITaskDefinition(
        task_alias="competitor_comparison_summary",
        admin_label="Competitor Comparison Summary",
        description="Deterministic competitor comparison summary presentation.",
        capability_note="Deterministic comparison summary presentation.",
        capabilities=("text",),
        default_tier="deterministic",
        allow_real_provider=False,
        structured_output_required=False,
        mock_only_for_now=True,
        admin_override_supported=False,
        uses_shared_fallback_by_default=False,
        deterministic_allowed=True,
    ),
    "migration_site_plan": AITaskDefinition(
        task_alias="migration_site_plan",
        admin_label="Migration Site Plan",
        description="Migration sitemap, page map, and content strategy planning tasks.",
        capability_note="Structured JSON planning tasks.",
        capabilities=("text", "structured_json"),
        default_tier="mid_reasoning",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "migration_site_generation": AITaskDefinition(
        task_alias="migration_site_generation",
        admin_label="Migration Site Generation",
        description="Full migration draft artifact generation tasks.",
        capability_note="Structured JSON + code generation for full drafts.",
        capabilities=("text", "structured_json", "code_generation"),
        default_tier="strongest_generation",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "migration_section_repair": AITaskDefinition(
        task_alias="migration_section_repair",
        admin_label="Migration Section Repair",
        description="Bounded migration page or section repair tasks.",
        capability_note="Structured JSON + code generation for scoped repairs.",
        capabilities=("text", "structured_json", "code_generation"),
        default_tier="mid_reasoning",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "validation_explainer": AITaskDefinition(
        task_alias="validation_explainer",
        admin_label="Validation Explainer",
        description="Structured explanation of validation or readiness outcomes.",
        capability_note="Structured JSON validation explanations.",
        capabilities=("text", "structured_json"),
        default_tier="mini",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "moderation": AITaskDefinition(
        task_alias="moderation",
        admin_label="Moderation",
        description="Reserved dedicated moderation task routing.",
        capability_note="Moderation model or deterministic fallback.",
        capabilities=("text", "moderation"),
        default_tier="dedicated_moderation",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=True,
        admin_override_supported=True,
        uses_shared_fallback_by_default=False,
        deterministic_allowed=True,
    ),
    "embeddings": AITaskDefinition(
        task_alias="embeddings",
        admin_label="Embeddings",
        description="Reserved embeddings and retrieval task routing.",
        capability_note="Embedding model or deterministic fallback.",
        capabilities=("text", "embeddings"),
        default_tier="embedding",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=True,
        admin_override_supported=True,
        uses_shared_fallback_by_default=False,
        deterministic_allowed=True,
    ),
    "evaluation_harness": AITaskDefinition(
        task_alias="evaluation_harness",
        admin_label="Evaluation Harness",
        description="Controlled non-production evaluation harness tasks.",
        capability_note="Structured JSON evaluation tasks.",
        capabilities=("text", "structured_json"),
        default_tier="compatibility_shared",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "migration_live_contract_validation": AITaskDefinition(
        task_alias="migration_live_contract_validation",
        admin_label="Migration Live Contract Validation",
        description="Manual migration contract validation tasks.",
        capability_note="Structured JSON live contract validation tasks.",
        capabilities=("text", "structured_json"),
        default_tier="compatibility_shared",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
        admin_override_supported=True,
        uses_shared_fallback_by_default=True,
        deterministic_allowed=False,
    ),
    "maintenance_cleanup": AITaskDefinition(
        task_alias="maintenance_cleanup",
        admin_label="Maintenance Cleanup",
        description="Deterministic maintenance and cleanup tasks.",
        capability_note="Deterministic cleanup or optional provider override.",
        capabilities=(),
        default_tier="deterministic",
        allow_real_provider=True,
        structured_output_required=False,
        mock_only_for_now=True,
        admin_override_supported=True,
        uses_shared_fallback_by_default=False,
        deterministic_allowed=True,
    ),
}

_AI_MODEL_SELECTABLE_VALUES: Final[tuple[AIModelSelectableValue, ...]] = (
    AIModelSelectableValue(
        model_name="gpt-5.6-luna",
        label="GPT-5.6 Luna",
        capability_note="Structured JSON helper and explainer tasks.",
        capabilities=("text", "structured_json"),
    ),
    AIModelSelectableValue(
        model_name="gpt-5.6-terra",
        label="GPT-5.6 Terra",
        capability_note="General generation, multimodal, and web-search tasks.",
        capabilities=_GENERATIVE_MODEL_CAPABILITIES,
    ),
    AIModelSelectableValue(
        model_name="gpt-5.6",
        label="GPT-5.6",
        capability_note="High-cost full generation and code-output tasks.",
        capabilities=_GENERATIVE_MODEL_CAPABILITIES,
    ),
    AIModelSelectableValue(
        model_name="omni-moderation",
        label="Omni Moderation",
        capability_note="Dedicated moderation tasks.",
        capabilities=_MODERATION_MODEL_CAPABILITIES,
    ),
    AIModelSelectableValue(
        model_name="text-embedding-3-small",
        label="Text Embedding 3 Small",
        capability_note="Embedding and retrieval tasks.",
        capabilities=_EMBEDDING_MODEL_CAPABILITIES,
    ),
    AIModelSelectableValue(
        model_name=_DETERMINISTIC_MODEL_NAME,
        label="Deterministic",
        capability_note="No provider call; use deterministic/manual handling.",
        capabilities=(),
    ),
)


def list_ai_task_definitions() -> tuple[AITaskDefinition, ...]:
    return tuple(_AI_TASK_REGISTRY.values())


def list_admin_configurable_ai_task_definitions() -> tuple[AITaskDefinition, ...]:
    return tuple(task for task in _AI_TASK_REGISTRY.values() if task.admin_override_supported)


def list_ai_model_selectable_values() -> tuple[AIModelSelectableValue, ...]:
    return _AI_MODEL_SELECTABLE_VALUES


def get_ai_task_registry() -> dict[str, AITaskDefinition]:
    return dict(_AI_TASK_REGISTRY)


def get_ai_task_definition(task_alias: str) -> AITaskDefinition:
    normalized = normalize_ai_task_alias(task_alias)
    if normalized is None or normalized not in _AI_TASK_REGISTRY:
        raise UnknownAITaskAliasError(task_alias)
    return _AI_TASK_REGISTRY[normalized]


def normalize_ai_task_alias(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_ai_model_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def resolve_openai_non_tool_structured_output_profile(model_name: str | None) -> OpenAINonToolStructuredOutputProfile:
    normalized = normalize_ai_model_identifier(model_name) or "unknown"
    if normalized.startswith("gpt-5"):
        return OpenAINonToolStructuredOutputProfile(
            model_name=normalized,
            endpoint_path="/responses",
            response_format_mode="json_schema",
            request_body_mode="responses_text_format_json_schema",
            supports_temperature_override=False,
            temperature_default_only=True,
            request_shape_adjusted=True,
        )
    return OpenAINonToolStructuredOutputProfile(
        model_name=normalized,
        endpoint_path="/chat/completions",
        response_format_mode="json_schema",
        request_body_mode="chat_json_schema",
        supports_temperature_override=True,
        temperature_default_only=False,
        request_shape_adjusted=False,
    )


def is_deprecated_ai_model_identifier(model_name: str | None) -> bool:
    return _match_deprecated_ai_model_identifier(normalize_ai_model_identifier(model_name)) is not None


def is_deterministic_ai_model_identifier(model_name: str | None) -> bool:
    return normalize_ai_model_identifier(model_name) == _DETERMINISTIC_MODEL_NAME


def ensure_ai_model_identifier_allowed(
    model_name: str | None,
    *,
    field_name: str = "model",
    task_alias: str | None = None,
    model_source: ResolvedModelSource = "explicit",
    allow_compatibility_legacy: bool = False,
    allow_deterministic: bool = False,
) -> str | None:
    normalized = normalize_ai_model_identifier(model_name)
    if normalized is None:
        return None
    if normalized == _DETERMINISTIC_MODEL_NAME:
        if allow_deterministic:
            return normalized
        raise AIModelValidationError(
            _build_invalid_model_message(
                field_name=field_name,
                task_alias=task_alias,
                model_source=model_source,
            ),
            reason_code="ai_model_value_invalid",
        )
    decision = inspect_ai_model_identifier(
        normalized,
        field_name=field_name,
        task_alias=task_alias,
        model_source=model_source,
        allow_compatibility_legacy=allow_compatibility_legacy,
    )
    if decision.blocked:
        raise AIModelValidationError(decision.safe_message, reason_code="ai_model_deprecated")
    return decision.model_name


def inspect_ai_model_identifier(
    model_name: str,
    *,
    field_name: str = "model",
    task_alias: str | None = None,
    model_source: ResolvedModelSource = "explicit",
    allow_compatibility_legacy: bool = False,
) -> AIModelValidationDecision:
    normalized = normalize_ai_model_identifier(model_name)
    if normalized is None:
        raise AIModelValidationError(f"{field_name} must not be blank.")
    deprecated_match = _match_deprecated_ai_model_identifier(normalized)
    if deprecated_match is None:
        return AIModelValidationDecision(
            model_name=normalized,
            deprecated_matched=False,
            blocked=False,
            compatibility_allowed=False,
            safe_message=_build_allowed_model_message(task_alias=task_alias, model_source=model_source),
        )
    if allow_compatibility_legacy:
        return AIModelValidationDecision(
            model_name=normalized,
            deprecated_matched=True,
            blocked=False,
            compatibility_allowed=True,
            safe_message=_build_compatibility_model_message(task_alias=task_alias, model_source=model_source),
        )
    return AIModelValidationDecision(
        model_name=normalized,
        deprecated_matched=True,
        blocked=True,
        compatibility_allowed=False,
        safe_message=_build_blocked_model_message(
            field_name=field_name,
            task_alias=task_alias,
            model_source=model_source,
        ),
    )


def resolve_ai_model_name(
    *,
    requested_model_name: str | None,
    task_override_model_name: str | None = None,
    business_default_model_name: str | None,
    env_default_model_name: str | None,
    provider_fallback_model_name: str | None,
    final_fallback_model_name: str = _BOOTSTRAP_FALLBACK_MODEL_NAME,
) -> ResolvedAIModelName:
    requested = normalize_ai_model_identifier(requested_model_name)
    if requested is not None:
        return ResolvedAIModelName(
            model_name=requested,
            model_source="explicit",
        )

    task_override = normalize_ai_model_identifier(task_override_model_name)
    if task_override is not None:
        return ResolvedAIModelName(
            model_name=task_override,
            model_source="task_override",
        )

    business_default = normalize_ai_model_identifier(business_default_model_name)
    if business_default is not None:
        return ResolvedAIModelName(
            model_name=business_default,
            model_source="business_default",
        )

    env_default = normalize_ai_model_identifier(env_default_model_name)
    if env_default is not None:
        return ResolvedAIModelName(
            model_name=env_default,
            model_source="env_default",
        )

    provider_fallback = normalize_ai_model_identifier(provider_fallback_model_name)
    if provider_fallback is not None:
        return ResolvedAIModelName(
            model_name=provider_fallback,
            model_source="provider_fallback",
        )

    return ResolvedAIModelName(
        model_name=normalize_ai_model_identifier(final_fallback_model_name) or _BOOTSTRAP_FALLBACK_MODEL_NAME,
        model_source="provider_fallback",
    )


def resolve_ai_model_for_task(
    *,
    task_alias: str,
    requested_model_name: str | None,
    task_override_model_name: str | None = None,
    business_default_model_name: str | None,
    env_default_model_name: str | None,
    provider_fallback_model_name: str | None,
    final_fallback_model_name: str = _BOOTSTRAP_FALLBACK_MODEL_NAME,
    enforce_capabilities: bool = True,
) -> ResolvedAIModelForTask:
    task = get_ai_task_definition(task_alias)
    if task.mock_only_for_now and not task.admin_override_supported:
        return _build_deterministic_ai_model_for_task(
            task=task,
            safe_diagnostic_message=(
                f"Task alias '{task.task_alias}' remains deterministic/mock-only in Phase 1; no provider model is resolved."
            ),
        )
    requested = normalize_ai_model_identifier(requested_model_name)
    task_override = normalize_ai_model_identifier(task_override_model_name)
    if (
        task.mock_only_for_now
        and requested is None
        and task_override is None
        and not task.uses_shared_fallback_by_default
    ):
        return _build_deterministic_ai_model_for_task(
            task=task,
            safe_diagnostic_message=(
                f"Task alias '{task.task_alias}' remains deterministic/mock-only in Phase 1; no provider model is resolved."
            ),
        )

    resolved = resolve_ai_model_name(
        requested_model_name=requested,
        task_override_model_name=task_override,
        business_default_model_name=business_default_model_name,
        env_default_model_name=env_default_model_name,
        provider_fallback_model_name=provider_fallback_model_name,
        final_fallback_model_name=final_fallback_model_name,
    )
    if resolved.model_name == _DETERMINISTIC_MODEL_NAME:
        ensure_ai_model_capabilities_for_task(
            task_alias=task.task_alias,
            model_name=resolved.model_name,
            model_source=resolved.model_source,
        )
        return _build_deterministic_ai_model_for_task(
            task=task,
            safe_diagnostic_message=(
                f"Task alias '{task.task_alias}' is configured for deterministic/mock-only handling; no provider model is resolved."
            ),
        )
    validation = inspect_ai_model_identifier(
        resolved.model_name,
        field_name="model",
        task_alias=task.task_alias,
        model_source=resolved.model_source,
        allow_compatibility_legacy=resolved.model_source in {"business_default", "env_default", "provider_fallback"},
    )
    if validation.blocked:
        raise AIModelValidationError(validation.safe_message, reason_code="ai_model_deprecated")
    if enforce_capabilities:
        ensure_ai_model_capabilities_for_task(
            task_alias=task.task_alias,
            model_name=validation.model_name,
            model_source=resolved.model_source,
        )
    return ResolvedAIModelForTask(
        task_alias=task.task_alias,
        model_name=validation.model_name,
        model_source=resolved.model_source,
        model_alias=_COMPATIBILITY_SHARED_MODEL_ALIAS,
        tier=task.default_tier,
        capabilities=task.capabilities,
        allow_real_provider=task.allow_real_provider,
        structured_output_required=task.structured_output_required,
        mock_only_for_now=False,
        deprecated_blocked=False,
        fallback_used=resolved.model_source in {"env_default", "provider_fallback"},
        compatibility_mapped=True,
        legacy_compatibility_mode=validation.compatibility_allowed,
        validation_status="compatibility_allowed" if validation.compatibility_allowed else "allowed",
        safe_diagnostic_message=validation.safe_message,
    )


def ensure_ai_model_capabilities_for_task(
    *,
    task_alias: str,
    model_name: str | None,
    model_source: ResolvedModelSource = "explicit",
) -> None:
    normalized_model = normalize_ai_model_identifier(model_name)
    if normalized_model is None:
        return
    task = get_ai_task_definition(task_alias)
    if normalized_model == _DETERMINISTIC_MODEL_NAME:
        if task.deterministic_allowed:
            return
        known_capabilities: tuple[AIModelCapability, ...] | None = ()
    else:
        known_capabilities = _resolve_known_ai_model_capabilities(normalized_model)
    if known_capabilities is None:
        return
    missing_capabilities = tuple(capability for capability in task.capabilities if capability not in known_capabilities)
    if not missing_capabilities:
        return
    raise AIModelValidationError(
        _build_capability_mismatch_message(
            task_alias=task.task_alias,
            model_source=model_source,
            missing_capabilities=missing_capabilities,
        ),
        reason_code="ai_model_capability_mismatch",
    )


def _match_deprecated_ai_model_identifier(model_name: str | None) -> str | None:
    if model_name is None:
        return None
    if model_name in _DEPRECATED_EXACT_MODELS:
        return model_name
    for prefix in _DEPRECATED_PREFIX_MODELS:
        if model_name.startswith(prefix):
            return prefix.removesuffix("-")
    return None


def _build_allowed_model_message(*, task_alias: str | None, model_source: ResolvedModelSource) -> str:
    if task_alias is None:
        return "AI model is allowed."
    return (
        f"Task alias '{task_alias}' resolved through Phase 1 compatibility_shared routing from source "
        f"'{model_source}'."
    )


def _build_compatibility_model_message(*, task_alias: str | None, model_source: ResolvedModelSource) -> str:
    if task_alias is None:
        return "AI model remains compatibility-mapped to a legacy shared runtime model."
    return (
        f"Task alias '{task_alias}' remains compatibility-mapped to a legacy shared runtime model from source "
        f"'{model_source}'."
    )


def _build_blocked_model_message(
    *,
    field_name: str,
    task_alias: str | None,
    model_source: ResolvedModelSource,
) -> str:
    if field_name and field_name != "model":
        return f"{field_name} cannot use deprecated or blocked model values."
    if task_alias is not None and model_source == "explicit":
        return f"Requested AI model for task alias '{task_alias}' cannot use deprecated or blocked model values."
    if task_alias is not None:
        return f"Configured AI model for task alias '{task_alias}' cannot use deprecated or blocked model values."
    return "Configured AI model cannot use deprecated or blocked model values."


def _build_invalid_model_message(
    *,
    field_name: str,
    task_alias: str | None,
    model_source: ResolvedModelSource,
) -> str:
    if field_name and field_name != "model":
        return f"{field_name} must resolve to a provider model or be blank."
    prefix = "Requested" if model_source == "explicit" else "Configured"
    if task_alias is not None:
        return f"{prefix} AI model for task alias '{task_alias}' must resolve to a provider model."
    return "Configured AI model must resolve to a provider model."


def _resolve_known_ai_model_capabilities(model_name: str) -> tuple[AIModelCapability, ...] | None:
    if model_name == _DETERMINISTIC_MODEL_NAME:
        return ()
    if model_name == "gpt-5.6-luna" or model_name.startswith("gpt-5.6-luna-"):
        return ("text", "structured_json")
    if model_name == "gpt-5.6-terra" or model_name.startswith("gpt-5.6-terra-"):
        return _GENERATIVE_MODEL_CAPABILITIES
    if model_name == "gpt-5.6" or model_name.startswith("gpt-5.6-"):
        return _GENERATIVE_MODEL_CAPABILITIES
    if model_name == "mock" or model_name.startswith("mock-"):
        return _GENERATIVE_MODEL_CAPABILITIES
    if (
        model_name.startswith("gpt-5")
        or model_name.startswith("gpt-4o")
        or model_name.startswith("gpt-4.1")
    ):
        return _GENERATIVE_MODEL_CAPABILITIES
    if model_name.startswith("text-embedding-"):
        return _EMBEDDING_MODEL_CAPABILITIES
    if model_name == "omni-moderation" or model_name == "omni-moderation-latest" or model_name.startswith("omni-moderation-"):
        return _MODERATION_MODEL_CAPABILITIES
    return None


def _build_capability_mismatch_message(
    *,
    task_alias: str,
    model_source: ResolvedModelSource,
    missing_capabilities: tuple[AIModelCapability, ...],
) -> str:
    required = ", ".join(missing_capabilities)
    prefix = "Requested" if model_source == "explicit" else "Configured"
    return f"{prefix} AI model for task alias '{task_alias}' does not satisfy required capabilities: {required}."


def _build_deterministic_ai_model_for_task(
    *,
    task: AITaskDefinition,
    safe_diagnostic_message: str,
) -> ResolvedAIModelForTask:
    return ResolvedAIModelForTask(
        task_alias=task.task_alias,
        model_name=None,
        model_source="deterministic",
        model_alias=None,
        tier=task.default_tier,
        capabilities=task.capabilities,
        allow_real_provider=False,
        structured_output_required=task.structured_output_required,
        mock_only_for_now=True,
        deprecated_blocked=False,
        fallback_used=False,
        compatibility_mapped=False,
        legacy_compatibility_mode=False,
        validation_status="deterministic",
        safe_diagnostic_message=safe_diagnostic_message,
    )
