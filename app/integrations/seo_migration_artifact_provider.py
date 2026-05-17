from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.integrations.ai_execution_core import (
    AIContextBlock,
    AIExecutionError,
    AIExecutionPolicy,
    apply_request_budget,
    execute_json_request,
)
from app.services.seo_migration_prompt import SEO_MIGRATION_PROMPT_VERSION, build_seo_migration_prompt


_DRAFT_REASON_TIMEOUT = "timeout"
_DRAFT_REASON_AUTHENTICATION_FAILED = "authentication_failed"
_DRAFT_REASON_RATE_LIMITED = "rate_limited"
_DRAFT_REASON_MALFORMED_RESPONSE = "malformed_response"
_DRAFT_REASON_MALFORMED_OUTPUT = "malformed_output"
_DRAFT_REASON_EMPTY_RESPONSE = "empty_response"
_DRAFT_REASON_UNSUPPORTED_CONFIGURATION = "unsupported_configuration"
_DRAFT_REASON_TRANSPORT_ERROR = "transport_error"
_DRAFT_REASON_VALIDATION_FAILED = "validation_failed"
_DRAFT_REASON_UNKNOWN = "unknown"
_DRAFT_ERROR_CODE_UNSUPPORTED_REQUEST_SHAPE_INPUT_NON_STRING = "unsupported_request_shape_input_non_string"
_DRAFT_ERROR_CODE_UNSUPPORTED_REQUEST_SHAPE_CONTRACT_DRIFT = "unsupported_request_shape_contract_drift"
_DRAFT_REASON_VALUES = {
    _DRAFT_REASON_TIMEOUT,
    _DRAFT_REASON_AUTHENTICATION_FAILED,
    _DRAFT_REASON_RATE_LIMITED,
    _DRAFT_REASON_MALFORMED_RESPONSE,
    _DRAFT_REASON_MALFORMED_OUTPUT,
    _DRAFT_REASON_EMPTY_RESPONSE,
    _DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
    _DRAFT_REASON_TRANSPORT_ERROR,
    _DRAFT_REASON_VALIDATION_FAILED,
    _DRAFT_REASON_UNKNOWN,
}
_COMPAT_REASON_SUPPORTED = "supported"
_COMPAT_REASON_PROVIDER_NOT_CONFIGURED = "provider_not_configured"
_COMPAT_REASON_UNSUPPORTED_MODEL_CONFIGURATION = "unsupported_model_configuration"
_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE = "unsupported_request_shape"
_COMPAT_REASON_UNSUPPORTED_ENDPOINT_MODE = "unsupported_endpoint_mode"
_COMPAT_REASON_TOOLS_REQUIRED_BUT_UNAVAILABLE = "tools_required_but_unavailable"
_COMPAT_REASON_DEGRADED_MODE_NOT_ALLOWED = "degraded_mode_not_allowed"
_COMPAT_REASON_UNKNOWN_PROVIDER_CAPABILITY = "unknown_provider_capability"
_COMPAT_REASON_VALUES = {
    _COMPAT_REASON_SUPPORTED,
    _COMPAT_REASON_PROVIDER_NOT_CONFIGURED,
    _COMPAT_REASON_UNSUPPORTED_MODEL_CONFIGURATION,
    _COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
    _COMPAT_REASON_UNSUPPORTED_ENDPOINT_MODE,
    _COMPAT_REASON_TOOLS_REQUIRED_BUT_UNAVAILABLE,
    _COMPAT_REASON_DEGRADED_MODE_NOT_ALLOWED,
    _COMPAT_REASON_UNKNOWN_PROVIDER_CAPABILITY,
}
_COMPAT_OPERATOR_MESSAGE_SUPPORTED = "AI configuration is compatible with migration draft generation."
_COMPAT_OPERATOR_MESSAGE_NOT_CONFIGURED = "The current AI configuration does not support migration draft generation."
_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS = (
    "This model/provider setup is not compatible with the current migration request settings."
)
_COMPAT_OPERATOR_MESSAGE_REQUEST_SHAPE = (
    "Current AI model/configuration is not compatible with migration draft generation."
)
_COMPAT_OPERATOR_MESSAGE_FULL_CAPABILITY_REQUIRED = "Full AI capability is required for migration draft generation."
_MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS = "/chat/completions"
_MIGRATION_COMPAT_ENDPOINT_RESPONSES = "/responses"
_MIGRATION_COMPAT_EXECUTION_MODE_FULL = "full"
_MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA = "json_schema"
_MIGRATION_REQUEST_BODY_MODE_CHAT_JSON_SCHEMA = "chat_json_schema"
_MIGRATION_REQUEST_BODY_MODE_RESPONSES_TEXT_FORMAT_JSON_SCHEMA = "responses_text_format_json_schema"
_PROVIDER_LOG_EVENT_REQUEST_START = "seo_migration_draft_provider_request_start"
_PROVIDER_LOG_EVENT_REQUEST_COMPLETE = "seo_migration_draft_provider_request_complete"
_PROVIDER_LOG_EVENT_REQUEST_FAILURE = "seo_migration_draft_provider_request_failure"
_PROVIDER_LOG_EVENT_RESPONSE_PARSE = "seo_migration_draft_provider_response_parse"
_PROVIDER_LOG_EVENT_REQUEST_CONTRACT_GUARD = "seo_migration_draft_provider_request_contract_guard"
_CORRELATION_HEADER_KEYS = (
    "x-request-id",
    "x-openai-request-id",
    "openai-request-id",
    "request-id",
)
_MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR = "json_decode_error"
_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN = "wrapped_in_markdown"
_MALFORMED_OUTPUT_REASON_WRAPPED_IN_PROSE = "wrapped_in_prose"
_MALFORMED_OUTPUT_REASON_PARTIAL_JSON = "partial_json"
_MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE = "invalid_top_level_shape"
_MALFORMED_OUTPUT_REASON_EMPTY = "empty_response"
_MALFORMED_OUTPUT_ALLOWED_REASONS = {
    _MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR,
    _MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,
    _MALFORMED_OUTPUT_REASON_WRAPPED_IN_PROSE,
    _MALFORMED_OUTPUT_REASON_PARTIAL_JSON,
    _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE,
    _MALFORMED_OUTPUT_REASON_EMPTY,
}

_MAX_FILE_COUNT = 12
_MAX_FILE_PATH_LENGTH = 140
_MAX_FILE_CONTENT_LENGTH = 120000
_MAX_PAGE_MAP_ITEMS = 20
_MAX_LIST_ITEMS = 24
_MAX_TEXT_FIELD_LENGTH = 8000
_RESPONSES_CONTRACT_TOP_LEVEL_KEYS = ("input", "model", "text")
_RESPONSES_CONTRACT_TEXT_TOP_LEVEL_KEYS = ("format",)
_RESPONSES_CONTRACT_TEXT_FORMAT_KEYS = ("name", "schema", "strict", "type")
_MIGRATION_DRAFT_CONTEXT_BUDGET_CHARS = 18000
_MIGRATION_DRAFT_CONTEXT_REQUIRED_KEYS = ("site_snapshot", "migration_workspace")
_MIGRATION_DRAFT_CONTEXT_OPTIONAL_TRIM_ORDER = (
    "existing_context_summaries",
    "draft_input_summary",
    "brand_business_facts_snapshot",
    "enriched_content_notes",
    "source_snapshot",
    "media_assets",
    "operator_requirements",
)
_MIGRATION_DRAFT_MAX_TOTAL_INPUT_SIZE = 120000
_MIGRATION_DRAFT_MAX_TRIMMING_PASSES = 7

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SEOMigrationGeneratedFileOutput:
    path: str
    content: str
    media_type: str


@dataclass(frozen=True)
class SEOMigrationArtifactGenerationOutput:
    strategy_summary: str
    page_map: list[dict[str, object]]
    homepage_structure: list[dict[str, object]]
    service_page_suggestions: list[dict[str, object]]
    cta_contact_structure: dict[str, object]
    seo_meta_suggestions: dict[str, object]
    redirect_suggestions: list[dict[str, object]]
    analytics_placeholders: list[dict[str, object]]
    generated_files: list[SEOMigrationGeneratedFileOutput]
    provider_name: str
    model_name: str
    prompt_version: str
    raw_response: str | None = None
    parse_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class SEOMigrationArtifactProviderError(RuntimeError):
    code: str
    safe_message: str
    provider_name: str
    model_name: str
    prompt_version: str
    reason: str | None = None
    retryable: bool | None = None
    correlation_id: str | None = None
    raw_output: str | None = None
    internal_details: dict[str, object] | None = None
    normalized_failure_category: str | None = None
    normalized_failure_reason: str | None = None
    normalized_failure_source: str | None = None
    normalized_retryable: bool | None = None
    attempt_count: int | None = None
    original_input_size: int | None = None
    final_input_size: int | None = None
    trimmed_bytes: int | None = None
    trimming_pass_count: int | None = None
    difficulty_score: int | None = None
    budget_outcome: str | None = None
    retry_suppressed: bool | None = None
    degraded_state: str | None = None

    def __str__(self) -> str:
        return self.safe_message


@dataclass(frozen=True)
class SEOMigrationProviderCompatibilityResult:
    supported: bool
    reason_code: str
    operator_message: str
    admin_summary: str
    retryable: bool
    provider_name: str
    model_name: str
    endpoint_path: str | None = None
    execution_mode: str | None = None
    web_search_enabled: bool | None = None
    degraded_mode: bool | None = None
    response_format_mode: str | None = None
    request_body_mode: str | None = None


@dataclass(frozen=True)
class _MigrationRequestShape:
    model_name: str
    endpoint_path: str
    execution_mode: str
    response_format_mode: str
    request_body_mode: str


@dataclass(frozen=True)
class _MigrationRequestShapeCompatibilityDecision:
    supported: bool
    reason_code: str
    operator_message: str
    admin_summary: str


@dataclass(frozen=True)
class _MigrationRequestShapeMatrixRule:
    rule_id: str
    endpoint_path: str
    execution_mode: str
    response_format_mode: str
    request_body_mode: str
    model_prefixes: tuple[str, ...]
    supported: bool
    reason_code: str
    operator_message: str

    def matches(self, *, shape: _MigrationRequestShape) -> bool:
        if shape.endpoint_path != self.endpoint_path:
            return False
        if shape.execution_mode != self.execution_mode:
            return False
        if shape.response_format_mode != self.response_format_mode:
            return False
        if shape.request_body_mode != self.request_body_mode:
            return False
        if not self.model_prefixes:
            return True
        return any(
            shape.model_name == prefix or shape.model_name.startswith(f"{prefix}-") for prefix in self.model_prefixes
        )

    def to_decision(self, *, shape: _MigrationRequestShape) -> _MigrationRequestShapeCompatibilityDecision:
        return _MigrationRequestShapeCompatibilityDecision(
            supported=self.supported,
            reason_code=self.reason_code,
            operator_message=self.operator_message,
            admin_summary=(
                f"{self.rule_id} reason={self.reason_code} model={shape.model_name} endpoint={shape.endpoint_path} "
                f"mode={shape.execution_mode} response_format={shape.response_format_mode} "
                f"request_body_mode={shape.request_body_mode}"
            ),
        )


_MIGRATION_REQUEST_SHAPE_COMPATIBILITY_MATRIX = (
    _MigrationRequestShapeMatrixRule(
        rule_id="supported_gpt_5_1_responses_json_schema",
        endpoint_path=_MIGRATION_COMPAT_ENDPOINT_RESPONSES,
        execution_mode=_MIGRATION_COMPAT_EXECUTION_MODE_FULL,
        response_format_mode=_MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA,
        request_body_mode=_MIGRATION_REQUEST_BODY_MODE_RESPONSES_TEXT_FORMAT_JSON_SCHEMA,
        model_prefixes=("gpt-5.1",),
        supported=True,
        reason_code=_COMPAT_REASON_SUPPORTED,
        operator_message=_COMPAT_OPERATOR_MESSAGE_SUPPORTED,
    ),
    _MigrationRequestShapeMatrixRule(
        rule_id="blocked_chat_completions_json_schema_for_migration",
        endpoint_path=_MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS,
        execution_mode=_MIGRATION_COMPAT_EXECUTION_MODE_FULL,
        response_format_mode=_MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA,
        request_body_mode=_MIGRATION_REQUEST_BODY_MODE_CHAT_JSON_SCHEMA,
        model_prefixes=("gpt",),
        supported=False,
        reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
        operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SHAPE,
    ),
)


@dataclass(frozen=True)
class _StructuredPayloadRecoveryResult:
    payload: dict[str, object] | None
    reason: str | None
    recovery_actions: tuple[str, ...]


@dataclass(frozen=True)
class _SalvagedMigrationOutput:
    output: SEOMigrationArtifactGenerationOutput
    parsed_candidate_count: int
    salvaged_candidate_count: int
    parse_warnings: tuple[str, ...]


class SEOMigrationArtifactGenerationProvider:
    def get_request_profile(self) -> dict[str, object]:
        return {
            "endpoint_path": None,
            "execution_mode": "full",
            "web_search_enabled": False,
            "degraded_mode": False,
            "response_format_mode": None,
            "request_body_mode": None,
        }

    def evaluate_compatibility(self) -> SEOMigrationProviderCompatibilityResult:
        provider_name = _clean_optional_value(getattr(self, "provider_name", None)) or "unknown"
        model_name = _clean_optional_value(getattr(self, "model_name", None)) or "unknown"
        request_profile = self.get_request_profile()
        return SEOMigrationProviderCompatibilityResult(
            supported=True,
            reason_code=_COMPAT_REASON_SUPPORTED,
            operator_message="AI configuration is compatible with migration draft generation.",
            admin_summary="provider_declared_compatible",
            retryable=False,
            provider_name=provider_name,
            model_name=model_name,
            endpoint_path=_clean_optional_value(request_profile.get("endpoint_path")),
            execution_mode=_clean_optional_value(request_profile.get("execution_mode")),
            web_search_enabled=(
                bool(request_profile.get("web_search_enabled"))
                if isinstance(request_profile.get("web_search_enabled"), bool)
                else None
            ),
            degraded_mode=(
                bool(request_profile.get("degraded_mode"))
                if isinstance(request_profile.get("degraded_mode"), bool)
                else None
            ),
            response_format_mode=_clean_optional_value(request_profile.get("response_format_mode")),
            request_body_mode=_clean_optional_value(request_profile.get("request_body_mode")),
        )

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        raise NotImplementedError


