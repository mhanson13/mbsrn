from __future__ import annotations

from datetime import timedelta
import logging
import re

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.business import Business
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.schemas.business import BusinessSettingsUpdateRequest

_EMAIL_REGEX = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)
_E164_REGEX = re.compile(r"^\+[1-9]\d{9,14}$")
# Contract guardrail:
# These bounds must remain aligned with frontend validation constants:
# frontend/operator-ui/lib/validation/constants.ts
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
_COMPETITOR_TIMEOUT_SECONDS_MIN = 10
_COMPETITOR_TIMEOUT_SECONDS_MAX = 90
_NOTIFICATION_SETTING_FIELDS = {
    "notification_phone",
    "notification_email",
    "sms_enabled",
    "email_enabled",
    "customer_auto_ack_enabled",
    "contractor_alerts_enabled",
}
_COMPETITOR_CANDIDATE_SETTING_FIELDS = {
    "competitor_candidate_min_relevance_score",
    "competitor_candidate_big_box_penalty",
    "competitor_candidate_directory_penalty",
    "competitor_candidate_local_alignment_bonus",
}
_COMPETITOR_TIMEOUT_SETTING_FIELDS = {
    "competitor_primary_timeout_seconds",
    "competitor_degraded_timeout_seconds",
}
_COMPETITOR_PREVIEW_MATCH_LOOKBACK_DAYS = 14

logger = logging.getLogger(__name__)


class BusinessSettingsNotFoundError(ValueError):
    pass


class BusinessSettingsValidationError(ValueError):
    pass


