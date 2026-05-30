from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.deps import (
    TenantContext,
    get_seo_analytics_service,
    get_seo_migration_service,
    get_seo_site_service,
    get_tenant_context,
    resolve_tenant_business_id,
)
from app.schemas.seo_recommendation import (
    SEORecommendationGA4OutcomeDeltaRead,
    SEORecommendationGA4OutcomeSnapshotRead,
    SEORecommendationGA4OutcomeWindowRead,
)
from app.schemas.seo_migration import (
    SEOMigrationAnalyticsConfigUpdateRequest,
    SEOMigrationArtifactApproveRequest,
    SEOMigrationArtifactDeleteActionRead,
    SEOMigrationArtifactFilePreviewRead,
    SEOMigrationArtifactVersionListResponse,
    SEOMigrationArtifactVersionRead,
    SEOMigrationDeployActionRead,
    SEOMigrationDeployConfigUpdateRequest,
    SEOMigrationDeployStatusRefreshRequest,
    SEOMigrationDeployRequest,
    SEOMigrationDraftGenerationErrorEnvelopeRead,
    SEOMigrationDraftGenerateRequest,
    SEOMigrationDraftReadinessRead,
    SEOMigrationDiscoveredMediaImportRead,
    SEOMigrationDiscoveredMediaImportRequest,
    SEOMigrationEnrichedContentUpdateRequest,
    SEOMigrationHistoryListRead,
    SEOMigrationMediaAssetListRead,
    SEOMigrationMediaAssetRead,
    SEOMigrationMediaAssetLifecycleActionRead,
    SEOMigrationMediaAssetLifecycleRequest,
    SEOMigrationMediaSuggestionBatchRead,
    SEOMigrationMediaSuggestionBatchRequest,
    SEOMigrationMediaAssetUpdateRequest,
    SEOMigrationPublishActionRead,
    SEOMigrationPublishConfigUpdateRequest,
    SEOMigrationPublishRequest,
    SEOMigrationRequirementsSuggestionRead,
    SEOMigrationRequirementsSuggestionRequest,
    SEOMigrationRepositoryAdoptActionRead,
    SEOMigrationPromptPreviewRead,
    SEOMigrationRequirementsUpdateRequest,
    SEOMigrationSourceIngestRequest,
    SEOMigrationSourceSnapshotRead,
    SEOMigrationWorkspaceCreateOrUpdateRequest,
    SEOMigrationWorkspaceRead,
    SEOMigrationWorkspaceSummaryRead,
)
from app.services.seo_analytics import SEOAnalyticsService
from app.services.seo_migration import (
    SEOMigrationNotFoundError,
    SEOMigrationService,
    SEOMigrationValidationError,
)
from app.services.seo_sites import SEOSiteNotFoundError, SEOSiteService


router = APIRouter(prefix="/api/businesses/{business_id}/seo", tags=["seo"])

_DRAFT_ONLY_NOTICE = (
    "Draft artifacts only. Nothing is published or deployed automatically. "
    "Approval, GitHub publish, and GKE deploy remain explicit operator-triggered steps."
)
_DRAFT_REASON_CODE_APP_AUTH_REQUIRED = "app_auth_required"
_DRAFT_REASON_CODE_SESSION_EXPIRED = "session_expired"
_DRAFT_REASON_CODE_GOOGLE_RECONNECT_REQUIRED = "google_reconnect_required"
_DRAFT_REASON_CODE_GOOGLE_INTEGRATION_UNAVAILABLE = "google_integration_unavailable"
_DRAFT_REASON_CODE_CONTEXT_UNAVAILABLE = "draft_generation_context_unavailable"
_DRAFT_REASON_CODE_PREFLIGHT_TOO_LARGE = "migration_generation_preflight_too_large"
_DRAFT_REASON_CODE_DEFAULT = "draft_generation_failed"
_GA4_OUTCOME_SESSIONS_DIRECTION_THRESHOLD_PERCENT = 5.0
_GA4_OUTCOME_ORGANIC_DIRECTION_THRESHOLD_PERCENT = 5.0
_GA4_OUTCOME_ENGAGEMENT_DIRECTION_THRESHOLD_POINTS = 0.02


def _normalize_ga4_outcome_anchor_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _derive_migration_ga4_outcome_anchor(workspace) -> tuple[str, datetime] | None:  # noqa: ANN001
    if isinstance(getattr(workspace, "last_deployed_at", None), datetime):
        return ("migration_deployed", _normalize_ga4_outcome_anchor_timestamp(workspace.last_deployed_at))
    if isinstance(getattr(workspace, "last_published_at", None), datetime):
        return ("migration_published", _normalize_ga4_outcome_anchor_timestamp(workspace.last_published_at))
    return None


