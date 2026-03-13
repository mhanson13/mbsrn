from __future__ import annotations

from datetime import datetime
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, TypeAdapter, ValidationError, field_validator

_EMAIL_FALLBACK_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")


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
            raise ValueError(
                "notification_phone must be a valid US phone number (10 digits, optional country code)."
            )
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


def _clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if cleaned == "":
        return None
    return cleaned


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
