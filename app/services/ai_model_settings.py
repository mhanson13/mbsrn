from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

ModelSource = Literal["explicit", "admin_config", "env", "provider_fallback"]
ResolvedModelSource = Literal["explicit", "admin_config", "env", "provider_fallback", "task_default"]
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
_LEGACY_SHARED_DEFAULT_MODEL_NAME: Final[str] = "gpt-4o-mini"
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
    pass


class UnknownAITaskAliasError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedAIModelName:
    model_name: str
    model_source: ModelSource


@dataclass(frozen=True)
class AITaskDefinition:
    task_alias: AITaskAlias
    description: str
    capabilities: tuple[AIModelCapability, ...]
    default_tier: AIModelTier
    allow_real_provider: bool
    structured_output_required: bool
    mock_only_for_now: bool


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
    safe_diagnostic_message: str


_AI_TASK_REGISTRY: Final[dict[str, AITaskDefinition]] = {
    "requirements_helper": AITaskDefinition(
        task_alias="requirements_helper",
        description="Short structured requirement helper and field-level suggestion tasks.",
        capabilities=("text", "structured_json"),
        default_tier="nano",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "media_metadata_helper": AITaskDefinition(
        task_alias="media_metadata_helper",
        description="Structured image metadata suggestion tasks for migration media assets.",
        capabilities=("text", "structured_json", "multimodal"),
        default_tier="nano",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "recommendation_explanation": AITaskDefinition(
        task_alias="recommendation_explanation",
        description="Recommendation narrative and bounded explanation tasks.",
        capabilities=("text", "structured_json"),
        default_tier="mini",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "competitor_analysis": AITaskDefinition(
        task_alias="competitor_analysis",
        description="Competitor discovery and synthesis tasks that may require web search.",
        capabilities=("text", "structured_json", "web_search"),
        default_tier="mid_reasoning",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "seo_audit_summary": AITaskDefinition(
        task_alias="seo_audit_summary",
        description="Deterministic SEO audit summary presentation.",
        capabilities=("text",),
        default_tier="deterministic",
        allow_real_provider=False,
        structured_output_required=False,
        mock_only_for_now=True,
    ),
    "competitor_comparison_summary": AITaskDefinition(
        task_alias="competitor_comparison_summary",
        description="Deterministic competitor comparison summary presentation.",
        capabilities=("text",),
        default_tier="deterministic",
        allow_real_provider=False,
        structured_output_required=False,
        mock_only_for_now=True,
    ),
    "migration_site_plan": AITaskDefinition(
        task_alias="migration_site_plan",
        description="Migration sitemap, page map, and content strategy planning tasks.",
        capabilities=("text", "structured_json"),
        default_tier="mid_reasoning",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "migration_site_generation": AITaskDefinition(
        task_alias="migration_site_generation",
        description="Full migration draft artifact generation tasks.",
        capabilities=("text", "structured_json", "code_generation"),
        default_tier="strongest_generation",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "migration_section_repair": AITaskDefinition(
        task_alias="migration_section_repair",
        description="Bounded migration page or section repair tasks.",
        capabilities=("text", "structured_json", "code_generation"),
        default_tier="mid_reasoning",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "validation_explainer": AITaskDefinition(
        task_alias="validation_explainer",
        description="Structured explanation of validation or readiness outcomes.",
        capabilities=("text", "structured_json"),
        default_tier="mini",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "moderation": AITaskDefinition(
        task_alias="moderation",
        description="Reserved dedicated moderation task routing.",
        capabilities=("text", "moderation"),
        default_tier="dedicated_moderation",
        allow_real_provider=False,
        structured_output_required=True,
        mock_only_for_now=True,
    ),
    "embeddings": AITaskDefinition(
        task_alias="embeddings",
        description="Reserved embeddings and retrieval task routing.",
        capabilities=("text", "embeddings"),
        default_tier="embedding",
        allow_real_provider=False,
        structured_output_required=True,
        mock_only_for_now=True,
    ),
    "evaluation_harness": AITaskDefinition(
        task_alias="evaluation_harness",
        description="Controlled non-production evaluation harness tasks.",
        capabilities=("text", "structured_json"),
        default_tier="compatibility_shared",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "migration_live_contract_validation": AITaskDefinition(
        task_alias="migration_live_contract_validation",
        description="Manual migration contract validation tasks.",
        capabilities=("text", "structured_json"),
        default_tier="compatibility_shared",
        allow_real_provider=True,
        structured_output_required=True,
        mock_only_for_now=False,
    ),
    "maintenance_cleanup": AITaskDefinition(
        task_alias="maintenance_cleanup",
        description="Deterministic maintenance and cleanup tasks.",
        capabilities=(),
        default_tier="deterministic",
        allow_real_provider=False,
        structured_output_required=False,
        mock_only_for_now=True,
    ),
}


def list_ai_task_definitions() -> tuple[AITaskDefinition, ...]:
    return tuple(_AI_TASK_REGISTRY.values())


def get_ai_task_registry() -> dict[str, AITaskDefinition]:
    return dict(_AI_TASK_REGISTRY)


def get_ai_task_definition(task_alias: str) -> AITaskDefinition:
    normalized = normalize_ai_task_alias(task_alias)
    if normalized is None or normalized not in _AI_TASK_REGISTRY:
        raise UnknownAITaskAliasError(f"Unknown AI task alias '{task_alias}'.")
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


def is_deprecated_ai_model_identifier(model_name: str | None) -> bool:
    return _match_deprecated_ai_model_identifier(normalize_ai_model_identifier(model_name)) is not None


def ensure_ai_model_identifier_allowed(
    model_name: str | None,
    *,
    field_name: str = "model",
    task_alias: str | None = None,
    model_source: ResolvedModelSource = "explicit",
    allow_compatibility_legacy: bool = False,
) -> str | None:
    normalized = normalize_ai_model_identifier(model_name)
    if normalized is None:
        return None
    decision = inspect_ai_model_identifier(
        normalized,
        field_name=field_name,
        task_alias=task_alias,
        model_source=model_source,
        allow_compatibility_legacy=allow_compatibility_legacy,
    )
    if decision.blocked:
        raise AIModelValidationError(decision.safe_message)
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
    admin_default_model_name: str | None,
    env_default_model_name: str | None,
    provider_fallback_model_name: str | None,
    final_fallback_model_name: str = _LEGACY_SHARED_DEFAULT_MODEL_NAME,
) -> ResolvedAIModelName:
    requested = normalize_ai_model_identifier(requested_model_name)
    if requested is not None:
        return ResolvedAIModelName(
            model_name=requested,
            model_source="explicit",
        )

    admin_default = normalize_ai_model_identifier(admin_default_model_name)
    if admin_default is not None:
        return ResolvedAIModelName(
            model_name=admin_default,
            model_source="admin_config",
        )

    env_default = normalize_ai_model_identifier(env_default_model_name)
    if env_default is not None:
        return ResolvedAIModelName(
            model_name=env_default,
            model_source="env",
        )

    provider_fallback = normalize_ai_model_identifier(provider_fallback_model_name)
    if provider_fallback is not None:
        return ResolvedAIModelName(
            model_name=provider_fallback,
            model_source="provider_fallback",
        )

    return ResolvedAIModelName(
        model_name=normalize_ai_model_identifier(final_fallback_model_name) or _LEGACY_SHARED_DEFAULT_MODEL_NAME,
        model_source="provider_fallback",
    )


def resolve_ai_model_for_task(
    *,
    task_alias: str,
    requested_model_name: str | None,
    admin_default_model_name: str | None,
    env_default_model_name: str | None,
    provider_fallback_model_name: str | None,
    final_fallback_model_name: str = _LEGACY_SHARED_DEFAULT_MODEL_NAME,
) -> ResolvedAIModelForTask:
    task = get_ai_task_definition(task_alias)
    if task.mock_only_for_now:
        return ResolvedAIModelForTask(
            task_alias=task.task_alias,
            model_name=None,
            model_source="task_default",
            model_alias=None,
            tier=task.default_tier,
            capabilities=task.capabilities,
            allow_real_provider=task.allow_real_provider,
            structured_output_required=task.structured_output_required,
            mock_only_for_now=True,
            deprecated_blocked=False,
            fallback_used=False,
            compatibility_mapped=False,
            legacy_compatibility_mode=False,
            safe_diagnostic_message=(
                f"Task alias '{task.task_alias}' remains deterministic/mock-only in Phase 1; no provider model is resolved."
            ),
        )

    resolved = resolve_ai_model_name(
        requested_model_name=requested_model_name,
        admin_default_model_name=admin_default_model_name,
        env_default_model_name=env_default_model_name,
        provider_fallback_model_name=provider_fallback_model_name,
        final_fallback_model_name=final_fallback_model_name,
    )
    validation = inspect_ai_model_identifier(
        resolved.model_name,
        field_name="model",
        task_alias=task.task_alias,
        model_source=resolved.model_source,
        allow_compatibility_legacy=resolved.model_source != "explicit",
    )
    if validation.blocked:
        raise AIModelValidationError(validation.safe_message)
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
        fallback_used=resolved.model_source in {"env", "provider_fallback"},
        compatibility_mapped=True,
        legacy_compatibility_mode=validation.compatibility_allowed,
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
        )
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


def _resolve_known_ai_model_capabilities(model_name: str) -> tuple[AIModelCapability, ...] | None:
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
    if model_name == "omni-moderation-latest" or model_name.startswith("omni-moderation-"):
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
