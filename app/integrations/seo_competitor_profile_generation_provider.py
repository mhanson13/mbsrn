from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
)
from app.models.seo_site import SEOSite
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

    def generate_competitor_profiles(
        self,
        *,
        site: SEOSite,
        existing_domains: list[str],
        candidate_count: int,
    ) -> SEOCompetitorProfileGenerationOutput:
        prompt = build_seo_competitor_profile_prompt(
            site=site,
            existing_domains=existing_domains,
            candidate_count=candidate_count,
            prompt_version=self.prompt_version,
            prompt_text_competitor=self.prompt_text_competitor,
        )
        payload = self._build_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            candidate_count=candidate_count,
        )
        raw_response = self._request_completion(payload)
        response_json = self._parse_json_object(
            raw_response,
            code=_PROVIDER_ERROR_PARSING,
            safe_message="Competitor profile generation response could not be parsed.",
        )
        assistant_content = self._extract_assistant_content(response_json)
        structured_json = self._parse_json_object(
            assistant_content,
            code=_PROVIDER_ERROR_INVALID_OUTPUT,
            safe_message="Competitor profile generation returned malformed output.",
            raw_output=assistant_content,
        )
        try:
            parsed = _OpenAICompetitorProfileResponse.model_validate(structured_json)
        except ValidationError as exc:
            raise self._provider_error(
                code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                safe_message="Competitor profile generation returned invalid structured output.",
                raw_output=assistant_content,
            ) from exc

        candidates = [
            SEOCompetitorProfileDraftCandidateOutput(
                suggested_name=item.name,
                suggested_domain=item.domain,
                competitor_type=item.competitor_type,
                summary=item.summary,
                why_competitor=item.why_competitor,
                evidence=item.evidence,
                confidence_score=item.confidence_score,
            )
            for item in parsed.candidates[: max(1, candidate_count)]
        ]
        model_name = _clean_optional_value(response_json.get("model")) or self.model_name
        return SEOCompetitorProfileGenerationOutput(
            candidates=candidates,
            provider_name=self.provider_name,
            model_name=model_name,
            prompt_version=prompt.prompt_version,
            raw_response=assistant_content,
        )

    def _request_completion(self, payload: dict[str, object]) -> str:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.api_base_url}/chat/completions",
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
            raise self._provider_error(
                code=_PROVIDER_ERROR_TIMEOUT,
                safe_message="Competitor profile generation timed out while calling the AI provider.",
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                raise self._provider_error(
                    code=_PROVIDER_ERROR_TIMEOUT,
                    safe_message="Competitor profile generation timed out while calling the AI provider.",
                ) from exc
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Competitor profile generation provider request failed.",
            ) from exc

    def _build_request_payload(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        candidate_count: int,
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
                    "name": "seo_competitor_profile_generation_response",
                    "strict": True,
                    "schema": _build_candidate_json_schema(candidate_count),
                },
            },
        }

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
