from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request

import pytest

from app.integrations.seo_migration_artifact_provider import (
    OpenAISEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
)


class _FakeResponse:
    def __init__(self, body: str, *, headers: dict[str, str] | None = None) -> None:
        self._body = body.encode("utf-8")
        self.headers = headers or {}

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        del exc_type, exc, tb
        return False

    def read(self) -> bytes:
        return self._body


def _build_migration_context() -> dict[str, object]:
    return {
        "site_snapshot": {
            "business_id": "11111111-1111-1111-1111-111111111111",
            "site_id": "22222222-2222-2222-2222-222222222222",
            "display_name": "TNM Fire",
            "base_url": "https://tnmfire.example/",
            "normalized_domain": "tnmfire.example",
            "industry": "fire protection",
            "primary_location": "Longmont, CO",
            "service_areas": ["Longmont"],
            "location_context": {"text": "Longmont, CO", "strength": "high", "source": "test"},
            "business_context": {
                "industry_context": "fire protection",
                "industry_context_strength": "high",
                "service_focus_terms": ["inspection"],
                "target_customer_context": "local SMB",
            },
        },
        "migration_workspace": {
            "workspace_id": "33333333-3333-3333-3333-333333333333",
            "source_url": "https://legacy.example/",
            "source_site_status": "ingested",
            "migration_status": "source_ingested",
        },
        "source_snapshot": {},
        "operator_requirements": {},
        "enriched_content_notes": {},
        "brand_business_facts_snapshot": {},
        "existing_context_summaries": {},
    }


def _build_success_assistant_payload(*, generated_files: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "strategy_summary": "Draft strategy",
        "page_map": [],
        "homepage_structure": [],
        "service_page_suggestions": [],
        "cta_contact_structure": {},
        "seo_meta_suggestions": {},
        "redirect_suggestions": [],
        "analytics_placeholders": [],
        "generated_files": generated_files
        if generated_files is not None
        else [
            {
                "path": "index.html",
                "media_type": "text/html",
                "content": "<html><body>Draft</body></html>",
            }
        ],
    }


def _build_chat_completion_response(content: str) -> str:
    payload = {
        "model": "gpt-5.1",
        "choices": [
            {
                "message": {
                    "content": content,
                }
            }
        ],
    }
    return json_dumps(payload)


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True)


def test_openai_migration_provider_timeout_maps_to_retryable_timeout_reason(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-4o-mini",
        timeout_seconds=5,
    )

    def _raise_timeout(request, timeout):  # noqa: ANN001
        del request, timeout
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())
    error = exc_info.value
    assert error.reason == "timeout"
    assert error.retryable is True
    assert "timed out" in error.safe_message.lower()


