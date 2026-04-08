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
        "generated_files": (
            generated_files
            if generated_files is not None
            else [
                {
                    "path": "index.html",
                    "media_type": "text/html",
                    "content": "<html><body>Draft</body></html>",
                }
            ]
        ),
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


def _build_responses_api_response(content: str) -> str:
    payload = {
        "model": "gpt-5.1",
        "output_text": content,
    }
    return json_dumps(payload)


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=True)


def _known_good_responses_contract_baseline() -> dict[str, object]:
    return {
        "model": "gpt-5.1",
        "endpoint_path": "/responses",
        "request_body_mode": "responses_text_format_json_schema",
        "top_level_keys": ["input", "model", "text"],
        "schema_name": "seo_migration_artifact_response",
        "text_format_type": "json_schema",
        "strict_enabled": True,
    }


def _count_non_false_additional_properties(schema_payload: object) -> int:
    count = 0
    stack: list[object] = [schema_payload]
    while stack:
        candidate = stack.pop()
        if not isinstance(candidate, dict):
            continue
        candidate_type = candidate.get("type")
        is_object_node = candidate_type == "object" or (
            isinstance(candidate_type, list) and "object" in candidate_type
        )
        if is_object_node and candidate.get("additionalProperties") is not False:
            count += 1
        properties = candidate.get("properties")
        if isinstance(properties, dict):
            stack.extend(properties.values())
        items = candidate.get("items")
        if isinstance(items, dict):
            stack.append(items)
        elif isinstance(items, list):
            stack.extend(items)
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            nested = candidate.get(key)
            if isinstance(nested, list):
                stack.extend(nested)
        additional_properties = candidate.get("additionalProperties")
        if isinstance(additional_properties, dict):
            stack.append(additional_properties)
    return count


def test_openai_migration_provider_compatibility_supports_known_responses_json_schema_shape_for_gpt_5_1() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )

    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is True
    assert compatibility.reason_code == "supported"
    assert compatibility.provider_name == "openai"
    assert compatibility.model_name == "gpt-5.1"
    assert compatibility.endpoint_path == "/responses"
    assert compatibility.execution_mode == "full"
    assert compatibility.web_search_enabled is False
    assert compatibility.degraded_mode is False
    assert compatibility.response_format_mode == "json_schema"
    assert compatibility.request_body_mode == "responses_text_format_json_schema"


def test_openai_migration_provider_compatibility_rejects_chat_json_schema_shape_for_gpt_4o_mini() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-4o-mini",
        timeout_seconds=5,
    )

    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert compatibility.provider_name == "openai"
    assert compatibility.model_name == "gpt-4o-mini"
    assert compatibility.endpoint_path == "/chat/completions"
    assert compatibility.execution_mode == "full"
    assert compatibility.web_search_enabled is False
    assert compatibility.degraded_mode is False
    assert compatibility.response_format_mode == "json_schema"
    assert compatibility.request_body_mode == "chat_json_schema"


def test_openai_migration_provider_compatibility_rejects_incompatible_model_configuration() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="text-embedding-3-small",
        timeout_seconds=5,
    )

    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_model_configuration"
    assert compatibility.retryable is False
    assert "request_shape_model_family_unsupported" in str(compatibility.admin_summary or "")


def test_openai_migration_provider_compatibility_rejects_degraded_mode(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-4o-mini",
        timeout_seconds=5,
    )

    def _degraded_profile() -> dict[str, object]:
        return {
            "endpoint_path": "/chat/completions",
            "execution_mode": "full",
            "web_search_enabled": False,
            "degraded_mode": True,
            "response_format_mode": "json_schema",
        }

    monkeypatch.setattr(provider, "get_request_profile", _degraded_profile)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "degraded_mode_not_allowed"
    assert compatibility.retryable is False