def _derive_ga4_outcome_unavailable_status(*, site_analytics_summary: object, ga4_property_id: str | None) -> str | None:
    if not str(ga4_property_id or "").strip():
        return "not_configured"

    ga4_reason = str(getattr(site_analytics_summary, "ga4_error_reason", "") or "").strip().lower()
    if ga4_reason == "not_configured":
        return "not_configured"
    if ga4_reason == "missing_oauth_scope":
        return "missing_scope"
    if ga4_reason in {"permission_denied", "access_denied"}:
        return "permission_denied"
    if ga4_reason == "no_data":
        return "insufficient_data"
    if ga4_reason in {"unknown_error", "invalid_property_format", "property_not_found"}:
        return "unavailable"

    ga4_health = getattr(site_analytics_summary, "ga4_health", None)
    ga4_health_status = str(getattr(ga4_health, "ga4_health_status", "") or "").strip().lower()
    if ga4_health_status == "not_configured":
        return "not_configured"
    if ga4_health_status == "missing_oauth_scope":
        return "missing_scope"
    if ga4_health_status == "permission_denied":
        return "permission_denied"
    if ga4_health_status == "no_data":
        return "insufficient_data"
    if ga4_health_status in {"invalid_property", "unavailable", "unknown"}:
        return "unavailable"

    summary_status = str(getattr(site_analytics_summary, "status", "") or "").strip().lower()
    if summary_status == "not_configured":
        return "not_configured"
    if summary_status == "unavailable":
        return "unavailable"
    return None


def _calculate_ga4_outcome_delta_percent(current: int, previous: int) -> float | None:
    normalized_current = max(0, int(current))
    normalized_previous = max(0, int(previous))
    if normalized_previous <= 0:
        if normalized_current <= 0:
            return 0.0
        return None
    return round(((normalized_current - normalized_previous) / normalized_previous) * 100, 2)


def _derive_ga4_outcome_direction(
    *,
    sessions_delta_percent: float | None,
    engagement_rate_delta_points: float | None,
    organic_sessions_delta_percent: float | None,
) -> str:
    directional_signals = 0
    improving_signals = 0
    declining_signals = 0

    if sessions_delta_percent is not None:
        directional_signals += 1
        if sessions_delta_percent >= _GA4_OUTCOME_SESSIONS_DIRECTION_THRESHOLD_PERCENT:
            improving_signals += 1
        elif sessions_delta_percent <= -_GA4_OUTCOME_SESSIONS_DIRECTION_THRESHOLD_PERCENT:
            declining_signals += 1

    if organic_sessions_delta_percent is not None:
        directional_signals += 1
        if organic_sessions_delta_percent >= _GA4_OUTCOME_ORGANIC_DIRECTION_THRESHOLD_PERCENT:
            improving_signals += 1
        elif organic_sessions_delta_percent <= -_GA4_OUTCOME_ORGANIC_DIRECTION_THRESHOLD_PERCENT:
            declining_signals += 1

    if engagement_rate_delta_points is not None:
        directional_signals += 1
        if engagement_rate_delta_points >= _GA4_OUTCOME_ENGAGEMENT_DIRECTION_THRESHOLD_POINTS:
            improving_signals += 1
        elif engagement_rate_delta_points <= -_GA4_OUTCOME_ENGAGEMENT_DIRECTION_THRESHOLD_POINTS:
            declining_signals += 1

    if directional_signals <= 0:
        return "insufficient_data"
    if improving_signals > 0 and declining_signals > 0:
        return "mixed"
    if improving_signals > 0 and declining_signals <= 0:
        return "improved"
    if declining_signals > 0 and improving_signals <= 0:
        return "declined"
    return "no_clear_change"


def _migration_outcome_anchor_label(anchor_type: str | None) -> str:
    normalized = str(anchor_type or "").strip().lower()
    if normalized == "migration_deployed":
        return "deploy"
    if normalized == "migration_published":
        return "publish"
    return "migration"


def _build_migration_ga4_outcome_operator_hint(
    *,
    status: str,
    anchor_type: str | None,
    outcome_direction: str | None = None,
) -> str:
    anchor_label = _migration_outcome_anchor_label(anchor_type)
    if status == "not_configured":
        return "GA4 outcome snapshot unavailable: add a GA4 property ID for this site."
    if status == "missing_scope":
        return "GA4 outcome snapshot unavailable: reconnect Google with Analytics readonly access."
    if status == "permission_denied":
        return "GA4 outcome snapshot unavailable: verify GA4 property Viewer access for the connected identity."
    if status == "pending_after_window":
        return f"Not enough time has passed to compare after-{anchor_label} traffic yet."
    if status == "insufficient_data":
        return "Not enough GA4 data is available to compare before and after this migration event."
    if status == "unavailable":
        return "GA4 outcome snapshot is temporarily unavailable for this site."
    if status != "available":
        return "GA4 outcome snapshot is unavailable for this migration event."

    if outcome_direction == "improved":
        return (
            f"Observed after {anchor_label}: traffic is higher in the post-event window. "
            "Keep monitoring future refresh cycles."
        )
    if outcome_direction == "declined":
        return (
            f"Observed after {anchor_label}: traffic is lower in the post-event window. "
            "Review related changes and monitor another refresh cycle."
        )
    if outcome_direction == "mixed":
        return f"Observed after {anchor_label}: metrics moved in different directions. Continue monitoring."
    if outcome_direction == "no_clear_change":
        return f"Observed after {anchor_label}: no clear movement is visible yet."
    return "Not enough GA4 data is available to compare before and after this migration event."


