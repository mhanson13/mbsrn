from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

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
_PROVIDER_LOG_EVENT_REQUEST_START = "seo_migration_draft_provider_request_start"
_PROVIDER_LOG_EVENT_REQUEST_COMPLETE = "seo_migration_draft_provider_request_complete"
_PROVIDER_LOG_EVENT_REQUEST_FAILURE = "seo_migration_draft_provider_request_failure"
_PROVIDER_LOG_EVENT_RESPONSE_PARSE = "seo_migration_draft_provider_response_parse"
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

    def __str__(self) -> str:
        return self.safe_message


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
        timeout_seconds: int = 30,
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
        self.api_base_url = api_base_url.rstrip("/")
        self.prompt_version = prompt_version.strip() or SEO_MIGRATION_PROMPT_VERSION
        self.prompt_text_recommendations = prompt_text_recommendations or ""

    def generate_artifacts(self, *, migration_context: dict[str, object]) -> SEOMigrationArtifactGenerationOutput:
        request_context = self._build_request_context(migration_context)
        prompt = build_seo_migration_prompt(
            migration_context=migration_context,
            prompt_version=self.prompt_version,
            prompt_text_recommendations=self.prompt_text_recommendations,
        )
        payload = self._build_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
        )
        started_at = time.perf_counter()
        try:
            raw_response = self._request_completion(
                payload,
                request_context=request_context,
            )
            response_json = self._parse_json_object(
                raw_response,
                reason=_DRAFT_REASON_MALFORMED_RESPONSE,
                safe_message="Migration draft response could not be parsed.",
            )
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
    ) -> str:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        endpoint_path = "/chat/completions"
        request = urllib.request.Request(
            url=f"{self.api_base_url}{endpoint_path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        started_at = time.perf_counter()
        self._log_provider_request_start(request_context=request_context, endpoint_path=endpoint_path)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body_text = response.read().decode("utf-8", errors="replace")
                duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
                correlation_id = self._extract_response_correlation_id(getattr(response, "headers", None))
                self._log_provider_request_complete(
                    request_context=request_context,
                    endpoint_path=endpoint_path,
                    duration_ms=duration_ms,
                    correlation_id=correlation_id,
                )
                return body_text
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            correlation_id = self._extract_response_correlation_id(getattr(exc, "headers", None))
            reason = _DRAFT_REASON_TRANSPORT_ERROR
            retryable = True
            safe_message = "Migration draft generation failed while communicating with the AI provider."
            if exc.code in {401, 403}:
                reason = _DRAFT_REASON_AUTHENTICATION_FAILED
                retryable = False
                safe_message = "AI provider authentication failed for migration draft generation."
            elif exc.code == 429:
                reason = _DRAFT_REASON_RATE_LIMITED
                retryable = True
                safe_message = "Migration draft generation is currently rate-limited by the AI provider."
            elif exc.code in {400, 404, 422}:
                reason = _DRAFT_REASON_UNSUPPORTED_CONFIGURATION
                retryable = False
                safe_message = "AI provider configuration is invalid for migration draft generation."
            elif exc.code in {408, 504}:
                reason = _DRAFT_REASON_TIMEOUT
                retryable = True
                safe_message = "Migration draft generation timed out while calling the AI provider."
            self._log_provider_request_failure(
                request_context=request_context,
                reason=reason,
                retryable=retryable,
                correlation_id=correlation_id,
                duration_ms=duration_ms,
                http_status=exc.code,
            )
            raise self._provider_error(
                code=reason,
                reason=reason,
                safe_message=safe_message,
                retryable=retryable,
                correlation_id=correlation_id,
                raw_output=body_text,
                internal_details={
                    "request_failure_logged": True,
                    "http_status": int(exc.code),
                },
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            self._log_provider_request_failure(
                request_context=request_context,
                reason=_DRAFT_REASON_TIMEOUT,
                retryable=True,
                duration_ms=duration_ms,
            )
            raise self._provider_error(
                code=_DRAFT_REASON_TIMEOUT,
                reason=_DRAFT_REASON_TIMEOUT,
                safe_message="Migration draft generation timed out while calling the AI provider.",
                retryable=True,
                internal_details={"request_failure_logged": True},
            ) from exc
        except urllib.error.URLError as exc:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                self._log_provider_request_failure(
                    request_context=request_context,
                    reason=_DRAFT_REASON_TIMEOUT,
                    retryable=True,
                    duration_ms=duration_ms,
                )
                raise self._provider_error(
                    code=_DRAFT_REASON_TIMEOUT,
                    reason=_DRAFT_REASON_TIMEOUT,
                    safe_message="Migration draft generation timed out while calling the AI provider.",
                    retryable=True,
                    internal_details={"request_failure_logged": True},
                ) from exc
            self._log_provider_request_failure(
                request_context=request_context,
                reason=_DRAFT_REASON_TRANSPORT_ERROR,
                retryable=True,
                duration_ms=duration_ms,
            )
            raise self._provider_error(
                code=_DRAFT_REASON_TRANSPORT_ERROR,
                reason=_DRAFT_REASON_TRANSPORT_ERROR,
                safe_message="Migration draft generation failed while communicating with the AI provider.",
                retryable=True,
                internal_details={"request_failure_logged": True},
            ) from exc
        except Exception as exc:
            duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
            self._log_provider_request_failure(
                request_context=request_context,
                reason=_DRAFT_REASON_UNKNOWN,
                retryable=None,
                duration_ms=duration_ms,
            )
            raise self._provider_error(
                code=_DRAFT_REASON_UNKNOWN,
                reason=_DRAFT_REASON_UNKNOWN,
                safe_message="Migration draft generation failed due to an unexpected AI provider error.",
                retryable=None,
                internal_details={"request_failure_logged": True},
            ) from exc

    def _build_request_payload(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
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
            error_reason = _DRAFT_REASON_EMPTY_RESPONSE if normalized_reason == _MALFORMED_OUTPUT_REASON_EMPTY else reason
            message = "Migration draft response did not include content." if error_reason == _DRAFT_REASON_EMPTY_RESPONSE else safe_message
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

    def _normalize_top_level_payload(self, parsed: object) -> tuple[dict[str, object] | None, str | None, tuple[str, ...]]:
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
        )

    def _build_request_context(self, migration_context: dict[str, object]) -> dict[str, object]:
        site_snapshot = migration_context.get("site_snapshot")
        workspace_context = migration_context.get("migration_workspace")
        site_payload = site_snapshot if isinstance(site_snapshot, dict) else {}
        workspace_payload = workspace_context if isinstance(workspace_context, dict) else {}
        return {
            "business_id": _clean_optional_value(site_payload.get("business_id")),
            "site_id": _clean_optional_value(site_payload.get("site_id")),
            "workspace_id": _clean_optional_value(workspace_payload.get("workspace_id")),
            "provider_name": self.provider_name,
            "model": self.model_name,
            "prompt_version": self.prompt_version,
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

    def _log_provider_request_start(self, *, request_context: dict[str, object] | None, endpoint_path: str) -> None:
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
                "timeout_seconds": int(self.timeout_seconds),
            },
        )

    def _log_provider_request_complete(
        self,
        *,
        request_context: dict[str, object] | None,
        endpoint_path: str,
        duration_ms: int,
        correlation_id: str | None,
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
                "duration_ms": max(0, int(duration_ms)),
                "correlation_id": _clean_optional_value(correlation_id),
            },
        )

    def _log_provider_request_failure(
        self,
        *,
        request_context: dict[str, object] | None,
        reason: str | None,
        retryable: bool | None,
        correlation_id: str | None = None,
        duration_ms: int | None = None,
        http_status: int | None = None,
        parsed_candidate_count: int | None = None,
        salvaged_candidate_count: int | None = None,
        malformed_output_reason: str | None = None,
        raw_length: int | None = None,
    ) -> None:
        context = request_context or {}
        normalized_reason = _clean_optional_value((reason or "").strip().lower()) or _DRAFT_REASON_UNKNOWN
        if normalized_reason not in _DRAFT_REASON_VALUES:
            normalized_reason = _DRAFT_REASON_UNKNOWN
        self._emit_structured_provider_log(
            level=logging.WARNING,
            event=_PROVIDER_LOG_EVENT_REQUEST_FAILURE,
            payload={
                "business_id": _clean_optional_value(context.get("business_id")),
                "site_id": _clean_optional_value(context.get("site_id")),
                "workspace_id": _clean_optional_value(context.get("workspace_id")),
                "model": self.model_name,
                "prompt_version": self.prompt_version,
                "failure_reason": normalized_reason,
                "retryable": retryable,
                "correlation_id": _clean_optional_value(correlation_id),
                "duration_ms": (max(0, int(duration_ms)) if duration_ms is not None else None),
                "http_status": (int(http_status) if http_status is not None else None),
                "parsed_candidate_count": self._coerce_optional_non_negative_int(parsed_candidate_count),
                "salvaged_candidate_count": self._coerce_optional_non_negative_int(salvaged_candidate_count),
                "malformed_output_reason": self._normalize_malformed_output_reason(malformed_output_reason),
                "raw_length": self._coerce_optional_non_negative_int(raw_length),
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
            "cta_contact_structure": {"type": "object", "additionalProperties": True},
            "seo_meta_suggestions": {"type": "object", "additionalProperties": True},
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
