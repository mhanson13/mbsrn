from __future__ import annotations

from dataclasses import dataclass
import json
import socket
import urllib.error
import urllib.request

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.services.seo_migration_prompt import SEO_MIGRATION_PROMPT_VERSION, build_seo_migration_prompt


_PROVIDER_ERROR_TIMEOUT = "timeout"
_PROVIDER_ERROR_AUTH_CONFIG = "provider_auth_config"
_PROVIDER_ERROR_INVALID_OUTPUT = "invalid_output"
_PROVIDER_ERROR_SCHEMA_VALIDATION = "schema_validation"
_PROVIDER_ERROR_PARSING = "parsing_error"
_PROVIDER_ERROR_REQUEST = "provider_request"

_MAX_FILE_COUNT = 12
_MAX_FILE_PATH_LENGTH = 140
_MAX_FILE_CONTENT_LENGTH = 120000
_MAX_PAGE_MAP_ITEMS = 20
_MAX_LIST_ITEMS = 24
_MAX_TEXT_FIELD_LENGTH = 8000


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
    raw_output: str | None = None

    def __str__(self) -> str:
        return self.safe_message


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
            code=_PROVIDER_ERROR_AUTH_CONFIG,
            safe_message=self.safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
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
                    "<html lang=\"en\">\n<head>\n"
                    "  <meta charset=\"utf-8\" />\n"
                    "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                    f"  <title>{site_name} | Local Fire Protection Services</title>\n"
                    "  <meta name=\"description\" content=\"Local fire protection installation, inspection, and service.\" />\n"
                    "  <!-- ANALYTICS_PLACEHOLDER -->\n"
                    "  <link rel=\"stylesheet\" href=\"styles.css\" />\n"
                    "</head>\n<body>\n"
                    f"  <header><h1>{site_name}</h1><p>Reliable local fire protection support.</p></header>\n"
                    "  <main>\n"
                    "    <section><h2>Services</h2><p>Installation, inspection, testing, and maintenance.</p></section>\n"
                    "    <section><h2>Contact</h2><p><a href=\"contact.html\">Request service</a></p></section>\n"
                    "  </main>\n"
                    "</body>\n</html>\n"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="services.html",
                media_type="text/html",
                content=(
                    "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\" />"
                    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
                    "<title>Services</title><link rel=\"stylesheet\" href=\"styles.css\" /></head>"
                    "<body><h1>Services</h1><p>Detailed service scope and coverage.</p></body></html>\n"
                ),
            ),
            SEOMigrationGeneratedFileOutput(
                path="contact.html",
                media_type="text/html",
                content=(
                    "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\" />"
                    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />"
                    "<title>Contact</title><link rel=\"stylesheet\" href=\"styles.css\" /></head>"
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
        prompt = build_seo_migration_prompt(
            migration_context=migration_context,
            prompt_version=self.prompt_version,
            prompt_text_recommendations=self.prompt_text_recommendations,
        )
        payload = self._build_request_payload(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
        )
        raw_response = self._request_completion(payload)
        response_json = self._parse_json_object(
            raw_response,
            code=_PROVIDER_ERROR_PARSING,
            safe_message="Migration draft response could not be parsed.",
        )
        assistant_content = self._extract_assistant_content(response_json)
        structured_json = self._parse_json_object(
            assistant_content,
            code=_PROVIDER_ERROR_INVALID_OUTPUT,
            safe_message="Migration draft returned malformed output.",
            raw_output=assistant_content,
        )
        try:
            parsed = _OpenAIMigrationResponse.model_validate(structured_json)
        except ValidationError as exc:
            raise self._provider_error(
                code=_PROVIDER_ERROR_SCHEMA_VALIDATION,
                safe_message="Migration draft returned invalid structured output.",
                raw_output=assistant_content,
            ) from exc

        model_name = _clean_optional_value(response_json.get("model")) or self.model_name
        files = [
            SEOMigrationGeneratedFileOutput(path=item.path, content=item.content, media_type=item.media_type)
            for item in parsed.generated_files
        ]
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
                    safe_message="AI provider authentication failed for migration draft generation.",
                    raw_output=body_text,
                ) from exc
            if exc.code in {408, 504}:
                raise self._provider_error(
                    code=_PROVIDER_ERROR_TIMEOUT,
                    safe_message="Migration draft generation timed out while calling the AI provider.",
                    raw_output=body_text,
                ) from exc
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Migration draft provider request failed.",
                raw_output=body_text,
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise self._provider_error(
                code=_PROVIDER_ERROR_TIMEOUT,
                safe_message="Migration draft generation timed out while calling the AI provider.",
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError) or isinstance(exc.reason, socket.timeout):
                raise self._provider_error(
                    code=_PROVIDER_ERROR_TIMEOUT,
                    safe_message="Migration draft generation timed out while calling the AI provider.",
                ) from exc
            raise self._provider_error(
                code=_PROVIDER_ERROR_REQUEST,
                safe_message="Migration draft provider request failed.",
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
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Migration draft response did not include choices.",
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Migration draft response choice was malformed.",
                raw_output=json.dumps(response_json, ensure_ascii=True, sort_keys=True),
            )
        message = first_choice.get("message")
        if not isinstance(message, dict):
            raise self._provider_error(
                code=_PROVIDER_ERROR_PARSING,
                safe_message="Migration draft response message was malformed.",
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
            safe_message="Migration draft response did not include content.",
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
    ) -> SEOMigrationArtifactProviderError:
        return SEOMigrationArtifactProviderError(
            code=code,
            safe_message=safe_message,
            provider_name=self.provider_name,
            model_name=self.model_name,
            prompt_version=self.prompt_version,
            raw_output=raw_output,
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
    service_page_suggestions: list[_OpenAIMigrationPageMapItem] = Field(default_factory=list, max_length=_MAX_LIST_ITEMS)
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

