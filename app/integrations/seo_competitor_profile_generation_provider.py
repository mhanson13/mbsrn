from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import socket
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
    ) -> SEOCompetitorProfileGenerationOutput:
        del site, existing_domains, candidate_count
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
    ) -> SEOCompetitorProfileGenerationOutput:
        self._log_prompt_resolution_metadata()
        prompt = build_seo_competitor_profile_prompt(
            site=site,
            existing_domains=existing_domains,
            candidate_count=candidate_count,
            prompt_version=self.prompt_version,
            prompt_text_competitor=self.prompt_text_competitor,
        )
        responses_payload = self._build_responses_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
        )
        chat_payload = self._build_chat_completions_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            candidate_count=candidate_count,
        )
        try:
            response_json: dict[str, object] | None = None
            assistant_content: str | None = None
            raw_response = self._request_completion(
                responses_payload,
                endpoint_path="/responses",
            )
            response_json = self._parse_json_object(
                raw_response,
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response could not be parsed.",
            )
            assistant_content = self._extract_assistant_content_from_responses(response_json)
            candidates = self._parse_or_normalize_candidates(
                assistant_content=assistant_content,
                candidate_count=candidate_count,
            )
            if not candidates:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_INVALID_OUTPUT,
                    safe_message="Competitor profile generation returned malformed output.",
                    raw_output=assistant_content,
                )
            model_name = _clean_optional_value(response_json.get("model")) or self.model_name
            return SEOCompetitorProfileGenerationOutput(
                candidates=candidates,
                provider_name=self.provider_name,
                model_name=model_name,
                prompt_version=prompt.prompt_version,
                raw_response=assistant_content,
            )
        except SEOCompetitorProfileProviderError as exc:
            logger.warning(
                (
                    "SEO competitor provider responses path failed; falling back to chat completions "
                    "provider_name=%s model_name=%s error_code=%s safe_message=%s"
                ),
                self.provider_name,
                self.model_name,
                exc.code,
                _compact_log_message(exc.safe_message),
            )
            raw_response = self._request_completion(
                chat_payload,
                endpoint_path="/chat/completions",
            )
            response_json = self._parse_json_object(
                raw_response,
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Competitor profile generation response could not be parsed.",
            )
            assistant_content = self._extract_assistant_content(response_json)
            candidates = self._parse_or_normalize_candidates(
                assistant_content=assistant_content,
                candidate_count=candidate_count,
            )
            if not candidates:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_INVALID_OUTPUT,
                    safe_message="Competitor profile generation returned malformed output.",
                    raw_output=assistant_content,
                )
            model_name = _clean_optional_value(response_json.get("model")) or self.model_name
            return SEOCompetitorProfileGenerationOutput(
                candidates=candidates,
                provider_name=self.provider_name,
                model_name=model_name,
                prompt_version=prompt.prompt_version,
                raw_response=assistant_content,
            )

    def _parse_or_normalize_candidates(
        self,
        *,
        assistant_content: str,
        candidate_count: int,
    ) -> list[SEOCompetitorProfileDraftCandidateOutput]:
        bounded_count = max(1, candidate_count)
        structured_json: dict[str, object] | None = None
        try:
            structured_json = self._parse_json_object(
                assistant_content,
                code=_PROVIDER_ERROR_INVALID_OUTPUT,
                safe_message="Competitor profile generation returned malformed output.",
                raw_output=assistant_content,
            )
        except SEOCompetitorProfileProviderError:
            structured_json = None

        if structured_json is not None:
            try:
                parsed = _OpenAICompetitorProfileResponse.model_validate(structured_json)
                return [
                    SEOCompetitorProfileDraftCandidateOutput(
                        suggested_name=item.name,
                        suggested_domain=item.domain,
                        competitor_type=item.competitor_type,
                        summary=item.summary,
                        why_competitor=item.why_competitor,
                        evidence=item.evidence,
                        confidence_score=item.confidence_score,
                    )
                    for item in parsed.candidates[:bounded_count]
                ]
            except ValidationError:
                logger.warning(
                    "Competitor profile generation strict schema validation failed; applying normalizer fallback."
                )

        normalized_payload = normalize_competitor_response(assistant_content)
        return self._coerce_candidates_from_normalized_payload(
            normalized_payload=normalized_payload,
            candidate_count=bounded_count,
        )

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

    def _request_completion(self, payload: dict[str, object], *, endpoint_path: str) -> str:
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

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            error_type, error_code, error_message = self._extract_provider_error_details(body_text)
            logger.warning(
                (
                    "SEO competitor provider HTTP error status=%s provider_name=%s model_name=%s "
                    "endpoint=%s error_type=%s error_code=%s error_message=%s"
                ),
                exc.code,
                self.provider_name,
                self.model_name,
                normalized_endpoint,
                error_type,
                error_code,
                error_message,
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
                    raw_output=body_text,
                ) from exc
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Competitor profile generation provider request failed.",
                raw_output=body_text,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            logger.warning(
                "SEO competitor provider timeout provider_name=%s model_name=%s endpoint=%s reason=%s",
                self.provider_name,
                self.model_name,
                normalized_endpoint,
                str(exc),
            )
            raise self._provider_error(
                code=_PROVIDER_ERROR_TIMEOUT,
                safe_message="Competitor profile generation timed out while calling the AI provider.",
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                logger.warning(
                    "SEO competitor provider timeout provider_name=%s model_name=%s endpoint=%s reason=%s",
                    self.provider_name,
                    self.model_name,
                    normalized_endpoint,
                    str(exc.reason),
                )
                raise self._provider_error(
                    code=_PROVIDER_ERROR_TIMEOUT,
                    safe_message="Competitor profile generation timed out while calling the AI provider.",
                ) from exc
            logger.warning(
                "SEO competitor provider URL error provider_name=%s model_name=%s endpoint=%s reason=%s",
                self.provider_name,
                self.model_name,
                normalized_endpoint,
                str(exc.reason),
            )
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Competitor profile generation provider request failed.",
            ) from exc

    def _build_responses_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, object]:
        return {
            "model": self.model_name,
            "tools": [{"type": "web_search"}],
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