def test_openai_migration_provider_responses_payload_matches_known_good_contract(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    captured_payload: dict[str, object] = {}

    def _capture_request(request, timeout):  # noqa: ANN001
        del timeout
        captured_payload.update(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(_build_responses_api_response(json_dumps(_build_success_assistant_payload())))

    monkeypatch.setattr(urllib.request, "urlopen", _capture_request)
    output = provider.generate_artifacts(migration_context=_build_migration_context())
    assert output.generated_files

    baseline = _known_good_responses_contract_baseline()
    assert captured_payload.get("model") == baseline["model"]
    assert sorted(captured_payload.keys()) == baseline["top_level_keys"]
    assert "messages" not in captured_payload
    assert "response_format" not in captured_payload
    assert "tools" not in captured_payload

    input_payload = captured_payload.get("input")
    assert isinstance(input_payload, str)
    assert input_payload.strip()
    assert "System Instructions:" in input_payload
    assert "User Request:" in input_payload

    text_payload = captured_payload.get("text")
    assert isinstance(text_payload, dict)
    format_payload = text_payload.get("format")
    assert isinstance(format_payload, dict)
    assert format_payload.get("type") == baseline["text_format_type"]
    assert format_payload.get("name") == baseline["schema_name"]
    assert format_payload.get("strict") is baseline["strict_enabled"]
    schema_payload = format_payload.get("schema")
    assert isinstance(schema_payload, dict)
    assert _count_non_false_additional_properties(schema_payload) == 0


def test_openai_migration_provider_compatibility_rejects_responses_payload_with_legacy_response_format(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload

    def _build_mixed_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "legacy",
                "strict": True,
                "schema": {"type": "object", "additionalProperties": False, "properties": {}},
            },
        }
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_mixed_payload)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_contains_legacy_response_format" in str(compatibility.admin_summary or "")


def test_openai_migration_provider_compatibility_rejects_responses_schema_with_non_false_additional_properties(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload

    def _build_invalid_schema_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        text_payload = payload.get("text")
        if isinstance(text_payload, dict):
            format_payload = text_payload.get("format")
            if isinstance(format_payload, dict):
                schema_payload = format_payload.get("schema")
                if isinstance(schema_payload, dict):
                    schema_payload["properties"] = {
                        **(schema_payload.get("properties") if isinstance(schema_payload.get("properties"), dict) else {}),
                        "cta_contact_structure": {"type": "object", "additionalProperties": True},
                    }
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_invalid_schema_payload)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_schema_additional_properties_not_false" in str(compatibility.admin_summary or "")


def test_openai_migration_provider_compatibility_rejects_responses_non_string_input(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload

    def _build_array_input_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        payload["input"] = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ]
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_array_input_payload)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_input_non_string" in str(compatibility.admin_summary or "")


def test_openai_migration_provider_runtime_blocks_non_string_input_before_provider_call(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload
    urlopen_called = False

    def _build_array_input_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        payload["input"] = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ]
        return payload

    def _capture_request(request, timeout):  # noqa: ANN001
        del request, timeout
        nonlocal urlopen_called
        urlopen_called = True
        return _FakeResponse(_build_responses_api_response(json_dumps(_build_success_assistant_payload())))

    monkeypatch.setattr(provider, "_build_request_payload", _build_array_input_payload)
    monkeypatch.setattr(urllib.request, "urlopen", _capture_request)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())

    error = exc_info.value
    assert error.reason == "unsupported_configuration"
    assert error.code == "unsupported_request_shape_input_non_string"
    assert error.retryable is False
    assert urlopen_called is False


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