def test_openai_migration_provider_auth_failure_maps_to_non_retryable_auth_reason(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-4o-mini",
        timeout_seconds=5,
    )

    def _raise_auth_error(request, timeout):  # noqa: ANN001
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
            code=401,
            msg="unauthorized",
            hdrs={"x-request-id": "provider-auth-1"},
            fp=io.BytesIO(b'{"error":"unauthorized"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _raise_auth_error)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())
    error = exc_info.value
    assert error.reason == "authentication_failed"
    assert error.retryable is False
    assert error.correlation_id == "provider-auth-1"
    assert "authentication failed" in error.safe_message.lower()


def test_openai_migration_provider_invalid_json_maps_to_malformed_response_reason(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-4o-mini",
        timeout_seconds=5,
    )

    def _return_invalid_json(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse("not-json")

    monkeypatch.setattr(urllib.request, "urlopen", _return_invalid_json)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())
    error = exc_info.value
    assert error.reason == "malformed_response"
    assert error.retryable is True
    assert "could not be parsed" in error.safe_message.lower()


def test_openai_migration_provider_parses_fenced_json_output(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    fenced_content = f"```json\n{json_dumps(_build_success_assistant_payload())}\n```"

    def _return_wrapped_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_chat_completion_response(fenced_content))

    monkeypatch.setattr(urllib.request, "urlopen", _return_wrapped_payload)
    output = provider.generate_artifacts(migration_context=_build_migration_context())
    assert output.generated_files
    assert output.generated_files[0].path == "index.html"
    assert any("Recovered structured JSON from wrapped provider output." in warning for warning in output.parse_warnings)


def test_openai_migration_provider_parses_json_with_leading_and_trailing_prose(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    prose_wrapped = f"Here is the JSON payload:\n{json_dumps(_build_success_assistant_payload())}\nThanks."

    def _return_wrapped_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_chat_completion_response(prose_wrapped))

    monkeypatch.setattr(urllib.request, "urlopen", _return_wrapped_payload)
    output = provider.generate_artifacts(migration_context=_build_migration_context())
    assert output.generated_files
    assert output.generated_files[0].path == "index.html"


def test_openai_migration_provider_salvages_partial_generated_files_on_schema_failure(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    malformed_payload = _build_success_assistant_payload(
        generated_files=[
            {
                "path": "index.html",
                "media_type": "text/html",
                "content": "<html><body>One</body></html>",
            },
            {
                "file_path": "styles.css",
                "content_type": "text/css",
                "text": "body { color: #222; }",
            },
            {
                "path": "contact.html",
                "media_type": "text/html",
                "content": "",
            },
        ],
    )
    # Force schema validation failure first, then verify salvage preserves valid file entries.
    malformed_payload["service_page_suggestions"] = [{"unexpected": "shape"}]

    def _return_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_chat_completion_response(json_dumps(malformed_payload)))

    monkeypatch.setattr(urllib.request, "urlopen", _return_payload)
    output = provider.generate_artifacts(migration_context=_build_migration_context())
    paths = {item.path for item in output.generated_files}
    assert paths == {"index.html", "styles.css"}
    assert any("Salvaged generated file entries" in warning for warning in output.parse_warnings)


def test_openai_migration_provider_truncated_json_maps_to_malformed_output_reason(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    truncated = '{"strategy_summary":"Draft","generated_files":[{"path":"index.html"'

    def _return_truncated_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_chat_completion_response(truncated))

    monkeypatch.setattr(urllib.request, "urlopen", _return_truncated_payload)
    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())
    assert exc_info.value.reason == "malformed_output"
    assert exc_info.value.retryable is True


def test_openai_migration_provider_empty_assistant_content_maps_to_empty_response(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )

    def _return_empty_content(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_chat_completion_response("   "))

    monkeypatch.setattr(urllib.request, "urlopen", _return_empty_content)
    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())
    assert exc_info.value.reason == "empty_response"


def test_openai_migration_provider_logs_parse_metrics_for_partial_recovery(monkeypatch, caplog) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    malformed_payload = _build_success_assistant_payload(
        generated_files=[
            {
                "path": "index.html",
                "media_type": "text/html",
                "content": "<html><body>One</body></html>",
            },
            {
                "file_path": "styles.css",
                "content_type": "text/css",
                "text": "body { color: #222; }",
            },
            {"path": "contact.html"},
        ],
    )
    malformed_payload["service_page_suggestions"] = [{"unexpected": "shape"}]

    def _return_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_chat_completion_response(json_dumps(malformed_payload)))

    monkeypatch.setattr(urllib.request, "urlopen", _return_payload)
    with caplog.at_level("INFO"):
        provider.generate_artifacts(migration_context=_build_migration_context())

    parse_events = [
        getattr(record, "json_fields", {})
        for record in caplog.records
        if isinstance(getattr(record, "json_fields", None), dict)
        and getattr(record, "json_fields", {}).get("event") == "seo_migration_draft_provider_response_parse"
    ]
    assert parse_events
    parse_event = parse_events[-1]
    assert parse_event.get("status") == "partial"
    assert parse_event.get("parsed_candidate_count") == 3
    assert parse_event.get("salvaged_candidate_count") == 1
    assert parse_event.get("raw_length") > 0
