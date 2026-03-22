from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.business import Business
from app.repositories.business_repository import BusinessRepository
from app.schemas.business import BusinessSettingsUpdateRequest

_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")
_SEO_AUDIT_CRAWL_MAX_PAGES_MIN = 5
_SEO_AUDIT_CRAWL_MAX_PAGES_MAX = 250
_COMPETITOR_CANDIDATE_MIN_RELEVANCE_SCORE_MIN = 0
_COMPETITOR_CANDIDATE_MIN_RELEVANCE_SCORE_MAX = 100
_COMPETITOR_CANDIDATE_BIG_BOX_PENALTY_MIN = 0
_COMPETITOR_CANDIDATE_BIG_BOX_PENALTY_MAX = 50
_COMPETITOR_CANDIDATE_DIRECTORY_PENALTY_MIN = 0
_COMPETITOR_CANDIDATE_DIRECTORY_PENALTY_MAX = 50
_COMPETITOR_CANDIDATE_LOCAL_ALIGNMENT_BONUS_MIN = 0
_COMPETITOR_CANDIDATE_LOCAL_ALIGNMENT_BONUS_MAX = 50


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
            "seo_audit_crawl_max_pages": updates.get(
                "seo_audit_crawl_max_pages",
                business.seo_audit_crawl_max_pages,
            ),
            "competitor_candidate_min_relevance_score": updates.get(
                "competitor_candidate_min_relevance_score",
                business.competitor_candidate_min_relevance_score,
            ),
            "competitor_candidate_big_box_penalty": updates.get(
                "competitor_candidate_big_box_penalty",
                business.competitor_candidate_big_box_penalty,
            ),
            "competitor_candidate_directory_penalty": updates.get(
                "competitor_candidate_directory_penalty",
                business.competitor_candidate_directory_penalty,
            ),
            "competitor_candidate_local_alignment_bonus": updates.get(
                "competitor_candidate_local_alignment_bonus",
                business.competitor_candidate_local_alignment_bonus,
            ),
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

        crawl_max_pages = int(effective["seo_audit_crawl_max_pages"])
        if crawl_max_pages < _SEO_AUDIT_CRAWL_MAX_PAGES_MIN or crawl_max_pages > _SEO_AUDIT_CRAWL_MAX_PAGES_MAX:
            raise BusinessSettingsValidationError(
                (
                    "seo_audit_crawl_max_pages must be between "
                    f"{_SEO_AUDIT_CRAWL_MAX_PAGES_MIN} and {_SEO_AUDIT_CRAWL_MAX_PAGES_MAX}."
                )
            )

        min_relevance_score = int(effective["competitor_candidate_min_relevance_score"])
        if (
            min_relevance_score < _COMPETITOR_CANDIDATE_MIN_RELEVANCE_SCORE_MIN
            or min_relevance_score > _COMPETITOR_CANDIDATE_MIN_RELEVANCE_SCORE_MAX
        ):
            raise BusinessSettingsValidationError(
                (
                    "competitor_candidate_min_relevance_score must be between "
                    f"{_COMPETITOR_CANDIDATE_MIN_RELEVANCE_SCORE_MIN} and "
                    f"{_COMPETITOR_CANDIDATE_MIN_RELEVANCE_SCORE_MAX}."
                )
            )

        big_box_penalty = int(effective["competitor_candidate_big_box_penalty"])
        if (
            big_box_penalty < _COMPETITOR_CANDIDATE_BIG_BOX_PENALTY_MIN
            or big_box_penalty > _COMPETITOR_CANDIDATE_BIG_BOX_PENALTY_MAX
        ):
            raise BusinessSettingsValidationError(
                (
                    "competitor_candidate_big_box_penalty must be between "
                    f"{_COMPETITOR_CANDIDATE_BIG_BOX_PENALTY_MIN} and "
                    f"{_COMPETITOR_CANDIDATE_BIG_BOX_PENALTY_MAX}."
                )
            )

        directory_penalty = int(effective["competitor_candidate_directory_penalty"])
        if (
            directory_penalty < _COMPETITOR_CANDIDATE_DIRECTORY_PENALTY_MIN
            or directory_penalty > _COMPETITOR_CANDIDATE_DIRECTORY_PENALTY_MAX
        ):
            raise BusinessSettingsValidationError(
                (
                    "competitor_candidate_directory_penalty must be between "
                    f"{_COMPETITOR_CANDIDATE_DIRECTORY_PENALTY_MIN} and "
                    f"{_COMPETITOR_CANDIDATE_DIRECTORY_PENALTY_MAX}."
                )
            )

        local_alignment_bonus = int(effective["competitor_candidate_local_alignment_bonus"])
        if (
            local_alignment_bonus < _COMPETITOR_CANDIDATE_LOCAL_ALIGNMENT_BONUS_MIN
            or local_alignment_bonus > _COMPETITOR_CANDIDATE_LOCAL_ALIGNMENT_BONUS_MAX
        ):
            raise BusinessSettingsValidationError(
                (
                    "competitor_candidate_local_alignment_bonus must be between "
                    f"{_COMPETITOR_CANDIDATE_LOCAL_ALIGNMENT_BONUS_MIN} and "
                    f"{_COMPETITOR_CANDIDATE_LOCAL_ALIGNMENT_BONUS_MAX}."
                )
            )

    def _is_valid_email(self, value: str | None) -> bool:
        if not value:
            return False
        return bool(_EMAIL_REGEX.match(value.strip()))

    def _is_valid_phone_e164(self, value: str | None) -> bool:
        if not value:
            return False
        return bool(_E164_REGEX.match(value.strip()))
