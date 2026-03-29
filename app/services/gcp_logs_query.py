from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from typing import Any

from app.core.time import utc_now
from app.integrations.google_cloud_logging import (
    GoogleCloudLoggingADCError,
    GoogleCloudLoggingAPIError,
    GoogleCloudLoggingClient,
)
from app.schemas.admin_logs import GCPLogEntryRead, GCPLogsQueryRequest, GCPLogsQueryResponse

_DEFAULT_PAGE_SIZE = 25
_DEFAULT_ORDER_BY = "timestamp desc"
_DEFAULT_TIME_WINDOW_HOURS = 24
_MAX_LABEL_ITEMS = 12
_MAX_LABEL_KEY_CHARS = 80
_MAX_LABEL_VALUE_CHARS = 120
_MAX_LOG_NAME_CHARS = 256
_MAX_RESOURCE_TYPE_CHARS = 128
_MAX_SEVERITY_CHARS = 32
_MAX_TIMESTAMP_CHARS = 64
_MAX_INSERT_ID_CHARS = 128
_MAX_PAYLOAD_SUMMARY_CHARS = 900
_MAX_PAGE_TOKEN_CHARS = 2048
_PROJECT_CONFIG_ERROR_MESSAGE = "Cloud Logging query is not configured: missing GCP project id. " "Set GCP_PROJECT_ID."
_ADC_CONFIG_ERROR_MESSAGE = (
    "Cloud Logging query is not configured: runtime Application Default Credentials are unavailable. "
    "Verify Workload Identity and deployed service account attachment for this environment."
)
_ADC_DEPENDENCY_CONFIG_ERROR_MESSAGE = (
    "Cloud Logging query runtime is misconfigured: google-auth transport dependency is unavailable in the API image."
)
_ADC_REFRESH_CONFIG_ERROR_MESSAGE = (
    "Cloud Logging query could not refresh runtime ADC access token. "
    "Verify Workload Identity token exchange for the deployed service account."
)
_PROJECT_SCOPE_CONFIG_ERROR_MESSAGE = (
    "Cloud Logging query is not configured: GCP_PROJECT_ID is invalid for Cloud Logging resource scope. "
    "Verify GCP_PROJECT_ID."
)
_RUNTIME_POD_NAME = (os.getenv("HOSTNAME") or "").strip()

logger = logging.getLogger(__name__)


class GCPLogsQueryValidationError(ValueError):
    pass


class GCPLogsQueryConfigurationError(ValueError):
    pass


class GCPLogsQueryPermissionError(ValueError):
    pass


class GCPLogsQueryTimeoutError(ValueError):
    pass


class GCPLogsQueryProviderError(ValueError):
    pass