class MisconfiguredSEOMigrationArtifactGenerationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(
        self,
        *,
        provider_name: str,
        model_name: str,
        prompt_version: str,
        safe_message: str,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.safe_message = safe_message

    def evaluate_compatibility(self) -> SEOMigrationProviderCompatibilityResult:
        return SEOMigrationProviderCompatibilityResult(
            supported=False,
            reason_code=_COMPAT_REASON_PROVIDER_NOT_CONFIGURED,
            operator_message="The current AI configuration does not support migration draft generation.",
            admin_summary=_clean_optional_value(self.safe_message) or "provider_misconfigured",
            retryable=False,
            provider_name=_clean_optional_value(self.provider_name) or "unknown",
            model_name=_clean_optional_value(self.model_name) or "unknown",
            endpoint_path=None,
            execution_mode="full",
            web_search_enabled=False,
            degraded_mode=False,
            response_format_mode=None,
            request_body_mode=None,
        )

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        del migration_context
        raise SEOMigrationArtifactProviderError(
            code=_DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
            safe_message=self.safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            reason=_DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
            retryable=False,
        )


class MockSEOMigrationArtifactGenerationProvider(SEOMigrationArtifactGenerationProvider):
    def __init__(
        self,
        *,
        provider_name: str = "mock",
        model_name: str = "mock-seo-migration-v1",
        prompt_version: str = SEO_MIGRATION_PROMPT_VERSION,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.prompt_version = prompt_version

    def get_request_profile(self) -> dict[str, object]:
        return {
            "endpoint_path": "mock://migration-draft",
            "execution_mode": "full",
            "web_search_enabled": False,
            "degraded_mode": False,
            "response_format_mode": "mock_schema",
            "request_body_mode": "mock_schema_payload",
        }

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        site_snapshot = migration_context.get("site_snapshot")
        site_name = "Business"
        if isinstance(site_snapshot, dict):
            raw_name = site_snapshot.get("display_name")
            if isinstance(raw_name, str) and raw_name.strip():
                site_name = raw_name.strip()

        strategy_summary = (
            f"{site_name} migration draft emphasizes clearer service positioning, stronger trust signals, "
            "and explicit conversion pathways with draft-only review gates."
        )

        page_map = [
            {"path": "/", "title": "Homepage", "purpose": "Primary conversion + trust positioning"},
            {"path": "/services.html", "title": "Services", "purpose": "Service specificity and local relevance"},
            {"path": "/contact.html", "title": "Contact", "purpose": "Calls, forms, and service-area clarity"},
        ]
        homepage_structure = [
            {"section": "hero", "headline": f"{site_name} | Reliable Local Service"},
            {"section": "services_overview", "headline": "Services we provide"},
            {"section": "trust_proof", "headline": "Why local customers choose us"},
            {"section": "cta", "headline": "Request service today"},
        ]
        service_page_suggestions = [
            {
                "slug": "fire-protection-installation",
                "title": "Fire Protection Installation",
                "summary": "Scope, process, and compliance highlights for installation work.",
            },
            {
                "slug": "inspection-and-testing",
                "title": "Inspection and Testing",
                "summary": "Routine inspection coverage, intervals, and rapid remediation pathways.",
            },
        ]
        cta_contact_structure = {
            "primary_cta": "Request a Quote",
            "secondary_cta": "Call for Immediate Service",
            "contact_fields": ["name", "email", "phone", "service_need", "city"],
        }
        seo_meta_suggestions = {
            "homepage_title": f"{site_name} | Local Fire Protection Services",
            "homepage_meta_description": (
                f"{site_name} provides local fire protection installation, inspection, and service."
            ),
            "focus_keywords": ["fire protection services", "inspection and testing", "local fire systems"],
        }
        redirect_suggestions = [{"from": "/index.html", "to": "/"}]
        analytics_placeholders = [{"name": "ga4", "placeholder": "<!-- ANALYTICS_PLACEHOLDER -->"}]
        generated_files = [
            SEOMigrationGeneratedFileOutput(
                path="index.html",
                media_type="text/html",
                content=(
                    "<!doctype html>\n"
                    '<html lang="en">\n<head>\n'
                    '  <meta charset="utf-8" />\n'
                    '  <meta name="viewport" content="width=device-width, initial-scale=1" />\n'
                    f"  <title>{site_name} | Local Fire Protection Services</title>\n"
                    '  <meta name="description" content="Local fire protection installation, inspection, and service." />\n'
                    "  <!-- ANALYTICS_PLACEHOLDER -->\n"
                    '  <link rel="stylesheet" href="styles.css" />\n'
                    "</head>\n<body>\n"
                    f"  <header><h1>{site_name}</h1><p>Reliable local fire protection support.</p></header>\n"
                    "  <main>\n"
                    "    <section><h2>Services</h2><p>Installation, inspection, testing, and maintenance.</p></section>\n"
                    '    <section><h2>Contact</h2><p><a href="contact.html">Request service</a></p></section>\n'
                    "  </main>\n"
                    "</body>\n</html>\n"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="services.html",
                media_type="text/html",
                content=(
                    '<!doctype html>\n<html lang="en"><head><meta charset="utf-8" />'
                    '<meta name="viewport" content="width=device-width, initial-scale=1" />'
                    '<title>Services</title><link rel="stylesheet" href="styles.css" /></head>'
                    "<body><h1>Services</h1><p>Detailed service scope and coverage.</p></body></html>\n"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="contact.html",
                media_type="text/html",
                content=(
                    '<!doctype html>\n<html lang="en"><head><meta charset="utf-8" />'
                    '<meta name="viewport" content="width=device-width, initial-scale=1" />'
                    '<title>Contact</title><link rel="stylesheet" href="styles.css" /></head>'
                    "<body><h1>Contact</h1><p>Call or submit a quote request.</p></body></html>\n"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="styles.css",
                media_type="text/css",
                content=(
                    ":root { --bg: #f8f8f6; --text: #1a1a1a; --accent: #c0392b; }\n"
                    "body { font-family: 'Work Sans', system-ui, sans-serif; margin: 0; background: var(--bg); color: var(--text); }\n"
                    "header, main { max-width: 960px; margin: 0 auto; padding: 1.2rem; }\n"
                    "a { color: var(--accent); }\n"
                ),
            ),
        ]

        return SEOMigrationArtifactGenerationOutput(
            strategy_summary=strategy_summary,
            page_map=page_map,
            homepage_structure=homepage_structure,
            service_page_suggestions=service_page_suggestions,
            cta_contact_structure=cta_contact_structure,
            seo_meta_suggestions=seo_meta_suggestions,
            redirect_suggestions=redirect_suggestions,
            analytics_placeholders=analytics_placeholders,
            generated_files=generated_files,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_response=json.dumps(
                {
                    "strategy_summary": strategy_summary,
                    "page_map": page_map,
                    "generated_files": [item.path for item in generated_files],
                },
                ensure_ascii=True,
            ),
        )


class OpenAISEOMigrationArtifactGenerationProvider(SEOMigrationArtifactGenerationProvider):
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: int = 120,
        api_base_url: str = "https://api.openai.com/v1",
        prompt_version: str = SEO_MIGRATION_PROMPT_VERSION,
        prompt_text_recommendations: str = "",
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("OpenAI API key is required")
        self.api_key = normalized_key
        self.model_name = model_name.strip() or "gpt-4o-mini"
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.timeout_source = "default"
        self.api_base_url = api_base_url.rstrip("/")
        self.prompt_version = prompt_version.strip() or SEO_MIGRATION_PROMPT_VERSION
        self.prompt_text_recommendations = prompt_text_recommendations or ""

    def get_request_profile(self) -> dict[str, object]:
        shape = self._resolve_request_shape_for_model(
            model_name=_clean_optional_value(self.model_name) or "unknown",
        )
        return {
            "endpoint_path": shape.endpoint_path,
            "execution_mode": shape.execution_mode,
            "web_search_enabled": False,
            "degraded_mode": False,
            "response_format_mode": shape.response_format_mode,
            "request_body_mode": shape.request_body_mode,
        }

    def evaluate_compatibility(self) -> SEOMigrationProviderCompatibilityResult:
        profile = self.get_request_profile()
        endpoint_path = _clean_optional_value(profile.get("endpoint_path"))
        execution_mode = _clean_optional_value(profile.get("execution_mode")) or _MIGRATION_COMPAT_EXECUTION_MODE_FULL
        web_search_enabled = bool(profile.get("web_search_enabled"))
        degraded_mode = bool(profile.get("degraded_mode"))
        response_format_mode = _clean_optional_value(profile.get("response_format_mode"))
        request_body_mode = _clean_optional_value(profile.get("request_body_mode"))
        provider_name = _clean_optional_value(self.provider_name) or "openai"
        model_name = _clean_optional_value(self.model_name) or "unknown"

        if not _clean_optional_value(self.api_key):
            return SEOMigrationProviderCompatibilityResult(
                supported=False,
                reason_code=_COMPAT_REASON_PROVIDER_NOT_CONFIGURED,
                operator_message=_COMPAT_OPERATOR_MESSAGE_NOT_CONFIGURED,
                admin_summary="openai_api_key_missing",
                retryable=False,
                provider_name=provider_name,
                model_name=model_name,
                endpoint_path=endpoint_path,
                execution_mode=execution_mode,
                web_search_enabled=web_search_enabled,
                degraded_mode=degraded_mode,
                response_format_mode=response_format_mode,
                request_body_mode=request_body_mode,
            )
        if web_search_enabled:
            return SEOMigrationProviderCompatibilityResult(
                supported=False,
                reason_code=_COMPAT_REASON_TOOLS_REQUIRED_BUT_UNAVAILABLE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_FULL_CAPABILITY_REQUIRED,
                admin_summary="migration_request_shape_requires_tools_but_provider_call_is_non_tool",
                retryable=False,
                provider_name=provider_name,
                model_name=model_name,
                endpoint_path=endpoint_path,
                execution_mode=execution_mode,
                web_search_enabled=web_search_enabled,
                degraded_mode=degraded_mode,
                response_format_mode=response_format_mode,
                request_body_mode=request_body_mode,
            )
        if degraded_mode:
            return SEOMigrationProviderCompatibilityResult(
                supported=False,
                reason_code=_COMPAT_REASON_DEGRADED_MODE_NOT_ALLOWED,
                operator_message=_COMPAT_OPERATOR_MESSAGE_FULL_CAPABILITY_REQUIRED,
                admin_summary="degraded_mode_not_allowed_for_migration",
                retryable=False,
                provider_name=provider_name,
                model_name=model_name,
                endpoint_path=endpoint_path,
                execution_mode=execution_mode,
                web_search_enabled=web_search_enabled,
                degraded_mode=degraded_mode,
                response_format_mode=response_format_mode,
                request_body_mode=request_body_mode,
            )

        request_shape_decision = self._evaluate_request_shape_compatibility(
            model_name=model_name,
            endpoint_path=endpoint_path,
            execution_mode=execution_mode,
            response_format_mode=response_format_mode,
            request_body_mode=request_body_mode,
        )
        if not request_shape_decision.supported:
            return SEOMigrationProviderCompatibilityResult(
                supported=False,
                reason_code=request_shape_decision.reason_code,
                operator_message=request_shape_decision.operator_message,
                admin_summary=request_shape_decision.admin_summary,
                retryable=False,
                provider_name=provider_name,
                model_name=model_name,
                endpoint_path=endpoint_path,
                execution_mode=execution_mode,
                web_search_enabled=web_search_enabled,
                degraded_mode=degraded_mode,
                response_format_mode=response_format_mode,
                request_body_mode=request_body_mode,
            )
        request_body_decision = self._evaluate_request_body_compatibility(
            model_name=model_name,
            endpoint_path=endpoint_path,
            execution_mode=execution_mode,
            response_format_mode=response_format_mode,
            request_body_mode=request_body_mode,
        )
        return SEOMigrationProviderCompatibilityResult(
            supported=request_body_decision.supported,
            reason_code=request_body_decision.reason_code,
            operator_message=request_body_decision.operator_message,
            admin_summary=request_body_decision.admin_summary,
            retryable=False,
            provider_name=provider_name,
            model_name=model_name,
            endpoint_path=endpoint_path,
            execution_mode=execution_mode,
            web_search_enabled=web_search_enabled,
            degraded_mode=degraded_mode,
            response_format_mode=response_format_mode,
            request_body_mode=request_body_mode,
        )

    def _evaluate_request_shape_compatibility(
        self,
        *,
        model_name: str,
        endpoint_path: str | None,
        execution_mode: str | None,
        response_format_mode: str | None,
        request_body_mode: str | None,
    ) -> _MigrationRequestShapeCompatibilityDecision:
        shape = self._build_migration_request_shape(
            model_name=model_name,
            endpoint_path=endpoint_path,
            execution_mode=execution_mode,
            response_format_mode=response_format_mode,
            request_body_mode=request_body_mode,
        )
        if shape.execution_mode != _MIGRATION_COMPAT_EXECUTION_MODE_FULL:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_ENDPOINT_MODE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=("execution_mode_unsupported " f"model={shape.model_name} mode={shape.execution_mode}"),
            )
        if shape.endpoint_path not in {
            _MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS,
            _MIGRATION_COMPAT_ENDPOINT_RESPONSES,
        }:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_ENDPOINT_MODE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=("endpoint_path_unsupported " f"model={shape.model_name} endpoint={shape.endpoint_path}"),
            )
        if shape.response_format_mode != _MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_MODEL_CONFIGURATION,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "response_format_mode_unsupported "
                    f"model={shape.model_name} response_format={shape.response_format_mode} "
                    f"request_body_mode={shape.request_body_mode}"
                ),
            )
        if shape.request_body_mode not in {
            _MIGRATION_REQUEST_BODY_MODE_CHAT_JSON_SCHEMA,
            _MIGRATION_REQUEST_BODY_MODE_RESPONSES_TEXT_FORMAT_JSON_SCHEMA,
        }:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "request_body_mode_unsupported "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"request_body_mode={shape.request_body_mode}"
                ),
            )

        for rule in _MIGRATION_REQUEST_SHAPE_COMPATIBILITY_MATRIX:
            if rule.matches(shape=shape):
                return rule.to_decision(shape=shape)

        if not shape.model_name.startswith("gpt-"):
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_MODEL_CONFIGURATION,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "request_shape_model_family_unsupported "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"mode={shape.execution_mode} response_format={shape.response_format_mode} "
                    f"request_body_mode={shape.request_body_mode}"
                ),
            )

        return _MigrationRequestShapeCompatibilityDecision(
            supported=False,
            reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
            operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
            admin_summary=(
                "request_shape_not_allowlisted "
                f"model={shape.model_name} endpoint={shape.endpoint_path} "
                f"mode={shape.execution_mode} response_format={shape.response_format_mode} "
                f"request_body_mode={shape.request_body_mode}"
            ),
        )

    def _evaluate_request_body_compatibility(
        self,
        *,
        model_name: str,
        endpoint_path: str | None,
        execution_mode: str | None,
        response_format_mode: str | None,
        request_body_mode: str | None,
    ) -> _MigrationRequestShapeCompatibilityDecision:
        shape = self._build_migration_request_shape(
            model_name=model_name,
            endpoint_path=endpoint_path,
            execution_mode=execution_mode,
            response_format_mode=response_format_mode,
            request_body_mode=request_body_mode,
        )
        payload = self._build_request_payload(
            system_prompt="migration_preflight_system_prompt",
            user_prompt="migration_preflight_user_prompt",
            request_profile={
                "endpoint_path": shape.endpoint_path,
                "execution_mode": shape.execution_mode,
                "response_format_mode": shape.response_format_mode,
                "request_body_mode": shape.request_body_mode,
            },
        )
        payload_model = _clean_optional_value(payload.get("model"))
        if payload_model is None:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "request_body_missing_model "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} request_body_mode={shape.request_body_mode}"
                ),
            )
        if shape.endpoint_path == _MIGRATION_COMPAT_ENDPOINT_RESPONSES:
            return self._validate_responses_request_body(shape=shape, payload=payload)
        if shape.endpoint_path == _MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS:
            return self._validate_chat_request_body(shape=shape, payload=payload)
        return _MigrationRequestShapeCompatibilityDecision(
            supported=False,
            reason_code=_COMPAT_REASON_UNSUPPORTED_ENDPOINT_MODE,
            operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
            admin_summary=(
                "request_body_endpoint_unknown "
                f"model={shape.model_name} endpoint={shape.endpoint_path} request_body_mode={shape.request_body_mode}"
            ),
        )

    def _validate_responses_request_body(
        self,
        *,
        shape: _MigrationRequestShape,
        payload: dict[str, object],
    ) -> _MigrationRequestShapeCompatibilityDecision:
        if shape.request_body_mode != _MIGRATION_REQUEST_BODY_MODE_RESPONSES_TEXT_FORMAT_JSON_SCHEMA:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_mode_mismatch "
                    f"model={shape.model_name} request_body_mode={shape.request_body_mode}"
                ),
            )
        input_payload = payload.get("input")
        if not isinstance(input_payload, str):
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_input_non_string "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"input_type={type(input_payload).__name__}"
                ),
            )
        if not input_payload.strip():
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_input_empty " f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        text_payload = payload.get("text")
        format_payload = text_payload.get("format") if isinstance(text_payload, dict) else None
        if not self._is_json_schema_format_payload(format_payload):
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_json_schema_invalid "
                    f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        if "messages" in payload:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_contains_legacy_messages "
                    f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        if "response_format" in payload:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_contains_legacy_response_format "
                    f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        if "tools" in payload:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_contains_tools " f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        top_level_keys = tuple(sorted(str(key) for key in payload.keys()))
        if top_level_keys != _RESPONSES_CONTRACT_TOP_LEVEL_KEYS:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_top_level_keys_mismatch "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"top_level_keys={list(top_level_keys)}"
                ),
            )
        text_top_level_keys = (
            tuple(sorted(str(key) for key in text_payload.keys())) if isinstance(text_payload, dict) else ()
        )
        if text_top_level_keys != _RESPONSES_CONTRACT_TEXT_TOP_LEVEL_KEYS:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_text_keys_mismatch "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"text_keys={list(text_top_level_keys)}"
                ),
            )
        text_format_keys = (
            tuple(sorted(str(key) for key in format_payload.keys())) if isinstance(format_payload, dict) else ()
        )
        if text_format_keys != _RESPONSES_CONTRACT_TEXT_FORMAT_KEYS:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_text_format_keys_mismatch "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"text_format_keys={list(text_format_keys)}"
                ),
            )
        schema_payload = format_payload.get("schema") if isinstance(format_payload, dict) else None
        (
            object_nodes_total,
            object_nodes_non_false,
            object_nodes_missing_required,
        ) = self._count_schema_object_nodes(schema_payload)
        if object_nodes_total <= 0 or object_nodes_non_false > 0:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_schema_additional_properties_not_false "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"object_nodes_total={object_nodes_total} object_nodes_non_false={object_nodes_non_false}"
                ),
            )
        if object_nodes_missing_required > 0:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "responses_request_body_schema_required_fields_incomplete "
                    f"model={shape.model_name} endpoint={shape.endpoint_path} "
                    f"object_nodes_total={object_nodes_total} "
                    f"object_nodes_missing_required={object_nodes_missing_required}"
                ),
            )
        return _MigrationRequestShapeCompatibilityDecision(
            supported=True,
            reason_code=_COMPAT_REASON_SUPPORTED,
            operator_message=_COMPAT_OPERATOR_MESSAGE_SUPPORTED,
            admin_summary=(
                "request_body_validated "
                f"model={shape.model_name} endpoint={shape.endpoint_path} "
                f"mode={shape.execution_mode} response_format={shape.response_format_mode} "
                f"request_body_mode={shape.request_body_mode}"
            ),
        )

    def _validate_chat_request_body(
        self,
        *,
        shape: _MigrationRequestShape,
        payload: dict[str, object],
    ) -> _MigrationRequestShapeCompatibilityDecision:
        if shape.request_body_mode != _MIGRATION_REQUEST_BODY_MODE_CHAT_JSON_SCHEMA:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "chat_request_body_mode_mismatch "
                    f"model={shape.model_name} request_body_mode={shape.request_body_mode}"
                ),
            )
        messages = payload.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "chat_request_body_invalid_messages " f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        if not self._messages_include_system_and_user(messages):
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "chat_request_body_missing_roles " f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        format_payload = payload.get("response_format")
        json_schema_payload = format_payload.get("json_schema") if isinstance(format_payload, dict) else None
        if not self._is_chat_json_schema_payload(format_payload, json_schema_payload):
            return _MigrationRequestShapeCompatibilityDecision(
                supported=False,
                reason_code=_COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                operator_message=_COMPAT_OPERATOR_MESSAGE_REQUEST_SETTINGS,
                admin_summary=(
                    "chat_request_body_json_schema_invalid " f"model={shape.model_name} endpoint={shape.endpoint_path}"
                ),
            )
        return _MigrationRequestShapeCompatibilityDecision(
            supported=True,
            reason_code=_COMPAT_REASON_SUPPORTED,
            operator_message=_COMPAT_OPERATOR_MESSAGE_SUPPORTED,
            admin_summary=(
                "request_body_validated "
                f"model={shape.model_name} endpoint={shape.endpoint_path} "
                f"mode={shape.execution_mode} response_format={shape.response_format_mode} "
                f"request_body_mode={shape.request_body_mode}"
            ),
        )

    @staticmethod
    def _build_migration_request_shape(
        *,
        model_name: str,
        endpoint_path: str | None,
        execution_mode: str | None,
        response_format_mode: str | None,
        request_body_mode: str | None,
    ) -> _MigrationRequestShape:
        return _MigrationRequestShape(
            model_name=(model_name or "").strip().lower() or "unknown",
            endpoint_path=(endpoint_path or "").strip().lower(),
            execution_mode=(execution_mode or "").strip().lower() or _MIGRATION_COMPAT_EXECUTION_MODE_FULL,
            response_format_mode=(response_format_mode or "").strip().lower(),
            request_body_mode=(request_body_mode or "").strip().lower(),
        )

    @staticmethod
    def _resolve_request_shape_for_model(*, model_name: str) -> _MigrationRequestShape:
        normalized_model = (model_name or "").strip().lower() or "unknown"
        if normalized_model == "gpt-5.1" or normalized_model.startswith("gpt-5.1-"):
            return _MigrationRequestShape(
                model_name=normalized_model,
                endpoint_path=_MIGRATION_COMPAT_ENDPOINT_RESPONSES,
                execution_mode=_MIGRATION_COMPAT_EXECUTION_MODE_FULL,
                response_format_mode=_MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA,
                request_body_mode=_MIGRATION_REQUEST_BODY_MODE_RESPONSES_TEXT_FORMAT_JSON_SCHEMA,
            )
        return _MigrationRequestShape(
            model_name=normalized_model,
            endpoint_path=_MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS,
            execution_mode=_MIGRATION_COMPAT_EXECUTION_MODE_FULL,
            response_format_mode=_MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA,
            request_body_mode=_MIGRATION_REQUEST_BODY_MODE_CHAT_JSON_SCHEMA,
        )

    @staticmethod
    def _messages_include_system_and_user(messages: list[object]) -> bool:
        roles_seen: set[str] = set()
        for item in messages:
            if not isinstance(item, dict):
                continue
            role = _clean_optional_value(item.get("role"))
            content = item.get("content")
            if role is None:
                continue
            if isinstance(content, str) and content.strip():
                roles_seen.add(role)
                continue
            if isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        roles_seen.add(role)
                        break
        return "system" in roles_seen and "user" in roles_seen

    @staticmethod
    def _is_json_schema_format_payload(payload: object) -> bool:
        if not isinstance(payload, dict):
            return False
        if _clean_optional_value(payload.get("type")) != "json_schema":
            return False
        schema_name = _clean_optional_value(payload.get("name"))
        strict_value = payload.get("strict")
        schema_payload = payload.get("schema")
        return (
            bool(schema_name) and isinstance(strict_value, bool) and strict_value and isinstance(schema_payload, dict)
        )

    @staticmethod
    def _is_chat_json_schema_payload(format_payload: object, schema_payload: object) -> bool:
        if not isinstance(format_payload, dict):
            return False
        if _clean_optional_value(format_payload.get("type")) != "json_schema":
            return False
        if not isinstance(schema_payload, dict):
            return False
        name = _clean_optional_value(schema_payload.get("name"))
        strict_value = schema_payload.get("strict")
        schema = schema_payload.get("schema")
        return bool(name) and isinstance(strict_value, bool) and strict_value and isinstance(schema, dict)

    @classmethod
    def _count_schema_object_nodes(cls, schema_payload: object) -> tuple[int, int, int]:
        object_nodes_total = 0
        object_nodes_non_false = 0
        object_nodes_missing_required = 0
        stack: list[object] = [schema_payload]
        while stack:
            candidate = stack.pop()
            if not isinstance(candidate, dict):
                continue
            candidate_type = candidate.get("type")
            is_object_node = candidate_type == "object" or (
                isinstance(candidate_type, list) and "object" in candidate_type
            )
            if is_object_node:
                object_nodes_total += 1
                if candidate.get("additionalProperties") is not False:
                    object_nodes_non_false += 1
                properties = candidate.get("properties")
                if isinstance(properties, dict) and properties:
                    property_keys = {str(key) for key in properties.keys()}
                    required_raw = candidate.get("required")
                    if not isinstance(required_raw, list):
                        object_nodes_missing_required += 1
                    else:
                        required_keys = {str(item) for item in required_raw if isinstance(item, str)}
                        if required_keys != property_keys:
                            object_nodes_missing_required += 1

            properties = candidate.get("properties")
            if isinstance(properties, dict):
                stack.extend(properties.values())

            items = candidate.get("items")
            if isinstance(items, dict):
                stack.append(items)
            elif isinstance(items, list):
                stack.extend(items)

            for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
                nested_list = candidate.get(key)
                if isinstance(nested_list, list):
                    stack.extend(nested_list)

            additional_properties = candidate.get("additionalProperties")
            if isinstance(additional_properties, dict):
                stack.append(additional_properties)

        return object_nodes_total, object_nodes_non_false, object_nodes_missing_required

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        budgeted_context, budget_result = self._apply_migration_context_budget(migration_context)
        request_context = self._build_request_context(migration_context)
        if bool(budget_result.get("overflow")) or (
            isinstance(budget_result.get("trimming_pass_count"), int)
            and int(budget_result.get("trimming_pass_count") or 0) > _MIGRATION_DRAFT_MAX_TRIMMING_PASSES
        ):
            self._log_request_budget(
                request_context=request_context,
                budget_result=budget_result,
                budget_outcome="precall_rejected",
            )
            self._log_provider_request_failure(
                request_context=request_context,
                reason=_DRAFT_REASON_VALIDATION_FAILED,
                retryable=False,
                failure_source="local_preflight",
                request_fingerprint={"context_budget": budget_result},
            )
            raise self._provider_error(
                code=_DRAFT_REASON_VALIDATION_FAILED,
                reason=_DRAFT_REASON_VALIDATION_FAILED,
                safe_message=(
                    "Migration draft request is too large or complex for synchronous generation. "
                    "Reduce optional context and try again."
                ),
                retryable=False,
                internal_details={
                    "request_failure_logged": False,
                    "normalized_failure_category": "local_validation_failure",
                    "normalized_failure_reason": "request_too_large_or_complex",
                    "normalized_failure_source": "local_validation",
                    "normalized_retryable": False,
                    "attempt_count": 0,
                    "context_budget": budget_result,
                },
                normalized_failure_category="local_validation_failure",
                normalized_failure_reason="request_too_large_or_complex",
                normalized_failure_source="local_validation",
                normalized_retryable=False,
                attempt_count=0,
            )
        prompt = build_seo_migration_prompt(
            migration_context=budgeted_context,
            prompt_version=self.prompt_version,
            prompt_text_recommendations=self.prompt_text_recommendations,
        )
        payload = self._build_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            request_profile=request_context,
        )
        request_fingerprint = self._build_request_fingerprint(
            payload=payload,
            request_context=request_context,
        )
        request_fingerprint["context_budget"] = budget_result
        self._log_request_budget(
            request_context=request_context,
            budget_result=budget_result,
            budget_outcome="provider_submission",
        )
        started_at = time.perf_counter()
        try:
            self._validate_runtime_request_payload_shape(
                payload=payload,
                request_context=request_context,
                request_fingerprint=request_fingerprint,
            )
            raw_response = self._request_completion(
                payload,
                request_context=request_context,
                request_fingerprint=request_fingerprint,
            )
            response_json = self._parse_json_object(
                raw_response,
                reason=_DRAFT_REASON_MALFORMED_RESPONSE,
                safe_message="Migration draft response could not be parsed.",
            )
            endpoint_path = _clean_optional_value((request_context or {}).get("endpoint_path"))
            if endpoint_path == _MIGRATION_COMPAT_ENDPOINT_RESPONSES:
                assistant_content = self._extract_assistant_content_from_responses(response_json)
            else:
                assistant_content = self._extract_assistant_content(response_json)
            raw_length = max(0, len(assistant_content))
            structured_json, parse_warnings, malformed_output_reason = self._parse_structured_json_output(
                assistant_content,
                reason=_DRAFT_REASON_MALFORMED_OUTPUT,
                safe_message="Migration draft returned malformed output.",
                raw_output=assistant_content,
            )
            model_name = _clean_optional_value(response_json.get("model")) or self.model_name
            parsed_candidate_count = self._count_generated_file_candidates(structured_json)
            salvaged_candidate_count = max(
                0,
                int(parsed_candidate_count if parse_warnings else 0),
            )
            try:
                parsed = _OpenAIMigrationResponse.model_validate(structured_json)
            except ValidationError as exc:
                salvaged = self._salvage_generation_output(
                    payload=structured_json,
                    model_name=model_name,
                    prompt_version=prompt.prompt_version,
                    raw_response=assistant_content,
                )
                if salvaged is not None:
                    parsed_candidate_count = max(parsed_candidate_count, salvaged.parsed_candidate_count)
                    salvaged_candidate_count += max(0, int(salvaged.salvaged_candidate_count))
                    combined_warnings = tuple([*parse_warnings, *salvaged.parse_warnings])
                    self._log_provider_response_parse(
                        request_context=request_context,
                        status="partial",
                        raw_length=raw_length,
                        parsed_candidate_count=parsed_candidate_count,
                        salvaged_candidate_count=salvaged_candidate_count,
                        malformed_output_reason=(
                            malformed_output_reason or _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE
                        ),
                    )
                    output = salvaged.output
                    return SEOMigrationArtifactGenerationOutput(
                        strategy_summary=output.strategy_summary,
                        page_map=output.page_map,
                        homepage_structure=output.homepage_structure,
                        service_page_suggestions=output.service_page_suggestions,
                        cta_contact_structure=output.cta_contact_structure,
                        seo_meta_suggestions=output.seo_meta_suggestions,
                        redirect_suggestions=output.redirect_suggestions,
                        analytics_placeholders=output.analytics_placeholders,
                        generated_files=output.generated_files,
                        provider_name=output.provider_name,
                        model_name=output.model_name,
                        prompt_version=output.prompt_version,
                        raw_response=assistant_content,
                        parse_warnings=combined_warnings,
                    )

                self._log_provider_response_parse(
                    request_context=request_context,
                    status="failed",
                    raw_length=raw_length,
                    parsed_candidate_count=parsed_candidate_count,
                    salvaged_candidate_count=0,
                    malformed_output_reason=(
                        malformed_output_reason or _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE
                    ),
                )
                raise self._provider_error(
                    code=_DRAFT_REASON_VALIDATION_FAILED,
                    reason=_DRAFT_REASON_VALIDATION_FAILED,
                    safe_message="Migration draft returned invalid structured output.",
                    retryable=True,
                    raw_output=assistant_content,
                    internal_details={
                        "raw_length": raw_length,
                        "parsed_candidate_count": parsed_candidate_count,
                        "salvaged_candidate_count": 0,
                        "malformed_output_reason": (
                            malformed_output_reason or _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE
                        ),
                    },
                ) from exc

            files = [
                SEOMigrationGeneratedFileOutput(path=item.path, content=item.content, media_type=item.media_type)
                for item in parsed.generated_files
            ]
            parsed_candidate_count = max(parsed_candidate_count, len(files))
            self._log_provider_response_parse(
                request_context=request_context,
                status="completed",
                raw_length=raw_length,
                parsed_candidate_count=parsed_candidate_count,
                salvaged_candidate_count=salvaged_candidate_count,
                malformed_output_reason=malformed_output_reason,
            )
            return SEOMigrationArtifactGenerationOutput(
                strategy_summary=parsed.strategy_summary,
                page_map=[item.model_dump(mode="json") for item in parsed.page_map],
                homepage_structure=[item.model_dump(mode="json") for item in parsed.homepage_structure],
                service_page_suggestions=[item.model_dump(mode="json") for item in parsed.service_page_suggestions],
                cta_contact_structure=parsed.cta_contact_structure or {},
                seo_meta_suggestions=parsed.seo_meta_suggestions or {},
                redirect_suggestions=[item.model_dump(mode="json") for item in parsed.redirect_suggestions],
                analytics_placeholders=[item.model_dump(mode="json") for item in parsed.analytics_placeholders],
                generated_files=files,
                provider_name=self.provider_name,
                model_name=model_name,
                prompt_version=prompt.prompt_version,
                raw_response=assistant_content,
                parse_warnings=parse_warnings,
            )
        except SEOMigrationArtifactProviderError as exc:
            already_logged = bool((exc.internal_details or {}).get("request_failure_logged"))
            if not already_logged:
                details = exc.internal_details or {}
                self._log_provider_request_failure(
                    request_context=request_context,
                    reason=exc.reason,
                    retryable=exc.retryable,
                    correlation_id=exc.correlation_id,
                    duration_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    request_fingerprint=request_fingerprint,
                    parsed_candidate_count=self._coerce_optional_non_negative_int(
                        details.get("parsed_candidate_count"),
                    ),
                    salvaged_candidate_count=self._coerce_optional_non_negative_int(
                        details.get("salvaged_candidate_count"),
                    ),
                    malformed_output_reason=self._normalize_malformed_output_reason(
                        details.get("malformed_output_reason"),
                    ),
                    raw_length=self._coerce_optional_non_negative_int(details.get("raw_length")),
                )
            raise

    def _request_completion(
        self,
        payload: dict[str, object],
        *,
        request_context: dict[str, object] | None = None,
        request_fingerprint: dict[str, object] | None = None,
    ) -> str:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        endpoint_path = _clean_optional_value((request_context or {}).get("endpoint_path")) or "/chat/completions"
        request_shape_details = self._request_shape_details(request_context=request_context)
        request = urllib.request.Request(
            url=f"{self.api_base_url}{endpoint_path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        self._log_provider_request_start(
            request_context=request_context,
            endpoint_path=endpoint_path,
            request_fingerprint=request_fingerprint,
        )
        try:
            context_budget = (
                request_fingerprint.get("context_budget")
                if isinstance(request_fingerprint, dict) and isinstance(request_fingerprint.get("context_budget"), dict)
                else {}
            )
            execution_response = execute_json_request(
                request=request,
                policy=AIExecutionPolicy(
                    feature_area="migration_draft",
                    timeout_seconds=max(1, int(self.timeout_seconds)),
                    max_attempts=2,
                    retry_backoff_seconds=0.2,
                    max_input_size=_MIGRATION_DRAFT_MAX_TOTAL_INPUT_SIZE,
                    original_input_size=context_budget.get("initial_size_bytes"),
                    final_input_size=context_budget.get("final_size_bytes"),
                    trimming_pass_count=(
                        int(context_budget.get("trimming_pass_count"))
                        if isinstance(context_budget.get("trimming_pass_count"), int)
                        else 0
                    ),
                    section_count=context_budget.get("section_count"),
                    schema_complexity_flag=(
                        self._coerce_optional_non_negative_int(
                            (
                                request_fingerprint.get("schema_object_nodes_total")
                                if isinstance(request_fingerprint, dict)
                                else None
                            ),
                        )
                        or 0
                    )
                    >= 10,
                ),
                extract_correlation_id=self._extract_response_correlation_id,
            )
            self._log_provider_request_complete(
                request_context=request_context,
                endpoint_path=endpoint_path,
                duration_ms=execution_response.duration_ms,
                correlation_id=execution_response.correlation_id,
                request_fingerprint=request_fingerprint,
            )
            return execution_response.body_text
        except AIExecutionError as exc:
            reason, safe_message = self._migration_reason_from_execution_error(exc)
            retryable = (
                bool(exc.normalized_failure.retryable) if isinstance(exc.normalized_failure.retryable, bool) else None
            )
            http_status = (
                int(exc.normalized_failure.http_status) if isinstance(exc.normalized_failure.http_status, int) else None
            )
            self._log_provider_request_failure(
                request_context=request_context,
                reason=reason,
                retryable=retryable,
                correlation_id=exc.correlation_id,
                duration_ms=exc.duration_ms,
                http_status=http_status,
                request_fingerprint=request_fingerprint,
            )
            raise self._provider_error(
                code=reason,
                reason=reason,
                safe_message=safe_message,
                retryable=retryable,
                correlation_id=exc.correlation_id,
                raw_output=exc.raw_response_text,
                internal_details={
                    "request_failure_logged": True,
                    "http_status": http_status,
                    "attempt_count": max(1, int(exc.attempt_count)),
                    "normalized_failure_category": exc.normalized_failure.category,
                    "normalized_failure_reason": exc.normalized_failure.reason,
                    "normalized_failure_source": exc.normalized_failure.source,
                    "normalized_retryable": bool(exc.normalized_failure.retryable),
                    "normalized_timeout_type": _clean_optional_value(exc.normalized_failure.timeout_type),
                    "original_input_size": self._coerce_optional_non_negative_int(exc.original_input_size),
                    "final_input_size": self._coerce_optional_non_negative_int(exc.final_input_size),
                    "trimmed_bytes": self._coerce_optional_non_negative_int(exc.trimmed_bytes),
                    "trimming_pass_count": self._coerce_optional_non_negative_int(exc.trimming_pass_count),
                    "difficulty_score": self._coerce_optional_non_negative_int(exc.difficulty_score),
                    "context_budget": context_budget,
                    "context_budget_size_chars": self._coerce_optional_non_negative_int(
                        context_budget.get("budget_size_chars"),
                    ),
                    "largest_context_block": _clean_optional_value(context_budget.get("largest_retained_block")),
                    "largest_context_block_size_chars": self._coerce_optional_non_negative_int(
                        context_budget.get("largest_retained_block_size_chars"),
                    ),
                    "budget_outcome": (
                        "retry_suppressed"
                        if exc.normalized_failure.reason == "request_too_large_or_complex"
                        else (
                            "precall_rejected"
                            if exc.normalized_failure.reason == "request_too_large"
                            else (
                                "trimmed_provider_submission"
                                if (isinstance(exc.trimming_pass_count, int) and exc.trimming_pass_count > 0)
                                or (isinstance(exc.trimmed_bytes, int) and exc.trimmed_bytes > 0)
                                else "provider_submission"
                            )
                        )
                    ),
                    "retry_suppressed": exc.normalized_failure.reason == "request_too_large_or_complex",
                    **request_shape_details,
                },
                normalized_failure_category=exc.normalized_failure.category,
                normalized_failure_reason=exc.normalized_failure.reason,
                normalized_failure_source=exc.normalized_failure.source,
                normalized_retryable=bool(exc.normalized_failure.retryable),
                attempt_count=max(1, int(exc.attempt_count)),
                original_input_size=exc.original_input_size,
                final_input_size=exc.final_input_size,
                trimmed_bytes=exc.trimmed_bytes,
                trimming_pass_count=exc.trimming_pass_count,
                difficulty_score=exc.difficulty_score,
                budget_outcome=(
                    "retry_suppressed"
                    if exc.normalized_failure.reason == "request_too_large_or_complex"
                    else (
                        "precall_rejected"
                        if exc.normalized_failure.reason == "request_too_large"
                        else (
                            "trimmed_provider_submission"
                            if (isinstance(exc.trimming_pass_count, int) and exc.trimming_pass_count > 0)
                            or (isinstance(exc.trimmed_bytes, int) and exc.trimmed_bytes > 0)
                            else "provider_submission"
                        )
                    )
                ),
                retry_suppressed=exc.normalized_failure.reason == "request_too_large_or_complex",
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive unexpected boundary
            self._log_provider_request_failure(
                request_context=request_context,
                reason=_DRAFT_REASON_UNKNOWN,
                retryable=None,
                request_fingerprint=request_fingerprint,
            )
            raise self._provider_error(
                code=_DRAFT_REASON_UNKNOWN,
                reason=_DRAFT_REASON_UNKNOWN,
                safe_message="Migration draft generation failed due to an unexpected AI provider error.",
                retryable=None,
                internal_details={
                    "request_failure_logged": True,
                    **request_shape_details,
                },
            ) from exc

    def _build_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        request_profile: dict[str, object] | None = None,
    ) -> dict[str, object]:
        profile = request_profile or self.get_request_profile()
        endpoint_path = (
            _clean_optional_value(profile.get("endpoint_path")) or _MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS
        )
        request_body_mode = _clean_optional_value(profile.get("request_body_mode"))
        if endpoint_path == _MIGRATION_COMPAT_ENDPOINT_RESPONSES:
            return self._build_responses_request_payload(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                request_body_mode=request_body_mode,
            )
        return self._build_chat_completions_request_payload(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            request_body_mode=request_body_mode,
        )

    def build_redacted_request_snapshot(
        self,
        *,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self._redact_request_payload(payload=payload)

    def serialize_redacted_request_snapshot(
        self,
        *,
        payload: dict[str, object],
    ) -> str:
        snapshot = self.build_redacted_request_snapshot(payload=payload)
        return json.dumps(snapshot, ensure_ascii=True, sort_keys=True)

    def _build_responses_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        request_body_mode: str | None,
    ) -> dict[str, object]:
        del request_body_mode
        return {
            "model": self.model_name,
            "input": self._build_responses_input_text(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
            ),
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "seo_migration_artifact_response",
                    "strict": True,
                    "schema": _build_migration_json_schema(),
                }
            },
        }

    @staticmethod
    def _build_responses_input_text(*, system_prompt: str, user_prompt: str) -> str:
        normalized_system = str(system_prompt or "").strip()
        normalized_user = str(user_prompt or "").strip()
        sections: list[str] = []
        if normalized_system:
            sections.append(f"System Instructions:\n{normalized_system}")
        if normalized_user:
            sections.append(f"User Request:\n{normalized_user}")
        combined = "\n\n".join(section for section in sections if section).strip()
        if combined:
            return combined
        fallback = "\n\n".join(part for part in (normalized_system, normalized_user) if part).strip()
        if fallback:
            return fallback
        return "Generate migration draft artifacts as structured JSON output."

    def _validate_runtime_request_payload_shape(
        self,
        *,
        payload: dict[str, object],
        request_context: dict[str, object] | None,
        request_fingerprint: dict[str, object] | None,
    ) -> None:
        context = request_context or {}
        endpoint_path = _clean_optional_value(context.get("endpoint_path"))
        response_format_mode = _clean_optional_value(context.get("response_format_mode"))
        request_body_mode = _clean_optional_value(context.get("request_body_mode"))
        if endpoint_path != _MIGRATION_COMPAT_ENDPOINT_RESPONSES:
            return
        if response_format_mode != _MIGRATION_COMPAT_RESPONSE_FORMAT_JSON_SCHEMA:
            return
        if request_body_mode != _MIGRATION_REQUEST_BODY_MODE_RESPONSES_TEXT_FORMAT_JSON_SCHEMA:
            return

        input_payload = payload.get("input")
        if isinstance(input_payload, str) and input_payload.strip():
            blocking_codes, warning_codes = self._evaluate_responses_contract_fingerprint(
                request_fingerprint=request_fingerprint,
            )
            if blocking_codes or warning_codes:
                self._log_provider_request_contract_guard(
                    request_context=request_context,
                    request_fingerprint=request_fingerprint,
                    blocking_codes=blocking_codes,
                    warning_codes=warning_codes,
                )
            if not blocking_codes:
                return
            reason_code = _DRAFT_ERROR_CODE_UNSUPPORTED_REQUEST_SHAPE_CONTRACT_DRIFT
            request_shape_details = self._request_shape_details(request_context=request_context)
            self._log_provider_request_failure(
                request_context=request_context,
                reason=_DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
                retryable=False,
                request_fingerprint=request_fingerprint,
                failure_source="local_preflight",
            )
            raise self._provider_error(
                code=reason_code,
                reason=_DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
                safe_message="AI provider configuration is invalid for migration draft generation.",
                retryable=False,
                internal_details={
                    "request_failure_logged": True,
                    "compatibility_reason_code": _COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                    "contract_drift_blocking_codes": list(blocking_codes),
                    "contract_drift_warning_codes": list(warning_codes),
                    **request_shape_details,
                },
            )

        reason_code = _DRAFT_ERROR_CODE_UNSUPPORTED_REQUEST_SHAPE_INPUT_NON_STRING
        request_shape_details = self._request_shape_details(request_context=request_context)
        input_mode = _clean_optional_value((request_fingerprint or {}).get("input_mode"))
        self._log_provider_request_failure(
            request_context=request_context,
            reason=_DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
            retryable=False,
            request_fingerprint=request_fingerprint,
            failure_source="local_preflight",
        )
        raise self._provider_error(
            code=reason_code,
            reason=_DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
            safe_message="AI provider configuration is invalid for migration draft generation.",
            retryable=False,
            internal_details={
                "request_failure_logged": True,
                "compatibility_reason_code": _COMPAT_REASON_UNSUPPORTED_REQUEST_SHAPE,
                "input_mode": input_mode,
                **request_shape_details,
            },
        )

    @staticmethod
    def _evaluate_responses_contract_fingerprint(
        *,
        request_fingerprint: dict[str, object] | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        fingerprint = request_fingerprint or {}
        blocking: list[str] = []
        warnings: list[str] = []

        top_level_keys = tuple(
            sorted(str(item) for item in fingerprint.get("top_level_keys", []) if isinstance(item, str))
        )
        if top_level_keys != _RESPONSES_CONTRACT_TOP_LEVEL_KEYS:
            blocking.append("top_level_keys_mismatch")

        text_top_level_keys = tuple(
            sorted(str(item) for item in fingerprint.get("text_top_level_keys", []) if isinstance(item, str))
        )
        if text_top_level_keys != _RESPONSES_CONTRACT_TEXT_TOP_LEVEL_KEYS:
            blocking.append("text_top_level_keys_mismatch")

        text_format_keys = tuple(
            sorted(str(item) for item in fingerprint.get("text_format_keys", []) if isinstance(item, str))
        )
        if text_format_keys != _RESPONSES_CONTRACT_TEXT_FORMAT_KEYS:
            blocking.append("text_format_keys_mismatch")

        if _clean_optional_value(fingerprint.get("input_mode")) != "string":
            blocking.append("input_mode_non_string")
        if bool(fingerprint.get("contains_tools")):
            blocking.append("contains_tools")
        if bool(fingerprint.get("contains_response_format_legacy")):
            blocking.append("contains_response_format_legacy")
        if bool(fingerprint.get("contains_messages_legacy")):
            blocking.append("contains_messages_legacy")
        if bool(fingerprint.get("has_extra_request_options")):
            blocking.append("has_extra_request_options")
        if bool(fingerprint.get("has_null_optional_fields")):
            blocking.append("has_null_optional_fields")
        if _clean_optional_value(fingerprint.get("text_format_type")) != "json_schema":
            blocking.append("text_format_type_mismatch")
        if _clean_optional_value(fingerprint.get("schema_name")) != "seo_migration_artifact_response":
            blocking.append("schema_name_mismatch")
        if bool(fingerprint.get("strict_enabled")) is not True:
            blocking.append("strict_enabled_mismatch")
        if int(fingerprint.get("schema_object_nodes_non_false_additional_properties") or 0) > 0:
            blocking.append("schema_additional_properties_non_false")
        if int(fingerprint.get("schema_object_nodes_missing_required") or 0) > 0:
            blocking.append("schema_object_nodes_missing_required")

        input_length_chars = fingerprint.get("input_length_chars")
        if isinstance(input_length_chars, int):
            if input_length_chars <= 0:
                blocking.append("input_length_non_positive")
            elif input_length_chars < 128:
                warnings.append("input_length_short")
        else:
            blocking.append("input_length_missing")

        return tuple(sorted(set(blocking))), tuple(sorted(set(warnings)))

    def _log_provider_request_contract_guard(
        self,
        *,
        request_context: dict[str, object] | None,
        request_fingerprint: dict[str, object] | None,
        blocking_codes: tuple[str, ...],
        warning_codes: tuple[str, ...],
    ) -> None:
        context = request_context or {}
        self._emit_structured_provider_log(
            level=(logging.WARNING if blocking_codes else logging.INFO),
            event=_PROVIDER_LOG_EVENT_REQUEST_CONTRACT_GUARD,
            payload={
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "endpoint_path": _clean_optional_value(context.get("endpoint_path")),
                "execution_mode": _clean_optional_value(context.get("execution_mode")) or "full",
                "response_format_mode": _clean_optional_value(context.get("response_format_mode")),
                "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
                "blocking_codes": list(blocking_codes),
                "warning_codes": list(warning_codes),
                **self._request_fingerprint_log_fields(request_fingerprint),
            },
        )

    def _build_chat_completions_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        request_body_mode: str | None,
    ) -> dict[str, object]:
        del request_body_mode
        return {
            "model": self.model_name,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "seo_migration_artifact_response",
                    "strict": True,
                    "schema": _build_migration_json_schema(),
                },
            },
        }

    def _redact_request_payload(self, *, payload: object) -> object:
        if isinstance(payload, dict):
            redacted: dict[str, object] = {}
            for key, value in payload.items():
                if key == "input":
                    redacted[key] = self._redact_request_input_value(value)
                    continue
                if key == "messages":
                    redacted[key] = self._redact_legacy_messages_value(value)
                    continue
                redacted[key] = self._redact_request_payload(payload=value)
            return redacted
        if isinstance(payload, list):
            return [self._redact_request_payload(payload=item) for item in payload]
        return payload

    def _redact_request_input_value(self, value: object) -> object:
        if isinstance(value, str):
            return f"<redacted_string:{len(value)} chars>"
        if isinstance(value, list):
            return [self._redact_request_payload(payload=item) for item in value]
        if isinstance(value, dict):
            return self._redact_request_payload(payload=value)
        return value

    def _redact_legacy_messages_value(self, value: object) -> object:
        if not isinstance(value, list):
            return value
        redacted_messages: list[object] = []
        for item in value:
            if not isinstance(item, dict):
                redacted_messages.append(item)
                continue
            message_payload = dict(item)
            content = message_payload.get("content")
            if isinstance(content, str):
                message_payload["content"] = f"<redacted_string:{len(content)} chars>"
            elif isinstance(content, list):
                redacted_parts: list[object] = []
                for part in content:
                    if not isinstance(part, dict):
                        redacted_parts.append(part)
                        continue
                    part_payload = dict(part)
                    text = part_payload.get("text")
                    if isinstance(text, str):
                        part_payload["text"] = f"<redacted_string:{len(text)} chars>"
                    redacted_parts.append(part_payload)
                message_payload["content"] = redacted_parts
            redacted_messages.append(message_payload)
        return redacted_messages

    def _extract_assistant_content(self, response_json: dict[str, object]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise self._provider_error(
                code=_DRAFT_REASON_EMPTY_RESPONSE,
                reason=_DRAFT_REASON_EMPTY_RESPONSE,
                safe_message="Migration draft response did not include choices.",
                retryable=True,
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise self._provider_error(
                code=_DRAFT_REASON_MALFORMED_RESPONSE,
                reason=_DRAFT_REASON_MALFORMED_RESPONSE,
                safe_message="Migration draft response choice was malformed.",
                retryable=True,
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise self._provider_error(
                code=_DRAFT_REASON_MALFORMED_RESPONSE,
                reason=_DRAFT_REASON_MALFORMED_RESPONSE,
                safe_message="Migration draft response message was malformed.",
                retryable=True,
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        content = message.get("content")
        if isinstance(content, str):
            normalized = content.strip()
            if normalized:
                return normalized
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
            if parts:
                return "\n".join(parts)
        raise self._provider_error(
            code=_DRAFT_REASON_EMPTY_RESPONSE,
            reason=_DRAFT_REASON_EMPTY_RESPONSE,
            safe_message="Migration draft response did not include content.",
            retryable=True,
            raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
        )

    def _extract_assistant_content_from_responses(self, response_json: dict[str, object]) -> str:
        output_text = response_json.get("output_text")
        if isinstance(output_text, str):
            normalized = output_text.strip()
            if normalized:
                return normalized

        output = response_json.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                parts: list[str] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                if parts:
                    return "\n".join(parts)
        raise self._provider_error(
            code=_DRAFT_REASON_EMPTY_RESPONSE,
            reason=_DRAFT_REASON_EMPTY_RESPONSE,
            safe_message="Migration draft response did not include content.",
            retryable=True,
            raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
        )

    def _parse_json_object(
        self,
        raw_json: str,
        *,
        reason: str,
        safe_message: str,
        raw_output: str | None = None,
    ) -> dict[str, object]:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise self._provider_error(
                code=reason,
                reason=reason,
                safe_message=safe_message,
                retryable=True,
                raw_output=raw_output or raw_json,
            ) from exc
        if not isinstance(parsed, dict):
            raise self._provider_error(
                code=reason,
                reason=reason,
                safe_message=safe_message,
                retryable=True,
                raw_output=raw_output or raw_json,
            )
        return parsed

    def _parse_structured_json_output(
        self,
        raw_json: str,
        *,
        reason: str,
        safe_message: str,
        raw_output: str | None = None,
    ) -> tuple[dict[str, object], tuple[str, ...], str | None]:
        normalized = raw_json.strip()
        raw_length = max(0, len(raw_json))
        if not normalized:
            raise self._provider_error(
                code=_DRAFT_REASON_EMPTY_RESPONSE,
                reason=_DRAFT_REASON_EMPTY_RESPONSE,
                safe_message="Migration draft response did not include content.",
                retryable=True,
                raw_output=raw_output or raw_json,
                internal_details={
                    "raw_length": raw_length,
                    "parsed_candidate_count": 0,
                    "salvaged_candidate_count": 0,
                    "malformed_output_reason": _MALFORMED_OUTPUT_REASON_EMPTY,
                },
            )
        recovery = self._recover_structured_payload(normalized)
        normalized_reason = self._normalize_malformed_output_reason(recovery.reason)
        if recovery.payload is None:
            error_reason = (
                _DRAFT_REASON_EMPTY_RESPONSE if normalized_reason == _MALFORMED_OUTPUT_REASON_EMPTY else reason
            )
            message = (
                "Migration draft response did not include content."
                if error_reason == _DRAFT_REASON_EMPTY_RESPONSE
                else safe_message
            )
            raise self._provider_error(
                code=error_reason,
                reason=error_reason,
                safe_message=message,
                retryable=True,
                raw_output=raw_output or raw_json,
                internal_details={
                    "raw_length": raw_length,
                    "parsed_candidate_count": 0,
                    "salvaged_candidate_count": 0,
                    "malformed_output_reason": normalized_reason or _MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR,
                },
            )
        warnings: list[str] = []
        if recovery.recovery_actions:
            warnings.append("Recovered structured JSON from wrapped provider output.")
        return recovery.payload, tuple(warnings), normalized_reason

    def _recover_structured_payload(self, raw_text: str) -> _StructuredPayloadRecoveryResult:
        normalized = raw_text.strip()
        if not normalized:
            return _StructuredPayloadRecoveryResult(
                payload=None,
                reason=_MALFORMED_OUTPUT_REASON_EMPTY,
                recovery_actions=(),
            )

        parsed = self._parse_json_value(normalized)
        if parsed is not None:
            payload, payload_reason, payload_actions = self._normalize_top_level_payload(parsed)
            return _StructuredPayloadRecoveryResult(
                payload=payload,
                reason=payload_reason,
                recovery_actions=payload_actions,
            )

        fenced = self._extract_markdown_fenced_json(normalized)
        if fenced is not None:
            fenced_parsed = self._parse_json_value(fenced)
            if fenced_parsed is not None:
                payload, payload_reason, payload_actions = self._normalize_top_level_payload(fenced_parsed)
                return _StructuredPayloadRecoveryResult(
                    payload=payload,
                    reason=payload_reason or _MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,
                    recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN, *payload_actions),
                )

        fragment, partial = self._extract_first_json_fragment(normalized)
        if fragment is not None:
            extracted = self._parse_json_value(fragment)
            if extracted is not None:
                payload, payload_reason, payload_actions = self._normalize_top_level_payload(extracted)
                return _StructuredPayloadRecoveryResult(
                    payload=payload,
                    reason=payload_reason or _MALFORMED_OUTPUT_REASON_WRAPPED_IN_PROSE,
                    recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_PROSE, *payload_actions),
                )

        if partial:
            return _StructuredPayloadRecoveryResult(
                payload=None,
                reason=_MALFORMED_OUTPUT_REASON_PARTIAL_JSON,
                recovery_actions=(),
            )
        if fenced is not None:
            return _StructuredPayloadRecoveryResult(
                payload=None,
                reason=_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,
                recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,),
            )
        return _StructuredPayloadRecoveryResult(
            payload=None,
            reason=_MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR,
            recovery_actions=(),
        )

    def _parse_json_value(self, raw_text: str) -> object | None:
        try:
            return json.loads(raw_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _normalize_top_level_payload(
        self, parsed: object
    ) -> tuple[dict[str, object] | None, str | None, tuple[str, ...]]:
        if isinstance(parsed, dict):
            return parsed, None, ()
        if isinstance(parsed, list):
            return (
                {"generated_files": parsed},
                _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE,
                (_MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE,),
            )
        return None, _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE, ()

    def _extract_markdown_fenced_json(self, raw_text: str) -> str | None:
        matches = re.findall(r"```(?:json)?\s*(.*?)```", raw_text, flags=re.IGNORECASE | re.DOTALL)
        if not matches:
            return None
        return matches[0].strip()

    def _extract_first_json_fragment(self, raw_text: str) -> tuple[str | None, bool]:
        candidates = [index for index, ch in enumerate(raw_text) if ch in "{["][:32]
        partial = False
        for start_index in candidates:
            extracted, is_partial = self._scan_balanced_json_fragment(raw_text, start_index=start_index)
            if extracted is not None:
                return extracted, False
            if is_partial:
                partial = True
        return None, partial

    def _scan_balanced_json_fragment(self, raw_text: str, *, start_index: int) -> tuple[str | None, bool]:
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

    def _count_generated_file_candidates(self, payload: dict[str, object]) -> int:
        generated_files = payload.get("generated_files")
        if not isinstance(generated_files, list):
            return 0
        return max(0, int(len(generated_files)))

    def _salvage_generation_output(
        self,
        *,
        payload: dict[str, object],
        model_name: str,
        prompt_version: str,
        raw_response: str,
    ) -> _SalvagedMigrationOutput | None:
        generated_files_raw = payload.get("generated_files")
        if not isinstance(generated_files_raw, list):
            return None
        parsed_candidate_count = max(0, int(len(generated_files_raw)))
        files: list[SEOMigrationGeneratedFileOutput] = []
        salvaged_candidate_count = 0
        for item in generated_files_raw:
            candidate_file, was_salvaged = self._coerce_generated_file_candidate(item)
            if candidate_file is None:
                continue
            files.append(candidate_file)
            if was_salvaged:
                salvaged_candidate_count += 1
            if len(files) >= _MAX_FILE_COUNT:
                break
        if not files:
            return None

        warnings: list[str] = []
        if parsed_candidate_count > len(files):
            warnings.append("Ignored malformed generated file entries from provider output.")
        if salvaged_candidate_count > 0:
            warnings.append("Salvaged generated file entries from partially malformed provider output.")
        strategy_summary = _clean_optional_value(payload.get("strategy_summary")) or "Draft strategy summary."
        output = SEOMigrationArtifactGenerationOutput(
            strategy_summary=strategy_summary,
            page_map=self._coerce_object_list(payload.get("page_map"), max_items=_MAX_PAGE_MAP_ITEMS),
            homepage_structure=self._coerce_object_list(payload.get("homepage_structure"), max_items=_MAX_LIST_ITEMS),
            service_page_suggestions=self._coerce_object_list(
                payload.get("service_page_suggestions"),
                max_items=_MAX_LIST_ITEMS,
            ),
            cta_contact_structure=self._coerce_dict(payload.get("cta_contact_structure")),
            seo_meta_suggestions=self._coerce_dict(payload.get("seo_meta_suggestions")),
            redirect_suggestions=self._coerce_object_list(
                payload.get("redirect_suggestions"),
                max_items=_MAX_LIST_ITEMS,
            ),
            analytics_placeholders=self._coerce_object_list(
                payload.get("analytics_placeholders"),
                max_items=_MAX_LIST_ITEMS,
            ),
            generated_files=files,
            provider_name=self.provider_name,
            model_name=model_name,
            prompt_version=prompt_version,
            raw_response=raw_response,
            parse_warnings=tuple(warnings),
        )
        return _SalvagedMigrationOutput(
            output=output,
            parsed_candidate_count=parsed_candidate_count,
            salvaged_candidate_count=max(0, int(salvaged_candidate_count)),
            parse_warnings=tuple(warnings),
        )

    def _coerce_generated_file_candidate(
        self,
        value: object,
    ) -> tuple[SEOMigrationGeneratedFileOutput | None, bool]:
        was_salvaged = False
        if isinstance(value, dict):
            try:
                parsed = _OpenAIMigrationGeneratedFile.model_validate(value)
                return (
                    SEOMigrationGeneratedFileOutput(
                        path=parsed.path,
                        content=parsed.content,
                        media_type=parsed.media_type,
                    ),
                    False,
                )
            except ValidationError:
                was_salvaged = True
            path = _clean_optional_value(value.get("path"))
            if path is None:
                path = _clean_optional_value(value.get("file_path"))
            if path is None:
                path = _clean_optional_value(value.get("name"))
            content = value.get("content")
            if content is None:
                content = value.get("text")
            if content is None:
                content = value.get("body")
            normalized_content = str(content or "").strip()
            media_type = _clean_optional_value(value.get("media_type"))
            if media_type is None:
                media_type = _clean_optional_value(value.get("content_type"))
            if path is None or not normalized_content:
                return None, was_salvaged
            if media_type is None:
                media_type = self._infer_media_type(path)
            return (
                SEOMigrationGeneratedFileOutput(
                    path=path,
                    content=normalized_content,
                    media_type=media_type,
                ),
                True,
            )
        return None, was_salvaged

    @staticmethod
    def _coerce_dict(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            normalized: dict[str, object] = {}
            for raw_key, raw_value in value.items():
                key = _clean_optional_value(raw_key)
                if key is None:
                    continue
                normalized[key] = raw_value
            return normalized
        return {}

    def _coerce_object_list(self, value: object, *, max_items: int) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        normalized: list[dict[str, object]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized.append(self._coerce_dict(item))
            if len(normalized) >= max_items:
                break
        return normalized

    @staticmethod
    def _infer_media_type(path: str) -> str:
        lowered = path.lower()
        if lowered.endswith(".html"):
            return "text/html"
        if lowered.endswith(".css"):
            return "text/css"
        if lowered.endswith(".js"):
            return "application/javascript"
        if lowered.endswith(".json"):
            return "application/json"
        if lowered.endswith(".xml"):
            return "application/xml"
        if lowered.endswith(".ico"):
            return "image/x-icon"
        if lowered.endswith(".webmanifest"):
            return "application/manifest+json"
        return "text/plain"

    @staticmethod
    def _coerce_optional_non_negative_int(value: object) -> int | None:
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, parsed)

    def _normalize_malformed_output_reason(self, value: object) -> str | None:
        normalized = _clean_optional_value(value)
        if normalized is None:
            return None
        lowered = normalized.lower()
        if lowered not in _MALFORMED_OUTPUT_ALLOWED_REASONS:
            return None
        return lowered

    def _provider_error(
        self,
        *,
        code: str,
        reason: str | None = None,
        safe_message: str,
        retryable: bool | None = None,
        correlation_id: str | None = None,
        raw_output: str | None = None,
        internal_details: dict[str, object] | None = None,
        normalized_failure_category: str | None = None,
        normalized_failure_reason: str | None = None,
        normalized_failure_source: str | None = None,
        normalized_retryable: bool | None = None,
        attempt_count: int | None = None,
        original_input_size: int | None = None,
        final_input_size: int | None = None,
        trimmed_bytes: int | None = None,
        trimming_pass_count: int | None = None,
        difficulty_score: int | None = None,
        budget_outcome: str | None = None,
        retry_suppressed: bool | None = None,
        degraded_state: str | None = None,
    ) -> SEOMigrationArtifactProviderError:
        normalized_reason = _clean_optional_value((reason or code).strip().lower()) or _DRAFT_REASON_UNKNOWN
        if normalized_reason not in _DRAFT_REASON_VALUES:
            normalized_reason = _DRAFT_REASON_UNKNOWN
        return SEOMigrationArtifactProviderError(
            code=code,
            safe_message=safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            reason=normalized_reason,
            retryable=retryable,
            correlation_id=_clean_optional_value(correlation_id),
            raw_output=raw_output,
            internal_details=internal_details,
            normalized_failure_category=_clean_optional_value(normalized_failure_category),
            normalized_failure_reason=_clean_optional_value(normalized_failure_reason),
            normalized_failure_source=_clean_optional_value(normalized_failure_source),
            normalized_retryable=(bool(normalized_retryable) if isinstance(normalized_retryable, bool) else None),
            attempt_count=(max(1, int(attempt_count)) if isinstance(attempt_count, int) else None),
            original_input_size=(max(0, int(original_input_size)) if isinstance(original_input_size, int) else None),
            final_input_size=(max(0, int(final_input_size)) if isinstance(final_input_size, int) else None),
            trimmed_bytes=(max(0, int(trimmed_bytes)) if isinstance(trimmed_bytes, int) else None),
            trimming_pass_count=(max(0, int(trimming_pass_count)) if isinstance(trimming_pass_count, int) else None),
            difficulty_score=(max(0, min(100, int(difficulty_score))) if isinstance(difficulty_score, int) else None),
            budget_outcome=_clean_optional_value(budget_outcome),
            retry_suppressed=(bool(retry_suppressed) if isinstance(retry_suppressed, bool) else None),
            degraded_state=_clean_optional_value(degraded_state),
        )

    @staticmethod
    def _migration_reason_from_execution_error(error: AIExecutionError) -> tuple[str, str]:
        failure = error.normalized_failure
        status = failure.http_status
        if failure.category == "remote_timeout":
            return _DRAFT_REASON_TIMEOUT, "Migration draft generation timed out while calling the AI provider."
        if failure.category == "remote_rate_limited":
            return (
                _DRAFT_REASON_RATE_LIMITED,
                "Migration draft generation is currently rate-limited by the AI provider.",
            )
        if failure.category == "configuration_missing":
            return (
                _DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
                "AI provider configuration is missing for migration draft generation.",
            )
        if failure.category == "configuration_invalid":
            if status in {401, 403}:
                return (
                    _DRAFT_REASON_AUTHENTICATION_FAILED,
                    "AI provider authentication failed for migration draft generation.",
                )
            return (
                _DRAFT_REASON_UNSUPPORTED_CONFIGURATION,
                "AI provider configuration is invalid for migration draft generation.",
            )
        if failure.category == "remote_invalid_response":
            return _DRAFT_REASON_MALFORMED_RESPONSE, "Migration draft response could not be parsed."
        if failure.category == "local_validation_failure":
            if failure.reason in {"request_too_large", "request_too_large_or_complex"}:
                return (
                    _DRAFT_REASON_VALIDATION_FAILED,
                    "Migration draft request is too large or complex for synchronous generation.",
                )
            return _DRAFT_REASON_VALIDATION_FAILED, "Migration draft returned invalid structured output."
        if failure.category == "remote_unavailable":
            return (
                _DRAFT_REASON_TRANSPORT_ERROR,
                "Migration draft generation failed while communicating with the AI provider.",
            )
        return _DRAFT_REASON_UNKNOWN, "Migration draft generation failed due to an unexpected AI provider error."

    def _apply_migration_context_budget(
        self,
        migration_context: dict[str, object],
    ) -> tuple[dict[str, object], dict[str, object]]:
        required_keys = [key for key in _MIGRATION_DRAFT_CONTEXT_REQUIRED_KEYS if key in migration_context]
        optional_keys: list[object] = [
            key
            for key in _MIGRATION_DRAFT_CONTEXT_OPTIONAL_TRIM_ORDER
            if key in migration_context and key not in required_keys
        ]
        for key in migration_context.keys():
            if key in required_keys or key in optional_keys:
                continue
            optional_keys.append(key)

        blocks: list[AIContextBlock] = []
        for key in required_keys:
            blocks.append(AIContextBlock(name=key, value=migration_context.get(key), required=True, trim_priority=0))
        for index, key in enumerate(optional_keys):
            blocks.append(
                AIContextBlock(
                    name=str(key),
                    value=migration_context.get(key),
                    required=False,
                    trim_priority=max(1, len(optional_keys) - index),
                )
            )

        decision = apply_request_budget(
            blocks=blocks,
            budget_size_chars=_MIGRATION_DRAFT_CONTEXT_BUDGET_CHARS,
        )
        retained = dict(decision.retained_blocks)
        budgeted_context: dict[str, object] = {}
        for key in required_keys:
            budgeted_context[key] = retained.get(key, migration_context.get(key, {}))
        for key in optional_keys:
            retained_key = str(key)
            if retained_key in retained:
                budgeted_context[key] = retained[retained_key]

        serialized_sizes: dict[str, int] = {}

        def _serialized_size(value: object) -> int:
            try:
                return max(0, len(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))))
            except (TypeError, ValueError):
                return max(0, len(str(value)))

        for key in required_keys:
            serialized_sizes[str(key)] = _serialized_size(retained.get(str(key), migration_context.get(key)))
        for key in optional_keys:
            key_name = str(key)
            if key_name in retained:
                serialized_sizes[key_name] = _serialized_size(retained.get(key_name))

        largest_retained_block = None
        largest_retained_block_size_chars = None
        if serialized_sizes:
            largest_retained_block, largest_retained_block_size_chars = max(
                serialized_sizes.items(),
                key=lambda item: item[1],
            )

        largest_dropped_optional_block = None
        largest_dropped_optional_block_size_chars = None
        dropped_blocks = list(decision.result.dropped_optional_blocks)
        if dropped_blocks:
            dropped_size_pairs: list[tuple[str, int]] = []
            for block_name in dropped_blocks:
                if block_name in migration_context:
                    dropped_size_pairs.append((block_name, _serialized_size(migration_context.get(block_name))))
            if dropped_size_pairs:
                largest_dropped_optional_block, largest_dropped_optional_block_size_chars = max(
                    dropped_size_pairs,
                    key=lambda item: item[1],
                )

        budget_result = {
            "initial_size_chars": decision.result.initial_size_chars,
            "final_size_chars": decision.result.final_size_chars,
            "initial_size_bytes": decision.result.initial_size_bytes,
            "final_size_bytes": decision.result.final_size_bytes,
            "trimmed_bytes": decision.result.trimmed_bytes,
            "trimming_pass_count": decision.result.trimming_pass_count,
            "section_count": decision.result.section_count,
            "budget_size_chars": decision.result.budget_size_chars,
            "dropped_optional_blocks": list(decision.result.dropped_optional_blocks),
            "dropped_duplicate_blocks": list(decision.result.dropped_duplicate_blocks),
            "required_blocks_retained": list(decision.result.required_blocks_retained),
            "optional_blocks_retained": list(decision.result.optional_blocks_retained),
            "largest_retained_block": largest_retained_block,
            "largest_retained_block_size_chars": largest_retained_block_size_chars,
            "largest_dropped_optional_block": largest_dropped_optional_block,
            "largest_dropped_optional_block_size_chars": largest_dropped_optional_block_size_chars,
            "overflow": bool(decision.result.overflow),
        }
        return budgeted_context, budget_result

    def _build_request_context(self, migration_context: dict[str, object]) -> dict[str, object]:
        site_snapshot = migration_context.get("site_snapshot")
        workspace_context = migration_context.get("migration_workspace")
        site_payload = site_snapshot if isinstance(site_snapshot, dict) else {}
        workspace_payload = workspace_context if isinstance(workspace_context, dict) else {}
        request_profile = self.get_request_profile()
        return {
            "business_id": _clean_optional_value(site_payload.get("business_id")),
            "site_id": _clean_optional_value(site_payload.get("site_id")),
            "workspace_id": _clean_optional_value(workspace_payload.get("workspace_id")),
            "provider_name": self.provider_name,
            "model": self.model_name,
            "prompt_version": self.prompt_version,
            "endpoint_path": _clean_optional_value(request_profile.get("endpoint_path")),
            "execution_mode": _clean_optional_value(request_profile.get("execution_mode")) or "full",
            "web_search_enabled": (
                bool(request_profile.get("web_search_enabled"))
                if isinstance(request_profile.get("web_search_enabled"), bool)
                else False
            ),
            "degraded_mode": (
                bool(request_profile.get("degraded_mode"))
                if isinstance(request_profile.get("degraded_mode"), bool)
                else False
            ),
            "response_format_mode": _clean_optional_value(request_profile.get("response_format_mode")),
            "request_body_mode": _clean_optional_value(request_profile.get("request_body_mode")),
        }

    @staticmethod
    def _request_shape_details(*, request_context: dict[str, object] | None) -> dict[str, object]:
        context = request_context or {}
        return {
            "endpoint_path": _clean_optional_value(context.get("endpoint_path")),
            "execution_mode": _clean_optional_value(context.get("execution_mode")) or "full",
            "response_format_mode": _clean_optional_value(context.get("response_format_mode")),
            "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
        }

    def _build_request_fingerprint(
        self,
        *,
        payload: dict[str, object],
        request_context: dict[str, object] | None,
    ) -> dict[str, object]:
        context = request_context or {}
        top_level_keys = sorted(str(key) for key in payload.keys())
        text_payload = payload.get("text")
        text_format_payload = text_payload.get("format") if isinstance(text_payload, dict) else None
        response_format_payload = payload.get("response_format")
        legacy_json_schema_payload = (
            response_format_payload.get("json_schema") if isinstance(response_format_payload, dict) else None
        )
        schema_payload = (
            text_format_payload.get("schema")
            if isinstance(text_format_payload, dict)
            else legacy_json_schema_payload.get("schema") if isinstance(legacy_json_schema_payload, dict) else None
        )
        schema_name = (
            _clean_optional_value(text_format_payload.get("name"))
            if isinstance(text_format_payload, dict)
            else (
                _clean_optional_value(legacy_json_schema_payload.get("name"))
                if isinstance(legacy_json_schema_payload, dict)
                else None
            )
        )
        strict_enabled_raw = (
            text_format_payload.get("strict")
            if isinstance(text_format_payload, dict)
            else legacy_json_schema_payload.get("strict") if isinstance(legacy_json_schema_payload, dict) else None
        )
        input_mode: str | None = None
        input_length_chars: int | None = None
        if "input" in payload:
            input_value = payload.get("input")
            if isinstance(input_value, str):
                input_mode = "string"
                input_length_chars = max(0, len(input_value))
            elif isinstance(input_value, list):
                input_mode = "array"
            elif isinstance(input_value, dict):
                input_mode = "object"
            elif input_value is None:
                input_mode = "null"
            else:
                input_mode = "unknown"
        elif "messages" in payload:
            legacy_messages = payload.get("messages")
            input_mode = "legacy_messages_array" if isinstance(legacy_messages, list) else "legacy_messages_non_array"
        endpoint_path = _clean_optional_value(context.get("endpoint_path"))
        has_extra_request_options = self._has_extra_request_options(
            endpoint_path=endpoint_path,
            payload=payload,
        )
        has_null_optional_fields = self._payload_contains_null(payload)

        (
            object_nodes_total,
            object_nodes_non_false,
            object_nodes_missing_required,
        ) = self._count_schema_object_nodes(schema_payload)
        return {
            "model": _clean_optional_value(payload.get("model")),
            "endpoint_path": endpoint_path,
            "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
            "has_text_format": isinstance(text_format_payload, dict),
            "text_format_type": (
                _clean_optional_value(text_format_payload.get("type"))
                if isinstance(text_format_payload, dict)
                else None
            ),
            "schema_name": schema_name,
            "strict_enabled": strict_enabled_raw if isinstance(strict_enabled_raw, bool) else None,
            "top_level_keys": top_level_keys,
            "text_top_level_keys": (
                sorted(str(key) for key in text_payload.keys()) if isinstance(text_payload, dict) else []
            ),
            "text_format_keys": (
                sorted(str(key) for key in text_format_payload.keys()) if isinstance(text_format_payload, dict) else []
            ),
            "schema_top_level_keys": (
                sorted(str(key) for key in schema_payload.keys()) if isinstance(schema_payload, dict) else []
            ),
            "input_mode": input_mode,
            "contains_tools": "tools" in payload,
            "contains_response_format_legacy": "response_format" in payload,
            "contains_messages_legacy": "messages" in payload,
            "has_null_optional_fields": has_null_optional_fields,
            "has_extra_request_options": has_extra_request_options,
            "input_length_chars": input_length_chars,
            "schema_object_nodes_total": object_nodes_total,
            "schema_object_nodes_non_false_additional_properties": object_nodes_non_false,
            "schema_object_nodes_missing_required": object_nodes_missing_required,
        }

    @staticmethod
    def _payload_contains_null(payload: object) -> bool:
        if payload is None:
            return True
        if isinstance(payload, dict):
            for value in payload.values():
                if OpenAISEOMigrationArtifactGenerationProvider._payload_contains_null(value):
                    return True
            return False
        if isinstance(payload, list):
            for item in payload:
                if OpenAISEOMigrationArtifactGenerationProvider._payload_contains_null(item):
                    return True
            return False
        return False

    @staticmethod
    def _has_extra_request_options(*, endpoint_path: str | None, payload: dict[str, object]) -> bool:
        if endpoint_path == _MIGRATION_COMPAT_ENDPOINT_RESPONSES:
            allowed_keys = {"model", "input", "text"}
        elif endpoint_path == _MIGRATION_COMPAT_ENDPOINT_CHAT_COMPLETIONS:
            allowed_keys = {"model", "temperature", "messages", "response_format"}
        else:
            return False
        for key in payload.keys():
            if str(key) not in allowed_keys:
                return True
        return False

    def _request_fingerprint_log_fields(self, request_fingerprint: dict[str, object] | None) -> dict[str, object]:
        fingerprint = request_fingerprint or {}
        return {
            "request_fingerprint_model": _clean_optional_value(fingerprint.get("model")),
            "request_fingerprint_endpoint_path": _clean_optional_value(fingerprint.get("endpoint_path")),
            "request_fingerprint_request_body_mode": _clean_optional_value(fingerprint.get("request_body_mode")),
            "request_fingerprint_has_text_format": (
                bool(fingerprint.get("has_text_format"))
                if isinstance(fingerprint.get("has_text_format"), bool)
                else None
            ),
            "request_fingerprint_text_format_type": _clean_optional_value(fingerprint.get("text_format_type")),
            "request_fingerprint_schema_name": _clean_optional_value(fingerprint.get("schema_name")),
            "request_fingerprint_strict_enabled": (
                bool(fingerprint.get("strict_enabled")) if isinstance(fingerprint.get("strict_enabled"), bool) else None
            ),
            "request_fingerprint_top_level_keys": (
                [str(item) for item in fingerprint.get("top_level_keys", []) if isinstance(item, str)]
                if isinstance(fingerprint.get("top_level_keys"), list)
                else []
            ),
            "request_fingerprint_text_top_level_keys": (
                [str(item) for item in fingerprint.get("text_top_level_keys", []) if isinstance(item, str)]
                if isinstance(fingerprint.get("text_top_level_keys"), list)
                else []
            ),
            "request_fingerprint_text_format_keys": (
                [str(item) for item in fingerprint.get("text_format_keys", []) if isinstance(item, str)]
                if isinstance(fingerprint.get("text_format_keys"), list)
                else []
            ),
            "request_fingerprint_schema_top_level_keys": (
                [str(item) for item in fingerprint.get("schema_top_level_keys", []) if isinstance(item, str)]
                if isinstance(fingerprint.get("schema_top_level_keys"), list)
                else []
            ),
            "request_fingerprint_input_mode": _clean_optional_value(fingerprint.get("input_mode")),
            "request_fingerprint_contains_tools": (
                bool(fingerprint.get("contains_tools")) if isinstance(fingerprint.get("contains_tools"), bool) else None
            ),
            "request_fingerprint_contains_response_format_legacy": (
                bool(fingerprint.get("contains_response_format_legacy"))
                if isinstance(fingerprint.get("contains_response_format_legacy"), bool)
                else None
            ),
            "request_fingerprint_contains_messages_legacy": (
                bool(fingerprint.get("contains_messages_legacy"))
                if isinstance(fingerprint.get("contains_messages_legacy"), bool)
                else None
            ),
            "request_fingerprint_has_null_optional_fields": (
                bool(fingerprint.get("has_null_optional_fields"))
                if isinstance(fingerprint.get("has_null_optional_fields"), bool)
                else None
            ),
            "request_fingerprint_has_extra_request_options": (
                bool(fingerprint.get("has_extra_request_options"))
                if isinstance(fingerprint.get("has_extra_request_options"), bool)
                else None
            ),
            "request_fingerprint_input_length_chars": self._coerce_optional_non_negative_int(
                fingerprint.get("input_length_chars"),
            ),
            "request_fingerprint_schema_object_nodes_total": self._coerce_optional_non_negative_int(
                fingerprint.get("schema_object_nodes_total"),
            ),
            "request_fingerprint_schema_object_nodes_non_false_additional_properties": self._coerce_optional_non_negative_int(
                fingerprint.get("schema_object_nodes_non_false_additional_properties"),
            ),
            "request_fingerprint_schema_object_nodes_missing_required": self._coerce_optional_non_negative_int(
                fingerprint.get("schema_object_nodes_missing_required"),
            ),
            "request_fingerprint_context_budget_initial_size_chars": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("initial_size_chars")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_final_size_chars": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("final_size_chars")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_original_input_size": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("initial_size_bytes")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_final_input_size": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("final_size_bytes")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_trimmed_bytes": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("trimmed_bytes")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_trimming_pass_count": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("trimming_pass_count")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_section_count": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("section_count")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_size_chars": self._coerce_optional_non_negative_int(
                (
                    (fingerprint.get("context_budget") or {}).get("budget_size_chars")
                    if isinstance(fingerprint.get("context_budget"), dict)
                    else None
                ),
            ),
            "request_fingerprint_context_budget_dropped_optional_blocks": (
                [
                    str(item)
                    for item in (fingerprint.get("context_budget") or {}).get("dropped_optional_blocks", [])
                    if isinstance(item, str)
                ]
                if isinstance(fingerprint.get("context_budget"), dict)
                else []
            ),
            "request_fingerprint_context_budget_overflow": (
                bool((fingerprint.get("context_budget") or {}).get("overflow"))
                if isinstance((fingerprint.get("context_budget") or {}).get("overflow"), bool)
                else None
            ),
        }

    def _extract_response_correlation_id(self, headers: object) -> str | None:
        if headers is None or not hasattr(headers, "get"):
            return None
        for key in _CORRELATION_HEADER_KEYS:
            value = _clean_optional_value(headers.get(key))
            if value:
                return value
        return None

    def _emit_structured_provider_log(self, *, level: int, event: str, payload: dict[str, object]) -> None:
        data = {"event": event, "provider_name": self.provider_name}
        data.update(payload)
        safe_payload = {key: value for key, value in data.items() if value is not None}
        try:
            serialized = json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            serialized = event
        logger.log(level, serialized, extra={"json_fields": safe_payload})

    def _log_request_budget(
        self,
        *,
        request_context: dict[str, object] | None,
        budget_result: dict[str, object],
        budget_outcome: str,
    ) -> None:
        context = request_context or {}
        self._emit_structured_provider_log(
            level=logging.INFO,
            event="seo_migration_draft_request_budget",
            payload={
                "feature_area": "migration_draft",
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "budget_outcome": _clean_optional_value(budget_outcome) or "unknown",
                "initial_size_chars": self._coerce_optional_non_negative_int(budget_result.get("initial_size_chars")),
                "final_size_chars": self._coerce_optional_non_negative_int(budget_result.get("final_size_chars")),
                "budget_size_chars": self._coerce_optional_non_negative_int(budget_result.get("budget_size_chars")),
                "original_input_size": self._coerce_optional_non_negative_int(budget_result.get("initial_size_bytes")),
                "final_input_size": self._coerce_optional_non_negative_int(budget_result.get("final_size_bytes")),
                "trimmed_bytes": self._coerce_optional_non_negative_int(budget_result.get("trimmed_bytes")),
                "trimming_pass_count": self._coerce_optional_non_negative_int(budget_result.get("trimming_pass_count")),
                "section_count": self._coerce_optional_non_negative_int(budget_result.get("section_count")),
                "dropped_optional_blocks": [
                    str(item) for item in budget_result.get("dropped_optional_blocks", []) if isinstance(item, str)
                ],
                "dropped_duplicate_blocks": [
                    str(item) for item in budget_result.get("dropped_duplicate_blocks", []) if isinstance(item, str)
                ],
                "overflow": (
                    bool(budget_result.get("overflow")) if isinstance(budget_result.get("overflow"), bool) else None
                ),
            },
        )

    def _log_provider_request_start(
        self,
        *,
        request_context: dict[str, object] | None,
        endpoint_path: str,
        request_fingerprint: dict[str, object] | None = None,
    ) -> None:
        context = request_context or {}
        self._emit_structured_provider_log(
            level=logging.INFO,
            event=_PROVIDER_LOG_EVENT_REQUEST_START,
            payload={
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "endpoint_path": endpoint_path,
                "execution_mode": _clean_optional_value(context.get("execution_mode")) or "full",
                "web_search_enabled": (
                    bool(context.get("web_search_enabled"))
                    if isinstance(context.get("web_search_enabled"), bool)
                    else False
                ),
                "degraded_mode": (
                    bool(context.get("degraded_mode")) if isinstance(context.get("degraded_mode"), bool) else False
                ),
                "response_format_mode": _clean_optional_value(context.get("response_format_mode")),
                "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
                "timeout_seconds": int(self.timeout_seconds),
                "timeout_source": _clean_optional_value(getattr(self, "timeout_source", None)) or "default",
                **self._request_fingerprint_log_fields(request_fingerprint),
            },
        )

    def _log_provider_request_complete(
        self,
        *,
        request_context: dict[str, object] | None,
        endpoint_path: str,
        duration_ms: int,
        correlation_id: str | None,
        request_fingerprint: dict[str, object] | None = None,
    ) -> None:
        context = request_context or {}
        self._emit_structured_provider_log(
            level=logging.INFO,
            event=_PROVIDER_LOG_EVENT_REQUEST_COMPLETE,
            payload={
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "endpoint_path": endpoint_path,
                "execution_mode": _clean_optional_value(context.get("execution_mode")) or "full",
                "web_search_enabled": (
                    bool(context.get("web_search_enabled"))
                    if isinstance(context.get("web_search_enabled"), bool)
                    else False
                ),
                "degraded_mode": (
                    bool(context.get("degraded_mode")) if isinstance(context.get("degraded_mode"), bool) else False
                ),
                "response_format_mode": _clean_optional_value(context.get("response_format_mode")),
                "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
                "duration_ms": max(0, int(duration_ms)),
                "correlation_id": _clean_optional_value(correlation_id),
                "timeout_seconds": int(self.timeout_seconds),
                "timeout_source": _clean_optional_value(getattr(self, "timeout_source", None)) or "default",
                **self._request_fingerprint_log_fields(request_fingerprint),
            },
        )

    def _log_provider_request_failure(
        self,
        *,
        request_context: dict[str, object] | None,
        reason: str | None,
        retryable: bool | None,
        failure_source: str = "remote_provider",
        correlation_id: str | None = None,
        duration_ms: int | None = None,
        http_status: int | None = None,
        request_fingerprint: dict[str, object] | None = None,
        parsed_candidate_count: int | None = None,
        salvaged_candidate_count: int | None = None,
        malformed_output_reason: str | None = None,
        raw_length: int | None = None,
    ) -> None:
        context = request_context or {}
        normalized_reason = _clean_optional_value((reason or "").strip().lower()) or _DRAFT_REASON_UNKNOWN
        if normalized_reason not in _DRAFT_REASON_VALUES:
            normalized_reason = _DRAFT_REASON_UNKNOWN
        normalized_failure_source = _clean_optional_value(failure_source) or "remote_provider"
        if normalized_failure_source not in {"remote_provider", "local_preflight"}:
            normalized_failure_source = "remote_provider"
        self._emit_structured_provider_log(
            level=logging.WARNING,
            event=_PROVIDER_LOG_EVENT_REQUEST_FAILURE,
            payload={
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "endpoint_path": _clean_optional_value(context.get("endpoint_path")),
                "execution_mode": _clean_optional_value(context.get("execution_mode")) or "full",
                "web_search_enabled": (
                    bool(context.get("web_search_enabled"))
                    if isinstance(context.get("web_search_enabled"), bool)
                    else False
                ),
                "degraded_mode": (
                    bool(context.get("degraded_mode")) if isinstance(context.get("degraded_mode"), bool) else False
                ),
                "response_format_mode": _clean_optional_value(context.get("response_format_mode")),
                "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
                "failure_reason": normalized_reason,
                "failure_source": normalized_failure_source,
                "retryable": retryable,
                "correlation_id": _clean_optional_value(correlation_id),
                "duration_ms": (max(0, int(duration_ms)) if duration_ms is not None else None),
                "http_status": (int(http_status) if http_status is not None else None),
                "timeout_seconds": int(self.timeout_seconds),
                "timeout_source": _clean_optional_value(getattr(self, "timeout_source", None)) or "default",
                "parsed_candidate_count": self._coerce_optional_non_negative_int(parsed_candidate_count),
                "salvaged_candidate_count": self._coerce_optional_non_negative_int(salvaged_candidate_count),
                "malformed_output_reason": self._normalize_malformed_output_reason(malformed_output_reason),
                "raw_length": self._coerce_optional_non_negative_int(raw_length),
                **self._request_fingerprint_log_fields(request_fingerprint),
            },
        )

    def _log_provider_response_parse(
        self,
        *,
        request_context: dict[str, object] | None,
        status: str,
        raw_length: int,
        parsed_candidate_count: int,
        salvaged_candidate_count: int,
        malformed_output_reason: str | None = None,
    ) -> None:
        context = request_context or {}
        normalized_status = _clean_optional_value(status) or "unknown"
        level = logging.INFO if normalized_status in {"completed", "partial"} else logging.WARNING
        self._emit_structured_provider_log(
            level=level,
            event=_PROVIDER_LOG_EVENT_RESPONSE_PARSE,
            payload={
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "status": normalized_status,
                "endpoint_path": _clean_optional_value(context.get("endpoint_path")),
                "execution_mode": _clean_optional_value(context.get("execution_mode")) or "full",
                "response_format_mode": _clean_optional_value(context.get("response_format_mode")),
                "request_body_mode": _clean_optional_value(context.get("request_body_mode")),
                "raw_length": max(0, int(raw_length)),
                "parsed_candidate_count": max(0, int(parsed_candidate_count)),
                "salvaged_candidate_count": max(0, int(salvaged_candidate_count)),
                "malformed_output_reason": self._normalize_malformed_output_reason(malformed_output_reason),
            },
        )


class _OpenAIMigrationPageMapItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    title: str
    purpose: str | None = None

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, value: object) -> str:
        normalized = _clean_optional_value(value) or ""
        if not normalized:
            raise ValueError("path is required")
        if len(normalized) > _MAX_FILE_PATH_LENGTH:
            return normalized[:_MAX_FILE_PATH_LENGTH]
        return normalized

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: object) -> str:
        normalized = _clean_optional_value(value) or ""
        if not normalized:
            raise ValueError("title is required")
        if len(normalized) > 180:
            return normalized[:180]
        return normalized

    @field_validator("purpose", mode="before")
    @classmethod
    def _normalize_purpose(cls, value: object) -> str | None:
        return _clean_optional_value(value)


class _OpenAIMigrationGeneratedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    media_type: str
    content: str

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, value: object) -> str:
        normalized = _clean_optional_value(value) or ""
        if not normalized:
            raise ValueError("path is required")
        if len(normalized) > _MAX_FILE_PATH_LENGTH:
            return normalized[:_MAX_FILE_PATH_LENGTH]
        return normalized

    @field_validator("media_type", mode="before")
    @classmethod
    def _normalize_media_type(cls, value: object) -> str:
        normalized = _clean_optional_value(value) or ""
        if not normalized:
            raise ValueError("media_type is required")
        if len(normalized) > 80:
            return normalized[:80]
        return normalized

    @field_validator("content", mode="before")
    @classmethod
    def _normalize_content(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("content is required")
        if len(normalized) > _MAX_FILE_CONTENT_LENGTH:
            return normalized[:_MAX_FILE_CONTENT_LENGTH]
        return normalized


class _OpenAIMigrationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_summary: str
    page_map: list[_OpenAIMigrationPageMapItem] = Field(default_factory=list, max_length=_MAX_PAGE_MAP_ITEMS)
    homepage_structure: list[_OpenAIMigrationPageMapItem] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    service_page_suggestions: list[_OpenAIMigrationPageMapItem] = Field(
        default_factory=list, max_length=_MAX_LIST_ITEMS
    )
    cta_contact_structure: dict[str, object] | None = None
    seo_meta_suggestions: dict[str, object] | None = None
    redirect_suggestions: list[_OpenAIMigrationPageMapItem] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    analytics_placeholders: list[_OpenAIMigrationPageMapItem] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
    generated_files: list[_OpenAIMigrationGeneratedFile] = Field(min_length=1, max_length=_MAX_FILE_COUNT)

    @field_validator("strategy_summary", mode="before")
    @classmethod
    def _normalize_strategy_summary(cls, value: object) -> str:
        normalized = _clean_optional_value(value) or ""
        if not normalized:
            raise ValueError("strategy_summary is required")
        if len(normalized) > _MAX_TEXT_FIELD_LENGTH:
            return normalized[:_MAX_TEXT_FIELD_LENGTH]
        return normalized


def _build_migration_json_schema() -> dict[str, object]:
    page_item_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["path", "title", "purpose"],
        "properties": {
            "path": {"type": "string"},
            "title": {"type": "string"},
            "purpose": {"type": ["string", "null"]},
        },
    }
    cta_contact_structure_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "primary_cta",
            "secondary_cta",
            "contact_fields",
            "contact_phone",
            "contact_email",
            "service_area_note",
            "availability_note",
        ],
        "properties": {
            "primary_cta": {"type": "string"},
            "secondary_cta": {"type": ["string", "null"]},
            "contact_fields": {"type": "array", "maxItems": _MAX_LIST_ITEMS, "items": {"type": "string"}},
            "contact_phone": {"type": ["string", "null"]},
            "contact_email": {"type": ["string", "null"]},
            "service_area_note": {"type": ["string", "null"]},
            "availability_note": {"type": ["string", "null"]},
        },
    }
    seo_meta_suggestions_schema: dict[str, object] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "homepage_title",
            "homepage_meta_description",
            "focus_keywords",
            "canonical_url",
            "og_title",
            "og_description",
        ],
        "properties": {
            "homepage_title": {"type": "string"},
            "homepage_meta_description": {"type": "string"},
            "focus_keywords": {"type": "array", "maxItems": _MAX_LIST_ITEMS, "items": {"type": "string"}},
            "canonical_url": {"type": ["string", "null"]},
            "og_title": {"type": ["string", "null"]},
            "og_description": {"type": ["string", "null"]},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "strategy_summary",
            "page_map",
            "homepage_structure",
            "service_page_suggestions",
            "cta_contact_structure",
            "seo_meta_suggestions",
            "redirect_suggestions",
            "analytics_placeholders",
            "generated_files",
        ],
        "properties": {
            "strategy_summary": {"type": "string"},
            "page_map": {"type": "array", "maxItems": _MAX_PAGE_MAP_ITEMS, "items": page_item_schema},
            "homepage_structure": {"type": "array", "maxItems": _MAX_LIST_ITEMS, "items": page_item_schema},
            "service_page_suggestions": {"type": "array", "maxItems": _MAX_LIST_ITEMS, "items": page_item_schema},
            "cta_contact_structure": cta_contact_structure_schema,
            "seo_meta_suggestions": seo_meta_suggestions_schema,
            "redirect_suggestions": {"type": "array", "maxItems": _MAX_LIST_ITEMS, "items": page_item_schema},
            "analytics_placeholders": {"type": "array", "maxItems": _MAX_LIST_ITEMS, "items": page_item_schema},
            "generated_files": {
                "type": "array",
                "minItems": 1,
                "maxItems": _MAX_FILE_COUNT,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["path", "media_type", "content"],
                    "properties": {
                        "path": {"type": "string"},
                        "media_type": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
            },
        },
    }


def _clean_optional_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None