def _build_migration_ga4_outcome_snapshot(
    *,
    seo_analytics_service: SEOAnalyticsService,
    site_analytics_summary: object,
    site_domain: str | None,
    ga4_property_id: str | None,
    anchor: tuple[str, datetime] | None,
) -> SEORecommendationGA4OutcomeSnapshotRead | None:
    if anchor is None:
        return None
    anchor_type, anchor_timestamp = anchor

    unavailable_status = _derive_ga4_outcome_unavailable_status(
        site_analytics_summary=site_analytics_summary,
        ga4_property_id=ga4_property_id,
    )
    if unavailable_status is not None:
        return SEORecommendationGA4OutcomeSnapshotRead(
            status=unavailable_status,
            source="site_scoped_ga4",
            anchor_type=anchor_type,
            anchor_timestamp=anchor_timestamp,
            outcome_direction="insufficient_data" if unavailable_status == "insufficient_data" else None,
            operator_hint=_build_migration_ga4_outcome_operator_hint(
                status=unavailable_status,
                anchor_type=anchor_type,
            ),
        )

    min_after_days = max(1, min(int(seo_analytics_service.settings.ga4_outcome_min_after_days), 30))
    if datetime.now(timezone.utc) < (anchor_timestamp + timedelta(days=min_after_days)):
        return SEORecommendationGA4OutcomeSnapshotRead(
            status="pending_after_window",
            source="site_scoped_ga4",
            anchor_type=anchor_type,
            anchor_timestamp=anchor_timestamp,
            operator_hint=_build_migration_ga4_outcome_operator_hint(
                status="pending_after_window",
                anchor_type=anchor_type,
            ),
        )

    comparison = seo_analytics_service.build_recommendation_outcome_comparison(
        site_domain=site_domain,
        anchor_timestamp=anchor_timestamp,
        page_path=None,
        ga4_property_id=ga4_property_id,
    )
    if comparison is None:
        return SEORecommendationGA4OutcomeSnapshotRead(
            status="insufficient_data",
            source="site_scoped_ga4",
            anchor_type=anchor_type,
            anchor_timestamp=anchor_timestamp,
            outcome_direction="insufficient_data",
            operator_hint=_build_migration_ga4_outcome_operator_hint(
                status="insufficient_data",
                anchor_type=anchor_type,
            ),
        )

    before_window = SEORecommendationGA4OutcomeWindowRead(
        start_date=comparison.before_window.start_date,
        end_date=comparison.before_window.end_date,
        sessions=max(0, int(comparison.before_window.sessions)),
        users=max(0, int(comparison.before_window.users)),
        engagement_rate=comparison.before_window.engagement_rate,
        organic_sessions=comparison.before_window.organic_search_sessions,
    )
    after_window = SEORecommendationGA4OutcomeWindowRead(
        start_date=comparison.after_window.start_date,
        end_date=comparison.after_window.end_date,
        sessions=max(0, int(comparison.after_window.sessions)),
        users=max(0, int(comparison.after_window.users)),
        engagement_rate=comparison.after_window.engagement_rate,
        organic_sessions=comparison.after_window.organic_search_sessions,
    )
    sessions_delta = int(after_window.sessions) - int(before_window.sessions)
    sessions_delta_percent = _calculate_ga4_outcome_delta_percent(
        current=after_window.sessions,
        previous=before_window.sessions,
    )
    engagement_rate_delta_points = None
    if before_window.engagement_rate is not None and after_window.engagement_rate is not None:
        engagement_rate_delta_points = round(after_window.engagement_rate - before_window.engagement_rate, 4)
    organic_sessions_delta_percent = None
    if before_window.organic_sessions is not None and after_window.organic_sessions is not None:
        organic_sessions_delta_percent = _calculate_ga4_outcome_delta_percent(
            current=after_window.organic_sessions,
            previous=before_window.organic_sessions,
        )
    outcome_direction = _derive_ga4_outcome_direction(
        sessions_delta_percent=sessions_delta_percent,
        engagement_rate_delta_points=engagement_rate_delta_points,
        organic_sessions_delta_percent=organic_sessions_delta_percent,
    )
    return SEORecommendationGA4OutcomeSnapshotRead(
        status="available",
        source="site_scoped_ga4",
        anchor_type=anchor_type,
        anchor_timestamp=anchor_timestamp,
        before_window=before_window,
        after_window=after_window,
        delta=SEORecommendationGA4OutcomeDeltaRead(
            sessions_delta=sessions_delta,
            sessions_delta_percent=sessions_delta_percent,
            engagement_rate_delta_points=engagement_rate_delta_points,
            organic_sessions_delta_percent=organic_sessions_delta_percent,
        ),
        outcome_direction=outcome_direction,
        operator_hint=_build_migration_ga4_outcome_operator_hint(
            status="available",
            anchor_type=anchor_type,
            outcome_direction=outcome_direction,
        ),
    )


def _to_workspace_read(workspace) -> SEOMigrationWorkspaceRead:  # noqa: ANN001
    return SEOMigrationWorkspaceRead.model_validate(workspace)


def _sanitize_generated_files_for_read(
    generated_files: object,
) -> list[dict[str, object]] | None:
    if not isinstance(generated_files, list):
        return None
    sanitized: list[dict[str, object]] = []
    for item in generated_files[:120]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        payload: dict[str, object] = {
            "path": path,
            "media_type": str(item.get("media_type") or "text/plain").strip().lower(),
        }
        size_bytes_raw = item.get("size_bytes")
        try:
            size_bytes_value = int(size_bytes_raw) if size_bytes_raw is not None else None
        except (TypeError, ValueError):
            size_bytes_value = None
        if isinstance(size_bytes_value, int) and size_bytes_value >= 0:
            payload["size_bytes"] = size_bytes_value
        content = item.get("content")
        if isinstance(content, str):
            payload["content"] = content
        sanitized.append(payload)
    return sanitized