class GCPLogsQueryService:
    def __init__(
        self,
        *,
        client: GoogleCloudLoggingClient,
        project_id: str | None,
        default_page_size: int = _DEFAULT_PAGE_SIZE,
        order_by: str = _DEFAULT_ORDER_BY,
    ) -> None:
        self.client = client
        self.project_id = (project_id or "").strip()
        self.default_page_size = default_page_size
        self.order_by = order_by

    def query_logs(self, *, payload: GCPLogsQueryRequest) -> GCPLogsQueryResponse:
        if not self.project_id:
            logger.warning("gcp_logs_query_failed classification=configuration_error reason=missing_project_id")
            raise GCPLogsQueryConfigurationError(_PROJECT_CONFIG_ERROR_MESSAGE)
        effective_page_size = int(payload.page_size or self.default_page_size)
        if effective_page_size <= 0:
            raise GCPLogsQueryValidationError("page_size must be greater than zero.")
        effective_filter, default_time_range_applied = self._build_effective_filter(payload)
        logger.info(
            (
                "gcp_logs_query_request_start project_id=%s page_size=%s has_page_token=%s "
                "filter_chars=%s default_time_range_applied=%s runtime_pod=%s"
            ),
            self.project_id,
            effective_page_size,
            bool(payload.page_token),
            len(effective_filter),
            default_time_range_applied,
            _RUNTIME_POD_NAME,
        )

        try:
            response_payload = self.client.list_entries(
                project_id=self.project_id,
                filter_text=effective_filter,
                page_size=effective_page_size,
                page_token=payload.page_token,
                order_by=self.order_by,
            )
        except GoogleCloudLoggingADCError as exc:
            adc_phase = str(getattr(exc, "phase", "adc_resolution_failure") or "adc_resolution_failure")
            adc_error_class = str(getattr(exc, "cause_class", "") or exc.__class__.__name__)
            logger.warning(
                "gcp_logs_query_failed classification=adc_unavailable project_id=%s adc_phase=%s error_class=%s error=%s runtime_pod=%s",
                self.project_id,
                adc_phase,
                adc_error_class,
                _summarize_error_message(exc),
                _RUNTIME_POD_NAME,
            )
            if adc_phase == "dependency_missing":
                raise GCPLogsQueryConfigurationError(_ADC_DEPENDENCY_CONFIG_ERROR_MESSAGE) from exc
            if adc_phase == "token_refresh_failure":
                raise GCPLogsQueryConfigurationError(_ADC_REFRESH_CONFIG_ERROR_MESSAGE) from exc
            raise GCPLogsQueryConfigurationError(_ADC_CONFIG_ERROR_MESSAGE) from exc
        except GoogleCloudLoggingAPIError as exc:
            if exc.is_project_configuration_error:
                logger.warning(
                    "gcp_logs_query_failed classification=project_configuration_error project_id=%s status_code=%s error_status=%s error_class=%s runtime_pod=%s",
                    self.project_id,
                    exc.status_code if exc.status_code is not None else "",
                    exc.error_status or "",
                    exc.__class__.__name__,
                    _RUNTIME_POD_NAME,
                )
                raise GCPLogsQueryConfigurationError(_PROJECT_SCOPE_CONFIG_ERROR_MESSAGE) from exc
            if exc.is_invalid_request:
                logger.warning(
                    "gcp_logs_query_failed classification=invalid_request project_id=%s status_code=%s error_status=%s error_class=%s runtime_pod=%s",
                    self.project_id,
                    exc.status_code if exc.status_code is not None else "",
                    exc.error_status or "",
                    exc.__class__.__name__,
                    _RUNTIME_POD_NAME,
                )
                raise GCPLogsQueryValidationError("Cloud Logging filter or pagination parameters are invalid.") from exc
            if exc.is_permission_denied:
                logger.warning(
                    "gcp_logs_query_failed classification=permission_denied project_id=%s status_code=%s error_status=%s error_class=%s runtime_pod=%s",
                    self.project_id,
                    exc.status_code if exc.status_code is not None else "",
                    exc.error_status or "",
                    exc.__class__.__name__,
                    _RUNTIME_POD_NAME,
                )
                raise GCPLogsQueryPermissionError(
                    "Cloud Logging permission denied for runtime service account. Verify roles/logging.viewer on GCP_PROJECT_ID."
                ) from exc
            if exc.is_timeout:
                logger.warning(
                    "gcp_logs_query_failed classification=timeout project_id=%s status_code=%s error_status=%s error_class=%s runtime_pod=%s",
                    self.project_id,
                    exc.status_code if exc.status_code is not None else "",
                    exc.error_status or "",
                    exc.__class__.__name__,
                    _RUNTIME_POD_NAME,
                )
                raise GCPLogsQueryTimeoutError("Cloud Logging request timed out.") from exc
            logger.warning(
                "gcp_logs_query_failed classification=provider_error project_id=%s status_code=%s error_status=%s error_class=%s runtime_pod=%s",
                self.project_id,
                exc.status_code if exc.status_code is not None else "",
                exc.error_status or "",
                exc.__class__.__name__,
                _RUNTIME_POD_NAME,
            )
            raise GCPLogsQueryProviderError("Cloud Logging request failed.") from exc

        raw_entries = response_payload.get("entries")
        sanitized_entries: list[GCPLogEntryRead] = []
        if isinstance(raw_entries, list):
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                sanitized_entries.append(self._sanitize_entry(item))
        next_page_token = _normalize_optional_text(
            response_payload.get("nextPageToken"),
            max_chars=_MAX_PAGE_TOKEN_CHARS,
        )
        adc_project_id = _normalize_optional_text(
            getattr(self.client, "detected_project_id", None),
            max_chars=80,
        )
        if adc_project_id and adc_project_id != self.project_id:
            logger.warning(
                "gcp_logs_query_project_mismatch configured_project_id=%s detected_adc_project_id=%s",
                self.project_id,
                adc_project_id,
            )
        logger.info(
            "gcp_logs_query_request_complete project_id=%s detected_adc_project_id=%s entry_count=%s next_page_token_present=%s runtime_pod=%s",
            self.project_id,
            adc_project_id or "",
            len(sanitized_entries),
            bool(next_page_token),
            _RUNTIME_POD_NAME,
        )
        return GCPLogsQueryResponse(
            entries=sanitized_entries,
            next_page_token=next_page_token,
            page_size=effective_page_size,
            order_by=self.order_by,
            resource_scope=[f"projects/{self.project_id}"],
            effective_filter=effective_filter,
            default_time_range_applied=default_time_range_applied,
        )

    def _build_effective_filter(self, payload: GCPLogsQueryRequest) -> tuple[str, bool]:
        # IMPORTANT: Do not apply hidden time filters; all time constraints must be visible to operator.
        base_filter = (payload.filter or "").strip()
        start_time = self._parse_optional_timestamp(payload.start_time, field_name="start_time")
        end_time = self._parse_optional_timestamp(payload.end_time, field_name="end_time")
        default_time_range_applied = False

        if start_time is None and end_time is None:
            start_time = utc_now() - timedelta(hours=_DEFAULT_TIME_WINDOW_HOURS)
            default_time_range_applied = True

        if start_time is not None and end_time is not None and start_time > end_time:
            raise GCPLogsQueryValidationError("start_time must be earlier than or equal to end_time.")

        effective_filter_parts = [f"({base_filter})"]
        if start_time is not None:
            effective_filter_parts.append(f'timestamp >= "{_format_timestamp_for_filter(start_time)}"')
        if end_time is not None:
            effective_filter_parts.append(f'timestamp <= "{_format_timestamp_for_filter(end_time)}"')
        return " AND ".join(effective_filter_parts), default_time_range_applied

    def _parse_optional_timestamp(self, value: str | None, *, field_name: str) -> datetime | None:
        normalized = (value or "").strip()
        if not normalized:
            return None
        try:
            if normalized.endswith("Z"):
                parsed = datetime.fromisoformat(f"{normalized[:-1]}+00:00")
            else:
                parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise GCPLogsQueryValidationError(f"{field_name} must be a valid ISO-8601 timestamp.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed

    def _sanitize_entry(self, item: dict[str, Any]) -> GCPLogEntryRead:
        resource_payload = item.get("resource")
        resource_type: str | None = None
        resource_labels: dict[str, str] | None = None
        if isinstance(resource_payload, dict):
            resource_type = _normalize_optional_text(
                resource_payload.get("type"),
                max_chars=_MAX_RESOURCE_TYPE_CHARS,
            )
            resource_labels = _normalize_labels(resource_payload.get("labels"))

        return GCPLogEntryRead(
            timestamp=_normalize_optional_text(item.get("timestamp"), max_chars=_MAX_TIMESTAMP_CHARS),
            severity=_normalize_optional_text(item.get("severity"), max_chars=_MAX_SEVERITY_CHARS),
            log_name=_normalize_optional_text(item.get("logName"), max_chars=_MAX_LOG_NAME_CHARS),
            resource_type=resource_type,
            labels=_normalize_labels(item.get("labels")),
            resource_labels=resource_labels,
            insert_id=_normalize_optional_text(item.get("insertId"), max_chars=_MAX_INSERT_ID_CHARS),
            text_payload_summary=_summarize_text_payload(item.get("textPayload")),
            json_payload_summary=_summarize_json_payload(item.get("jsonPayload")),
            proto_payload_summary=_summarize_json_payload(item.get("protoPayload")),
        )


def _normalize_optional_text(value: object, *, max_chars: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) <= max_chars:
        return normalized
    truncated_max = max_chars - 3
    if truncated_max <= 0:
        return normalized[:max_chars]
    return f"{normalized[:truncated_max]}..."


def _normalize_labels(value: object) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, str] = {}
    for key, raw_value in value.items():
        normalized_key = _normalize_optional_text(key, max_chars=_MAX_LABEL_KEY_CHARS)
        normalized_value = _normalize_optional_text(raw_value, max_chars=_MAX_LABEL_VALUE_CHARS)
        if normalized_key is None or normalized_value is None:
            continue
        normalized[normalized_key] = normalized_value
        if len(normalized) >= _MAX_LABEL_ITEMS:
            break
    if not normalized:
        return None
    return normalized


def _summarize_text_payload(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return _truncate_summary(normalized)


def _summarize_json_payload(value: object) -> str | None:
    if value is None:
        return None
    try:
        serialized = json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError):
        serialized = str(value)
    serialized = serialized.strip()
    if not serialized:
        return None
    return _truncate_summary(serialized)


def _truncate_summary(value: str) -> str:
    if len(value) <= _MAX_PAYLOAD_SUMMARY_CHARS:
        return value
    return f"{value[: _MAX_PAYLOAD_SUMMARY_CHARS - 3]}..."


def _summarize_error_message(error: Exception) -> str:
    normalized = " ".join(str(error or "").split())
    if not normalized:
        normalized = error.__class__.__name__
    if len(normalized) <= 240:
        return normalized
    return f"{normalized[:237]}..."


def _format_timestamp_for_filter(value: datetime) -> str:
    utc_value = value.astimezone(timezone.utc).replace(microsecond=0)
    return utc_value.isoformat().replace("+00:00", "Z")
