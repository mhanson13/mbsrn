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
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count, reduced_context_mode
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
    ) -> SEOCompetitorProfileGenerationOutput:
        self._log_prompt_resolution_metadata()
        prompt = build_seo_competitor_profile_prompt(
            site=site,
            existing_domains=existing_domains,
            candidate_count=candidate_count,
            reduced_context_mode=reduced_context_mode,
            prompt_version=self.prompt_version,
            prompt_text_competitor=self.prompt_text_competitor,
        )
        responses_request_debug = self._build_request_debug_metadata(
            endpoint_path="/responses",
            candidate_count=candidate_count,
            prompt_metrics=prompt.prompt_telemetry,
        )
        self._log_prompt_telemetry(responses_request_debug)
        responses_payload = self._build_responses_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            candidate_count=candidate_count,
        )
        chat_request_debug = self._build_request_debug_metadata(
            endpoint_path="/chat/completions",
            candidate_count=candidate_count,
            prompt_metrics=prompt.prompt_telemetry,
        )
        chat_payload = self._build_chat_completions_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            candidate_count=candidate_count,
        )
        try:
            response_json: dict[str, object] | None = None
            assistant_content: str | None = None
            responses_response = self._request_completion(
                responses_payload,
                endpoint_path="/responses",
                request_debug=responses_request_debug,
            )
            response_json = self._parse_json_object(
                responses_response.body_text,
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response could not be parsed.",
            )
            assistant_content = self._extract_assistant_content_from_responses(response_json)
            candidates = self._parse_or_normalize_candidates(
                assistant_content=assistant_content,
                candidate_count=candidate_count,
                endpoint_path="/responses",
                request_debug=responses_request_debug,
            )
            if not candidates:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_INVALID_OUTPUT,
                    safe_message="Competitor profile generation returned malformed output.",
                    raw_output=self._build_request_failure_debug_payload(
                        endpoint_path="/responses",
                        failure_kind="malformed_output",
                        request_debug=responses_request_debug,
                        provider_error_body=assistant_content,
                        malformed_output_reason=_MALFORMED_OUTPUT_REASON_MISSING_CANDIDATES_ARRAY,
                    ),
                )
            model_name = _clean_optional_value(response_json.get("model")) or self.model_name
            return SEOCompetitorProfileGenerationOutput(
                candidates=candidates,
                provider_name=self.provider_name,
                model_name=model_name,
                prompt_version=prompt.prompt_version,
                raw_response=assistant_content,
                endpoint_path="/responses",
                web_search_enabled=True,
                request_duration_ms=responses_response.request_duration_ms,
            )
        except SEOCompetitorProfileProviderError as exc:
            if not self._should_fallback_to_chat_completions(exc):
                raise
            logger.warning(
                (
                    "SEO competitor provider responses path reported unsupported web search; "
                    "falling back to chat completions "
                    "provider_name=%s model_name=%s endpoint=%s error_code=%s safe_message=%s "
                    "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
                ),
                self.provider_name,
                self.model_name,
                responses_request_debug.get("endpoint_path"),
                exc.code,
                _compact_log_message(exc.safe_message),
                responses_request_debug.get("prompt_total_chars"),
                responses_request_debug.get("context_json_chars"),
                responses_request_debug.get("prompt_size_risk"),
            )
            chat_response = self._request_completion(
                chat_payload,
                endpoint_path="/chat/completions",
                request_debug=chat_request_debug,
            )
            response_json = self._parse_json_object(
                chat_response.body_text,
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response could not be parsed.",
            )
            assistant_content = self._extract_assistant_content(response_json)
            candidates = self._parse_or_normalize_candidates(
                assistant_content=assistant_content,
                candidate_count=candidate_count,
                endpoint_path="/chat/completions",
                request_debug=chat_request_debug,
            )
            if not candidates:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_INVALID_OUTPUT,
                    safe_message="Competitor profile generation returned malformed output.",
                    raw_output=self._build_request_failure_debug_payload(
                        endpoint_path="/chat/completions",
                        failure_kind="malformed_output",
                        request_debug=chat_request_debug,
                        provider_error_body=assistant_content,
                        malformed_output_reason=_MALFORMED_OUTPUT_REASON_MISSING_CANDIDATES_ARRAY,
                    ),
                )
            model_name = _clean_optional_value(response_json.get("model")) or self.model_name
            return SEOCompetitorProfileGenerationOutput(
                candidates=candidates,
                provider_name=self.provider_name,
                model_name=model_name,
                prompt_version=prompt.prompt_version,
                raw_response=assistant_content,
                endpoint_path="/chat/completions",
                web_search_enabled=False,
                request_duration_ms=chat_response.request_duration_ms,
            )

    def _parse_or_normalize_candidates(
        self,
        *,
        assistant_content: str,
        candidate_count: int,
        endpoint_path: str,
        request_debug: dict[str, object] | None,
    ) -> list[SEOCompetitorProfileDraftCandidateOutput]:
        bounded_count = max(1, candidate_count)
        recovery = self._recover_structured_payload(assistant_content)
        normalized_json_text = assistant_content
        has_candidate_array = False
        invalid_field_type_count = 0
        if recovery.payload is not None:
            try:
                normalized_json_text = json.dumps(recovery.payload, ensure_ascii=True, sort_keys=True)
            except (TypeError, ValueError):
                normalized_json_text = assistant_content
            structured_candidates, has_candidate_array, invalid_field_type_count = (
                self._coerce_candidates_from_structured_payload(
                    payload=recovery.payload,
                    candidate_count=bounded_count,
                )
            )
            if structured_candidates:
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
                return structured_candidates

            if has_candidate_array and invalid_field_type_count > 0:
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
        normalized_candidates = self._coerce_candidates_from_normalized_payload(
            normalized_payload=normalized_payload,
            candidate_count=bounded_count,
        )
        if normalized_candidates:
            return normalized_candidates

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
                malformed_output_reason=malformed_reason,
                recovery_actions=recovery.recovery_actions,
            ),
        )

    def _coerce_candidates_from_structured_payload(
        self,
        *,
        payload: dict[str, object],
        candidate_count: int,
    ) -> tuple[list[SEOCompetitorProfileDraftCandidateOutput], bool, int]:
        raw_candidates = payload.get("candidates")
        if not isinstance(raw_candidates, list):
            return [], False, 0
        candidates: list[SEOCompetitorProfileDraftCandidateOutput] = []
        invalid_field_type_count = 0
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
        return candidates, True, invalid_field_type_count

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
    ) -> list[SEOCompetitorProfileDraftCandidateOutput]:
        raw_competitors = normalized_payload.get("competitors")
        if not isinstance(raw_competitors, list):
            return []

        candidates: list[SEOCompetitorProfileDraftCandidateOutput] = []
        for raw_competitor in raw_competitors:
            if not isinstance(raw_competitor, dict):
                continue

            suggested_name = _clean_optional_value(raw_competitor.get("name")) or "Unknown"
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
        return candidates

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

    def _request_completion(
        self,
        payload: dict[str, object],
        *,
        endpoint_path: str,
        request_debug: dict[str, object] | None = None,
    ) -> _OpenAICompletionResponse:
        normalized_endpoint = endpoint_path.strip() or "/chat/completions"
        if not normalized_endpoint.startswith("/"):
            normalized_endpoint = f"/{normalized_endpoint}"
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

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
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
        provider_error_message: str | None = None
        try:
            parsed = json.loads(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            endpoint_path = _clean_optional_value(parsed.get("endpoint_path"))
            provider_error_message = _clean_optional_value(parsed.get("provider_error_message"))

        if endpoint_path and endpoint_path != "/responses":
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
                "SEO competitor prompt assembly telemetry provider_name=%s model_name=%s endpoint=%s "
                "prompt_total_chars=%s context_json_chars=%s prompt_size_risk=%s"
            ),
            self.provider_name,
            self.model_name,
            request_debug.get("endpoint_path"),
            prompt_total_chars,
            context_json_chars,
            prompt_size_risk,
        )

    def _build_request_debug_metadata(
        self,
        *,
        endpoint_path: str,
        candidate_count: int,
        prompt_metrics: dict[str, int] | None,
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
        normalized_endpoint = endpoint_path.strip() or "/chat/completions"
        return {
            "endpoint_path": normalized_endpoint,
            "candidate_count": max(1, int(candidate_count)),
            "prompt_total_chars": prompt_total_chars,
            "context_json_chars": context_json_chars,
            "user_prompt_chars": user_prompt_chars,
            "reduced_context_mode": reduced_context_mode,
            "prompt_size_risk": prompt_size_risk,
            "timeout_seconds": self.timeout_seconds,
            "web_search_enabled": normalized_endpoint == "/responses",
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


def _normalize_text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _clean_optional_value(item)
        if text:
            normalized.append(text)
    return normalized


def _coerce_bounded_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _compact_log_message(value: str | None) -> str | None:
    cleaned = _clean_optional_value(value)
    if cleaned is None:
        return None
    if len(cleaned) <= _PROVIDER_ERROR_MESSAGE_MAX_CHARS:
        return cleaned
    return f"{cleaned[:_PROVIDER_ERROR_MESSAGE_MAX_CHARS]}..."
