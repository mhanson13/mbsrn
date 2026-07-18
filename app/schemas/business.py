from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, TypeAdapter, ValidationError, field_validator

_EMAIL_FALLBACK_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")

AIBusinessModelSource = Literal[
    "explicit",
    "task_override",
    "business_default",
    "env_default",
    "provider_fallback",
    "deterministic",
]
AIBusinessModelValidationStatus = Literal["allowed", "compatibility_allowed", "deterministic", "invalid"]


class BusinessAIModelSelectableValueRead(BaseModel):
    model: str
    label: str
    capability_note: str


class BusinessAITaskModelRoutingRead(BaseModel):
    task_alias: str
    task_label: str
    capability_note: str
    capabilities: list[str] = Field(default_factory=list)
    override_model: str | None
    effective_model: str | None
    source: AIBusinessModelSource
    fallback_used: bool
    validation_status: AIBusinessModelValidationStatus
    validation_error: str | None = None


class BusinessSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    notification_phone: str | None
    notification_email: str | None
    sms_enabled: bool
    email_enabled: bool
    customer_auto_ack_enabled: bool
    contractor_alerts_enabled: bool
    seo_audit_crawl_max_pages: int
    competitor_candidate_min_relevance_score: int
    competitor_candidate_big_box_penalty: int
    competitor_candidate_directory_penalty: int
    competitor_candidate_local_alignment_bonus: int
    competitor_primary_timeout_seconds: int | None
    competitor_degraded_timeout_seconds: int | None
    migration_draft_timeout_seconds: int | None
    ai_prompt_text_competitor: str | None
    ai_prompt_text_recommendations: str | None
    default_ai_model: str | None
    ai_model_overrides: dict[str, str] | None = None
    ai_model_routing: list[BusinessAITaskModelRoutingRead] = Field(default_factory=list)
    ai_model_selectable_values: list[BusinessAIModelSelectableValueRead] = Field(default_factory=list)
    timezone: str
    created_at: datetime
    updated_at: datetime


class BusinessSettingsUpdateRequest(BaseModel):
    notification_phone: str | None = None
    notification_email: str | None = None
    sms_enabled: bool | None = None
    email_enabled: bool | None = None
    customer_auto_ack_enabled: bool | None = None
    contractor_alerts_enabled: bool | None = None
    seo_audit_crawl_max_pages: int | None = Field(default=None, ge=5, le=250)
    competitor_candidate_min_relevance_score: int | None = Field(default=None, ge=0, le=100)
    competitor_candidate_big_box_penalty: int | None = Field(default=None, ge=0, le=50)
    competitor_candidate_directory_penalty: int | None = Field(default=None, ge=0, le=50)
    competitor_candidate_local_alignment_bonus: int | None = Field(default=None, ge=0, le=50)
    competitor_primary_timeout_seconds: int | None = Field(default=None, ge=10, le=90)
    competitor_degraded_timeout_seconds: int | None = Field(default=None, ge=10, le=90)
    migration_draft_timeout_seconds: int | None = Field(default=None, ge=30, le=600)
    ai_prompt_text_competitor: str | None = Field(
        default=None,
        max_length=20000,
        description=(
            "Business-scoped competitor prompt override. Blank/whitespace values are treated "
            "as unset and fall back to deployment/default prompt configuration."
        ),
    )
    ai_prompt_text_recommendations: str | None = Field(
        default=None,
        max_length=20000,
        description=(
            "Business-scoped recommendation prompt override. Blank/whitespace values are treated "
            "as unset and fall back to deployment/default prompt configuration."
        ),
    )
    default_ai_model: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Business-scoped legacy/global AI model fallback. Blank/whitespace values are treated "
            "as unset and fall back to deployment/default model configuration."
        ),
    )
    ai_model_overrides: dict[str, str | None] | None = Field(
        default=None,
        description=(
            "Business-scoped AI task model overrides keyed by task alias. Blank/whitespace values are "
            "treated as inherit/clear for that alias."
        ),
    )
    competitor_tuning_preview_event_id: str | None = Field(default=None, min_length=1, max_length=36)
    timezone: str | None = None

    @field_validator("notification_email", mode="before")
    @classmethod
    def normalize_and_validate_email(cls, value: str | None) -> str | None:
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            return None
        normalized = cleaned.lower()
        try:
            adapter = TypeAdapter(EmailStr)
            return str(adapter.validate_python(normalized))
        except ImportError:
            if not _EMAIL_FALLBACK_REGEX.match(normalized):
                raise ValueError("notification_email must be a valid email address.")
            return normalized
        except ValidationError as exc:
            raise ValueError("notification_email must be a valid email address.") from exc

    @field_validator("notification_phone", mode="before")
    @classmethod
    def normalize_and_validate_phone(cls, value: str | None) -> str | None:
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            return None
        normalized = _normalize_us_phone(cleaned)
        if normalized is None:
            raise ValueError("notification_phone must be a valid US phone number (10 digits, optional country code).")
        return normalized

    @field_validator("timezone", mode="before")
    @classmethod
    def normalize_and_validate_timezone(cls, value: str | None) -> str | None:
        cleaned = _clean_optional_text(value)
        if cleaned is None:
            return None
        try:
            ZoneInfo(cleaned)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone.") from exc
        return cleaned

    @field_validator("competitor_tuning_preview_event_id", mode="before")
    @classmethod
    def normalize_preview_event_id(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("ai_prompt_text_competitor", "ai_prompt_text_recommendations", mode="before")
    @classmethod
    def normalize_ai_prompt_text_overrides(cls, value: str | None) -> str | None:
        return _clean_optional_text(value)

    @field_validator("default_ai_model", mode="before")
    @classmethod
    def normalize_default_ai_model(cls, value: str | None) -> str | None:
        return _normalize_optional_model_name(value)

    @field_validator("ai_model_overrides", mode="before")
    @classmethod
    def normalize_ai_model_overrides(cls, value: object) -> dict[str, str | None] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("ai_model_overrides must be an object mapping task aliases to model identifiers or null.")
        normalized: dict[str, str | None] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise ValueError("ai_model_overrides keys must be non-empty task alias strings.")
            alias = raw_key.strip().lower()
            if alias == "":
                raise ValueError("ai_model_overrides keys must be non-empty task alias strings.")
            if raw_value is not None and not isinstance(raw_value, str):
                raise ValueError("ai_model_overrides values must be strings or null.")
            normalized[alias] = _normalize_optional_model_name(raw_value)
        return normalized


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    return cleaned


def _normalize_optional_model_name(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "":
        return None
    return normalized


def _normalize_us_phone(value: str) -> str | None:
    condensed = re.sub(r"[()\s\-.]", "", value)

    if condensed.startswith("+"):
        if condensed.count("+") != 1:
            return None
        digits = condensed[1:]
        if not digits.isdigit():
            return None
        candidate = f"+{digits}"
        if not _E164_REGEX.match(candidate):
            return None
        return candidate

    if "+" in condensed or not condensed.isdigit():
        return None
    if len(condensed) == 10:
        return f"+1{condensed}"
    if len(condensed) == 11 and condensed.startswith("1"):
        return f"+{condensed}"
    return None
