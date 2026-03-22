from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.integrations.seo_recommendation_narrative_provider import SEORecommendationNarrativeProviderError
from app.integrations.seo_summary_provider import SEORecommendationNarrativeProvider
from app.models.business import Business
from app.models.seo_competitor_tuning_preview_event import SEOCompetitorTuningPreviewEvent
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_narrative import SEORecommendationNarrative
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_recommendation_narrative_repository import SEORecommendationNarrativeRepository
from app.repositories.seo_recommendation_repository import SEORecommendationRepository
from app.services.seo_competitor_profile_candidate_quality import (
    BIG_BOX_PENALTY_MAX,
    BIG_BOX_PENALTY_MIN,
    DEFAULT_BIG_BOX_PENALTY,
    DEFAULT_DIRECTORY_PENALTY,
    DEFAULT_LOCAL_ALIGNMENT_BONUS,
    DEFAULT_MIN_RELEVANCE_SCORE,
    DIRECTORY_PENALTY_MAX,
    DIRECTORY_PENALTY_MIN,
    EXCLUSION_REASON_KEYS,
    EXCLUSION_REASON_BIG_BOX_MISMATCH,
    EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR,
    EXCLUSION_REASON_LOW_RELEVANCE,
    LOCAL_ALIGNMENT_BONUS_MAX,
    LOCAL_ALIGNMENT_BONUS_MIN,
    MIN_RELEVANCE_SCORE_MAX,
    MIN_RELEVANCE_SCORE_MIN,
    default_exclusion_reason_counts,
)
from app.services.seo_recommendation_narrative_prompt import SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION


logger = logging.getLogger(__name__)
_COMPETITOR_TELEMETRY_LOOKBACK_DAYS = 30
_PREVIEW_CAVEAT = (
    "Preview is deterministic and estimated from recent persisted telemetry. "
    "It does not apply settings and does not guarantee exact future counts."
)
_PREVIEW_SUMMARY_MAX_CHARS = 500
_PREVIEW_RISK_FLAG_MAX_CHARS = 160
_TUNING_SETTINGS_BOUNDS: dict[str, tuple[int, int]] = {
    "competitor_candidate_min_relevance_score": (MIN_RELEVANCE_SCORE_MIN, MIN_RELEVANCE_SCORE_MAX),
    "competitor_candidate_big_box_penalty": (BIG_BOX_PENALTY_MIN, BIG_BOX_PENALTY_MAX),
    "competitor_candidate_directory_penalty": (DIRECTORY_PENALTY_MIN, DIRECTORY_PENALTY_MAX),
    "competitor_candidate_local_alignment_bonus": (LOCAL_ALIGNMENT_BONUS_MIN, LOCAL_ALIGNMENT_BONUS_MAX),
}
_DEFAULT_TUNING_VALUES: dict[str, int] = {
    "competitor_candidate_min_relevance_score": DEFAULT_MIN_RELEVANCE_SCORE,
    "competitor_candidate_big_box_penalty": DEFAULT_BIG_BOX_PENALTY,
    "competitor_candidate_directory_penalty": DEFAULT_DIRECTORY_PENALTY,
    "competitor_candidate_local_alignment_bonus": DEFAULT_LOCAL_ALIGNMENT_BONUS,
}


class SEORecommendationNarrativeNotFoundError(ValueError):
    pass


class SEORecommendationNarrativeValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEORecommendationNarrativeResult:
    narrative: SEORecommendationNarrative


@dataclass(frozen=True)
class SEORecommendationTuningImpactPreviewResult:
    business_id: str
    site_id: str
    preview_event_id: str | None
    source_recommendation_run_id: str | None
    source_narrative_id: str | None
    current_values: dict[str, int]
    proposed_values: dict[str, int]
    telemetry_window: dict[str, object]
    estimated_impact: dict[str, object]
    caveat: str