def test_openai_migration_provider_request_logs_include_request_shape_metadata(monkeypatch, caplog) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )

    def _return_invalid_json(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse("not-json")

    monkeypatch.setattr(urllib.request, "urlopen", _return_invalid_json)
    with caplog.at_level("INFO"):
        with pytest.raises(SEOMigrationArtifactProviderError):
            provider.generate_artifacts(migration_context=_build_migration_context())

    start_events = [
        getattr(record, "json_fields", {})
        for record in caplog.records
        if isinstance(getattr(record, "json_fields", None), dict)
        and getattr(record, "json_fields", {}).get("event") == "seo_migration_draft_provider_request_start"
    ]
    failure_events = [
        getattr(record, "json_fields", {})
        for record in caplog.records
        if isinstance(getattr(record, "json_fields", None), dict)
        and getattr(record, "json_fields", {}).get("event") == "seo_migration_draft_provider_request_failure"
    ]
    assert start_events
    assert failure_events
    start = start_events[-1]
    assert start.get("endpoint_path") == "/responses"
    assert start.get("execution_mode") == "full"
    assert start.get("web_search_enabled") is False
    assert start.get("degraded_mode") is False
    assert start.get("response_format_mode") == "json_schema"
    assert start.get("request_body_mode") == "responses_text_format_json_schema"
    assert start.get("timeout_seconds") == 5
    assert start.get("timeout_source") == "default"
    assert start.get("request_fingerprint_model") == "gpt-5.1"
    assert start.get("request_fingerprint_endpoint_path") == "/responses"
    assert start.get("request_fingerprint_request_body_mode") == "responses_text_format_json_schema"
    assert start.get("request_fingerprint_has_text_format") is True
    assert start.get("request_fingerprint_text_format_type") == "json_schema"
    assert start.get("request_fingerprint_schema_name") == "seo_migration_artifact_response"
    assert start.get("request_fingerprint_strict_enabled") is True
    assert start.get("request_fingerprint_top_level_keys") == ["input", "model", "text"]
    assert start.get("request_fingerprint_text_format_keys") == ["name", "schema", "strict", "type"]
    assert start.get("request_fingerprint_input_mode") == "string"
    assert start.get("request_fingerprint_contains_tools") is False
    assert start.get("request_fingerprint_contains_response_format_legacy") is False
    assert start.get("request_fingerprint_contains_messages_legacy") is False
    assert start.get("request_fingerprint_schema_object_nodes_non_false_additional_properties") == 0
    assert "system_prompt" not in start
    assert "user_prompt" not in start
    assert "raw_payload" not in start

    failure = failure_events[-1]
    assert failure.get("endpoint_path") == "/responses"
    assert failure.get("execution_mode") == "full"
    assert failure.get("web_search_enabled") is False
    assert failure.get("degraded_mode") is False
    assert failure.get("response_format_mode") == "json_schema"
    assert failure.get("request_body_mode") == "responses_text_format_json_schema"
    assert failure.get("failure_reason") == "malformed_response"
    assert failure.get("timeout_seconds") == 5
    assert failure.get("timeout_source") == "default"
    assert failure.get("request_fingerprint_model") == "gpt-5.1"
    assert failure.get("request_fingerprint_top_level_keys") == ["input", "model", "text"]
    assert failure.get("request_fingerprint_contains_response_format_legacy") is False
    assert failure.get("request_fingerprint_contains_messages_legacy") is False
    assert "system_prompt" not in failure
    assert "user_prompt" not in failure
    assert "raw_payload" not in failure


def test_openai_migration_provider_parses_fenced_json_output(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    fenced_content = f"```json\n{json_dumps(_build_success_assistant_payload())}\n```"

    def _return_wrapped_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_responses_api_response(fenced_content))

    monkeypatch.setattr(urllib.request, "urlopen", _return_wrapped_payload)
    output = provider.generate_artifacts(migration_context=_build_migration_context())
    assert output.generated_files
    assert output.generated_files[0].path == "index.html"
    assert any(
        "Recovered structured JSON from wrapped provider output." in warning for warning in output.parse_warnings
    )


def test_openai_migration_provider_parses_json_with_leading_and_trailing_prose(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    prose_wrapped = f"Here is the JSON payload:\n{json_dumps(_build_success_assistant_payload())}\nThanks."

    def _return_wrapped_payload(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(_build_responses_api_response(prose_wrapped))

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
        return _FakeResponse(_build_responses_api_response(json_dumps(malformed_payload)))

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
        return _FakeResponse(_build_responses_api_response(truncated))

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
        return _FakeResponse(_build_responses_api_response("   "))

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
        return _FakeResponse(_build_responses_api_response(json_dumps(malformed_payload)))

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
