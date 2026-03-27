from __future__ import annotations

import json
from typing import Any

from app.integrations.google_cloud_logging import (
    GoogleCloudLoggingADCError,
    GoogleCloudLoggingAPIError,
    GoogleCloudLoggingClient,
)
from app.schemas.admin_logs import GCPLogEntryRead, GCPLogsQueryRequest, GCPLogsQueryResponse

_DEFAULT_PAGE_SIZE = 25
_DEFAULT_ORDER_BY = "timestamp desc"
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
_PROJECT_CONFIG_ERROR_MESSAGE = (
    "Cloud Logging query is not configured: missing GCP project id. "
    "Set GCP_PROJECT_ID."
)
_ADC_CONFIG_ERROR_MESSAGE = (
    "Cloud Logging query is not configured: runtime Application Default Credentials are unavailable. "
    "Verify the deployed service account is attached and has Cloud Logging read access."
)


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
            raise GCPLogsQueryConfigurationError(_PROJECT_CONFIG_ERROR_MESSAGE)
        effective_page_size = int(payload.page_size or self.default_page_size)
        if effective_page_size <= 0:
            raise GCPLogsQueryValidationError("page_size must be greater than zero.")

        try:
            response_payload = self.client.list_entries(
                project_id=self.project_id,
                filter_text=payload.filter,
                page_size=effective_page_size,
                page_token=payload.page_token,
                order_by=self.order_by,
            )
        except GoogleCloudLoggingADCError as exc:
            raise GCPLogsQueryConfigurationError(_ADC_CONFIG_ERROR_MESSAGE) from exc
        except GoogleCloudLoggingAPIError as exc:
            if exc.is_invalid_request:
                raise GCPLogsQueryValidationError("Cloud Logging filter or pagination parameters are invalid.") from exc
            if exc.is_permission_denied:
                raise GCPLogsQueryPermissionError(
                    "Cloud Logging permission denied for runtime service account."
                ) from exc
            if exc.is_timeout:
                raise GCPLogsQueryTimeoutError("Cloud Logging request timed out.") from exc
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
        return GCPLogsQueryResponse(
            entries=sanitized_entries,
            next_page_token=next_page_token,
            page_size=effective_page_size,
            order_by=self.order_by,
            resource_scope=[f"projects/{self.project_id}"],
        )

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