class BusinessSettingsService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_competitor_profile_generation_repository: SEOCompetitorProfileGenerationRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_competitor_profile_generation_repository = seo_competitor_profile_generation_repository

    def get(self, *, business_id: str) -> Business:
        business = self.business_repository.get(business_id)
        if not business:
            raise BusinessSettingsNotFoundError("Business not found")
        return business

    def update_settings(self, *, business_id: str, payload: BusinessSettingsUpdateRequest) -> Business:
        business = self.get(business_id=business_id)

        updates = payload.model_dump(exclude_unset=True)
        explicit_preview_event_id = (
            str(updates.pop("competitor_tuning_preview_event_id") or "").strip()
            if "competitor_tuning_preview_event_id" in updates
            else None
        )
        if explicit_preview_event_id == "":
            explicit_preview_event_id = None
        previous_competitor_values = self._competitor_settings_from_business(business)
        effective = self._effective_settings(business=business, updates=updates)
        # Validate only the setting sections touched by this PATCH payload so one
        # invalid section cannot poison updates to unrelated admin controls.
        self._validate_effective_settings(updates=updates, effective=effective)

        for field_name, value in updates.items():
            setattr(business, field_name, value)

        self.business_repository.save(business)
        self.session.commit()
        self.session.refresh(business)
        self._link_recent_preview_event_for_competitor_settings_change(
            business=business,
            updates=updates,
            previous_competitor_values=previous_competitor_values,
            explicit_preview_event_id=explicit_preview_event_id,
        )
        return business

    def _link_recent_preview_event_for_competitor_settings_change(
        self,
        *,
        business: Business,
        updates: dict,
        previous_competitor_values: dict[str, int],
        explicit_preview_event_id: str | None,
    ) -> None:
        changed_keys = {
            key
            for key in _COMPETITOR_CANDIDATE_SETTING_FIELDS
            if key in updates and int(getattr(business, key)) != int(previous_competitor_values[key])
        }
        if not changed_keys:
            return

        applied_values = self._competitor_settings_from_business(business)
        created_after = utc_now() - timedelta(days=_COMPETITOR_PREVIEW_MATCH_LOOKBACK_DAYS)
        try:
            matched_event = None
            if explicit_preview_event_id:
                matched_event = self._find_explicit_preview_event_match_for_tuning_change(
                    business_id=business.id,
                    preview_event_id=explicit_preview_event_id,
                    changed_keys=changed_keys,
                    previous_values=previous_competitor_values,
                    applied_values=applied_values,
                )

            if matched_event is None:
                matched_event = self.seo_competitor_profile_generation_repository.find_recent_unapplied_preview_event_for_business_matching_tuning(
                    business_id=business.id,
                    changed_keys=changed_keys,
                    previous_values=previous_competitor_values,
                    applied_values=applied_values,
                    created_after=created_after,
                )

            if matched_event is None or matched_event.applied_at is not None:
                return
            matched_event.applied_at = utc_now()
            self.seo_competitor_profile_generation_repository.save_tuning_preview_event(matched_event)
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            logger.warning(
                (
                    "Failed to link competitor tuning preview event business_id=%s changed_keys=%s "
                    "explicit_preview_event_id=%s reason=%s"
                ),
                business.id,
                ",".join(sorted(changed_keys)),
                explicit_preview_event_id,
                str(exc),
            )

    def _find_explicit_preview_event_match_for_tuning_change(
        self,
        *,
        business_id: str,
        preview_event_id: str,
        changed_keys: set[str],
        previous_values: dict[str, int],
        applied_values: dict[str, int],
    ):
        event = self.seo_competitor_profile_generation_repository.get_tuning_preview_event_for_business(
            business_id=business_id,
            preview_event_id=preview_event_id,
        )
        if event is None or event.applied_at is not None:
            return None
        event_values = self._tuning_values_from_preview_response(event.preview_response)
        if event_values is None:
            return None
        current_values, proposed_values = event_values
        for key in changed_keys:
            if key not in _COMPETITOR_CANDIDATE_SETTING_FIELDS:
                return None
            if current_values.get(key) != previous_values.get(key):
                return None
            if proposed_values.get(key) != applied_values.get(key):
                return None
        return event

    @staticmethod
    def _tuning_values_from_preview_response(
        preview_response: dict[str, object] | None,
    ) -> tuple[dict[str, int], dict[str, int]] | None:
        if not isinstance(preview_response, dict):
            return None
        raw_current = preview_response.get("current_values")
        raw_proposed = preview_response.get("proposed_values")
        if not isinstance(raw_current, dict) or not isinstance(raw_proposed, dict):
            return None
        current_values: dict[str, int] = {}
        proposed_values: dict[str, int] = {}
        for key in _COMPETITOR_CANDIDATE_SETTING_FIELDS:
            try:
                current_values[key] = int(raw_current.get(key))
                proposed_values[key] = int(raw_proposed.get(key))
            except (TypeError, ValueError):
                return None
        return current_values, proposed_values

    @staticmethod
    def _competitor_settings_from_business(business: Business) -> dict[str, int]:
        return {
            "competitor_candidate_min_relevance_score": int(business.competitor_candidate_min_relevance_score),
            "competitor_candidate_big_box_penalty": int(business.competitor_candidate_big_box_penalty),
            "competitor_candidate_directory_penalty": int(business.competitor_candidate_directory_penalty),
            "competitor_candidate_local_alignment_bonus": int(business.competitor_candidate_local_alignment_bonus),
        }

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
            "competitor_primary_timeout_seconds": updates.get(
                "competitor_primary_timeout_seconds",
                business.competitor_primary_timeout_seconds,
            ),
            "competitor_degraded_timeout_seconds": updates.get(
                "competitor_degraded_timeout_seconds",
                business.competitor_degraded_timeout_seconds,
            ),
            "ai_prompt_text_competitor": updates.get(
                "ai_prompt_text_competitor",
                business.ai_prompt_text_competitor,
            ),
            "ai_prompt_text_recommendations": updates.get(
                "ai_prompt_text_recommendations",
                business.ai_prompt_text_recommendations,
            ),
            "timezone": updates.get("timezone", business.timezone),
        }

    def _validate_effective_settings(self, *, updates: dict, effective: dict) -> None:
        if _NOTIFICATION_SETTING_FIELDS.intersection(updates.keys()):
            self._validate_notification_settings(effective)
        if "seo_audit_crawl_max_pages" in updates:
            self._validate_crawl_page_limit(effective)
        if _COMPETITOR_CANDIDATE_SETTING_FIELDS.intersection(updates.keys()):
            self._validate_competitor_candidate_quality_settings(effective)
        if _COMPETITOR_TIMEOUT_SETTING_FIELDS.intersection(updates.keys()):
            self._validate_competitor_timeout_settings(effective)

    def _validate_notification_settings(self, effective: dict) -> None:
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

    def _validate_crawl_page_limit(self, effective: dict) -> None:
        crawl_max_pages = int(effective["seo_audit_crawl_max_pages"])
        if crawl_max_pages < _SEO_AUDIT_CRAWL_MAX_PAGES_MIN or crawl_max_pages > _SEO_AUDIT_CRAWL_MAX_PAGES_MAX:
            raise BusinessSettingsValidationError(
                (
                    "seo_audit_crawl_max_pages must be between "
                    f"{_SEO_AUDIT_CRAWL_MAX_PAGES_MIN} and {_SEO_AUDIT_CRAWL_MAX_PAGES_MAX}."
                )
            )

    def _validate_competitor_candidate_quality_settings(self, effective: dict) -> None:
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

    def _validate_competitor_timeout_settings(self, effective: dict) -> None:
        self._validate_optional_competitor_timeout_field(
            effective=effective,
            field_name="competitor_primary_timeout_seconds",
        )
        self._validate_optional_competitor_timeout_field(
            effective=effective,
            field_name="competitor_degraded_timeout_seconds",
        )

    def _validate_optional_competitor_timeout_field(self, *, effective: dict, field_name: str) -> None:
        raw_value = effective.get(field_name)
        if raw_value is None:
            return
        timeout_seconds = int(raw_value)
        if timeout_seconds < _COMPETITOR_TIMEOUT_SECONDS_MIN or timeout_seconds > _COMPETITOR_TIMEOUT_SECONDS_MAX:
            raise BusinessSettingsValidationError(
                (
                    f"{field_name} must be between "
                    f"{_COMPETITOR_TIMEOUT_SECONDS_MIN} and {_COMPETITOR_TIMEOUT_SECONDS_MAX}."
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
