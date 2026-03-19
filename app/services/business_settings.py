from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories.business_repository import BusinessRepository
from app.schemas.business import BusinessSettingsUpdateRequest

_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")


class BusinessSettingsNotFoundError(ValueError):
    pass


class BusinessSettingsValidationError(ValueError):
    pass


class BusinessSettingsService:
    def __init__(self, *, session: Session, business_repository: BusinessRepository) -> None:
        self.session = session
        self.business_repository = business_repository

    def get(self, *, business_id: str) -> Business:
        business = self.business_repository.get(business_id)
        if not business:
            raise BusinessSettingsNotFoundError("Business not found")
        return business

    def update_settings(self, *, business_id: str, payload: BusinessSettingsUpdateRequest) -> Business:
        business = self.get(business_id=business_id)

        updates = payload.model_dump(exclude_unset=True)
        effective = self._effective_settings(business=business, updates=updates)
        self._validate_effective_settings(effective)

        for field_name, value in updates.items():
            setattr(business, field_name, value)

        self.business_repository.save(business)
        self.session.commit()
        self.session.refresh(business)
        return business

    def _effective_settings(self, *, business: Business, updates: dict) -> dict:
        return {
            "notification_phone": updates.get("notification_phone", business.notification_phone),
            "notification_email": updates.get("notification_email", business.notification_email),
            "sms_enabled": updates.get("sms_enabled", business.sms_enabled),
            "email_enabled": updates.get("email_enabled", business.email_enabled),
            "customer_auto_ack_enabled": updates.get("customer_auto_ack_enabled", business.customer_auto_ack_enabled),
            "contractor_alerts_enabled": updates.get("contractor_alerts_enabled", business.contractor_alerts_enabled),
            "timezone": updates.get("timezone", business.timezone),
        }

    def _validate_effective_settings(self, effective: dict) -> None:
        sms_enabled = bool(effective["sms_enabled"])
        email_enabled = bool(effective["email_enabled"])
        sms_channel_usable = sms_enabled and self._is_valid_phone_e164(effective["notification_phone"])
        email_channel_usable = email_enabled and self._is_valid_email(effective["notification_email"])

        if sms_enabled and not sms_channel_usable:
            raise BusinessSettingsValidationError(
                "notification_phone is required and must be valid when sms_enabled is true."
            )

        if email_enabled and not email_channel_usable:
            raise BusinessSettingsValidationError(
                "notification_email is required and must be valid when email_enabled is true."
            )

        if effective["contractor_alerts_enabled"] and not (sms_channel_usable or email_channel_usable):
            raise BusinessSettingsValidationError(
                "At least one usable enabled channel (sms or email) is required when contractor_alerts_enabled is true."
            )

        # Customer auto-ack uses the incoming lead's contact details plus enabled channels.
        # It does not depend on business notification targets, only channel availability.
        if effective["customer_auto_ack_enabled"] and not (sms_enabled or email_enabled):
            raise BusinessSettingsValidationError(
                "At least one channel (sms or email) must be enabled when customer_auto_ack_enabled is true."
            )

    def _is_valid_email(self, value: str | None) -> bool:
        if not value:
            return False
        return bool(_EMAIL_REGEX.match(value.strip()))

    def _is_valid_phone_e164(self, value: str | None) -> bool:
        if not value:
            return False
        return bool(_E164_REGEX.match(value.strip()))