def _to_artifact_read(artifact) -> SEOMigrationArtifactVersionRead:  # noqa: ANN001
    artifact_read = SEOMigrationArtifactVersionRead.model_validate(artifact)
    artifact_read.generated_files_json = _sanitize_generated_files_for_read(artifact.generated_files_json)
    return artifact_read


def _validation_error_detail(exc: SEOMigrationValidationError) -> str | dict[str, object]:
    detail = exc.to_error_detail()
    if isinstance(detail, dict):
        reason_code = _normalize_draft_generation_reason_code(detail.get("reason_code") or detail.get("error_code"))
        if reason_code is not None:
            detail["reason_code"] = reason_code
            if not detail.get("error_code"):
                detail["error_code"] = reason_code
    if isinstance(detail, dict) and (
        detail.get("failure_category")
        or detail.get("failure_reason")
        or detail.get("error_code")
        or detail.get("reason_code")
        or detail.get("retryable") is not None
    ):
        return detail
    return str(exc)


def _normalize_draft_generation_reason_code(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized in {
        _DRAFT_REASON_CODE_APP_AUTH_REQUIRED,
        _DRAFT_REASON_CODE_SESSION_EXPIRED,
        _DRAFT_REASON_CODE_GOOGLE_RECONNECT_REQUIRED,
        _DRAFT_REASON_CODE_GOOGLE_INTEGRATION_UNAVAILABLE,
        _DRAFT_REASON_CODE_CONTEXT_UNAVAILABLE,
        _DRAFT_REASON_CODE_PREFLIGHT_TOO_LARGE,
    }:
        return normalized
    if normalized in {
        "reconnect_required",
        "google_refresh_required",
        "google_token_expired",
        "google_token_revoked",
        "google_token_invalid",
        "google_scope_missing",
        "google_consent_expired",
        "google_auth_required",
    }:
        return _DRAFT_REASON_CODE_GOOGLE_RECONNECT_REQUIRED
    if normalized in {
        "google_status_unavailable",
        "google_integration_status_unavailable",
        "google_integration_read_failed",
        "google_connection_unavailable",
    }:
        return _DRAFT_REASON_CODE_GOOGLE_INTEGRATION_UNAVAILABLE
    if normalized in {"context_unavailable", "context_assembly_failed"}:
        return _DRAFT_REASON_CODE_CONTEXT_UNAVAILABLE
    return None


def _draft_generation_error_detail(exc: SEOMigrationValidationError) -> str | dict[str, object]:
    raw_detail = _validation_error_detail(exc)
    detail = raw_detail if isinstance(raw_detail, dict) else {"message": str(raw_detail or exc)}
    detail = {**detail}
    message = str(detail.get("message") or str(exc) or "Draft generation failed.").strip()
    raw_reason = str(detail.get("reason_code") or detail.get("error_code") or "").strip().lower()
    normalized_reason = _normalize_draft_generation_reason_code(raw_reason) or raw_reason or _DRAFT_REASON_CODE_DEFAULT
    failure_category = str(detail.get("failure_category") or "").strip().lower() or None
    retryable_raw = detail.get("retryable")
    retryable: bool
    if isinstance(retryable_raw, bool):
        retryable = retryable_raw
    else:
        retryable = normalized_reason not in {
            _DRAFT_REASON_CODE_APP_AUTH_REQUIRED,
            _DRAFT_REASON_CODE_SESSION_EXPIRED,
            _DRAFT_REASON_CODE_GOOGLE_RECONNECT_REQUIRED,
            "source_site_ingest_required",
            "operator_requirements_required",
            "enriched_content_required",
            "provider_config_missing",
            "unsupported_model_configuration",
            "unsupported_request_shape",
            "unsupported_endpoint_mode",
            "tools_required_but_unavailable",
            "degraded_mode_not_allowed",
        }
        if failure_category == "config_missing":
            retryable = False
    operator_action, reconnect_target = _draft_generation_operator_action(
        reason_code=normalized_reason,
        retryable=retryable,
    )

    payload: dict[str, object] = {
        "message": message,
        "reason_code": normalized_reason,
        "error_code": normalized_reason,
        "retryable": retryable,
        "operator_action": operator_action,
    }
    if reconnect_target is not None:
        payload["reconnect_target"] = reconnect_target

    diagnostic_context: dict[str, object] = {}
    for key in (
        "failure_category",
        "failure_reason",
        "correlation_id",
        "workspace_id",
        "artifact_version_id",
        "provider_name",
        "model_name",
        "prompt_version",
        "timeout_seconds",
        "timeout_source",
    ):
        value = detail.get(key)
        if value is None:
            continue
        if key == "timeout_seconds":
            if isinstance(value, int) and value >= 1:
                diagnostic_context[key] = int(value)
            continue
        if isinstance(value, bool):
            diagnostic_context[key] = value
            continue
        normalized_value = str(value).strip()
        if normalized_value:
            diagnostic_context[key] = normalized_value
    if diagnostic_context:
        payload["diagnostic_context"] = diagnostic_context

    # Preserve existing top-level diagnostic fields consumed by UI callers.
    for key in (
        "failure_category",
        "failure_reason",
        "correlation_id",
        "workspace_id",
        "artifact_version_id",
        "provider_name",
        "model_name",
        "prompt_version",
        "timeout_seconds",
        "timeout_source",
    ):
        if key in diagnostic_context:
            payload[key] = diagnostic_context[key]

    return payload


def _draft_generation_operator_action(*, reason_code: str, retryable: bool) -> tuple[str, str | None]:
    normalized_reason = str(reason_code or "").strip().lower()
    if normalized_reason in {_DRAFT_REASON_CODE_APP_AUTH_REQUIRED, _DRAFT_REASON_CODE_SESSION_EXPIRED}:
        return ("Sign back into MBSRN and retry draft generation.", "mbsrn_session")
    if normalized_reason == _DRAFT_REASON_CODE_GOOGLE_RECONNECT_REQUIRED:
        return (
            "Reconnect Google Search Console / Analytics, then retry draft generation.",
            "google_search_console_analytics",
        )
    if normalized_reason == _DRAFT_REASON_CODE_GOOGLE_INTEGRATION_UNAVAILABLE:
        return (
            "Retry shortly. If Google integration state remains unavailable, reconnect Google and retry.",
            "google_search_console_analytics",
        )
    if normalized_reason in {
        "source_site_ingest_required",
        "operator_requirements_required",
        "enriched_content_required",
    }:
        return ("Update workspace inputs to resolve draft readiness blockers, then retry generation.", None)
    if normalized_reason in {
        "provider_config_missing",
        "unsupported_model_configuration",
        "unsupported_request_shape",
        "unsupported_endpoint_mode",
        "tools_required_but_unavailable",
        "degraded_mode_not_allowed",
    }:
        return ("Review AI provider/model configuration for migration draft compatibility.", None)
    if normalized_reason == _DRAFT_REASON_CODE_CONTEXT_UNAVAILABLE:
        return ("Retry draft generation. If this persists, contact support with the correlation reference.", None)
    if normalized_reason == _DRAFT_REASON_CODE_PREFLIGHT_TOO_LARGE:
        return (
            "Generation was blocked before provider call by migration preflight safety limits. "
            "Reduce requirements or selected context, or ask Admin to increase bounded migration AI budget.",
            None,
        )
    if retryable:
        return ("Retry draft generation. If this repeats, review diagnostics and contact support.", None)
    return ("Resolve the blocking draft-generation issue and retry.", None)


@router.put("/sites/{site_id}/migration/workspace", response_model=SEOMigrationWorkspaceRead)
def upsert_seo_migration_workspace(
    business_id: str,
    site_id: str,
    payload: SEOMigrationWorkspaceCreateOrUpdateRequest | None = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    normalized_payload = payload or SEOMigrationWorkspaceCreateOrUpdateRequest()
    try:
        workspace = migration_service.create_or_update_workspace(
            business_id=scoped_business_id,
            site_id=site_id,
            source_url=normalized_payload.source_url,
            operator_requirements=(
                normalized_payload.operator_requirements.model_dump(mode="json")
                if normalized_payload.operator_requirements
                else None
            ),
            enriched_content_notes=(
                normalized_payload.enriched_content_notes.model_dump(mode="json")
                if normalized_payload.enriched_content_notes
                else None
            ),
            publish_config=(
                normalized_payload.publish_config.model_dump(mode="json") if normalized_payload.publish_config else None
            ),
            deploy_config=(
                normalized_payload.deploy_config.model_dump(mode="json") if normalized_payload.deploy_config else None
            ),
            deploy_config_field_names=(
                set(normalized_payload.deploy_config.model_fields_set) if normalized_payload.deploy_config else None
            ),
            analytics_config=(
                normalized_payload.analytics_config.model_dump(mode="json")
                if normalized_payload.analytics_config
                else None
            ),
            principal_id=tenant_context.principal_id,
            principal_role=tenant_context.principal_role,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.get("/sites/{site_id}/migration/workspace", response_model=SEOMigrationWorkspaceRead)
def get_seo_migration_workspace(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.get_workspace(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.post("/sites/{site_id}/migration/source-ingest", response_model=SEOMigrationWorkspaceRead)
def ingest_seo_migration_source(
    business_id: str,
    site_id: str,
    payload: SEOMigrationSourceIngestRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.ingest_source_snapshot(
            business_id=scoped_business_id,
            site_id=site_id,
            source_url=payload.source_url,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.get("/sites/{site_id}/migration/media/assets", response_model=SEOMigrationMediaAssetListRead)
def list_seo_migration_media_assets(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationMediaAssetListRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        payload = migration_service.list_workspace_media_assets(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    source_discovered = payload.get("source_discovered") if isinstance(payload, dict) else []
    operator_uploaded = payload.get("operator_uploaded") if isinstance(payload, dict) else []
    selected_assets = payload.get("selected_assets") if isinstance(payload, dict) else []
    return SEOMigrationMediaAssetListRead(
        source_discovered=[SEOMigrationMediaAssetRead.model_validate(item) for item in source_discovered or []],
        operator_uploaded=[SEOMigrationMediaAssetRead.model_validate(item) for item in operator_uploaded or []],
        selected_assets=[SEOMigrationMediaAssetRead.model_validate(item) for item in selected_assets or []],
        source_discovered_count=int(payload.get("source_discovered_count") or 0) if isinstance(payload, dict) else 0,
        pages_scanned_count=int(payload.get("pages_scanned_count") or 0) if isinstance(payload, dict) else 0,
        source_imported_count=int(payload.get("source_imported_count") or 0) if isinstance(payload, dict) else 0,
        operator_uploaded_count=int(payload.get("operator_uploaded_count") or 0) if isinstance(payload, dict) else 0,
        selected_assets_count=int(payload.get("selected_assets_count") or 0) if isinstance(payload, dict) else 0,
        media_asset_categories=list(payload.get("media_asset_categories") or []) if isinstance(payload, dict) else [],
        selected_assets_trimmed=bool(payload.get("selected_assets_trimmed")) if isinstance(payload, dict) else False,
        diagnostics=list(payload.get("diagnostics") or []) if isinstance(payload, dict) else [],
    )


@router.get("/sites/{site_id}/migration/media/assets/{asset_id}/preview")
def preview_seo_migration_media_asset(
    business_id: str,
    site_id: str,
    asset_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> Response:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        content_type, payload = migration_service.preview_workspace_media_asset(
            business_id=scoped_business_id,
            site_id=site_id,
            asset_id=asset_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return Response(
        content=payload,
        media_type=content_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/sites/{site_id}/migration/media/upload",
    response_model=SEOMigrationMediaAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_seo_migration_media_asset(
    business_id: str,
    site_id: str,
    request: Request,
    filename: str = Query(..., min_length=1, max_length=160),
    selected_for_draft: bool = Query(default=False),
    category: str | None = Query(default=None),
    alt_text: str | None = Query(default=None),
    description: str | None = Query(default=None),
    usage_note: str | None = Query(default=None),
    page_assignment: str | None = Query(default=None),
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationMediaAssetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    payload = await request.body()
    content_type = request.headers.get("content-type")
    try:
        media_asset = migration_service.upload_workspace_media_asset(
            business_id=scoped_business_id,
            site_id=site_id,
            filename=filename,
            content_type=content_type,
            payload=payload,
            selected_for_draft=bool(selected_for_draft),
            category=category,
            alt_text=alt_text,
            description=description,
            usage_note=usage_note,
            page_assignment=page_assignment,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationMediaAssetRead.model_validate(media_asset)


@router.patch("/sites/{site_id}/migration/media/assets/{asset_id}", response_model=SEOMigrationMediaAssetRead)
def update_seo_migration_media_asset(
    business_id: str,
    site_id: str,
    asset_id: str,
    payload: SEOMigrationMediaAssetUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationMediaAssetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        media_asset = migration_service.update_workspace_media_asset(
            business_id=scoped_business_id,
            site_id=site_id,
            asset_id=asset_id,
            selected_for_draft=payload.selected_for_draft,
            apply_suggested_metadata=bool(payload.apply_suggested_metadata),
            category=payload.category,
            alt_text=payload.alt_text,
            description=payload.description,
            usage_note=payload.usage_note,
            page_assignment=payload.page_assignment,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationMediaAssetRead.model_validate(media_asset)


@router.post(
    "/sites/{site_id}/migration/media/assets/{asset_id}/lifecycle",
    response_model=SEOMigrationMediaAssetLifecycleActionRead,
)
def update_seo_migration_media_asset_lifecycle(
    business_id: str,
    site_id: str,
    asset_id: str,
    payload: SEOMigrationMediaAssetLifecycleRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationMediaAssetLifecycleActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        result = migration_service.update_workspace_media_asset_lifecycle(
            business_id=scoped_business_id,
            site_id=site_id,
            asset_id=asset_id,
            action=payload.action,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationMediaAssetLifecycleActionRead.model_validate(result)


@router.post(
    "/sites/{site_id}/migration/media/assets/{asset_id}/suggest-metadata", response_model=SEOMigrationMediaAssetRead
)
def suggest_seo_migration_media_asset_metadata(
    business_id: str,
    site_id: str,
    asset_id: str,
    force_refresh: bool = Query(default=False),
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationMediaAssetRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        media_asset = migration_service.suggest_media_asset_metadata(
            business_id=scoped_business_id,
            site_id=site_id,
            asset_id=asset_id,
            force_refresh=bool(force_refresh),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationMediaAssetRead.model_validate(media_asset)


@router.post(
    "/sites/{site_id}/migration/media/assets/suggest-metadata", response_model=SEOMigrationMediaSuggestionBatchRead
)
def suggest_seo_migration_media_assets_metadata_batch(
    business_id: str,
    site_id: str,
    payload: SEOMigrationMediaSuggestionBatchRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationMediaSuggestionBatchRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        batch_result = migration_service.suggest_media_assets_metadata_batch(
            business_id=scoped_business_id,
            site_id=site_id,
            asset_ids=payload.asset_ids,
            force_refresh=bool(payload.force_refresh),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationMediaSuggestionBatchRead.model_validate(batch_result)


@router.post(
    "/sites/{site_id}/migration/media/discovered/import",
    response_model=SEOMigrationDiscoveredMediaImportRead,
)
def import_seo_migration_discovered_media_assets(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDiscoveredMediaImportRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationDiscoveredMediaImportRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        import_result = migration_service.import_discovered_media_assets(
            business_id=scoped_business_id,
            site_id=site_id,
            discovered_image_ids=payload.discovered_image_ids,
            normalized_urls=payload.normalized_urls,
            selected_for_draft=payload.selected_for_draft,
            allow_quality_override=bool(payload.allow_quality_override),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationDiscoveredMediaImportRead.model_validate(import_result)


@router.put("/sites/{site_id}/migration/operator-requirements", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_operator_requirements(
    business_id: str,
    site_id: str,
    payload: SEOMigrationRequirementsUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_operator_requirements(
            business_id=scoped_business_id,
            site_id=site_id,
            operator_requirements=payload.operator_requirements.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.post(
    "/sites/{site_id}/migration/requirements/suggest",
    response_model=SEOMigrationRequirementsSuggestionRead,
)
def suggest_seo_migration_requirements_field(
    business_id: str,
    site_id: str,
    payload: SEOMigrationRequirementsSuggestionRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationRequirementsSuggestionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        suggestion_payload = migration_service.suggest_operator_requirement_field(
            business_id=scoped_business_id,
            site_id=site_id,
            field=payload.field,
            current_value=payload.current_value,
            force_refresh=payload.force_refresh,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationRequirementsSuggestionRead.model_validate(suggestion_payload)


@router.put("/sites/{site_id}/migration/enriched-content", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_enriched_content_notes(
    business_id: str,
    site_id: str,
    payload: SEOMigrationEnrichedContentUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_enriched_content_notes(
            business_id=scoped_business_id,
            site_id=site_id,
            enriched_content_notes=payload.enriched_content_notes.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/publish-config", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_publish_config(
    business_id: str,
    site_id: str,
    payload: SEOMigrationPublishConfigUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_publish_config(
            business_id=scoped_business_id,
            site_id=site_id,
            publish_config=payload.publish_config.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/deploy-config", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_deploy_config(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDeployConfigUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_deploy_config(
            business_id=scoped_business_id,
            site_id=site_id,
            deploy_config=payload.deploy_config.model_dump(mode="json"),
            deploy_config_field_names=set(payload.deploy_config.model_fields_set),
            principal_id=tenant_context.principal_id,
            principal_role=tenant_context.principal_role,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.put("/sites/{site_id}/migration/analytics-config", response_model=SEOMigrationWorkspaceRead)
def update_seo_migration_analytics_config(
    business_id: str,
    site_id: str,
    payload: SEOMigrationAnalyticsConfigUpdateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationWorkspaceRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        workspace = migration_service.update_analytics_config(
            business_id=scoped_business_id,
            site_id=site_id,
            analytics_config=payload.analytics_config.model_dump(mode="json"),
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_workspace_read(workspace)


@router.get("/sites/{site_id}/migration/summary", response_model=SEOMigrationWorkspaceSummaryRead)
def get_seo_migration_workspace_summary(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
    seo_site_service: SEOSiteService = Depends(get_seo_site_service),
    seo_analytics_service: SEOAnalyticsService = Depends(get_seo_analytics_service),
) -> SEOMigrationWorkspaceSummaryRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        summary = migration_service.get_workspace_summary(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        site = seo_site_service.get_site(business_id=scoped_business_id, site_id=site_id)
    except SEOSiteNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    site_domain = (site.normalized_domain or site.base_url or "").strip() or None
    site_analytics_summary = seo_analytics_service.get_site_summary(
        business_id=scoped_business_id,
        site_id=site_id,
        site_domain=site_domain,
        ga4_property_id=site.ga4_property_id,
        enforce_site_ga4_property=True,
    )
    ga4_outcome_snapshot = _build_migration_ga4_outcome_snapshot(
        seo_analytics_service=seo_analytics_service,
        site_analytics_summary=site_analytics_summary,
        site_domain=site_domain,
        ga4_property_id=site.ga4_property_id,
        anchor=_derive_migration_ga4_outcome_anchor(summary.workspace),
    )
    source_snapshot = (
        SEOMigrationSourceSnapshotRead.model_validate(summary.source_snapshot) if summary.source_snapshot else None
    )
    latest_artifact = _to_artifact_read(summary.latest_artifact) if summary.latest_artifact else None
    return SEOMigrationWorkspaceSummaryRead(
        workspace=_to_workspace_read(summary.workspace),
        source_snapshot=source_snapshot,
        context_summary=summary.context_summary,
        latest_artifact=latest_artifact,
        publish_readiness=summary.publish_readiness,
        deploy_readiness=summary.deploy_readiness,
        publish_history=summary.publish_history,
        deploy_history=summary.deploy_history,
        ga4_outcome_snapshot=ga4_outcome_snapshot,
        draft_only_notice=_DRAFT_ONLY_NOTICE,
    )


@router.get("/sites/{site_id}/migration/prompt-preview", response_model=SEOMigrationPromptPreviewRead)
def get_seo_migration_prompt_preview(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationPromptPreviewRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        preview = migration_service.get_prompt_preview(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationPromptPreviewRead(
        provider_name=preview.provider_name,
        model_name=preview.model_name,
        prompt_version=preview.prompt_version,
        context_json=preview.context_json,
        system_prompt=preview.system_prompt,
        user_prompt=preview.user_prompt,
    )


@router.get("/sites/{site_id}/migration/draft-readiness", response_model=SEOMigrationDraftReadinessRead)
def get_seo_migration_draft_readiness(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationDraftReadinessRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        readiness = migration_service.get_draft_generation_readiness(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationDraftReadinessRead.model_validate(readiness)


@router.post(
    "/sites/{site_id}/migration/generate-draft-artifacts",
    response_model=SEOMigrationArtifactVersionRead,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": SEOMigrationDraftGenerationErrorEnvelopeRead}},
)
def generate_seo_migration_draft_artifacts(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDraftGenerateRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionRead:
    del payload.force_new_version
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        artifact = migration_service.generate_draft_artifacts(
            business_id=scoped_business_id,
            site_id=site_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=_draft_generation_error_detail(exc),
        ) from exc
    return _to_artifact_read(artifact)


@router.get("/sites/{site_id}/migration/artifact-versions", response_model=SEOMigrationArtifactVersionListResponse)
def list_seo_migration_artifact_versions(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionListResponse:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        versions = migration_service.list_artifact_versions(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationArtifactVersionListResponse(
        items=[_to_artifact_read(item) for item in versions],
        total=len(versions),
    )


@router.get(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}",
    response_model=SEOMigrationArtifactVersionRead,
)
def get_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        artifact = migration_service.get_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_artifact_read(artifact)


@router.post(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/approve",
    response_model=SEOMigrationArtifactVersionRead,
)
def approve_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    payload: SEOMigrationArtifactApproveRequest | None = None,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactVersionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    normalized_payload = payload or SEOMigrationArtifactApproveRequest()
    try:
        artifact = migration_service.approve_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
            approval_notes=normalized_payload.approval_notes,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return _to_artifact_read(artifact)


@router.delete(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}",
    response_model=SEOMigrationArtifactDeleteActionRead,
)
def delete_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactDeleteActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.delete_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationArtifactDeleteActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        deleted_artifact_version_id=action_result.deleted_artifact_version_id,
        deleted_artifact_version_number=action_result.deleted_artifact_version_number,
    )


@router.post("/sites/{site_id}/migration/publish", response_model=SEOMigrationPublishActionRead)
def publish_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    payload: SEOMigrationPublishRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationPublishActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.publish_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=payload.artifact_version_id,
            dry_run=payload.dry_run,
            commit_message=payload.commit_message,
            analytics_measurement_id=payload.analytics_measurement_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationPublishActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        artifact=_to_artifact_read(action_result.artifact),
        readiness=action_result.readiness,
        result=action_result.result,
    )


@router.post(
    "/sites/{site_id}/migration/publish/adopt-repository", response_model=SEOMigrationRepositoryAdoptActionRead
)
def adopt_seo_migration_publish_repository(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationRepositoryAdoptActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.adopt_publish_repository(
            business_id=scoped_business_id,
            site_id=site_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=_validation_error_detail(exc)
        ) from exc
    return SEOMigrationRepositoryAdoptActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        readiness=action_result.readiness,
        result=action_result.result,
    )


@router.post("/sites/{site_id}/migration/deploy", response_model=SEOMigrationDeployActionRead)
def deploy_seo_migration_artifact_version(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDeployRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationDeployActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.deploy_artifact_version(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=payload.artifact_version_id,
            dry_run=payload.dry_run,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationDeployActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        artifact=_to_artifact_read(action_result.artifact),
        readiness=action_result.readiness,
        result=action_result.result,
    )


@router.post("/sites/{site_id}/migration/deploy/refresh-status", response_model=SEOMigrationDeployActionRead)
def refresh_seo_migration_deploy_status(
    business_id: str,
    site_id: str,
    payload: SEOMigrationDeployStatusRefreshRequest,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationDeployActionRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        action_result = migration_service.refresh_deploy_run_status(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=payload.artifact_version_id,
            principal_id=tenant_context.principal_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationDeployActionRead(
        workspace=_to_workspace_read(action_result.workspace),
        artifact=_to_artifact_read(action_result.artifact),
        readiness=action_result.readiness,
        result=action_result.result,
    )


@router.get("/sites/{site_id}/migration/publish-history", response_model=SEOMigrationHistoryListRead)
def list_seo_migration_publish_history(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationHistoryListRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        history = migration_service.list_publish_history(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationHistoryListRead(items=history, total=len(history))


@router.get("/sites/{site_id}/migration/deploy-history", response_model=SEOMigrationHistoryListRead)
def list_seo_migration_deploy_history(
    business_id: str,
    site_id: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationHistoryListRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        history = migration_service.list_deploy_history(
            business_id=scoped_business_id,
            site_id=site_id,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return SEOMigrationHistoryListRead(items=history, total=len(history))


@router.get(
    "/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/file-preview",
    response_model=SEOMigrationArtifactFilePreviewRead,
)
def preview_seo_migration_artifact_file(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    path: str = Query(min_length=1, max_length=160),
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> SEOMigrationArtifactFilePreviewRead:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        media_type, content = migration_service.preview_artifact_file(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
            path=path,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return SEOMigrationArtifactFilePreviewRead(
        artifact_version_id=artifact_version_id,
        path=path,
        media_type=media_type,
        content=content,
    )


@router.get("/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/files/{file_path:path}")
def stream_seo_migration_artifact_file(
    business_id: str,
    site_id: str,
    artifact_version_id: str,
    file_path: str,
    tenant_context: TenantContext = Depends(get_tenant_context),
    migration_service: SEOMigrationService = Depends(get_seo_migration_service),
) -> Response:
    scoped_business_id = resolve_tenant_business_id(
        tenant_context=tenant_context,
        requested_business_id=business_id,
    )
    try:
        media_type, payload = migration_service.read_artifact_file_content(
            business_id=scoped_business_id,
            site_id=site_id,
            artifact_version_id=artifact_version_id,
            path=file_path,
        )
    except SEOMigrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SEOMigrationValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type=media_type,
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )
