from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
)
from app.models.seo_site import SEOSite
from app.services.competitors.normalizer import normalize_competitor_response
from app.services.seo_competitor_profile_prompt import (
    SEO_COMPETITOR_PROFILE_PROMPT_VERSION,
    build_seo_competitor_profile_prompt,
)


_PROVIDER_ERROR_TIMEOUT = "timeout"
_PROVIDER_ERROR_AUTH_CONFIG = "provider_auth_config"
_PROVIDER_ERROR_INVALID_OUTPUT = "invalid_output"
_PROVIDER_ERROR_SCHEMA_VALIDATION = "schema_validation"
_PROVIDER_ERROR_PARSING = "parsing_error"
_PROVIDER_ERROR_REQUEST = "provider_request"
_LEGACY_PROMPT_CONFIG_KEY = "ai_prompt_text_recommendation"
_PROVIDER_ERROR_MESSAGE_MAX_CHARS = 320
_ASSISTANT_CONTENT_EXCERPT_MAX_CHARS = 480
_PROMPT_SIZE_WARN_THRESHOLD_CHARS = 10000
_PROMPT_SIZE_HIGH_RISK_CHARS = 14000
_STRUCTURED_LOG_EVENT_REQUEST_START = "competitor_provider_request_start"
_STRUCTURED_LOG_EVENT_REQUEST_COMPLETE = "competitor_provider_request_complete"
_STRUCTURED_LOG_EVENT_REQUEST_ERROR = "competitor_provider_request_error"
_STRUCTURED_LOG_EVENT_CANDIDATE_PIPELINE = "competitor_candidate_pipeline"
_MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR = "json_decode_error"
_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN = "wrapped_in_markdown"
_MALFORMED_OUTPUT_REASON_MISSING_CANDIDATES_ARRAY = "missing_candidates_array"
_MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE = "invalid_top_level_shape"
_MALFORMED_OUTPUT_REASON_PARTIAL_JSON = "partial_json"
_MALFORMED_OUTPUT_REASON_INVALID_FIELD_TYPES = "invalid_field_types"
_MALFORMED_OUTPUT_ALLOWED_REASONS = {
    _MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR,
    _MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,
    _MALFORMED_OUTPUT_REASON_MISSING_CANDIDATES_ARRAY,
    _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE,
    _MALFORMED_OUTPUT_REASON_PARTIAL_JSON,
    _MALFORMED_OUTPUT_REASON_INVALID_FIELD_TYPES,
}
_PROVIDER_CALL_TYPE_TOOL_ENABLED = "tool_enabled"
_PROVIDER_CALL_TYPE_NON_TOOL = "non_tool"
_PROVIDER_CALL_TYPES = {
    _PROVIDER_CALL_TYPE_TOOL_ENABLED,
    _PROVIDER_CALL_TYPE_NON_TOOL,
}
_EXECUTION_MODE_FAST_PATH = "fast_path"
_EXECUTION_MODE_FULL = "full"
_EXECUTION_MODE_DEGRADED = "degraded"
_EXECUTION_MODES = {
    _EXECUTION_MODE_FAST_PATH,
    _EXECUTION_MODE_FULL,
    _EXECUTION_MODE_DEGRADED,
}
_PROMPT_VERSION_MARKER_PATTERN = re.compile(r"(?mi)^\s*PROMPT_VERSION:\s*([^\r\n]+)\s*$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SEOCompetitorProfileProviderError(RuntimeError):
    code: str
    safe_message: str
    provider_name: str
    model_name: str
    prompt_version: str
    raw_output: str | None = None

    def __str__(self) -> str:
        return self.safe_message


@dataclass(frozen=True)
class _OpenAICompletionResponse:
    body_text: str
    request_duration_ms: int


@dataclass(frozen=True)
class _StructuredPayloadRecoveryResult:
    payload: dict[str, object] | None
    reason: str | None
    recovery_actions: tuple[str, ...]


@dataclass(frozen=True)
class _ParsedCandidateResult:
    candidates: list[SEOCompetitorProfileDraftCandidateOutput]
    parsed_candidate_count: int
    salvaged_candidate_count: int
    raw_candidate_count: int
    dropped_missing_fields_count: int


class MisconfiguredSEOCompetitorProfileGenerationProvider:
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

    def generate_competitor_profiles(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
        reduced_context_mode: bool = False,
        timeout_seconds: int | None = None,
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count, reduced_context_mode, timeout_seconds
        raise SEOCompetitorProfileProviderError(
            code=_PROVIDER_ERROR_AUTH_CONFIG,
            safe_message=self.safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )


class OpenAISEOCompetitorProfileGenerationProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: int = 30,
        api_base_url: str = "https://api.openai.com/v1",
        prompt_version: str = SEO_COMPETITOR_PROFILE_PROMPT_VERSION,
        prompt_text_competitor: str | None = None,
        # DEPRECATED: use prompt_text_competitor.
        prompt_text_recommendation: str | None = None,
        prompt_source: str = "unknown",
        prompt_config_key: str = "ai_prompt_text_competitor",
        legacy_config_used: bool = False,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("OpenAI API key is required")
        self.api_key = normalized_key
        self.model_name = model_name.strip() or "gpt-4o-mini"
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.api_base_url = api_base_url.rstrip("/")
        self.prompt_version = prompt_version.strip() or SEO_COMPETITOR_PROFILE_PROMPT_VERSION
        effective_prompt_text_competitor = prompt_text_competitor
        if effective_prompt_text_competitor is None:
            effective_prompt_text_competitor = prompt_text_recommendation or ""
        self.prompt_text_competitor = effective_prompt_text_competitor
        # DEPRECATED: retained for compatibility with existing tests/callers.
        self.prompt_text_recommendation = effective_prompt_text_competitor
        self.prompt_source = str(prompt_source or "unknown").strip() or "unknown"
        self.prompt_config_key = str(prompt_config_key or "ai_prompt_text_competitor").strip()
        self.legacy_config_used = bool(legacy_config_used)

    def generate_competitor_profiles(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
        reduced_context_mode: bool = False,
        run_id: str | None = None,
        attempt_number: int | None = None,
        degraded_mode: bool = False,
        execution_mode: str | None = None,
        provider_call_type: str | None = None,
        web_search_enabled: bool | None = None,
        timeout_seconds: int | None = None,
    ) -> SEOCompetitorProfileGenerationOutput:
        effective_timeout_seconds = self._resolve_timeout_seconds(timeout_seconds)
        self._log_prompt_resolution_metadata()
        prompt = build_seo_competitor_profile_prompt(
            site=site,
            existing_domains=existing_domains,
            candidate_count=candidate_count,
            reduced_context_mode=reduced_context_mode,
            prompt_version=self.prompt_version,
            prompt_text_competitor=self.prompt_text_competitor,
        )
        resolved_prompt_version = self._resolve_prompt_version_from_user_prompt(
            prompt.user_prompt,
            fallback=prompt.prompt_version,
        )
        normalized_execution_mode = self._normalize_execution_mode(
            execution_mode=execution_mode,
            degraded_mode=degraded_mode,
            reduced_context_mode=reduced_context_mode,
        )
        normalized_provider_call_type = self._normalize_provider_call_type(
            provider_call_type=provider_call_type,
            web_search_enabled=web_search_enabled,
        )
        request_debug = self._build_request_debug_metadata(
            provider_call_type=normalized_provider_call_type,
            execution_mode=normalized_execution_mode,
            candidate_count=candidate_count,
            prompt_metrics=prompt.prompt_telemetry,
            run_id=run_id,
            attempt_number=attempt_number,
            degraded_mode=degraded_mode,
            timeout_seconds=effective_timeout_seconds,
        )
        self._log_prompt_telemetry(request_debug)
        allow_legacy_responses_fallback = (
            provider_call_type is None
            and web_search_enabled is None
            and normalized_provider_call_type == _PROVIDER_CALL_TYPE_TOOL_ENABLED
        )

        try:
            return self._execute_provider_call(
                prompt=prompt,
                candidate_count=candidate_count,
                provider_call_type=normalized_provider_call_type,
                request_debug=request_debug,
                timeout_seconds=effective_timeout_seconds,
                resolved_prompt_version=resolved_prompt_version,
            )
        except SEOCompetitorProfileProviderError as exc:
            if self._should_log_structured_error(exc):
                self._log_provider_request_error_from_provider_error(
                    provider_error=exc,
                    endpoint_path=self._endpoint_path_for_provider_call_type(normalized_provider_call_type),
                    request_debug=request_debug,
                )
            if not allow_legacy_responses_fallback or not self._should_fallback_to_chat_completions(exc):
                raise
            fallback_call_type = _PROVIDER_CALL_TYPE_NON_TOOL
            fallback_request_debug = self._build_request_debug_metadata(
                provider_call_type=fallback_call_type,
                execution_mode=normalized_execution_mode,
                candidate_count=candidate_count,
                prompt_metrics=prompt.prompt_telemetry,
                run_id=run_id,
                attempt_number=attempt_number,
                degraded_mode=degraded_mode,
                timeout_seconds=effective_timeout_seconds,
            )
            logger.warning(
                (
                    "SEO competitor provider responses path reported unsupported web search; "
                    "falling back to chat completions "
                    "provider_name=%s model_name=%s provider_call_type=%s execution_mode=%s endpoint=%s "
                    "error_code=%s safe_message=%s "
                    "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
                ),
                self.provider_name,
                self.model_name,
                request_debug.get("provider_call_type"),
                request_debug.get("execution_mode"),
                request_debug.get("endpoint_path"),
                exc.code,
                _compact_log_message(exc.safe_message),
                request_debug.get("prompt_total_chars"),
                request_debug.get("context_json_chars"),
                request_debug.get("prompt_size_risk"),
            )
            try:
                return self._execute_provider_call(
                    prompt=prompt,
                    candidate_count=candidate_count,
                    provider_call_type=fallback_call_type,
                    request_debug=fallback_request_debug,
                    timeout_seconds=effective_timeout_seconds,
                    resolved_prompt_version=resolved_prompt_version,
                )
            except SEOCompetitorProfileProviderError as chat_exc:
                if self._should_log_structured_error(chat_exc):
                    self._log_provider_request_error_from_provider_error(
                        provider_error=chat_exc,
                        endpoint_path=self._endpoint_path_for_provider_call_type(fallback_call_type),
                        request_debug=fallback_request_debug,
                    )
                raise

    def _execute_provider_call(
        self,
        *,
        prompt,
        candidate_count: int,
        provider_call_type: str,
        request_debug: dict[str, object] | None,
        timeout_seconds: int,
        resolved_prompt_version: str,
    ) -> SEOCompetitorProfileGenerationOutput:
        endpoint_path = self._endpoint_path_for_provider_call_type(provider_call_type)
        if provider_call_type == _PROVIDER_CALL_TYPE_TOOL_ENABLED:
            payload = self._build_responses_request_payload(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
                candidate_count=candidate_count,
            )
            extract_assistant_content = self._extract_assistant_content_from_responses
        else:
            payload = self._build_chat_completions_request_payload(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
                candidate_count=candidate_count,
            )
            extract_assistant_content = self._extract_assistant_content

        response = self._request_completion(
            payload,
            endpoint_path=endpoint_path,
            request_debug=request_debug,
            timeout_seconds=timeout_seconds,
        )
        response_json = self._parse_json_object(
            response.body_text,
            code=_PROVIDER_ERROR_PARSING,
            safe_message="Competitor profile generation response could not be parsed.",
        )
        assistant_content = extract_assistant_content(response_json)
        candidate_parse_result = self._parse_or_normalize_candidates(
            assistant_content=assistant_content,
            candidate_count=candidate_count,
            endpoint_path=endpoint_path,
            request_debug=request_debug,
            request_duration_ms=response.request_duration_ms,
        )
        candidates = candidate_parse_result.candidates
        self._log_candidate_pipeline(
            endpoint_path=endpoint_path,
            request_debug=request_debug,
            raw_candidate_count=candidate_parse_result.raw_candidate_count,
            valid_candidate_count=candidate_parse_result.parsed_candidate_count,
            dropped_missing_fields_count=candidate_parse_result.dropped_missing_fields_count,
        )
        model_name = _clean_optional_value(response_json.get("model")) or self.model_name
        self._log_provider_request_complete(
            endpoint_path=endpoint_path,
            request_debug=request_debug,
            request_duration_ms=response.request_duration_ms,
            parsed_candidate_count=candidate_parse_result.parsed_candidate_count,
            salvaged_candidate_count=candidate_parse_result.salvaged_candidate_count,
        )
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates,
            provider_name=self.provider_name,
            model_name=model_name,
            prompt_version=resolved_prompt_version,
            raw_response=assistant_content,
            provider_call_type=provider_call_type,
            endpoint_path=endpoint_path,
            web_search_enabled=self._web_search_enabled_for_provider_call_type(provider_call_type),
            request_duration_ms=response.request_duration_ms,
        )

    def _resolve_prompt_version_from_user_prompt(self, user_prompt: str, *, fallback: str) -> str:
        if not user_prompt:
            return fallback
        match = _PROMPT_VERSION_MARKER_PATTERN.search(user_prompt)
        if not match:
            return fallback
        extracted = _clean_optional_value(match.group(1))
        return extracted or fallback

    def _parse_or_normalize_candidates(
        self,
        *,
        assistant_content: str,
        candidate_count: int,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
        request_duration_ms: int | None = None,
    ) -> _ParsedCandidateResult:
        bounded_count = max(1, candidate_count)
        recovery = self._recover_structured_payload(assistant_content)
        normalized_json_text = assistant_content
        has_candidate_array = False
        raw_candidate_count = 0
        invalid_field_type_count = 0
        coerced_candidate_count = 0

        if recovery.payload is not None:
            try:
                normalized_json_text = json.dumps(recovery.payload, ensure_ascii=True, sort_keys=True)
            except (TypeError, ValueError):
                normalized_json_text = assistant_content

            (
                structured_candidates,
                has_candidate_array,
                invalid_field_type_count,
                coerced_candidate_count,
                raw_candidate_count,
            ) = self._coerce_candidates_from_structured_payload(
                payload=recovery.payload,
                candidate_count=bounded_count,
            )
            filtered_structured_candidates, dropped_missing_fields_count = self._filter_candidates_with_required_fields(
                structured_candidates
            )
            if has_candidate_array:
                if recovery.recovery_actions:
                    logger.info(
                        (
                            "Competitor profile payload recovered from wrapped output "
                            "provider_name=%s model_name=%s endpoint=%s recovery_actions=%s"
                        ),
                        self.provider_name,
                        self.model_name,
                        endpoint_path,
                        ",".join(recovery.recovery_actions),
                    )
                if invalid_field_type_count > 0:
                    logger.warning(
                        (
                            "Competitor profile payload included malformed candidate entries; "
                            "valid entries were preserved provider_name=%s model_name=%s endpoint=%s "
                            "invalid_field_type_count=%s"
                        ),
                        self.provider_name,
                        self.model_name,
                        endpoint_path,
                        invalid_field_type_count,
                    )
                salvaged_candidate_count = 0
                if recovery.recovery_actions:
                    salvaged_candidate_count = len(filtered_structured_candidates)
                elif coerced_candidate_count > 0:
                    salvaged_candidate_count = min(len(filtered_structured_candidates), coerced_candidate_count)
                return _ParsedCandidateResult(
                    candidates=filtered_structured_candidates,
                    parsed_candidate_count=len(filtered_structured_candidates),
                    salvaged_candidate_count=max(0, int(salvaged_candidate_count)),
                    raw_candidate_count=max(0, int(raw_candidate_count)),
                    dropped_missing_fields_count=max(0, int(dropped_missing_fields_count)),
                )

            if invalid_field_type_count > 0:
                logger.warning(
                    (
                        "Competitor profile payload candidate entries failed strict typing; "
                        "attempting normalized salvage provider_name=%s model_name=%s endpoint=%s "
                        "invalid_field_type_count=%s"
                    ),
                    self.provider_name,
                    self.model_name,
                    endpoint_path,
                    invalid_field_type_count,
                )

        normalized_payload = normalize_competitor_response(normalized_json_text)
        normalized_candidates, normalized_raw_candidate_count = self._coerce_candidates_from_normalized_payload(
            normalized_payload=normalized_payload,
            candidate_count=bounded_count,
        )
        filtered_normalized_candidates, dropped_missing_fields_count = self._filter_candidates_with_required_fields(
            normalized_candidates
        )
        if normalized_raw_candidate_count > 0:
            salvaged_candidate_count = 0
            if recovery.recovery_actions or invalid_field_type_count > 0:
                salvaged_candidate_count = len(filtered_normalized_candidates)
            return _ParsedCandidateResult(
                candidates=filtered_normalized_candidates,
                parsed_candidate_count=len(filtered_normalized_candidates),
                salvaged_candidate_count=max(0, int(salvaged_candidate_count)),
                raw_candidate_count=max(0, int(normalized_raw_candidate_count)),
                dropped_missing_fields_count=max(0, int(dropped_missing_fields_count)),
            )

        malformed_reason = recovery.reason
        if malformed_reason is None:
            if has_candidate_array and invalid_field_type_count > 0:
                malformed_reason = _MALFORMED_OUTPUT_REASON_INVALID_FIELD_TYPES
            elif recovery.payload is not None and not has_candidate_array:
                malformed_reason = _MALFORMED_OUTPUT_REASON_MISSING_CANDIDATES_ARRAY
            else:
                malformed_reason = _MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR
        if malformed_reason not in _MALFORMED_OUTPUT_ALLOWED_REASONS:
            malformed_reason = _MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR
        raise self._provider_error(
            code=_PROVIDER_ERROR_INVALID_OUTPUT,
            safe_message="Competitor profile generation returned malformed output.",
            raw_output=self._build_request_failure_debug_payload(
                endpoint_path=endpoint_path,
                failure_kind="malformed_output",
                request_debug=request_debug,
                provider_error_body=assistant_content,
                request_duration_ms=request_duration_ms,
                malformed_output_reason=malformed_reason,
                recovery_actions=recovery.recovery_actions,
            ),
        )

    def _coerce_candidates_from_structured_payload(
        self,
        *,
        payload: dict[str, object],
        candidate_count: int,
    ) -> tuple[list[SEOCompetitorProfileDraftCandidateOutput], bool, int, int, int]:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return [], False, 0, 0, 0
        candidates: list[SEOCompetitorProfileDraftCandidateOutput] = []
        invalid_field_type_count = 0
        coerced_candidate_count = 0
        for raw_candidate in raw_candidates:
            if len(candidates) >= candidate_count:
                break
            try:
                parsed_candidate = _OpenAICompetitorProfileCandidate.model_validate(raw_candidate)
            except ValidationError:
                coerced_candidate = self._coerce_candidate_from_structured_item(raw_candidate)
                if coerced_candidate is None:
                    invalid_field_type_count += 1
                    continue
                invalid_field_type_count += 1
                coerced_candidate_count += 1
                candidates.append(coerced_candidate)
                continue
            candidates.append(
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name=parsed_candidate.name,
                    suggested_domain=parsed_candidate.domain,
                    competitor_type=parsed_candidate.competitor_type,
                    summary=parsed_candidate.summary,
                    why_competitor=parsed_candidate.why_competitor,
                    evidence=parsed_candidate.evidence,
                    confidence_score=parsed_candidate.confidence_score,
                )
            )
        return candidates, True, invalid_field_type_count, coerced_candidate_count, len(raw_candidates)

    def _coerce_candidate_from_structured_item(
        self,
        raw_candidate: object,
    ) -> SEOCompetitorProfileDraftCandidateOutput | None:
        if not isinstance(raw_candidate, dict):
            return None
        suggested_name = _clean_optional_value(
            raw_candidate.get("name") if raw_candidate.get("name") is not None else raw_candidate.get("suggested_name")
        ) or ""
        suggested_domain = _clean_optional_value(
            raw_candidate.get("domain")
            if raw_candidate.get("domain") is not None
            else raw_candidate.get("suggested_domain")
        ) or ""
        competitor_type = _clean_optional_value(raw_candidate.get("competitor_type")) or "unknown"
        summary = _clean_optional_value(raw_candidate.get("summary"))
        why_competitor = _clean_optional_value(raw_candidate.get("why_competitor"))
        evidence = _clean_optional_value(raw_candidate.get("evidence"))
        confidence_score = self._coerce_confidence_score_for_recovery(raw_candidate)
        return SEOCompetitorProfileDraftCandidateOutput(
            suggested_name=suggested_name,
            suggested_domain=suggested_domain,
            competitor_type=competitor_type,
            summary=summary,
            why_competitor=why_competitor,
            evidence=evidence,
            confidence_score=confidence_score,
        )

    def _coerce_confidence_score_for_recovery(self, raw_candidate: dict[str, object]) -> float:
        if "confidence_score" in raw_candidate:
            direct_score = self._coerce_optional_float(raw_candidate.get("confidence_score"))
            if direct_score is not None:
                return direct_score
            return -1.0
        relevance = _coerce_bounded_int(raw_candidate.get("relevance_score"), minimum=1, maximum=5, default=3)
        visibility = _coerce_bounded_int(raw_candidate.get("visibility_score"), minimum=1, maximum=5, default=3)
        return max(0.0, min(1.0, (relevance + visibility) / 10.0))

    def _coerce_optional_float(self, value: object) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        if parsed != parsed:  # NaN
            return None
        if parsed in {float("inf"), float("-inf")}:
            return None
        return parsed

    def _recover_structured_payload(self, raw_text: str) -> _StructuredPayloadRecoveryResult:
        normalized = raw_text.strip()
        if not normalized:
            return _StructuredPayloadRecoveryResult(
                payload=None,
                reason=_MALFORMED_OUTPUT_REASON_JSON_DECODE_ERROR,
                recovery_actions=(),
            )

        parsed = self._parse_candidate_json_value(normalized)
        if parsed is not None:
            payload, payload_reason = self._normalize_payload_shape(parsed)
            return _StructuredPayloadRecoveryResult(payload=payload, reason=payload_reason, recovery_actions=())

        fenced = self._extract_markdown_fenced_json(normalized)
        if fenced is not None:
            fenced_parsed = self._parse_candidate_json_value(fenced)
            if fenced_parsed is not None:
                payload, payload_reason = self._normalize_payload_shape(fenced_parsed)
                if payload is not None:
                    return _StructuredPayloadRecoveryResult(
                        payload=payload,
                        reason=None,
                        recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,),
                    )
                return _StructuredPayloadRecoveryResult(
                    payload=None,
                    reason=payload_reason,
                    recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,),
                )

        extracted_json_fragment, fragment_partial = self._extract_first_json_fragment(normalized)
        if extracted_json_fragment is not None:
            extracted_parsed = self._parse_candidate_json_value(extracted_json_fragment)
            if extracted_parsed is not None:
                payload, payload_reason = self._normalize_payload_shape(extracted_parsed)
                return _StructuredPayloadRecoveryResult(
                    payload=payload,
                    reason=payload_reason,
                    recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,)
                    if fenced is not None
                    else (),
                )
        if fragment_partial:
            return _StructuredPayloadRecoveryResult(
                payload=None,
                reason=_MALFORMED_OUTPUT_REASON_PARTIAL_JSON,
                recovery_actions=(_MALFORMED_OUTPUT_REASON_WRAPPED_IN_MARKDOWN,)
                if fenced is not None
                else (),
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

    def _parse_candidate_json_value(self, raw_text: str) -> object | None:
        try:
            return json.loads(raw_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _normalize_payload_shape(self, parsed: object) -> tuple[dict[str, object] | None, str | None]:
        if isinstance(parsed, dict):
            return parsed, None
        if isinstance(parsed, list):
            return {"candidates": parsed}, None
        return None, _MALFORMED_OUTPUT_REASON_INVALID_TOP_LEVEL_SHAPE

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

    def _coerce_candidates_from_normalized_payload(
        self,
        *,
        normalized_payload: dict[str, object],
        candidate_count: int,
    ) -> tuple[list[SEOCompetitorProfileDraftCandidateOutput], int]:
        raw_competitors = normalized_payload.get("competitors")
        if not isinstance(raw_competitors, list):
            return [], 0

        candidates: list[SEOCompetitorProfileDraftCandidateOutput] = []
        for raw_competitor in raw_competitors:
            if not isinstance(raw_competitor, dict):
                continue

            suggested_name = _clean_optional_value(raw_competitor.get("name")) or ""
            suggested_domain = _clean_optional_value(raw_competitor.get("domain")) or ""
            summary = _clean_optional_value(raw_competitor.get("summary"))
            opportunities = _normalize_text_list(raw_competitor.get("opportunities"))
            strengths = _normalize_text_list(raw_competitor.get("strengths"))
            differentiators = _normalize_text_list(raw_competitor.get("differentiators"))
            threats = _normalize_text_list(raw_competitor.get("threats"))

            why_competitor = opportunities[0] if opportunities else (differentiators[0] if differentiators else summary)
            evidence = strengths[0] if strengths else (differentiators[0] if differentiators else (threats[0] if threats else None))

            relevance_score = _coerce_bounded_int(raw_competitor.get("relevance_score"), minimum=1, maximum=5, default=3)
            visibility_score = _coerce_bounded_int(raw_competitor.get("visibility_score"), minimum=1, maximum=5, default=3)
            confidence_score = max(0.0, min(1.0, (relevance_score + visibility_score) / 10.0))

            candidates.append(
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name=suggested_name,
                    suggested_domain=suggested_domain,
                    competitor_type="unknown",
                    summary=summary,
                    why_competitor=why_competitor,
                    evidence=evidence,
                    confidence_score=confidence_score,
                )
            )
            if len(candidates) >= candidate_count:
                break
        return candidates, len(raw_competitors)

    def _filter_candidates_with_required_fields(
        self,
        candidates: list[SEOCompetitorProfileDraftCandidateOutput],
    ) -> tuple[list[SEOCompetitorProfileDraftCandidateOutput], int]:
        filtered: list[SEOCompetitorProfileDraftCandidateOutput] = []
        dropped_missing_fields_count = 0
        for candidate in candidates:
            normalized_name = _clean_optional_value(candidate.suggested_name)
            normalized_domain = _normalize_domain_hostname(candidate.suggested_domain)
            if normalized_name is None or normalized_domain is None:
                dropped_missing_fields_count += 1
                continue
            filtered.append(
                SEOCompetitorProfileDraftCandidateOutput(
                    suggested_name=normalized_name,
                    suggested_domain=normalized_domain,
                    competitor_type=candidate.competitor_type,
                    summary=candidate.summary,
                    why_competitor=candidate.why_competitor,
                    evidence=candidate.evidence,
                    confidence_score=candidate.confidence_score,
                )
            )
        return filtered, dropped_missing_fields_count

    def _log_prompt_resolution_metadata(self) -> None:
        logger.info(
            (
                "ai_prompt_resolution pipeline=competitor prompt_source=%s legacy_config_used=%s "
                "prompt_config_key=%s model_name=%s provider_name=%s"
            ),
            self.prompt_source,
            self.legacy_config_used,
            self.prompt_config_key,
            self.model_name,
            self.provider_name,
        )
        if self.legacy_config_used:
            logger.warning(
                (
                    "ai_prompt_legacy_fallback pipeline=competitor prompt_source=%s "
                    "prompt_config_key=%s legacy_config_key=%s model_name=%s provider_name=%s "
                    "split_prompt_unset_or_blank=true migrate_to_split_prompt=true"
                ),
                self.prompt_source,
                self.prompt_config_key,
                _LEGACY_PROMPT_CONFIG_KEY,
                self.model_name,
                self.provider_name,
            )

    def _emit_structured_provider_log(
        self,
        *,
        level: int,
        event: str,
        payload: dict[str, object],
    ) -> None:
        structured_payload = {"event": event, "provider_name": self.provider_name}
        structured_payload.update(payload)
        safe_payload = {
            key: value
            for key, value in structured_payload.items()
            if value is not None
        }
        try:
            serialized = json.dumps(safe_payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            serialized = event
        logger.log(level, serialized, extra={"json_fields": safe_payload})

    def _log_candidate_pipeline(
        self,
        *,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
        raw_candidate_count: int,
        valid_candidate_count: int,
        dropped_missing_fields_count: int,
    ) -> None:
        debug = request_debug or {}
        self._emit_structured_provider_log(
            level=logging.INFO,
            event=_STRUCTURED_LOG_EVENT_CANDIDATE_PIPELINE,
            payload={
                "run_id": _clean_optional_value(debug.get("run_id")),
                "attempt_number": _coerce_optional_bounded_int(
                    debug.get("attempt_number"),
                    minimum=0,
                    maximum=1000,
                ),
                "execution_mode": _clean_optional_value(debug.get("execution_mode")),
                "provider_call_type": _clean_optional_value(debug.get("provider_call_type")),
                "endpoint_path": endpoint_path,
                "raw_count": max(0, int(raw_candidate_count)),
                "valid_count": max(0, int(valid_candidate_count)),
                "dropped_missing_fields": max(0, int(dropped_missing_fields_count)),
                "web_search_enabled": debug.get("web_search_enabled"),
                "degraded_mode": bool(debug.get("degraded_mode")),
            },
        )

    def _log_provider_request_start(
        self,
        *,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
    ) -> None:
        debug = request_debug or {}
        self._emit_structured_provider_log(
            level=logging.INFO,
            event=_STRUCTURED_LOG_EVENT_REQUEST_START,
            payload={
                "run_id": _clean_optional_value(debug.get("run_id")),
                "attempt_number": _coerce_optional_bounded_int(
                    debug.get("attempt_number"),
                    minimum=0,
                    maximum=1000,
                ),
                "execution_mode": _clean_optional_value(debug.get("execution_mode")),
                "provider_call_type": _clean_optional_value(debug.get("provider_call_type")),
                "endpoint_path": endpoint_path,
                "model": self.model_name,
                "web_search_enabled": debug.get("web_search_enabled"),
                "degraded_mode": bool(debug.get("degraded_mode")),
                "reduced_context_mode": bool(debug.get("reduced_context_mode")),
                "prompt_chars": _coerce_optional_bounded_int(
                    debug.get("prompt_total_chars"),
                    minimum=0,
                    maximum=250000,
                ),
                "timeout_seconds_used": _coerce_optional_bounded_int(
                    debug.get("timeout_seconds"),
                    minimum=1,
                    maximum=3600,
                ),
            },
        )

    def _log_provider_request_complete(
        self,
        *,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
        request_duration_ms: int | None,
        parsed_candidate_count: int,
        salvaged_candidate_count: int,
    ) -> None:
        debug = request_debug or {}
        payload: dict[str, object] = {
            "run_id": _clean_optional_value(debug.get("run_id")),
            "attempt_number": _coerce_optional_bounded_int(
                debug.get("attempt_number"),
                minimum=0,
                maximum=1000,
            ),
            "execution_mode": _clean_optional_value(debug.get("execution_mode")),
            "provider_call_type": _clean_optional_value(debug.get("provider_call_type")),
            "endpoint_path": endpoint_path,
            "duration_ms": _coerce_optional_bounded_int(
                request_duration_ms,
                minimum=0,
                maximum=3_600_000,
            ),
            "model": self.model_name,
            "web_search_enabled": debug.get("web_search_enabled"),
            "degraded_mode": bool(debug.get("degraded_mode")),
            "reduced_context_mode": bool(debug.get("reduced_context_mode")),
            "timeout_seconds_used": _coerce_optional_bounded_int(
                debug.get("timeout_seconds"),
                minimum=1,
                maximum=3600,
            ),
            "parsed_candidate_count": max(0, int(parsed_candidate_count)),
            "discovery_candidate_count": max(0, int(parsed_candidate_count)),
            "post_parse_candidate_count": max(0, int(parsed_candidate_count)),
        }
        if salvaged_candidate_count > 0:
            payload["salvaged_candidate_count"] = max(0, int(salvaged_candidate_count))
        self._emit_structured_provider_log(
            level=logging.INFO,
            event=_STRUCTURED_LOG_EVENT_REQUEST_COMPLETE,
            payload=payload,
        )

    def _log_provider_request_error(
        self,
        *,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
        error_type: str | None,
        failure_kind: str,
        malformed_output_reason: str | None = None,
        request_duration_ms: int | None = None,
    ) -> None:
        debug = request_debug or {}
        payload: dict[str, object] = {
            "run_id": _clean_optional_value(debug.get("run_id")),
            "attempt_number": _coerce_optional_bounded_int(
                debug.get("attempt_number"),
                minimum=0,
                maximum=1000,
            ),
            "execution_mode": _clean_optional_value(debug.get("execution_mode")),
            "provider_call_type": _clean_optional_value(debug.get("provider_call_type")),
            "endpoint_path": endpoint_path,
            "duration_ms": _coerce_optional_bounded_int(
                request_duration_ms,
                minimum=0,
                maximum=3_600_000,
            ),
            "model": self.model_name,
            "web_search_enabled": debug.get("web_search_enabled"),
            "degraded_mode": bool(debug.get("degraded_mode")),
            "reduced_context_mode": bool(debug.get("reduced_context_mode")),
            "timeout_seconds_used": _coerce_optional_bounded_int(
                debug.get("timeout_seconds"),
                minimum=1,
                maximum=3600,
            ),
            "error_type": _sanitize_log_error_type(error_type),
            "failure_kind": failure_kind,
        }
        normalized_reason = _clean_optional_value(
            str(malformed_output_reason or "").strip().lower()
        )
        if normalized_reason in _MALFORMED_OUTPUT_ALLOWED_REASONS:
            payload["malformed_output_reason"] = normalized_reason
        self._emit_structured_provider_log(
            level=logging.WARNING,
            event=_STRUCTURED_LOG_EVENT_REQUEST_ERROR,
            payload=payload,
        )

    def _should_log_structured_error(self, provider_error: SEOCompetitorProfileProviderError) -> bool:
        if provider_error.code in {_PROVIDER_ERROR_INVALID_OUTPUT, _PROVIDER_ERROR_SCHEMA_VALIDATION, _PROVIDER_ERROR_PARSING}:
            return True
        failure_kind, _, _, _ = self._extract_structured_failure_details(provider_error.raw_output)
        return failure_kind == "malformed_output"

    def _log_provider_request_error_from_provider_error(
        self,
        *,
        provider_error: SEOCompetitorProfileProviderError,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
    ) -> None:
        failure_kind, malformed_output_reason, duration_ms, parsed_endpoint = self._extract_structured_failure_details(
            provider_error.raw_output
        )
        effective_failure_kind = failure_kind or "malformed_output"
        effective_endpoint = parsed_endpoint or endpoint_path
        if effective_failure_kind not in {"timeout", "provider_request", "malformed_output"}:
            effective_failure_kind = "provider_request"
        if effective_failure_kind == "malformed_output":
            error_type = provider_error.code or _PROVIDER_ERROR_INVALID_OUTPUT
        else:
            error_type = provider_error.code or _PROVIDER_ERROR_REQUEST
        self._log_provider_request_error(
            endpoint_path=effective_endpoint,
            request_debug=request_debug,
            error_type=error_type,
            failure_kind=effective_failure_kind,
            malformed_output_reason=malformed_output_reason,
            request_duration_ms=duration_ms,
        )

    def _extract_structured_failure_details(
        self,
        raw_output: str | None,
    ) -> tuple[str | None, str | None, int | None, str | None]:
        if not raw_output:
            return None, None, None, None
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None, None, None, None
        if not isinstance(parsed, dict):
            return None, None, None, None
        failure_kind = _clean_optional_value(parsed.get("failure_kind"))
        if failure_kind not in {"timeout", "provider_request", "malformed_output"}:
            failure_kind = None
        malformed_output_reason = _clean_optional_value(parsed.get("malformed_output_reason"))
        if malformed_output_reason not in _MALFORMED_OUTPUT_ALLOWED_REASONS:
            malformed_output_reason = None
        endpoint_path = _clean_optional_value(parsed.get("endpoint_path"))
        request_debug = parsed.get("request_debug")
        request_duration_ms = None
        if isinstance(request_debug, dict):
            request_duration_ms = _coerce_optional_bounded_int(
                request_debug.get("request_duration_ms"),
                minimum=0,
                maximum=3_600_000,
            )
        return failure_kind, malformed_output_reason, request_duration_ms, endpoint_path

    def _request_completion(
        self,
        payload: dict[str, object],
        *,
        endpoint_path: str,
        request_debug: dict[str, object] | None = None,
        timeout_seconds: int | None = None,
    ) -> _OpenAICompletionResponse:
        normalized_endpoint = endpoint_path.strip() or "/chat/completions"
        if not normalized_endpoint.startswith("/"):
            normalized_endpoint = f"/{normalized_endpoint}"
        effective_timeout_seconds = self._resolve_timeout_seconds(timeout_seconds)
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.api_base_url}{normalized_endpoint}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        request_started_at = time.perf_counter()
        self._log_provider_request_start(
            endpoint_path=normalized_endpoint,
            request_debug=request_debug,
        )

        try:
            with urllib.request.urlopen(request, timeout=effective_timeout_seconds) as response:
                body_text = response.read().decode("utf-8", errors="replace")
            request_duration_ms = max(0, int((time.perf_counter() - request_started_at) * 1000))
            return _OpenAICompletionResponse(
                body_text=body_text,
                request_duration_ms=request_duration_ms,
            )
        except urllib.error.HTTPError as exc:
            request_duration_ms = max(0, int((time.perf_counter() - request_started_at) * 1000))
            body_text = exc.read().decode("utf-8", errors="replace")
            error_type, error_code, error_message = self._extract_provider_error_details(body_text)
            logger.warning(
                (
                    "SEO competitor provider HTTP error status=%s provider_name=%s model_name=%s "
                    "endpoint=%s error_type=%s error_code=%s error_message=%s "
                    "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
                ),
                exc.code,
                self.provider_name,
                self.model_name,
                normalized_endpoint,
                error_type,
                error_code,
                error_message,
                request_debug.get("prompt_total_chars") if request_debug else None,
                request_debug.get("context_json_chars") if request_debug else None,
                request_debug.get("prompt_size_risk") if request_debug else None,
            )
            failure_kind = "timeout" if exc.code in {408, 504} else "provider_request"
            self._log_provider_request_error(
                endpoint_path=normalized_endpoint,
                request_debug=request_debug,
                error_type=error_type or error_code or "http_error",
                failure_kind=failure_kind,
                request_duration_ms=request_duration_ms,
            )
            if exc.code in {401, 403}:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_AUTH_CONFIG,
                    safe_message=(
                        "AI provider authentication failed. Verify competitor profile provider credentials."
                    ),
                    raw_output=body_text,
                ) from exc
            if exc.code in {408, 504}:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_TIMEOUT,
                    safe_message="Competitor profile generation timed out while calling the AI provider.",
                    raw_output=self._build_request_failure_debug_payload(
                        endpoint_path=normalized_endpoint,
                        failure_kind="timeout",
                        request_debug=request_debug,
                        provider_error_body=body_text,
                        request_duration_ms=request_duration_ms,
                    ),
                ) from exc
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Competitor profile generation provider request failed.",
                raw_output=self._build_request_failure_debug_payload(
                    endpoint_path=normalized_endpoint,
                    failure_kind="provider_request",
                    request_debug=request_debug,
                    provider_error_body=body_text,
                    request_duration_ms=request_duration_ms,
                ),
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            request_duration_ms = max(0, int((time.perf_counter() - request_started_at) * 1000))
            logger.warning(
                (
                    "SEO competitor provider timeout provider_name=%s model_name=%s endpoint=%s reason=%s "
                    "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
                ),
                self.provider_name,
                self.model_name,
                normalized_endpoint,
                str(exc),
                request_debug.get("prompt_total_chars") if request_debug else None,
                request_debug.get("context_json_chars") if request_debug else None,
                request_debug.get("prompt_size_risk") if request_debug else None,
            )
            self._log_provider_request_error(
                endpoint_path=normalized_endpoint,
                request_debug=request_debug,
                error_type="timeout",
                failure_kind="timeout",
                request_duration_ms=request_duration_ms,
            )
            raise self._provider_error(
                code=_PROVIDER_ERROR_TIMEOUT,
                safe_message="Competitor profile generation timed out while calling the AI provider.",
                raw_output=self._build_request_failure_debug_payload(
                    endpoint_path=normalized_endpoint,
                    failure_kind="timeout",
                    request_debug=request_debug,
                    provider_error_body=str(exc),
                    request_duration_ms=request_duration_ms,
                ),
            ) from exc
        except urllib.error.URLError as exc:
            request_duration_ms = max(0, int((time.perf_counter() - request_started_at) * 1000))
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                logger.warning(
                    (
                        "SEO competitor provider timeout provider_name=%s model_name=%s endpoint=%s reason=%s "
                        "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
                    ),
                    self.provider_name,
                    self.model_name,
                    normalized_endpoint,
                    str(exc.reason),
                    request_debug.get("prompt_total_chars") if request_debug else None,
                    request_debug.get("context_json_chars") if request_debug else None,
                    request_debug.get("prompt_size_risk") if request_debug else None,
                )
                self._log_provider_request_error(
                    endpoint_path=normalized_endpoint,
                    request_debug=request_debug,
                    error_type="timeout",
                    failure_kind="timeout",
                    request_duration_ms=request_duration_ms,
                )
                raise self._provider_error(
                    code=_PROVIDER_ERROR_TIMEOUT,
                    safe_message="Competitor profile generation timed out while calling the AI provider.",
                    raw_output=self._build_request_failure_debug_payload(
                        endpoint_path=normalized_endpoint,
                        failure_kind="timeout",
                        request_debug=request_debug,
                        provider_error_body=str(exc.reason),
                        request_duration_ms=request_duration_ms,
                    ),
                ) from exc
            logger.warning(
                (
                    "SEO competitor provider URL error provider_name=%s model_name=%s endpoint=%s reason=%s "
                    "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
                ),
                self.provider_name,
                self.model_name,
                normalized_endpoint,
                str(exc.reason),
                request_debug.get("prompt_total_chars") if request_debug else None,
                request_debug.get("context_json_chars") if request_debug else None,
                request_debug.get("prompt_size_risk") if request_debug else None,
            )
            self._log_provider_request_error(
                endpoint_path=normalized_endpoint,
                request_debug=request_debug,
                error_type=exc.reason.__class__.__name__ if exc.reason is not None else "url_error",
                failure_kind="provider_request",
                request_duration_ms=request_duration_ms,
            )
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Competitor profile generation provider request failed.",
                raw_output=self._build_request_failure_debug_payload(
                    endpoint_path=normalized_endpoint,
                    failure_kind="provider_request",
                    request_debug=request_debug,
                    provider_error_body=str(exc.reason),
                    request_duration_ms=request_duration_ms,
                ),
            ) from exc

    def _should_fallback_to_chat_completions(
        self,
        error: SEOCompetitorProfileProviderError,
    ) -> bool:
        if error.code != _PROVIDER_ERROR_REQUEST:
            return False
        raw_output = _clean_optional_value(error.raw_output)
        if raw_output is None:
            return False

        endpoint_path: str | None = None
        provider_call_type: str | None = None
        provider_error_message: str | None = None
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            endpoint_path = _clean_optional_value(parsed.get("endpoint_path"))
            provider_error_message = _clean_optional_value(parsed.get("provider_error_message"))
            request_debug = parsed.get("request_debug")
            if isinstance(request_debug, dict):
                provider_call_type = _clean_optional_value(request_debug.get("provider_call_type"))

        if provider_call_type in _PROVIDER_CALL_TYPES:
            if provider_call_type != _PROVIDER_CALL_TYPE_TOOL_ENABLED:
                return False
        elif endpoint_path and endpoint_path != "/responses":
            return False

        comparison_text = (provider_error_message or "").lower()
        if not comparison_text:
            # Backward compatibility for non-debug payloads.
            comparison_text = raw_output.lower()
        if "web_search" not in comparison_text:
            return False
        if "not supported" in comparison_text:
            return True
        if "unsupported_parameter" in comparison_text:
            return True
        if "unsupported parameter" in comparison_text:
            return True
        return False

    def _build_responses_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        candidate_count: int,
    ) -> dict[str, object]:
        return {
            "model": self.model_name,
            "tools": [{"type": "web_search"}],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "seo_competitor_profile_generation_response",
                    "strict": True,
                    "schema": _build_candidate_json_schema(candidate_count),
                }
            },
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    def _build_chat_completions_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        candidate_count: int,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "seo_competitor_profile_generation_response",
                    "strict": True,
                    "schema": _build_candidate_json_schema(candidate_count),
                },
            },
        }
        if self._model_supports_temperature():
            payload["temperature"] = 0
        return payload

    def _model_supports_temperature(self) -> bool:
        return not self.model_name.strip().lower().startswith("gpt-5-mini")

    def _normalize_provider_call_type(
        self,
        *,
        provider_call_type: str | None,
        web_search_enabled: bool | None,
    ) -> str:
        normalized = _clean_optional_value(provider_call_type)
        if normalized in _PROVIDER_CALL_TYPES:
            return normalized
        if isinstance(web_search_enabled, bool):
            return (
                _PROVIDER_CALL_TYPE_TOOL_ENABLED
                if web_search_enabled
                else _PROVIDER_CALL_TYPE_NON_TOOL
            )
        return _PROVIDER_CALL_TYPE_TOOL_ENABLED

    def _normalize_execution_mode(
        self,
        *,
        execution_mode: str | None,
        degraded_mode: bool,
        reduced_context_mode: bool,
    ) -> str:
        normalized = _clean_optional_value(execution_mode)
        if normalized in _EXECUTION_MODES:
            return normalized
        if degraded_mode:
            return _EXECUTION_MODE_DEGRADED
        if reduced_context_mode:
            return _EXECUTION_MODE_FAST_PATH
        return _EXECUTION_MODE_FULL

    @staticmethod
    def _endpoint_path_for_provider_call_type(provider_call_type: str) -> str:
        if provider_call_type == _PROVIDER_CALL_TYPE_NON_TOOL:
            return "/chat/completions"
        return "/responses"

    @staticmethod
    def _web_search_enabled_for_provider_call_type(provider_call_type: str) -> bool:
        return provider_call_type == _PROVIDER_CALL_TYPE_TOOL_ENABLED

    def _resolve_timeout_seconds(self, timeout_seconds: int | None) -> int:
        if timeout_seconds is None:
            return self.timeout_seconds
        try:
            return max(1, int(timeout_seconds))
        except (TypeError, ValueError):
            return self.timeout_seconds

    def _extract_provider_error_details(self, body_text: str) -> tuple[str | None, str | None, str | None]:
        normalized_body = body_text.strip()
        if not normalized_body:
            return None, None, None
        try:
            parsed = json.loads(normalized_body)
        except json.JSONDecodeError:
            return None, None, _compact_log_message(normalized_body)
        if not isinstance(parsed, dict):
            return None, None, _compact_log_message(normalized_body)
        error_payload = parsed.get("error")
        if isinstance(error_payload, dict):
            error_type = _clean_optional_value(error_payload.get("type"))
            error_code = _clean_optional_value(error_payload.get("code"))
            error_message = _clean_optional_value(error_payload.get("message"))
            return error_type, error_code, _compact_log_message(error_message)
        return None, None, _compact_log_message(_clean_optional_value(parsed.get("message")))

    def _log_prompt_telemetry(self, request_debug: dict[str, object]) -> None:
        prompt_total_chars = request_debug.get("prompt_total_chars")
        context_json_chars = request_debug.get("context_json_chars")
        prompt_size_risk = request_debug.get("prompt_size_risk")
        level = logging.WARNING if prompt_size_risk in {"high", "elevated"} else logging.INFO
        logger.log(
            level,
            (
                "SEO competitor prompt assembly telemetry provider_name=%s model_name=%s "
                "provider_call_type=%s execution_mode=%s endpoint=%s "
                "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
            ),
            self.provider_name,
            self.model_name,
            request_debug.get("provider_call_type"),
            request_debug.get("execution_mode"),
            request_debug.get("endpoint_path"),
            prompt_total_chars,
            context_json_chars,
            prompt_size_risk,
        )

    def _build_request_debug_metadata(
        self,
        *,
        provider_call_type: str,
        execution_mode: str,
        candidate_count: int,
        prompt_metrics: dict[str, int] | None,
        run_id: str | None,
        attempt_number: int | None,
        degraded_mode: bool,
        timeout_seconds: int,
    ) -> dict[str, object]:
        metrics = prompt_metrics or {}
        prompt_total_chars = _coerce_bounded_int(
            metrics.get("total_prompt_chars"),
            minimum=0,
            maximum=250000,
            default=0,
        )
        context_json_chars = _coerce_bounded_int(
            metrics.get("context_json_chars"),
            minimum=0,
            maximum=250000,
            default=0,
        )
        user_prompt_chars = _coerce_bounded_int(
            metrics.get("user_prompt_chars"),
            minimum=0,
            maximum=250000,
            default=0,
        )
        reduced_context_mode = bool(metrics.get("reduced_context_mode"))
        if prompt_total_chars >= _PROMPT_SIZE_HIGH_RISK_CHARS:
            prompt_size_risk = "high"
        elif prompt_total_chars >= _PROMPT_SIZE_WARN_THRESHOLD_CHARS:
            prompt_size_risk = "elevated"
        else:
            prompt_size_risk = "normal"
        normalized_provider_call_type = self._normalize_provider_call_type(
            provider_call_type=provider_call_type,
            web_search_enabled=None,
        )
        normalized_execution_mode = self._normalize_execution_mode(
            execution_mode=execution_mode,
            degraded_mode=degraded_mode,
            reduced_context_mode=reduced_context_mode,
        )
        normalized_endpoint = self._endpoint_path_for_provider_call_type(normalized_provider_call_type)
        normalized_run_id = _clean_optional_value(run_id)
        normalized_attempt_number = _coerce_optional_bounded_int(
            attempt_number,
            minimum=0,
            maximum=1000,
        )
        return {
            "run_id": normalized_run_id,
            "attempt_number": normalized_attempt_number,
            "degraded_mode": bool(degraded_mode),
            "execution_mode": normalized_execution_mode,
            "provider_call_type": normalized_provider_call_type,
            "endpoint_path": normalized_endpoint,
            "candidate_count": max(1, int(candidate_count)),
            "prompt_total_chars": prompt_total_chars,
            "context_json_chars": context_json_chars,
            "user_prompt_chars": user_prompt_chars,
            "reduced_context_mode": reduced_context_mode,
            "prompt_size_risk": prompt_size_risk,
            "timeout_seconds": timeout_seconds,
            "web_search_enabled": self._web_search_enabled_for_provider_call_type(normalized_provider_call_type),
        }

    def _build_request_failure_debug_payload(
        self,
        *,
        endpoint_path: str,
        failure_kind: str,
        request_debug: dict[str, object] | None,
        provider_error_body: str | None,
        request_duration_ms: int | None = None,
        malformed_output_reason: str | None = None,
        recovery_actions: tuple[str, ...] | None = None,
    ) -> str | None:
        normalized_failure_kind = (failure_kind or "").strip().lower()
        if normalized_failure_kind not in {"timeout", "provider_request", "malformed_output"}:
            normalized_failure_kind = "provider_request"
        payload: dict[str, object] = {
            "failure_kind": normalized_failure_kind,
            "endpoint_path": endpoint_path,
        }
        if request_debug:
            payload["request_debug"] = {
                "run_id": request_debug.get("run_id"),
                "attempt_number": request_debug.get("attempt_number"),
                "execution_mode": request_debug.get("execution_mode"),
                "provider_call_type": request_debug.get("provider_call_type"),
                "degraded_mode": request_debug.get("degraded_mode"),
                "candidate_count": request_debug.get("candidate_count"),
                "prompt_total_chars": request_debug.get("prompt_total_chars"),
                "context_json_chars": request_debug.get("context_json_chars"),
                "user_prompt_chars": request_debug.get("user_prompt_chars"),
                "reduced_context_mode": request_debug.get("reduced_context_mode"),
                "prompt_size_risk": request_debug.get("prompt_size_risk"),
                "timeout_seconds": request_debug.get("timeout_seconds"),
                "web_search_enabled": request_debug.get("web_search_enabled"),
            }
        if request_duration_ms is not None:
            payload.setdefault("request_debug", {})
            if isinstance(payload["request_debug"], dict):
                payload["request_debug"]["request_duration_ms"] = max(0, int(request_duration_ms))
        if normalized_failure_kind == "malformed_output":
            normalized_reason = _clean_optional_value((malformed_output_reason or "").strip().lower())
            if normalized_reason in _MALFORMED_OUTPUT_ALLOWED_REASONS:
                payload["malformed_output_reason"] = normalized_reason
            if recovery_actions:
                normalized_actions = [
                    action
                    for action in recovery_actions
                    if action in _MALFORMED_OUTPUT_ALLOWED_REASONS
                ]
                if normalized_actions:
                    payload["recovery_actions"] = normalized_actions
        compact_error = _compact_log_message(_clean_optional_value(provider_error_body))
        if compact_error:
            if normalized_failure_kind == "malformed_output":
                payload["assistant_content_excerpt"] = compact_error[:_ASSISTANT_CONTENT_EXCERPT_MAX_CHARS]
            else:
                payload["provider_error_message"] = compact_error
        try:
            return json.dumps(payload, ensure_ascii=True, sort_keys=True)
        except (TypeError, ValueError):
            return None

    def _extract_assistant_content(self, response_json: dict[str, object]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response did not include choices.",
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response choice was malformed.",
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )

        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response message was malformed.",
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
            code=_PROVIDER_ERROR_PARSING,
            safe_message="Competitor profile generation response did not include content.",
            raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
        )

    def _extract_assistant_content_from_responses(self, response_json: dict[str, object]) -> str:
        output_text = response_json.get("output_text")
        if isinstance(output_text, str):
            normalized_output_text = output_text.strip()
            if normalized_output_text:
                return normalized_output_text

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
            code=_PROVIDER_ERROR_PARSING,
            safe_message="Competitor profile generation response did not include content.",
            raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
        )

    def _parse_json_object(
        self,
        raw_json: str,
        *,
        code: str,
        safe_message: str,
        raw_output: str | None = None,
    ) -> dict[str, object]:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise self._provider_error(
                code=code,
                safe_message=safe_message,
                raw_output=raw_output or raw_json,
            ) from exc
        if not isinstance(parsed, dict):
            raise self._provider_error(
                code=code,
                safe_message=safe_message,
                raw_output=raw_output or raw_json,
            )
        return parsed

    def _provider_error(
        self,
        *,
        code: str,
        safe_message: str,
        raw_output: str | None = None,
    ) -> SEOCompetitorProfileProviderError:
        return SEOCompetitorProfileProviderError(
            code=code,
            safe_message=safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output=raw_output,
        )


class _OpenAICompetitorProfileCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    domain: str
    competitor_type: str
    summary: str | None = None
    why_competitor: str | None = None
    evidence: str | None = None
    confidence_score: float

    @field_validator("name", "domain", "competitor_type", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("value is required")
        return normalized

    @field_validator("summary", "why_competitor", "evidence", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence_score must be numeric") from exc


class _OpenAICompetitorProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidates: list[_OpenAICompetitorProfileCandidate] = Field(min_length=1)


def _build_candidate_json_schema(candidate_count: int) -> dict[str, object]:
    bounded_count = max(1, min(20, candidate_count))
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["candidates"],
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": 1,
                "maxItems": bounded_count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name",
                        "domain",
                        "competitor_type",
                        "summary",
                        "why_competitor",
                        "evidence",
                        "confidence_score",
                    ],
                    "properties": {
                        "name": {"type": "string"},
                        "domain": {"type": "string"},
                        "competitor_type": {"type": "string"},
                        "summary": {"type": ["string", "null"]},
                        "why_competitor": {"type": ["string", "null"]},
                        "evidence": {"type": ["string", "null"]},
                        "confidence_score": {"type": "number"},
                    },
                },
            },
        },
    }


def _clean_optional_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_domain_hostname(value: object) -> str | None:
    normalized = _clean_optional_value(value)
    if normalized is None:
        return None
    candidate = normalized.strip()
    if not candidate:
        return None
    parse_target = candidate if "://" in candidate else f"//{candidate}"
    parsed = urllib.parse.urlsplit(parse_target)
    hostname = parsed.hostname
    if hostname is None:
        return None
    clean_hostname = hostname.strip().lower().rstrip(".")
    if not clean_hostname:
        return None
    if any(char.isspace() for char in clean_hostname):
        return None
    return clean_hostname


def _normalize_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _clean_optional_value(item)
        if text:
            normalized.append(text)
    return normalized


def _coerce_optional_bounded_int(value: object, *, minimum: int, maximum: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return max(minimum, min(maximum, parsed))


def _coerce_bounded_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _sanitize_log_error_type(value: object) -> str | None:
    normalized = _clean_optional_value(value)
    if normalized is None:
        return None
    compact = re.sub(r"[^a-zA-Z0-9_.:/-]+", "_", normalized)
    compact = compact.strip("_")
    if not compact:
        return None
    if len(compact) <= 96:
        return compact
    return compact[:96]


def _compact_log_message(value: str | None) -> str | None:
    cleaned = _clean_optional_value(value)
    if cleaned is None:
        return None
    if len(cleaned) <= _PROVIDER_ERROR_MESSAGE_MAX_CHARS:
        return cleaned
    return f"{cleaned[:_PROVIDER_ERROR_MESSAGE_MAX_CHARS]}..."