class SEORecommendationNarrativeService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        seo_recommendation_repository: SEORecommendationRepository,
        seo_recommendation_narrative_repository: SEORecommendationNarrativeRepository,
        seo_competitor_profile_generation_repository: SEOCompetitorProfileGenerationRepository,
        provider: SEORecommendationNarrativeProvider,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.seo_recommendation_repository = seo_recommendation_repository
        self.seo_recommendation_narrative_repository = seo_recommendation_narrative_repository
        self.seo_competitor_profile_generation_repository = seo_competitor_profile_generation_repository
        self.provider = provider

    def summarize_run(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
        created_by_principal_id: str | None,
    ) -> SEORecommendationNarrativeResult:
        business = self._require_business(business_id)
        run = self._get_run_for_business(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
        if run.status != "completed":
            raise SEORecommendationNarrativeValidationError(
                "Recommendation run must be completed before narrative generation"
            )

        recommendations = self.seo_recommendation_repository.list_recommendations_for_business_run(
            business_id,
            recommendation_run_id,
        )
        by_status, by_category, by_severity, by_effort_bucket, by_priority_band = self._summarize(recommendations)
        backlog = self._build_backlog(recommendations)
        competitor_telemetry_summary = self._build_competitor_telemetry_summary(
            business_id=business_id,
            site_id=site_id,
        )
        current_tuning_values = self._build_current_tuning_values(business)

        version = self.seo_recommendation_narrative_repository.next_version(
            business_id,
            recommendation_run_id,
        )

        try:
            output = self.provider.generate_narrative(
                run=run,
                recommendations=recommendations,
                by_status=by_status,
                by_category=by_category,
                by_severity=by_severity,
                by_effort_bucket=by_effort_bucket,
                by_priority_band=by_priority_band,
                backlog=backlog,
                competitor_telemetry_summary=competitor_telemetry_summary,
                current_tuning_values=current_tuning_values,
            )
            narrative = SEORecommendationNarrative(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                recommendation_run_id=recommendation_run_id,
                version=version,
                status="completed",
                narrative_text=output.narrative_text,
                top_themes_json=output.top_themes,
                sections_json=output.sections,
                provider_name=output.provider_name,
                model_name=output.model_name,
                prompt_version=output.prompt_version,
                error_message=None,
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_recommendation_narrative_repository.create(narrative)
            self.session.commit()
            self.session.refresh(narrative)
            return SEORecommendationNarrativeResult(narrative=narrative)
        except SEORecommendationNarrativeProviderError as exc:
            logger.warning(
                (
                    "SEO recommendation narrative generation failed business_id=%s site_id=%s "
                    "recommendation_run_id=%s code=%s"
                ),
                business_id,
                site_id,
                recommendation_run_id,
                exc.code,
            )
            failed = SEORecommendationNarrative(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                recommendation_run_id=recommendation_run_id,
                version=version,
                status="failed",
                narrative_text=None,
                top_themes_json=[],
                sections_json=None,
                provider_name=exc.provider_name,
                model_name=exc.model_name,
                prompt_version=exc.prompt_version,
                error_message=exc.safe_message,
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_recommendation_narrative_repository.create(failed)
            self.session.commit()
            raise SEORecommendationNarrativeValidationError(exc.safe_message) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "SEO recommendation narrative generation failed business_id=%s site_id=%s recommendation_run_id=%s reason=%s",
                business_id,
                site_id,
                recommendation_run_id,
                str(exc),
            )
            provider_name, model_name, prompt_version = self._provider_defaults()
            failed = SEORecommendationNarrative(
                id=str(uuid4()),
                business_id=business_id,
                site_id=site_id,
                recommendation_run_id=recommendation_run_id,
                version=version,
                status="failed",
                narrative_text=None,
                top_themes_json=[],
                sections_json=None,
                provider_name=provider_name,
                model_name=model_name,
                prompt_version=prompt_version,
                error_message="Recommendation narrative generation failed.",
                created_by_principal_id=created_by_principal_id,
            )
            self.seo_recommendation_narrative_repository.create(failed)
            self.session.commit()
            raise SEORecommendationNarrativeValidationError("Recommendation narrative generation failed") from exc

    def list_narratives(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
    ) -> list[SEORecommendationNarrative]:
        self._require_business(business_id)
        self._get_run_for_business(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
        return self.seo_recommendation_narrative_repository.list_for_business_run(
            business_id,
            recommendation_run_id,
        )

    def get_latest_narrative(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_run_id: str,
    ) -> SEORecommendationNarrative:
        self._require_business(business_id)
        self._get_run_for_business(
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=recommendation_run_id,
        )
        narrative = self.seo_recommendation_narrative_repository.get_latest_for_business_run(
            business_id,
            recommendation_run_id,
        )
        if narrative is None:
            raise SEORecommendationNarrativeNotFoundError("Recommendation narrative not found")
        return narrative

    def get_narrative(
        self,
        *,
        business_id: str,
        site_id: str,
        narrative_id: str,
    ) -> SEORecommendationNarrative:
        self._require_business(business_id)
        narrative = self.seo_recommendation_narrative_repository.get_for_business(business_id, narrative_id)
        if narrative is None or narrative.site_id != site_id:
            raise SEORecommendationNarrativeNotFoundError("Recommendation narrative not found")
        return narrative

    def preview_tuning_impact(
        self,
        *,
        business_id: str,
        site_id: str,
        current_values_overrides: dict[str, int] | None,
        proposed_values_overrides: dict[str, int],
        recommendation_run_id: str | None,
        narrative_id: str | None,
    ) -> SEORecommendationTuningImpactPreviewResult:
        business = self._require_business(business_id)

        source_run_id = recommendation_run_id
        source_narrative_id = narrative_id
        if recommendation_run_id:
            self._get_run_for_business(
                business_id=business_id,
                site_id=site_id,
                recommendation_run_id=recommendation_run_id,
            )
        if narrative_id:
            narrative = self.get_narrative(
                business_id=business_id,
                site_id=site_id,
                narrative_id=narrative_id,
            )
            source_narrative_id = narrative.id
            if source_run_id is None:
                source_run_id = narrative.recommendation_run_id
            elif source_run_id != narrative.recommendation_run_id:
                raise SEORecommendationNarrativeValidationError(
                    "narrative_id must belong to recommendation_run_id when both are provided"
                )

        current_values = self._merge_tuning_overrides(
            base_values=self._build_current_tuning_values(business),
            overrides=current_values_overrides or {},
        )
        proposed_values = self._merge_tuning_overrides(
            base_values=current_values,
            overrides=proposed_values_overrides,
        )
        if proposed_values == current_values:
            raise SEORecommendationNarrativeValidationError(
                "Proposed tuning values must differ from current values."
            )

        telemetry_window = self._build_competitor_telemetry_summary(
            business_id=business_id,
            site_id=site_id,
        )
        estimated_impact = self._estimate_tuning_impact(
            telemetry_window=telemetry_window,
            current_values=current_values,
            proposed_values=proposed_values,
        )
        preview_event = SEOCompetitorTuningPreviewEvent(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            source_narrative_id=source_narrative_id,
            source_recommendation_run_id=source_run_id,
            preview_request={
                "current_values_overrides": dict(sorted((current_values_overrides or {}).items())),
                "proposed_values_overrides": dict(sorted(proposed_values_overrides.items())),
                "current_values": dict(sorted(current_values.items())),
                "proposed_values": dict(sorted(proposed_values.items())),
                "source_recommendation_run_id": source_run_id,
                "source_narrative_id": source_narrative_id,
            },
            preview_response={
                "telemetry_window": telemetry_window,
                "estimated_impact": self._sanitize_estimated_impact_for_preview_storage(estimated_impact),
                "current_values": dict(sorted(current_values.items())),
                "proposed_values": dict(sorted(proposed_values.items())),
                "caveat": _PREVIEW_CAVEAT,
            },
            applied_at=None,
            evaluated_generation_run_id=None,
            evaluated_at=None,
            estimated_included_delta=None,
            actual_included_delta=None,
            error_margin=None,
            direction_correct=None,
        )
        try:
            self.seo_competitor_profile_generation_repository.create_tuning_preview_event(preview_event)
            self.session.commit()
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            logger.warning(
                "Failed to persist tuning preview event business_id=%s site_id=%s reason=%s",
                business_id,
                site_id,
                str(exc),
            )
            raise SEORecommendationNarrativeValidationError(
                "Unable to persist tuning impact preview event."
            ) from exc
        return SEORecommendationTuningImpactPreviewResult(
            business_id=business_id,
            site_id=site_id,
            preview_event_id=preview_event.id,
            source_recommendation_run_id=source_run_id,
            source_narrative_id=source_narrative_id,
            current_values=current_values,
            proposed_values=proposed_values,
            telemetry_window=telemetry_window,
            estimated_impact=estimated_impact,
            caveat=_PREVIEW_CAVEAT,
        )

    def _get_run_for_business(self, *, business_id: str, site_id: str, recommendation_run_id: str):
        run = self.seo_recommendation_repository.get_run_for_business(business_id, recommendation_run_id)
        if run is None or run.site_id != site_id:
            raise SEORecommendationNarrativeNotFoundError("SEO recommendation run not found")
        return run

    def _require_business(self, business_id: str) -> Business:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEORecommendationNarrativeNotFoundError("Business not found")
        return business

    def _summarize(
        self,
        recommendations: list[SEORecommendation],
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
        by_status = Counter()
        by_category = Counter()
        by_severity = Counter()
        by_effort_bucket = Counter()
        by_priority_band = Counter()
        for item in recommendations:
            by_status[(item.status or "").strip().lower() or "open"] += 1
            by_category[(item.category or "").strip().upper() or "TECHNICAL"] += 1
            by_severity[(item.severity or "").strip().upper() or "INFO"] += 1
            by_effort_bucket[(item.effort_bucket or "").strip().upper() or "MEDIUM"] += 1
            by_priority_band[(item.priority_band or "").strip().lower() or "medium"] += 1
        return (
            dict(sorted(by_status.items())),
            dict(sorted(by_category.items())),
            dict(sorted(by_severity.items())),
            dict(sorted(by_effort_bucket.items())),
            dict(sorted(by_priority_band.items())),
        )

    def _build_backlog(self, recommendations: list[SEORecommendation]) -> list[SEORecommendation]:
        actionable = [
            item
            for item in recommendations
            if (item.status or "").strip().lower() in {"open", "in_progress", "accepted"}
        ]
        return sorted(
            actionable,
            key=lambda rec: (
                -int(rec.priority_score or 0),
                (rec.created_at.isoformat() if rec.created_at is not None else ""),
                rec.id,
            ),
        )

    def _provider_defaults(self) -> tuple[str, str, str]:
        provider_name = str(getattr(self.provider, "provider_name", "") or "").strip() or "narrative-provider-error"
        model_name = str(getattr(self.provider, "model_name", "") or "").strip() or "narrative-provider-error"
        prompt_version = (
            str(getattr(self.provider, "prompt_version", "") or "").strip()
            or SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION
        )
        return provider_name, model_name, prompt_version

    def _build_current_tuning_values(self, business: Business) -> dict[str, int]:
        raw_values = {
            "competitor_candidate_min_relevance_score": business.competitor_candidate_min_relevance_score,
            "competitor_candidate_big_box_penalty": business.competitor_candidate_big_box_penalty,
            "competitor_candidate_directory_penalty": business.competitor_candidate_directory_penalty,
            "competitor_candidate_local_alignment_bonus": business.competitor_candidate_local_alignment_bonus,
        }
        normalized: dict[str, int] = {}
        for setting, bounds in _TUNING_SETTINGS_BOUNDS.items():
            default_value = _DEFAULT_TUNING_VALUES[setting]
            raw_value = raw_values.get(setting, default_value)
            normalized[setting] = self._bounded_int(
                raw_value,
                minimum=bounds[0],
                maximum=bounds[1],
                default=default_value,
            )
        return normalized

    def _build_competitor_telemetry_summary(self, *, business_id: str, site_id: str) -> dict[str, object]:
        window_start = utc_now() - timedelta(days=_COMPETITOR_TELEMETRY_LOOKBACK_DAYS)
        (
            total_runs,
            total_raw_candidate_count,
            total_included_candidate_count,
            total_excluded_candidate_count,
        ) = self.seo_competitor_profile_generation_repository.summarize_candidate_telemetry_totals(
            business_id=business_id,
            site_id=site_id,
            created_after=window_start,
        )
        exclusion_reason_records = (
            self.seo_competitor_profile_generation_repository.list_exclusion_reason_counts_for_business_site_created_after(
                business_id=business_id,
                site_id=site_id,
                created_after=window_start,
            )
        )
        exclusion_counts_by_reason = default_exclusion_reason_counts()
        for record in exclusion_reason_records:
            for reason in EXCLUSION_REASON_KEYS:
                try:
                    exclusion_counts_by_reason[reason] += max(0, int(record.get(reason, 0)))
                except (TypeError, ValueError, AttributeError):
                    continue

        return {
            "lookback_days": _COMPETITOR_TELEMETRY_LOOKBACK_DAYS,
            "total_runs": int(total_runs),
            "total_raw_candidate_count": int(total_raw_candidate_count),
            "total_included_candidate_count": int(total_included_candidate_count),
            "total_excluded_candidate_count": int(total_excluded_candidate_count),
            "exclusion_counts_by_reason": exclusion_counts_by_reason,
        }

    def _merge_tuning_overrides(
        self,
        *,
        base_values: dict[str, int],
        overrides: dict[str, int],
    ) -> dict[str, int]:
        merged = dict(base_values)
        for key, raw_value in overrides.items():
            if key not in _TUNING_SETTINGS_BOUNDS:
                raise SEORecommendationNarrativeValidationError(f"Unsupported tuning setting: {key}")
            bounds = _TUNING_SETTINGS_BOUNDS[key]
            merged[key] = self._bounded_int(
                raw_value,
                minimum=bounds[0],
                maximum=bounds[1],
                default=merged[key],
            )
        return merged

    def _estimate_tuning_impact(
        self,
        *,
        telemetry_window: dict[str, object],
        current_values: dict[str, int],
        proposed_values: dict[str, int],
    ) -> dict[str, object]:
        raw_count = max(0, int(telemetry_window.get("total_raw_candidate_count", 0) or 0))
        excluded_count = max(0, int(telemetry_window.get("total_excluded_candidate_count", 0) or 0))
        lookback_days = max(1, int(telemetry_window.get("lookback_days", _COMPETITOR_TELEMETRY_LOOKBACK_DAYS) or 1))
        baseline_reason_counts = default_exclusion_reason_counts()
        raw_reason_counts = telemetry_window.get("exclusion_counts_by_reason")
        if isinstance(raw_reason_counts, dict):
            for reason in EXCLUSION_REASON_KEYS:
                try:
                    baseline_reason_counts[reason] = max(0, int(raw_reason_counts.get(reason, 0)))
                except (TypeError, ValueError):
                    baseline_reason_counts[reason] = 0

        estimated_reason_deltas = default_exclusion_reason_counts()
        risk_flags: list[str] = []

        if raw_count <= 0:
            return {
                "insufficient_data": True,
                "estimated_included_candidate_delta": 0,
                "estimated_excluded_candidate_delta": 0,
                "estimated_exclusion_reason_deltas": dict(sorted(estimated_reason_deltas.items())),
                "summary": (
                    "Insufficient recent competitor telemetry for deterministic impact estimation. "
                    "Run generation again to collect telemetry."
                ),
                "risk_flags": [],
            }

        min_relevance_delta = (
            proposed_values["competitor_candidate_min_relevance_score"]
            - current_values["competitor_candidate_min_relevance_score"]
        )
        if min_relevance_delta != 0:
            low_relevance_step = max(1, int(round(raw_count * 0.02)))
            self._apply_reason_delta(
                reason=EXCLUSION_REASON_LOW_RELEVANCE,
                requested_delta=min_relevance_delta * low_relevance_step,
                baseline_counts=baseline_reason_counts,
                estimated_deltas=estimated_reason_deltas,
                raw_count=raw_count,
            )
            if min_relevance_delta < 0:
                risk_flags.append("Lower minimum relevance score may increase weak or noisy candidates.")
            else:
                risk_flags.append("Higher minimum relevance score may reduce candidate volume.")

        directory_penalty_delta = (
            proposed_values["competitor_candidate_directory_penalty"]
            - current_values["competitor_candidate_directory_penalty"]
        )
        if directory_penalty_delta != 0:
            directory_step = max(1, int(round(raw_count * 0.01)))
            self._apply_reason_delta(
                reason=EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR,
                requested_delta=directory_penalty_delta * directory_step,
                baseline_counts=baseline_reason_counts,
                estimated_deltas=estimated_reason_deltas,
                raw_count=raw_count,
            )
            if directory_penalty_delta < 0:
                risk_flags.append("Lower directory penalty may admit more directory or aggregator candidates.")
            else:
                risk_flags.append("Higher directory penalty may suppress directory or aggregator noise.")

        big_box_penalty_delta = (
            proposed_values["competitor_candidate_big_box_penalty"]
            - current_values["competitor_candidate_big_box_penalty"]
        )
        if big_box_penalty_delta != 0:
            big_box_step = max(1, int(round(raw_count * 0.01)))
            self._apply_reason_delta(
                reason=EXCLUSION_REASON_BIG_BOX_MISMATCH,
                requested_delta=big_box_penalty_delta * big_box_step,
                baseline_counts=baseline_reason_counts,
                estimated_deltas=estimated_reason_deltas,
                raw_count=raw_count,
            )
            if big_box_penalty_delta < 0:
                risk_flags.append("Lower big-box penalty may admit more non-local big-box matches.")
            else:
                risk_flags.append("Higher big-box penalty may reduce non-local big-box false positives.")

        local_alignment_delta = (
            proposed_values["competitor_candidate_local_alignment_bonus"]
            - current_values["competitor_candidate_local_alignment_bonus"]
        )
        if local_alignment_delta != 0:
            local_step = max(1, int(round(raw_count * 0.01)))
            self._apply_reason_delta(
                reason=EXCLUSION_REASON_LOW_RELEVANCE,
                requested_delta=-(local_alignment_delta * local_step),
                baseline_counts=baseline_reason_counts,
                estimated_deltas=estimated_reason_deltas,
                raw_count=raw_count,
            )
            self._apply_reason_delta(
                reason=EXCLUSION_REASON_BIG_BOX_MISMATCH,
                requested_delta=-int(round(local_alignment_delta * local_step * 0.5)),
                baseline_counts=baseline_reason_counts,
                estimated_deltas=estimated_reason_deltas,
                raw_count=raw_count,
            )
            if local_alignment_delta > 0:
                risk_flags.append("Higher local alignment bonus may reduce non-local false positives.")
            else:
                risk_flags.append("Lower local alignment bonus may allow more geographically weak matches.")

        estimated_excluded_delta = sum(estimated_reason_deltas.values())
        estimated_excluded_delta = max(-excluded_count, min(raw_count - excluded_count, estimated_excluded_delta))
        estimated_included_delta = -estimated_excluded_delta

        top_reason = None
        non_zero_reason_deltas = {k: v for k, v in estimated_reason_deltas.items() if v != 0}
        if non_zero_reason_deltas:
            top_reason = max(non_zero_reason_deltas.items(), key=lambda item: abs(item[1]))
        if estimated_included_delta > 0:
            summary = (
                f"Estimated increase of {estimated_included_delta} included candidates over the last "
                f"{lookback_days} days of telemetry."
            )
        elif estimated_included_delta < 0:
            summary = (
                f"Estimated decrease of {abs(estimated_included_delta)} included candidates over the last "
                f"{lookback_days} days of telemetry."
            )
        else:
            summary = f"No material included-candidate change is estimated over the last {lookback_days} days."
        if top_reason is not None:
            reason_label = top_reason[0].replace("_", " ")
            summary = f"{summary} Primary modeled driver: {reason_label} ({top_reason[1]:+d})."

        deduped_flags = list(dict.fromkeys(flag for flag in risk_flags if flag))[:4]
        return {
            "insufficient_data": False,
            "estimated_included_candidate_delta": int(estimated_included_delta),
            "estimated_excluded_candidate_delta": int(estimated_excluded_delta),
            "estimated_exclusion_reason_deltas": dict(sorted(estimated_reason_deltas.items())),
            "summary": summary,
            "risk_flags": deduped_flags,
        }

    def _sanitize_estimated_impact_for_preview_storage(
        self,
        estimated_impact: dict[str, object],
    ) -> dict[str, object]:
        sanitized = dict(estimated_impact)
        raw_summary = str(sanitized.get("summary", "") or "").strip()
        if len(raw_summary) > _PREVIEW_SUMMARY_MAX_CHARS:
            raw_summary = raw_summary[: _PREVIEW_SUMMARY_MAX_CHARS - 3] + "..."
        sanitized["summary"] = raw_summary

        raw_risk_flags = sanitized.get("risk_flags")
        if isinstance(raw_risk_flags, list):
            bounded_flags: list[str] = []
            for raw_item in raw_risk_flags[:4]:
                normalized = str(raw_item or "").strip()
                if not normalized:
                    continue
                if len(normalized) > _PREVIEW_RISK_FLAG_MAX_CHARS:
                    normalized = normalized[: _PREVIEW_RISK_FLAG_MAX_CHARS - 3] + "..."
                bounded_flags.append(normalized)
            sanitized["risk_flags"] = bounded_flags
        else:
            sanitized["risk_flags"] = []
        return sanitized

    @staticmethod
    def _apply_reason_delta(
        *,
        reason: str,
        requested_delta: int,
        baseline_counts: dict[str, int],
        estimated_deltas: dict[str, int],
        raw_count: int,
    ) -> int:
        if requested_delta == 0:
            return 0
        baseline = max(0, int(baseline_counts.get(reason, 0)))
        current_estimated = baseline + int(estimated_deltas.get(reason, 0))
        minimum_allowed_delta = -current_estimated
        maximum_allowed_delta = raw_count - current_estimated
        applied_delta = max(minimum_allowed_delta, min(maximum_allowed_delta, int(requested_delta)))
        estimated_deltas[reason] = int(estimated_deltas.get(reason, 0)) + applied_delta
        return applied_delta

    @staticmethod
    def _bounded_int(value: object, *, minimum: int, maximum: int, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = int(default)
        if parsed < minimum:
            return minimum
        if parsed > maximum:
            return maximum
        return parsed
