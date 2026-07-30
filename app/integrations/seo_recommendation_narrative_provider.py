from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.log_sanitizer import sanitize_log_payload
from app.integrations.ai_execution_core import (
    AIContextBlock,
    AIExecutionError,
    AIExecutionPolicy,
    apply_request_budget,
    execute_json_request,
)
from app.integrations.seo_summary_provider import SEORecommendationNarrativeOutput
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.services.seo_competitor_profile_candidate_quality import (
    BIG_BOX_PENALTY_MAX,
    BIG_BOX_PENALTY_MIN,
    DIRECTORY_PENALTY_MAX,
    DIRECTORY_PENALTY_MIN,
    LOCAL_ALIGNMENT_BONUS_MAX,
    LOCAL_ALIGNMENT_BONUS_MIN,
    MIN_RELEVANCE_SCORE_MAX,
    MIN_RELEVANCE_SCORE_MIN,
)
from app.services.seo_recommendation_narrative_prompt import (
    SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION,
    build_seo_recommendation_narrative_prompt,
)
from app.services.seo_recommendation_diversity import (
    normalize_recommendation_next_actions,
)
from app.services.ai_model_settings import resolve_openai_non_tool_structured_output_profile


_PROVIDER_ERROR_TIMEOUT = "timeout"
_PROVIDER_ERROR_AUTH_CONFIG = "provider_auth_config"
_PROVIDER_ERROR_INVALID_OUTPUT = "invalid_output"
_PROVIDER_ERROR_SCHEMA_VALIDATION = "schema_validation"
_PROVIDER_ERROR_PARSING = "parsing_error"
_PROVIDER_ERROR_REQUEST = "provider_request"
_LEGACY_PROMPT_CONFIG_KEY = "ai_prompt_text_recommendation"
_NARRATIVE_RESPONSE_FORMAT_NAME = "seo_recommendation_narrative_response"
logger = logging.getLogger(__name__)

_MAX_NARRATIVE_TEXT_LENGTH = 6000
_MAX_THEME_LENGTH = 140
_MAX_THEMES = 8
_MAX_SECTION_TEXT_LENGTH = 1200
_MAX_NEXT_ACTION_LENGTH = 220
_MAX_NEXT_ACTIONS = 10
_MAX_RECOMMENDATION_REFERENCES = 25
_MAX_TUNING_SUGGESTIONS = 4
_MAX_TUNING_REASON_LENGTH = 320
_MAX_TUNING_LINKED_RECOMMENDATION_IDS = 8
_RECOMMENDATION_CONTEXT_BUDGET_CHARS = 28000
_RECOMMENDATION_MAX_TOTAL_INPUT_SIZE = 95000
_RECOMMENDATION_REQUIRED_CONTEXT_KEYS = ("current_tuning_values",)
_RECOMMENDATION_OPTIONAL_TRIM_ORDER = (
    "competitor_context",
    "competitor_telemetry_summary",
)

_ALLOWED_TUNING_SETTINGS_BOUNDS: dict[str, tuple[int, int]] = {
    "competitor_candidate_min_relevance_score": (
        MIN_RELEVANCE_SCORE_MIN,
        MIN_RELEVANCE_SCORE_MAX,
    ),
    "competitor_candidate_big_box_penalty": (
        BIG_BOX_PENALTY_MIN,
        BIG_BOX_PENALTY_MAX,
    ),
    "competitor_candidate_directory_penalty": (
        DIRECTORY_PENALTY_MIN,
        DIRECTORY_PENALTY_MAX,
    ),
    "competitor_candidate_local_alignment_bonus": (
        LOCAL_ALIGNMENT_BONUS_MIN,
        LOCAL_ALIGNMENT_BONUS_MAX,
    ),
}
_ALLOWED_TUNING_CONFIDENCE = {"low", "medium", "high"}


@dataclass(frozen=True)
class SEORecommendationNarrativeProviderError(RuntimeError):
    code: str
    safe_message: str
    provider_name: str
    model_name: str
    prompt_version: str
    raw_output: str | None = None
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


class MisconfiguredSEORecommendationNarrativeProvider:
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

    def generate_narrative(
        self,
        *,
        run: SEORecommendationRun,
        recommendations: list[SEORecommendation],
        by_status: dict[str, int],
        by_category: dict[str, int],
        by_severity: dict[str, int],
        by_effort_bucket: dict[str, int],
        by_priority_band: dict[str, int],
        backlog: list[SEORecommendation],
        competitor_telemetry_summary: dict[str, object],
        current_tuning_values: dict[str, int],
        competitor_context: dict[str, object] | None = None,
    ) -> SEORecommendationNarrativeOutput:
        del (
            run,
            recommendations,
            by_status,
            by_category,
            by_severity,
            by_effort_bucket,
            by_priority_band,
            backlog,
            competitor_telemetry_summary,
            current_tuning_values,
            competitor_context,
        )
        raise SEORecommendationNarrativeProviderError(
            code=_PROVIDER_ERROR_AUTH_CONFIG,
            safe_message=self.safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
        )


class OpenAISEORecommendationNarrativeProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        timeout_seconds: int = 30,
        api_base_url: str = "https://api.openai.com/v1",
        prompt_version: str = SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION,
        prompt_text_recommendations: str | None = None,
        # DEPRECATED: use prompt_text_recommendations.
        prompt_text_recommendation: str | None = None,
        prompt_source: str = "unknown",
        prompt_config_key: str = "ai_prompt_text_recommendations",
        legacy_config_used: bool = False,
    ) -> None:
        normalized_key = api_key.strip()
        if not normalized_key:
            raise ValueError("OpenAI API key is required")
        self.api_key = normalized_key
        self.model_name = model_name.strip() or "gpt-4o-mini"
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.api_base_url = api_base_url.rstrip("/")
        self.prompt_version = prompt_version.strip() or SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION
        effective_prompt_text_recommendations = prompt_text_recommendations
        if effective_prompt_text_recommendations is None:
            effective_prompt_text_recommendations = prompt_text_recommendation or ""
        self.prompt_text_recommendations = effective_prompt_text_recommendations
        # DEPRECATED: retained for compatibility with existing tests/callers.
        self.prompt_text_recommendation = effective_prompt_text_recommendations
        self.prompt_source = str(prompt_source or "unknown").strip() or "unknown"
        self.prompt_config_key = str(prompt_config_key or "ai_prompt_text_recommendations").strip()
        self.legacy_config_used = bool(legacy_config_used)

    def generate_narrative(
        self,
        *,
        run: SEORecommendationRun,
        recommendations: list[SEORecommendation],
        by_status: dict[str, int],
        by_category: dict[str, int],
        by_severity: dict[str, int],
        by_effort_bucket: dict[str, int],
        by_priority_band: dict[str, int],
        backlog: list[SEORecommendation],
        competitor_telemetry_summary: dict[str, object],
        current_tuning_values: dict[str, int],
        competitor_context: dict[str, object] | None = None,
    ) -> SEORecommendationNarrativeOutput:
        self._log_prompt_resolution_metadata()
        (
            budgeted_competitor_telemetry_summary,
            budgeted_current_tuning_values,
            budgeted_competitor_context,
            budget_result,
        ) = self._apply_recommendation_context_budget(
            competitor_telemetry_summary=competitor_telemetry_summary,
            current_tuning_values=current_tuning_values,
            competitor_context=competitor_context,
        )
        prompt = build_seo_recommendation_narrative_prompt(
            run=run,
            recommendations=recommendations,
            by_status=by_status,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort_bucket,
            by_priority_band=by_priority_band,
            backlog=backlog,
            competitor_telemetry_summary=budgeted_competitor_telemetry_summary,
            current_tuning_values=budgeted_current_tuning_values,
            competitor_context=budgeted_competitor_context,
            prompt_version=self.prompt_version,
            prompt_text_recommendations=self.prompt_text_recommendations,
        )
        if bool(budget_result.get("overflow")):
            self._log_budget_decision(
                budget_result=budget_result,
                budget_outcome="precall_rejected",
            )
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message=("Recommendation narrative request is too large or complex for synchronous generation."),
                normalized_failure_category="local_validation_failure",
                normalized_failure_reason="request_too_large_or_complex",
                normalized_failure_source="local_validation",
                normalized_retryable=False,
                attempt_count=0,
            )
        self._log_budget_decision(
            budget_result=budget_result,
            budget_outcome="provider_submission",
        )
        request_profile = resolve_openai_non_tool_structured_output_profile(self.model_name)
        if request_profile.endpoint_path == "/responses":
            payload = self._build_responses_request_payload(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
            )
            extract_assistant_content = self._extract_assistant_content_from_responses
        else:
            payload = self._build_chat_completions_request_payload(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
            )
            extract_assistant_content = self._extract_assistant_content
        raw_response = self._request_completion(
            payload,
            budget_result=budget_result,
            endpoint_path=request_profile.endpoint_path,
        )
        response_json = self._parse_json_object(
            raw_response,
            code=_PROVIDER_ERROR_PARSING,
            safe_message="Recommendation narrative response could not be parsed.",
        )
        assistant_content = extract_assistant_content(response_json)
        structured_json = self._parse_json_object(
            assistant_content,
            code=_PROVIDER_ERROR_INVALID_OUTPUT,
            safe_message="Recommendation narrative returned malformed output.",
            raw_output=assistant_content,
            allow_recovery=True,
        )
        try:
            parsed = _OpenAIRecommendationNarrativeResponse.model_validate(structured_json)
        except ValidationError as exc:
            salvaged = self._salvage_narrative_response(structured_json)
            if salvaged is None:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                    safe_message="Recommendation narrative returned invalid structured output.",
                    raw_output=assistant_content,
                ) from exc
            logger.info(
                (
                    "Recommendation narrative provider output partially salvaged "
                    "provider_name=%s model_name=%s parsed_sections=%s"
                ),
                self.provider_name,
                self.model_name,
                "yes" if salvaged.sections is not None else "no",
            )
            parsed = salvaged

        model_name = _clean_optional_value(response_json.get("model")) or self.model_name
        allowed_ids = {_clean_optional_value(getattr(item, "id", None)) for item in recommendations}
        allowed_recommendation_ids = {item for item in allowed_ids if item}

        sections = self._normalize_sections(
            parsed.sections,
            allowed_recommendation_ids=allowed_recommendation_ids,
            competitor_telemetry_summary=competitor_telemetry_summary,
            current_tuning_values=current_tuning_values,
            by_status=by_status,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort_bucket,
            by_priority_band=by_priority_band,
        )
        return SEORecommendationNarrativeOutput(
            narrative_text=self._normalize_narrative_text(parsed.narrative_text),
            top_themes=self._normalize_top_themes(parsed.top_themes),
            sections=sections,
            provider_name=self.provider_name,
            model_name=model_name,
            prompt_version=prompt.prompt_version,
        )

    def _log_prompt_resolution_metadata(self) -> None:
        logger.info(
            (
                "ai_prompt_resolution pipeline=recommendations prompt_source=%s legacy_config_used=%s "
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
                    "ai_prompt_legacy_fallback pipeline=recommendations prompt_source=%s "
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
        budget_result: dict[str, object],
        endpoint_path: str,
    ) -> str:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        normalized_endpoint_path = endpoint_path.strip() or "/chat/completions"
        if not normalized_endpoint_path.startswith("/"):
            normalized_endpoint_path = f"/{normalized_endpoint_path}"
        request = urllib.request.Request(
            url=f"{self.api_base_url}{normalized_endpoint_path}",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            execution_response = execute_json_request(
                request=request,
                policy=AIExecutionPolicy(
                    feature_area="recommendation_ai",
                    timeout_seconds=max(1, int(self.timeout_seconds)),
                    max_attempts=2,
                    retry_backoff_seconds=0.15,
                    max_input_size=_RECOMMENDATION_MAX_TOTAL_INPUT_SIZE,
                    original_input_size=budget_result.get("initial_size_bytes"),
                    final_input_size=budget_result.get("final_size_bytes"),
                    trimming_pass_count=(
                        int(budget_result.get("trimming_pass_count"))
                        if isinstance(budget_result.get("trimming_pass_count"), int)
                        else 0
                    ),
                    section_count=budget_result.get("section_count"),
                    schema_complexity_flag=True,
                ),
            )
            logger.info(
                (
                    "recommendation_narrative_provider_request_complete provider_name=%s model_name=%s "
                    "attempt_count=%s duration_ms=%s original_input_size=%s final_input_size=%s "
                    "trimmed_bytes=%s trimming_pass_count=%s difficulty_score=%s"
                ),
                self.provider_name,
                self.model_name,
                execution_response.attempt_count,
                execution_response.duration_ms,
                execution_response.original_input_size,
                execution_response.final_input_size,
                execution_response.trimmed_bytes,
                execution_response.trimming_pass_count,
                execution_response.difficulty_score,
            )
            return execution_response.body_text
        except AIExecutionError as exc:
            code = _PROVIDER_ERROR_REQUEST
            safe_message = "Recommendation narrative provider request failed."
            if exc.normalized_failure.reason == "provider_auth_or_configuration_invalid":
                code = _PROVIDER_ERROR_AUTH_CONFIG
                safe_message = (
                    "AI provider authentication failed. Verify recommendation narrative provider credentials."
                )
            elif exc.normalized_failure.category in {"configuration_missing", "configuration_invalid"}:
                safe_message = "AI provider rejected the recommendation narrative request configuration."
            elif exc.normalized_failure.category == "remote_timeout":
                code = _PROVIDER_ERROR_TIMEOUT
                safe_message = "Recommendation narrative generation timed out while calling the AI provider."
                if exc.normalized_failure.reason == "request_too_large_or_complex":
                    code = _PROVIDER_ERROR_REQUEST
                    safe_message = (
                        "Recommendation narrative request is too large or complex for synchronous generation."
                    )
            elif exc.normalized_failure.category == "local_validation_failure" and exc.normalized_failure.reason in {
                "request_too_large",
                "request_too_large_or_complex",
            }:
                code = _PROVIDER_ERROR_REQUEST
                safe_message = "Recommendation narrative request is too large or complex for synchronous generation."
            logger.warning(
                (
                    "recommendation_narrative_provider_request_failure provider_name=%s model_name=%s code=%s "
                    "normalized_failure_category=%s normalized_failure_reason=%s normalized_failure_source=%s "
                    "normalized_retryable=%s attempt_count=%s duration_ms=%s original_input_size=%s "
                    "final_input_size=%s trimmed_bytes=%s trimming_pass_count=%s difficulty_score=%s"
                ),
                self.provider_name,
                self.model_name,
                code,
                exc.normalized_failure.category,
                exc.normalized_failure.reason,
                exc.normalized_failure.source,
                exc.normalized_failure.retryable,
                exc.attempt_count,
                exc.duration_ms,
                exc.original_input_size,
                exc.final_input_size,
                exc.trimmed_bytes,
                exc.trimming_pass_count,
                exc.difficulty_score,
            )
            raise self._provider_error(
                code=code,
                safe_message=safe_message,
                raw_output=exc.raw_response_text,
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

    def _build_responses_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, object]:
        return {
            "model": self.model_name,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _NARRATIVE_RESPONSE_FORMAT_NAME,
                    "strict": True,
                    "schema": _build_narrative_json_schema(),
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
    ) -> dict[str, object]:
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
                    "name": _NARRATIVE_RESPONSE_FORMAT_NAME,
                    "strict": True,
                    "schema": _build_narrative_json_schema(),
                },
            },
        }

    def _extract_assistant_content(self, response_json: dict[str, object]) -> str:
        choices = response_json.get("choices")
        if not isinstance(choices, list) or not choices:
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Recommendation narrative response did not include choices.",
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Recommendation narrative response choice was malformed.",
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Recommendation narrative response message was malformed.",
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
            safe_message="Recommendation narrative response did not include content.",
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
            safe_message="Recommendation narrative response did not include content.",
            raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
        )

    def _parse_json_object(
        self,
        raw_json: str,
        *,
        code: str,
        safe_message: str,
        raw_output: str | None = None,
        allow_recovery: bool = False,
    ) -> dict[str, object]:
        parsed = self._try_parse_json_value(raw_json)
        if parsed is None and allow_recovery:
            recovered = self._recover_json_object(raw_json)
            parsed = recovered
        if parsed is None:
            raise self._provider_error(
                code=code,
                safe_message=safe_message,
                raw_output=raw_output or raw_json,
            )
        if not isinstance(parsed, dict):
            raise self._provider_error(
                code=code,
                safe_message=safe_message,
                raw_output=raw_output or raw_json,
            )
        return parsed

    def _try_parse_json_value(self, raw_text: str) -> object | None:
        try:
            return json.loads(raw_text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def _recover_json_object(self, raw_text: str) -> dict[str, object] | None:
        normalized = raw_text.strip()
        if not normalized:
            return None
        fenced = self._extract_markdown_fenced_json(normalized)
        if fenced is not None:
            parsed = self._try_parse_json_value(fenced)
            if isinstance(parsed, dict):
                return parsed
        fragment, _ = self._extract_first_json_fragment(normalized)
        if fragment is None:
            return None
        parsed_fragment = self._try_parse_json_value(fragment)
        if isinstance(parsed_fragment, dict):
            return parsed_fragment
        return None

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

    def _salvage_narrative_response(self, payload: dict[str, object]) -> _OpenAIRecommendationNarrativeResponse | None:
        narrative_text = _clean_optional_value(payload.get("narrative_text"))
        if narrative_text is None:
            narrative_text = _clean_optional_value(payload.get("narrative"))
        if narrative_text is None:
            return None

        raw_themes = payload.get("top_themes")
        top_themes: list[str] = []
        if isinstance(raw_themes, list):
            for item in raw_themes:
                normalized = _clean_optional_value(item)
                if normalized:
                    top_themes.append(normalized)
                if len(top_themes) >= _MAX_THEMES:
                    break
        elif raw_themes is not None:
            normalized_theme = _clean_optional_value(raw_themes)
            if normalized_theme:
                top_themes.append(normalized_theme)

        sections_payload = payload.get("sections")
        normalized_sections: dict[str, object] | None = None
        if isinstance(sections_payload, dict):
            next_actions = self._coerce_text_list(
                sections_payload.get("next_actions"),
                max_items=_MAX_NEXT_ACTIONS,
            )
            recommendation_references = self._coerce_text_list(
                sections_payload.get("recommendation_references"),
                max_items=_MAX_RECOMMENDATION_REFERENCES,
            )
            tuning_suggestions: list[dict[str, object]] = []
            raw_tuning = sections_payload.get("tuning_suggestions")
            raw_tuning_count = 0
            if isinstance(raw_tuning, list):
                raw_tuning_count = len(raw_tuning)
                for suggestion in raw_tuning:
                    if not isinstance(suggestion, dict):
                        continue
                    try:
                        normalized_suggestion = _OpenAIRecommendationNarrativeTuningSuggestion.model_validate(
                            suggestion
                        )
                    except ValidationError:
                        continue
                    tuning_suggestions.append(normalized_suggestion.model_dump(mode="json"))
                    if len(tuning_suggestions) >= _MAX_TUNING_SUGGESTIONS:
                        break
            if raw_tuning_count > 0 and not tuning_suggestions:
                return None
            normalized_sections = {
                "summary": _clean_optional_value(sections_payload.get("summary")),
                "priority_rationale": _clean_optional_value(sections_payload.get("priority_rationale")),
                "next_actions": next_actions,
                "recommendation_references": recommendation_references,
                "tuning_suggestions": tuning_suggestions,
            }
        normalized_payload: dict[str, object] = {
            "narrative_text": narrative_text,
            "top_themes": top_themes,
            "sections": normalized_sections,
        }
        try:
            return _OpenAIRecommendationNarrativeResponse.model_validate(normalized_payload)
        except ValidationError:
            return None

    def _coerce_text_list(self, value: object, *, max_items: int) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            text = _clean_optional_value(item)
            if text is None:
                continue
            normalized.append(text)
            if len(normalized) >= max_items:
                break
        return normalized

    def _normalize_narrative_text(self, value: str) -> str:
        normalized = _clean_optional_value(value) or "No narrative text returned."
        if len(normalized) > _MAX_NARRATIVE_TEXT_LENGTH:
            return normalized[:_MAX_NARRATIVE_TEXT_LENGTH]
        return normalized

    def _normalize_top_themes(self, values: list[str]) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in values:
            normalized = _clean_optional_value(item)
            if not normalized:
                continue
            if len(normalized) > _MAX_THEME_LENGTH:
                normalized = normalized[:_MAX_THEME_LENGTH]
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= _MAX_THEMES:
                break
        return deduped

    def _normalize_sections(
        self,
        sections: _OpenAIRecommendationNarrativeSections | None,
        *,
        allowed_recommendation_ids: set[str],
        competitor_telemetry_summary: dict[str, object],
        current_tuning_values: dict[str, int],
        by_status: dict[str, int],
        by_category: dict[str, int],
        by_severity: dict[str, int],
        by_effort_bucket: dict[str, int],
        by_priority_band: dict[str, int],
    ) -> dict[str, object]:
        summary = _clean_optional_value(sections.summary if sections is not None else None)
        priority_rationale = _clean_optional_value(sections.priority_rationale if sections is not None else None)
        if summary and len(summary) > _MAX_SECTION_TEXT_LENGTH:
            summary = summary[:_MAX_SECTION_TEXT_LENGTH]
        if priority_rationale and len(priority_rationale) > _MAX_SECTION_TEXT_LENGTH:
            priority_rationale = priority_rationale[:_MAX_SECTION_TEXT_LENGTH]

        next_actions: list[str] = []
        references: list[str] = []
        tuning_suggestions: list[dict[str, object]] = []
        if sections is not None:
            raw_next_actions: list[str] = []
            for value in sections.next_actions:
                normalized = _clean_optional_value(value)
                if not normalized:
                    continue
                if len(normalized) > _MAX_NEXT_ACTION_LENGTH:
                    normalized = normalized[:_MAX_NEXT_ACTION_LENGTH]
                raw_next_actions.append(normalized)
            next_actions = normalize_recommendation_next_actions(
                raw_next_actions,
                limit=_MAX_NEXT_ACTIONS,
                max_length=_MAX_NEXT_ACTION_LENGTH,
            )

            for value in sections.recommendation_references:
                normalized = _clean_optional_value(value)
                if not normalized:
                    continue
                if normalized not in allowed_recommendation_ids:
                    continue
                if normalized not in references:
                    references.append(normalized)
                if len(references) >= _MAX_RECOMMENDATION_REFERENCES:
                    break

            if self._telemetry_supports_tuning_suggestions(competitor_telemetry_summary):
                for suggestion in sections.tuning_suggestions:
                    setting = _clean_optional_value(suggestion.setting)
                    if not setting or setting not in _ALLOWED_TUNING_SETTINGS_BOUNDS:
                        raise self._provider_error(
                            code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                            safe_message="Recommendation narrative returned invalid structured output.",
                        )

                    linked_recommendation_ids: list[str] = []
                    for recommendation_id in suggestion.linked_recommendation_ids:
                        normalized_id = _clean_optional_value(recommendation_id)
                        if not normalized_id:
                            continue
                        if normalized_id not in allowed_recommendation_ids:
                            raise self._provider_error(
                                code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                                safe_message="Recommendation narrative returned invalid structured output.",
                            )
                        if normalized_id not in linked_recommendation_ids:
                            linked_recommendation_ids.append(normalized_id)
                        if len(linked_recommendation_ids) >= _MAX_TUNING_LINKED_RECOMMENDATION_IDS:
                            break
                    if not linked_recommendation_ids:
                        raise self._provider_error(
                            code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                            safe_message="Recommendation narrative returned invalid structured output.",
                        )

                    current_value = self._coerce_tuning_value(
                        setting=setting,
                        value=current_tuning_values.get(setting, suggestion.current_value),
                    )
                    recommended_value = self._coerce_tuning_value(
                        setting=setting,
                        value=suggestion.recommended_value,
                    )
                    reason = _clean_optional_value(suggestion.reason)
                    if not reason:
                        raise self._provider_error(
                            code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                            safe_message="Recommendation narrative returned invalid structured output.",
                        )
                    if len(reason) > _MAX_TUNING_REASON_LENGTH:
                        reason = reason[:_MAX_TUNING_REASON_LENGTH]

                    confidence = _clean_optional_value(suggestion.confidence)
                    normalized_confidence = (confidence or "").lower()
                    if normalized_confidence not in _ALLOWED_TUNING_CONFIDENCE:
                        raise self._provider_error(
                            code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                            safe_message="Recommendation narrative returned invalid structured output.",
                        )
                    tuning_suggestions.append(
                        {
                            "setting": setting,
                            "current_value": current_value,
                            "recommended_value": recommended_value,
                            "reason": reason,
                            "linked_recommendation_ids": linked_recommendation_ids,
                            "confidence": normalized_confidence,
                        }
                    )
                    if len(tuning_suggestions) >= _MAX_TUNING_SUGGESTIONS:
                        break

        return {
            "summary": summary,
            "priority_rationale": priority_rationale,
            "next_actions": next_actions,
            "recommendation_references": references,
            "tuning_suggestions": tuning_suggestions,
            "status_rollup": _normalize_int_map(by_status),
            "category_rollup": _normalize_int_map(by_category),
            "severity_rollup": _normalize_int_map(by_severity),
            "effort_rollup": _normalize_int_map(by_effort_bucket),
            "priority_band_rollup": _normalize_int_map(by_priority_band),
        }

    def _telemetry_supports_tuning_suggestions(self, telemetry_summary: dict[str, object]) -> bool:
        raw_count = self._coerce_non_negative_int(telemetry_summary.get("total_raw_candidate_count"))
        excluded_count = self._coerce_non_negative_int(telemetry_summary.get("total_excluded_candidate_count"))
        return raw_count > 0 and excluded_count > 0

    def _coerce_tuning_value(self, *, setting: str, value: object) -> int:
        minimum, maximum = _ALLOWED_TUNING_SETTINGS_BOUNDS[setting]
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise self._provider_error(
                code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                safe_message="Recommendation narrative returned invalid structured output.",
            ) from exc
        if parsed < minimum or parsed > maximum:
            raise self._provider_error(
                code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                safe_message="Recommendation narrative returned invalid structured output.",
            )
        return parsed

    @staticmethod
    def _coerce_non_negative_int(value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return max(0, parsed)

    def _apply_recommendation_context_budget(
        self,
        *,
        competitor_telemetry_summary: dict[str, object],
        current_tuning_values: dict[str, int],
        competitor_context: dict[str, object] | None,
    ) -> tuple[dict[str, object], dict[str, int], dict[str, object] | None, dict[str, object]]:
        available_blocks: dict[str, object] = {
            "competitor_telemetry_summary": competitor_telemetry_summary,
            "competitor_context": competitor_context or {},
            "current_tuning_values": current_tuning_values,
        }
        required_keys = [key for key in _RECOMMENDATION_REQUIRED_CONTEXT_KEYS if key in available_blocks]
        optional_keys: list[str] = [
            key for key in _RECOMMENDATION_OPTIONAL_TRIM_ORDER if key in available_blocks and key not in required_keys
        ]
        for key in available_blocks.keys():
            if key in required_keys or key in optional_keys:
                continue
            optional_keys.append(str(key))

        blocks: list[AIContextBlock] = []
        for key in required_keys:
            blocks.append(
                AIContextBlock(
                    name=key,
                    value=available_blocks.get(key),
                    required=True,
                    trim_priority=0,
                )
            )
        for index, key in enumerate(optional_keys):
            blocks.append(
                AIContextBlock(
                    name=key,
                    value=available_blocks.get(key),
                    required=False,
                    trim_priority=max(1, len(optional_keys) - index),
                )
            )
        decision = apply_request_budget(
            blocks=blocks,
            budget_size_chars=_RECOMMENDATION_CONTEXT_BUDGET_CHARS,
        )
        retained = decision.retained_blocks
        dropped_optional_blocks = list(decision.result.dropped_optional_blocks)
        aggressive_trim_applied = len(dropped_optional_blocks) > 0
        # Recommendation degraded behavior: if we had to trim for budget, remove
        # enrichment context entirely instead of mixing partial enrichment.
        budgeted_competitor_telemetry_summary = (
            competitor_telemetry_summary
            if "competitor_telemetry_summary" in retained and not aggressive_trim_applied
            else {}
        )
        budgeted_current_tuning_values = current_tuning_values if "current_tuning_values" in retained else {}
        if "competitor_context" in retained and not aggressive_trim_applied:
            budgeted_competitor_context = competitor_context or {}
        else:
            budgeted_competitor_context = None
        budget_result = {
            "initial_size_chars": decision.result.initial_size_chars,
            "final_size_chars": decision.result.final_size_chars,
            "initial_size_bytes": decision.result.initial_size_bytes,
            "final_size_bytes": decision.result.final_size_bytes,
            "trimmed_bytes": decision.result.trimmed_bytes,
            "trimming_pass_count": decision.result.trimming_pass_count,
            "section_count": decision.result.section_count,
            "budget_size_chars": decision.result.budget_size_chars,
            "dropped_optional_blocks": dropped_optional_blocks,
            "dropped_duplicate_blocks": list(decision.result.dropped_duplicate_blocks),
            "required_blocks_retained": list(decision.result.required_blocks_retained),
            "optional_blocks_retained": list(decision.result.optional_blocks_retained),
            "aggressive_trim_applied": aggressive_trim_applied,
            "overflow": bool(decision.result.overflow),
        }
        return (
            budgeted_competitor_telemetry_summary,
            budgeted_current_tuning_values,
            budgeted_competitor_context,
            budget_result,
        )

    def _log_budget_decision(self, *, budget_result: dict[str, object], budget_outcome: str) -> None:
        logger.info(
            (
                "recommendation_narrative_request_budget provider_name=%s model_name=%s initial_size_chars=%s "
                "final_size_chars=%s budget_size_chars=%s original_input_size=%s final_input_size=%s "
                "trimmed_bytes=%s trimming_pass_count=%s section_count=%s dropped_optional_blocks=%s "
                "dropped_duplicate_blocks=%s aggressive_trim_applied=%s overflow=%s"
            ),
            self.provider_name,
            self.model_name,
            budget_result.get("initial_size_chars"),
            budget_result.get("final_size_chars"),
            budget_result.get("budget_size_chars"),
            budget_result.get("initial_size_bytes"),
            budget_result.get("final_size_bytes"),
            budget_result.get("trimmed_bytes"),
            budget_result.get("trimming_pass_count"),
            budget_result.get("section_count"),
            budget_result.get("dropped_optional_blocks"),
            budget_result.get("dropped_duplicate_blocks"),
            budget_result.get("aggressive_trim_applied"),
            budget_result.get("overflow"),
        )
        payload = {
            "event": "recommendation_narrative_request_budget",
            "feature_area": "recommendation_ai",
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "budget_outcome": budget_outcome,
            "initial_size_chars": budget_result.get("initial_size_chars"),
            "final_size_chars": budget_result.get("final_size_chars"),
            "budget_size_chars": budget_result.get("budget_size_chars"),
            "original_input_size": budget_result.get("initial_size_bytes"),
            "final_input_size": budget_result.get("final_size_bytes"),
            "trimmed_bytes": budget_result.get("trimmed_bytes"),
            "trimming_pass_count": budget_result.get("trimming_pass_count"),
            "section_count": budget_result.get("section_count"),
            "dropped_optional_blocks": budget_result.get("dropped_optional_blocks"),
            "dropped_duplicate_blocks": budget_result.get("dropped_duplicate_blocks"),
            "aggressive_trim_applied": budget_result.get("aggressive_trim_applied"),
            "overflow": budget_result.get("overflow"),
        }
        safe_payload = {key: value for key, value in payload.items() if value is not None}
        safe_payload = sanitize_log_payload(safe_payload)
        if not isinstance(safe_payload, dict):
            logger.info("recommendation_narrative_request_budget")
            return
        logger.info(
            json.dumps(safe_payload, ensure_ascii=True, sort_keys=True),
            extra={"json_fields": safe_payload},
        )

    def _provider_error(
        self,
        *,
        code: str,
        safe_message: str,
        raw_output: str | None = None,
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
    ) -> SEORecommendationNarrativeProviderError:
        return SEORecommendationNarrativeProviderError(
            code=code,
            safe_message=safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output=raw_output,
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


class _OpenAIRecommendationNarrativeSections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str | None = None
    priority_rationale: str | None = None
    next_actions: list[str] = Field(default_factory=list, max_length=_MAX_NEXT_ACTIONS)
    recommendation_references: list[str] = Field(default_factory=list, max_length=_MAX_RECOMMENDATION_REFERENCES)
    tuning_suggestions: list["_OpenAIRecommendationNarrativeTuningSuggestion"] = Field(
        default_factory=list,
        max_length=_MAX_TUNING_SUGGESTIONS,
    )

    @field_validator("summary", "priority_rationale", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("next_actions", mode="before")
    @classmethod
    def _normalize_actions_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("next_actions must be a list")
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized

    @field_validator("recommendation_references", mode="before")
    @classmethod
    def _normalize_references_list(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("recommendation_references must be a list")
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized


class _OpenAIRecommendationNarrativeTuningSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setting: str
    current_value: int
    recommended_value: int
    reason: str
    linked_recommendation_ids: list[str] = Field(default_factory=list, max_length=_MAX_TUNING_LINKED_RECOMMENDATION_IDS)
    confidence: str

    @field_validator("setting", mode="before")
    @classmethod
    def _normalize_setting(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if normalized not in _ALLOWED_TUNING_SETTINGS_BOUNDS:
            raise ValueError("setting is not allowed")
        return normalized

    @field_validator("current_value", "recommended_value", mode="before")
    @classmethod
    def _normalize_int_value(cls, value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("value must be an integer") from exc

    @field_validator("recommended_value")
    @classmethod
    def _validate_recommended_value_bounds(
        cls,
        value: int,
        info,
    ) -> int:
        setting = str(info.data.get("setting") or "").strip()
        bounds = _ALLOWED_TUNING_SETTINGS_BOUNDS.get(setting)
        if bounds is None:
            raise ValueError("setting is required")
        if value < bounds[0] or value > bounds[1]:
            raise ValueError("recommended_value is out of bounds")
        return value

    @field_validator("current_value")
    @classmethod
    def _validate_current_value_bounds(
        cls,
        value: int,
        info,
    ) -> int:
        setting = str(info.data.get("setting") or "").strip()
        bounds = _ALLOWED_TUNING_SETTINGS_BOUNDS.get(setting)
        if bounds is None:
            raise ValueError("setting is required")
        if value < bounds[0] or value > bounds[1]:
            raise ValueError("current_value is out of bounds")
        return value

    @field_validator("reason", mode="before")
    @classmethod
    def _normalize_reason(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("reason is required")
        if len(normalized) > _MAX_TUNING_REASON_LENGTH:
            return normalized[:_MAX_TUNING_REASON_LENGTH]
        return normalized

    @field_validator("linked_recommendation_ids", mode="before")
    @classmethod
    def _normalize_linked_recommendation_ids(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("linked_recommendation_ids must be a list")
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        if not normalized:
            raise ValueError("linked_recommendation_ids is required")
        return normalized

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in _ALLOWED_TUNING_CONFIDENCE:
            raise ValueError("confidence must be low, medium, or high")
        return normalized


class _OpenAIRecommendationNarrativeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narrative_text: str
    top_themes: list[str] = Field(default_factory=list, max_length=_MAX_THEMES)
    sections: _OpenAIRecommendationNarrativeSections | None = None

    @field_validator("narrative_text", mode="before")
    @classmethod
    def _normalize_narrative_text(cls, value: object) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("narrative_text is required")
        return normalized

    @field_validator("top_themes", mode="before")
    @classmethod
    def _normalize_top_themes(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise TypeError("top_themes must be a list")
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized


_OpenAIRecommendationNarrativeSections.model_rebuild()


def _build_narrative_json_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["narrative_text", "top_themes", "sections"],
        "properties": {
            "narrative_text": {"type": "string"},
            "top_themes": {
                "type": "array",
                "maxItems": _MAX_THEMES,
                "items": {"type": "string"},
            },
            "sections": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "required": [
                    "summary",
                    "priority_rationale",
                    "next_actions",
                    "recommendation_references",
                    "tuning_suggestions",
                ],
                "properties": {
                    "summary": {"type": ["string", "null"]},
                    "priority_rationale": {"type": ["string", "null"]},
                    "next_actions": {
                        "type": "array",
                        "maxItems": _MAX_NEXT_ACTIONS,
                        "items": {"type": "string"},
                    },
                    "recommendation_references": {
                        "type": "array",
                        "maxItems": _MAX_RECOMMENDATION_REFERENCES,
                        "items": {"type": "string"},
                    },
                    "tuning_suggestions": {
                        "type": "array",
                        "maxItems": _MAX_TUNING_SUGGESTIONS,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "setting",
                                "current_value",
                                "recommended_value",
                                "reason",
                                "linked_recommendation_ids",
                                "confidence",
                            ],
                            "properties": {
                                "setting": {"type": "string"},
                                "current_value": {"type": "integer"},
                                "recommended_value": {"type": "integer"},
                                "reason": {"type": "string"},
                                "linked_recommendation_ids": {
                                    "type": "array",
                                    "maxItems": _MAX_TUNING_LINKED_RECOMMENDATION_IDS,
                                    "items": {"type": "string"},
                                },
                                "confidence": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    }


def _normalize_int_map(raw: dict[str, int]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in sorted(raw.items()):
        if not isinstance(key, str):
            continue
        clean_key = _clean_optional_value(key)
        if not clean_key:
            continue
        try:
            normalized[clean_key] = int(value)
        except (TypeError, ValueError):
            continue
    return normalized


def _clean_optional_value(value: object) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None
