from __future__ import annotations

from datetime import date, timedelta

from app.api.routes.seo import _derive_effectiveness_confidence, _derive_effectiveness_context
from app.schemas.seo_recommendation import (
    SEORecommendationMeasurementContextRead,
    SEORecommendationMeasurementDeltaSummaryRead,
    SEORecommendationMeasurementMetricWindowRead,
    SEORecommendationMeasurementWindowSummaryRead,
    SEORecommendationSearchConsoleContextRead,
    SEORecommendationSearchConsoleDeltaSummaryRead,
    SEORecommendationSearchConsoleWindowSummaryRead,
)


def _measurement_context(
    *,
    before_sessions: int,
    after_sessions: int,
    comparison_scope: str,
) -> SEORecommendationMeasurementContextRead:
    before_start = date.today() - timedelta(days=14)
    before_end = date.today() - timedelta(days=8)
    after_start = date.today() - timedelta(days=7)
    after_end = date.today() - timedelta(days=1)
    delta_absolute = after_sessions - before_sessions
    delta_percent = None if before_sessions <= 0 else round((delta_absolute / before_sessions) * 100, 2)
    return SEORecommendationMeasurementContextRead(
        measurement_status="available",
        comparison_scope="page" if comparison_scope == "page" else "site",
        sessions=SEORecommendationMeasurementMetricWindowRead(
            current=after_sessions,
            previous=before_sessions,
            delta_absolute=delta_absolute,
            delta_percent=delta_percent,
        ),
        delta_summary=SEORecommendationMeasurementDeltaSummaryRead(
            sessions_delta_absolute=delta_absolute,
            sessions_delta_percent=delta_percent,
        ),
        before_window_summary=SEORecommendationMeasurementWindowSummaryRead(
            start_date=before_start,
            end_date=before_end,
            users=max(1, before_sessions // 2),
            sessions=before_sessions,
            pageviews=max(1, before_sessions * 2),
        ),
        after_window_summary=SEORecommendationMeasurementWindowSummaryRead(
            start_date=after_start,
            end_date=after_end,
            users=max(1, after_sessions // 2),
            sessions=after_sessions,
            pageviews=max(1, after_sessions * 2),
        ),
    )


def _search_context(
    *,
    before_impressions: int,
    after_impressions: int,
    comparison_scope: str,
) -> SEORecommendationSearchConsoleContextRead:
    before_start = date.today() - timedelta(days=14)
    before_end = date.today() - timedelta(days=8)
    after_start = date.today() - timedelta(days=7)
    after_end = date.today() - timedelta(days=1)
    delta_absolute = after_impressions - before_impressions
    delta_percent = None if before_impressions <= 0 else round((delta_absolute / before_impressions) * 100, 2)
    return SEORecommendationSearchConsoleContextRead(
        search_console_status="available",
        comparison_scope="page" if comparison_scope == "page" else "site",
        current_window_summary=SEORecommendationSearchConsoleWindowSummaryRead(
            start_date=after_start,
            end_date=after_end,
            clicks=max(1, after_impressions // 25),
            impressions=after_impressions,
            ctr=4.2,
            average_position=8.1,
        ),
        previous_window_summary=SEORecommendationSearchConsoleWindowSummaryRead(
            start_date=before_start,
            end_date=before_end,
            clicks=max(1, before_impressions // 25),
            impressions=before_impressions,
            ctr=3.7,
            average_position=9.0,
        ),
        delta_summary=SEORecommendationSearchConsoleDeltaSummaryRead(
            clicks_delta_absolute=max(1, delta_absolute // 25),
            clicks_delta_percent=delta_percent,
            impressions_delta_absolute=delta_absolute,
            impressions_delta_percent=delta_percent,
            ctr_delta_absolute=0.5,
            average_position_delta_absolute=-0.9,
        ),
        top_queries_summary=[],
    )


def test_effectiveness_confidence_is_high_for_high_volume_aligned_improvement() -> None:
    context = _derive_effectiveness_context(
        traffic_context=_measurement_context(before_sessions=160, after_sessions=230, comparison_scope="page"),
        search_context=_search_context(before_impressions=3200, after_impressions=4200, comparison_scope="page"),
    )
    assert context is not None
    assert context.effectiveness_status == "available"
    assert context.effectiveness_trend == "improving"
    assert context.effectiveness_confidence == "high"
    assert context.summary is not None
    assert "has improved" in context.summary.lower()


def test_effectiveness_confidence_is_low_for_low_volume_noisy_delta() -> None:
    context = _derive_effectiveness_context(
        traffic_context=_measurement_context(before_sessions=6, after_sessions=9, comparison_scope="page"),
        search_context=None,
    )
    assert context is not None
    assert context.effectiveness_status == "partial"
    assert context.effectiveness_trend == "improving"
    assert context.effectiveness_confidence == "low"
    assert context.summary is not None
    assert "appears to be improving" in context.summary.lower()


def test_effectiveness_confidence_degrades_to_flat_for_conflicting_signals() -> None:
    context = _derive_effectiveness_context(
        traffic_context=_measurement_context(before_sessions=150, after_sessions=225, comparison_scope="page"),
        search_context=_search_context(before_impressions=3200, after_impressions=2500, comparison_scope="page"),
    )
    assert context is not None
    assert context.effectiveness_status == "available"
    assert context.effectiveness_trend == "flat"
    assert context.effectiveness_confidence == "low"
    assert context.summary is not None
    assert "mixed" in context.summary.lower()


def test_effectiveness_confidence_prefers_page_scope_over_site_scope() -> None:
    site_confidence = _derive_effectiveness_confidence(
        volume=160,
        delta_absolute=12,
        delta_percent=7.5,
        comparison_scope="site",
        volume_moderate_threshold=60,
        volume_high_threshold=160,
        delta_absolute_moderate_threshold=10.0,
        delta_absolute_high_threshold=30.0,
        delta_percent_moderate_threshold=5.0,
        delta_percent_high_threshold=12.0,
    )
    page_confidence = _derive_effectiveness_confidence(
        volume=160,
        delta_absolute=12,
        delta_percent=7.5,
        comparison_scope="page",
        volume_moderate_threshold=60,
        volume_high_threshold=160,
        delta_absolute_moderate_threshold=10.0,
        delta_absolute_high_threshold=30.0,
        delta_percent_moderate_threshold=5.0,
        delta_percent_high_threshold=12.0,
    )
    assert site_confidence == "moderate"
    assert page_confidence == "high"


def test_effectiveness_context_is_insufficient_when_no_measurement_signals_exist() -> None:
    context = _derive_effectiveness_context(traffic_context=None, search_context=None)
    assert context is not None
    assert context.effectiveness_status == "insufficient"
    assert context.effectiveness_trend == "insufficient_data"
    assert context.effectiveness_confidence == "low"
