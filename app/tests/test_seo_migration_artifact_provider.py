from __future__ import annotations

import io
import json
import logging
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


def _known_good_responses_snapshot_baseline() -> dict[str, object]:
    return {
        "top_level_keys": ["input", "model", "text"],
        "text_top_level_keys": ["format"],
        "text_format_keys": ["name", "schema", "strict", "type"],
    }


def _count_non_false_additional_properties(schema_payload: object) -> int:
    count = 0
    stack: list[object] = [schema_payload]
    while stack:
        candidate = stack.pop()
        if not isinstance(candidate, dict):
            continue
        candidate_type = candidate.get("type")
        is_object_node = candidate_type == "object" or (isinstance(candidate_type, list) and "object" in candidate_type)
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


def _count_object_nodes_missing_full_required(schema_payload: object) -> int:
    count = 0
    stack: list[object] = [schema_payload]
    while stack:
        candidate = stack.pop()
        if not isinstance(candidate, dict):
            continue
        candidate_type = candidate.get("type")
        is_object_node = candidate_type == "object" or (isinstance(candidate_type, list) and "object" in candidate_type)
        if is_object_node:
            properties = candidate.get("properties")
            if isinstance(properties, dict) and properties:
                required_raw = candidate.get("required")
                if not isinstance(required_raw, list):
                    count += 1
                else:
                    required_set = {str(item) for item in required_raw if isinstance(item, str)}
                    properties_set = {str(key) for key in properties.keys()}
                    if required_set != properties_set:
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


def test_openai_migration_provider_compatibility_supports_known_responses_json_schema_shape_for_gpt_5_6_terra() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.6-terra",
        timeout_seconds=5,
    )

    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is True
    assert compatibility.reason_code == "supported"
    assert compatibility.provider_name == "openai"
    assert compatibility.model_name == "gpt-5.6-terra"
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
    assert _count_object_nodes_missing_full_required(schema_payload) == 0


def test_openai_migration_provider_gpt_5_6_terra_uses_responses_request_contract(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.6-terra",
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

    assert captured_payload.get("model") == "gpt-5.6-terra"
    assert sorted(captured_payload.keys()) == ["input", "model", "text"]
    assert "messages" not in captured_payload
    assert "response_format" not in captured_payload
    assert "tools" not in captured_payload
    assert isinstance(captured_payload.get("input"), str)
    assert captured_payload["text"]["format"]["type"] == "json_schema"

    redacted_snapshot = provider.build_redacted_request_snapshot(payload=captured_payload)
    serialized_snapshot = provider.serialize_redacted_request_snapshot(payload=captured_payload)
    assert isinstance(serialized_snapshot, str) and serialized_snapshot
    snapshot_baseline = _known_good_responses_snapshot_baseline()
    assert sorted(redacted_snapshot.keys()) == snapshot_baseline["top_level_keys"]
    text_snapshot = redacted_snapshot.get("text")
    assert isinstance(text_snapshot, dict)
    assert sorted(text_snapshot.keys()) == snapshot_baseline["text_top_level_keys"]
    format_snapshot = text_snapshot.get("format")
    assert isinstance(format_snapshot, dict)
    assert sorted(format_snapshot.keys()) == snapshot_baseline["text_format_keys"]
    redacted_input = redacted_snapshot.get("input")
    assert isinstance(redacted_input, str)
    assert redacted_input.startswith("<redacted_string:")
    assert "System Instructions:" not in redacted_input
    assert "User Request:" not in redacted_input


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


def test_openai_migration_provider_compatibility_rejects_responses_payload_with_extra_top_level_key(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload

    def _build_payload_with_extra_top_level_key(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        payload["metadata"] = {"purpose": "contract-drift-test"}
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_payload_with_extra_top_level_key)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_top_level_keys_mismatch" in str(compatibility.admin_summary or "")


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
                        **(
                            schema_payload.get("properties")
                            if isinstance(schema_payload.get("properties"), dict)
                            else {}
                        ),
                        "cta_contact_structure": {"type": "object", "additionalProperties": True},
                    }
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_invalid_schema_payload)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_schema_additional_properties_not_false" in str(compatibility.admin_summary or "")


def test_openai_migration_provider_compatibility_rejects_responses_schema_with_incomplete_required_fields(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload

    def _build_incomplete_required_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        text_payload = payload.get("text")
        if isinstance(text_payload, dict):
            format_payload = text_payload.get("format")
            if isinstance(format_payload, dict):
                schema_payload = format_payload.get("schema")
                if isinstance(schema_payload, dict):
                    properties = schema_payload.get("properties")
                    if isinstance(properties, dict):
                        cta_schema = properties.get("cta_contact_structure")
                        if isinstance(cta_schema, dict):
                            cta_schema.pop("required", None)
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_incomplete_required_payload)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_schema_required_fields_incomplete" in str(compatibility.admin_summary or "")


def test_openai_migration_provider_compatibility_rejects_responses_non_strict_json_schema(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload

    def _build_non_strict_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        text_payload = payload.get("text")
        if isinstance(text_payload, dict):
            format_payload = text_payload.get("format")
            if isinstance(format_payload, dict):
                format_payload["strict"] = False
        return payload

    monkeypatch.setattr(provider, "_build_request_payload", _build_non_strict_payload)
    compatibility = provider.evaluate_compatibility()
    assert compatibility.supported is False
    assert compatibility.reason_code == "unsupported_request_shape"
    assert "responses_request_body_json_schema_invalid" in str(compatibility.admin_summary or "")


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


def test_openai_migration_provider_runtime_blocks_contract_drift_extra_top_level_key_before_provider_call(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    original_builder = provider._build_request_payload
    urlopen_called = False

    def _build_drifted_payload(**kwargs):  # noqa: ANN001
        payload = original_builder(**kwargs)
        payload["metadata"] = {"reason": "drift"}
        return payload

    def _capture_request(request, timeout):  # noqa: ANN001
        del request, timeout
        nonlocal urlopen_called
        urlopen_called = True
        return _FakeResponse(_build_responses_api_response(json_dumps(_build_success_assistant_payload())))

    monkeypatch.setattr(provider, "_build_request_payload", _build_drifted_payload)
    monkeypatch.setattr(urllib.request, "urlopen", _capture_request)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=_build_migration_context())

    error = exc_info.value
    assert error.reason == "unsupported_configuration"
    assert error.code == "unsupported_request_shape_contract_drift"
    assert error.retryable is False
    assert urlopen_called is False
    details = error.internal_details or {}
    blocking_codes = details.get("contract_drift_blocking_codes")
    assert isinstance(blocking_codes, list)
    assert "top_level_keys_mismatch" in blocking_codes
    assert "has_extra_request_options" in blocking_codes


def test_openai_migration_provider_runtime_logs_contract_warning_for_short_input_but_allows_request(
    monkeypatch,
    caplog,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )

    def _build_short_input_text(**kwargs):  # noqa: ANN001
        del kwargs
        return "short-input"

    def _capture_request(request, timeout):  # noqa: ANN001
        del timeout
        payload = json.loads(request.data.decode("utf-8"))
        assert payload.get("input") == "short-input"
        return _FakeResponse(_build_responses_api_response(json_dumps(_build_success_assistant_payload())))

    monkeypatch.setattr(provider, "_build_responses_input_text", _build_short_input_text)
    monkeypatch.setattr(urllib.request, "urlopen", _capture_request)

    with caplog.at_level("INFO"):
        output = provider.generate_artifacts(migration_context=_build_migration_context())

    assert output.generated_files
    guard_events = [
        getattr(record, "json_fields", {})
        for record in caplog.records
        if isinstance(getattr(record, "json_fields", None), dict)
        and getattr(record, "json_fields", {}).get("event") == "seo_migration_draft_provider_request_contract_guard"
    ]
    assert guard_events
    guard_event = guard_events[-1]
    assert guard_event.get("blocking_codes") == []
    assert guard_event.get("warning_codes") == ["input_length_short"]
    assert guard_event.get("request_fingerprint_input_mode") == "string"


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
    assert error.retryable is False
    assert error.normalized_failure_category == "remote_timeout"
    assert error.normalized_failure_reason == "request_too_large_or_complex"
    assert error.normalized_failure_source == "remote_provider"
    assert error.normalized_retryable is False
    assert error.attempt_count == 1
    assert "timed out" in error.safe_message.lower()


def test_openai_migration_provider_fails_early_when_required_context_exceeds_budget(monkeypatch, caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.integrations.seo_migration_artifact_provider")
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    site_snapshot = dict(migration_context.get("site_snapshot") or {})
    site_snapshot["display_name"] = "X" * 180000
    migration_context["site_snapshot"] = site_snapshot

    provider_called = False

    def _fail_if_called(request, timeout):  # noqa: ANN001
        del request, timeout
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider call should not happen for oversized required context")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_if_called)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=migration_context)

    error = exc_info.value
    assert provider_called is False
    assert error.reason == "validation_failed"
    assert error.retryable is False
    assert error.normalized_failure_category == "local_validation_failure"
    assert error.normalized_failure_reason == "request_too_large_or_complex"
    assert error.normalized_failure_source == "local_validation"
    assert error.attempt_count == 1
    budget_events = [
        record.__dict__.get("json_fields")
        for record in caplog.records
        if isinstance(record.__dict__.get("json_fields"), dict)
        and record.__dict__["json_fields"].get("event") == "seo_migration_draft_request_budget"
    ]
    assert budget_events
    latest_budget_event = budget_events[-1]
    assert latest_budget_event.get("feature_area") == "migration_draft"
    assert latest_budget_event.get("budget_outcome") == "precall_rejected"
    assert isinstance(latest_budget_event.get("trimmed_bytes"), int)
    assert isinstance(latest_budget_event.get("trimming_pass_count"), int)


def test_openai_migration_provider_blocks_before_provider_when_admin_preflight_mode_blocks(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["existing_context_summaries"] = {"summary": "A" * 24000}
    migration_context["generation_safety"] = {
        "migration_preflight_mode": "block_before_provider",
        "migration_max_final_input_chars": 3000,
        "migration_max_difficulty_score": 5,
        "migration_compact_fallback_enabled": True,
    }

    provider_called = False

    def _fail_if_called(request, timeout):  # noqa: ANN001
        del request, timeout
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider call should be blocked by preflight")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_if_called)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=migration_context)

    error = exc_info.value
    assert provider_called is False
    assert error.code == "migration_generation_preflight_too_large"
    assert error.reason == "validation_failed"
    assert error.normalized_failure_source == "local_validation"
    details = error.internal_details or {}
    safety = details.get("generation_safety") if isinstance(details.get("generation_safety"), dict) else {}
    assert safety.get("migration_preflight_mode") == "block_before_provider"
    assert safety.get("compact_fallback_attempted") is False
    assert safety.get("preflight_blocked") is True


def test_openai_migration_provider_compact_fallback_reduces_budget_and_continues(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["existing_context_summaries"] = {"summary": "A" * 24000}
    migration_context["generation_safety"] = {
        "migration_preflight_mode": "compact_fallback",
        "migration_max_final_input_chars": 8000,
        "migration_max_difficulty_score": 20,
        "migration_compact_fallback_enabled": True,
        "migration_compact_page_limit": 3,
        "migration_compact_media_asset_limit": 2,
        "migration_compact_recommendation_limit": 3,
    }

    body = _build_responses_api_response(json_dumps(_build_success_assistant_payload()))

    def _mock_urlopen(request, timeout):  # noqa: ANN001
        del request, timeout
        return _FakeResponse(body, headers={"x-request-id": "req-compact-fallback"})

    monkeypatch.setattr(urllib.request, "urlopen", _mock_urlopen)
    evaluation_results = [
        {
            "blocked": True,
            "block_reason": "final_input_chars_exceeded",
            "difficulty_score": 14,
            "exceeds_final_input_chars": True,
            "exceeds_difficulty_score": False,
            "overflow": False,
            "trimming_pass_limit_exceeded": False,
            "max_final_input_chars": 8000,
            "max_difficulty_score": 20,
        },
        {
            "blocked": False,
            "block_reason": None,
            "difficulty_score": 7,
            "exceeds_final_input_chars": False,
            "exceeds_difficulty_score": False,
            "overflow": False,
            "trimming_pass_limit_exceeded": False,
            "max_final_input_chars": 8000,
            "max_difficulty_score": 20,
        },
    ]

    def _mock_evaluate_generation_preflight(**kwargs):  # noqa: ANN001
        del kwargs
        return evaluation_results.pop(0)

    monkeypatch.setattr(provider, "_evaluate_generation_preflight", _mock_evaluate_generation_preflight)

    output = provider.generate_artifacts(migration_context=migration_context)
    assert output.generated_files
    safety = getattr(provider, "last_generation_safety", {})
    assert isinstance(safety, dict)
    assert safety.get("compact_fallback_attempted") is True
    assert safety.get("budget_capped") is True
    assert safety.get("preflight_blocked") is False


def test_openai_migration_provider_compact_fallback_still_blocks_when_required_context_remains_too_large(
    monkeypatch,
) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    site_snapshot = dict(migration_context.get("site_snapshot") or {})
    site_snapshot["display_name"] = "X" * 180000
    migration_context["site_snapshot"] = site_snapshot
    migration_context["generation_safety"] = {
        "migration_preflight_mode": "compact_fallback",
        "migration_max_final_input_chars": 3000,
        "migration_max_difficulty_score": 8,
        "migration_compact_fallback_enabled": True,
    }

    provider_called = False

    def _fail_if_called(request, timeout):  # noqa: ANN001
        del request, timeout
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider call should remain blocked when compact fallback cannot satisfy safety limits")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_if_called)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=migration_context)

    error = exc_info.value
    assert provider_called is False
    assert error.code == "migration_generation_preflight_too_large"
    details = error.internal_details or {}
    safety = details.get("generation_safety") if isinstance(details.get("generation_safety"), dict) else {}
    assert safety.get("compact_fallback_attempted") is True
    assert safety.get("preflight_blocked") is True


def test_openai_migration_provider_budget_trimming_preserves_required_context_blocks() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["existing_context_summaries"] = {"summary": "A" * 52000}
    migration_context["brand_business_facts_snapshot"] = {"facts": "B" * 52000}
    migration_context["enriched_content_notes"] = {"notes": "C" * 52000}

    budgeted_context, budget_result = provider._apply_migration_context_budget(migration_context)

    assert "site_snapshot" in budgeted_context
    assert "migration_workspace" in budgeted_context
    assert "existing_context_summaries" not in budgeted_context
    assert "brand_business_facts_snapshot" not in budgeted_context
    dropped_blocks = budget_result.get("dropped_optional_blocks") or []
    assert dropped_blocks[:2] == ["existing_context_summaries", "brand_business_facts_snapshot"]
    assert isinstance(budget_result.get("trimming_pass_count"), int)
    assert isinstance(budget_result.get("trimmed_bytes"), int)


def test_openai_migration_provider_uses_generation_budget_context_chars_with_safety_bounds() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["generation_budget"] = {"migration_context_budget_chars": 9000}
    migration_context["existing_context_summaries"] = {"summary": "A" * 15000}

    _, budget_result = provider._apply_migration_context_budget(migration_context)
    assert budget_result.get("budget_size_chars") == 9000

    migration_context["generation_budget"] = {"migration_context_budget_chars": 1000000}
    _, capped_budget_result = provider._apply_migration_context_budget(migration_context)
    assert capped_budget_result.get("budget_size_chars") == 150000


def test_openai_migration_provider_allows_realistic_operator_requirements_under_new_default_cap() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["operator_requirements"] = {"website_requirements": "R" * 5000}
    migration_context["existing_context_summaries"] = {"summary": "S" * 9000}

    _, budget_result = provider._apply_migration_context_budget(migration_context)
    preflight = provider._evaluate_generation_preflight(
        budget_result=budget_result,
        generation_safety=provider._resolve_generation_safety_profile(migration_context),
    )

    assert int(budget_result.get("final_size_chars") or 0) > 12000
    assert preflight.get("blocked") is False


def test_openai_migration_provider_preflight_allows_compacted_media_heavy_context_under_difficulty_cap() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["generation_safety"] = {
        "migration_preflight_mode": "compact_fallback",
        "migration_max_final_input_chars": 32000,
        "migration_max_difficulty_score": 18,
        "migration_compact_fallback_enabled": True,
        "migration_compact_page_limit": 6,
        "migration_compact_media_asset_limit": 5,
        "migration_compact_recommendation_limit": 8,
    }

    generation_safety = provider._resolve_generation_safety_profile(migration_context)
    preflight = provider._evaluate_generation_preflight(
        budget_result={
            "initial_size_chars": 69509,
            "initial_size_bytes": 69509,
            "final_size_chars": 13485,
            "final_size_bytes": 13485,
            "trimmed_bytes": 57065,
            "trimming_pass_count": 6,
            "section_count": 8,
            "budget_size_chars": 90000,
            "largest_retained_block": "media_assets",
            "largest_retained_block_size_chars": 5175,
            "overflow": False,
        },
        generation_safety=generation_safety,
    )

    assert preflight.get("difficulty_score") <= 18
    assert preflight.get("blocked") is False
    assert preflight.get("blocked_setting") is None


def test_openai_migration_provider_preflight_blocks_when_difficulty_still_exceeds_cap() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    migration_context["generation_safety"] = {
        "migration_preflight_mode": "block_before_provider",
        "migration_max_final_input_chars": 32000,
        "migration_max_difficulty_score": 18,
        "migration_compact_fallback_enabled": False,
    }

    generation_safety = provider._resolve_generation_safety_profile(migration_context)
    preflight = provider._evaluate_generation_preflight(
        budget_result={
            "final_size_chars": 28000,
            "final_size_bytes": 28000,
            "trimming_pass_count": 7,
            "section_count": 14,
            "budget_size_chars": 90000,
            "overflow": False,
        },
        generation_safety=generation_safety,
    )

    assert preflight.get("blocked") is True
    assert preflight.get("block_reason") == "difficulty_score_exceeded"
    assert preflight.get("blocked_setting") == "migration_max_difficulty_score"
    assert preflight.get("difficulty_score") > 18


def test_openai_migration_provider_preflight_reports_both_input_and_difficulty_blockers() -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    generation_safety = provider._resolve_generation_safety_profile(
        {
            "generation_safety": {
                "migration_preflight_mode": "block_before_provider",
                "migration_max_final_input_chars": 12000,
                "migration_max_difficulty_score": 10,
                "migration_compact_fallback_enabled": False,
            },
        },
    )
    preflight = provider._evaluate_generation_preflight(
        budget_result={
            "final_size_chars": 18000,
            "final_size_bytes": 18000,
            "trimming_pass_count": 6,
            "section_count": 12,
            "budget_size_chars": 90000,
            "overflow": False,
        },
        generation_safety=generation_safety,
    )

    assert preflight.get("blocked") is True
    assert preflight.get("block_reason") == "final_input_and_difficulty_exceeded"
    assert preflight.get("blocked_setting") == "migration_max_final_input_chars,migration_max_difficulty_score"


def test_openai_migration_provider_clamps_hard_preflight_caps_and_skips_provider_call(monkeypatch) -> None:
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key="test-key",
        model_name="gpt-5.1",
        timeout_seconds=5,
    )
    migration_context = _build_migration_context()
    site_snapshot = dict(migration_context.get("site_snapshot") or {})
    site_snapshot["display_name"] = "X" * 220000
    migration_context["site_snapshot"] = site_snapshot
    migration_context["generation_safety"] = {
        "migration_preflight_mode": "block_before_provider",
        "migration_max_final_input_chars": 999999,
        "migration_max_difficulty_score": 999,
        "migration_compact_fallback_enabled": False,
    }

    provider_called = False

    def _fail_if_called(request, timeout):  # noqa: ANN001
        del request, timeout
        nonlocal provider_called
        provider_called = True
        raise AssertionError("provider call should be skipped when preflight blocks")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_if_called)

    with pytest.raises(SEOMigrationArtifactProviderError) as exc_info:
        provider.generate_artifacts(migration_context=migration_context)

    error = exc_info.value
    assert provider_called is False
    assert error.code == "migration_generation_preflight_too_large"
    assert "provider call skipped: yes" in error.safe_message.lower()
    details = error.internal_details or {}
    safety = details.get("generation_safety") if isinstance(details.get("generation_safety"), dict) else {}
    assert safety.get("migration_max_final_input_chars") == 64000
    assert safety.get("migration_max_difficulty_score") == 24
    assert details.get("provider_call_skipped") is True


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
    assert error.normalized_failure_category == "configuration_invalid"
    assert error.normalized_failure_reason == "provider_auth_or_configuration_invalid"
    assert error.normalized_failure_source == "local_configuration"
    assert error.normalized_retryable is False
    assert error.attempt_count == 1
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
    assert start.get("task_alias") == "migration_site_generation"
    assert start.get("endpoint_path") == "/responses"
    assert start.get("execution_mode") == "full"
    assert start.get("web_search_enabled") is False
    assert start.get("degraded_mode") is False
    assert start.get("response_format_mode") == "json_schema"
    assert start.get("request_body_mode") == "responses_text_format_json_schema"
    assert start.get("request_shape_adjusted") is True
    assert start.get("request_shape_adjustment_reason") == "ai_model_request_shape_unsupported"
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
    assert start.get("request_fingerprint_text_top_level_keys") == ["format"]
    assert start.get("request_fingerprint_text_format_keys") == ["name", "schema", "strict", "type"]
    assert start.get("request_fingerprint_input_mode") == "string"
    assert start.get("request_fingerprint_input_length_chars") > 0
    assert start.get("request_fingerprint_has_null_optional_fields") is False
    assert start.get("request_fingerprint_has_extra_request_options") is False
    assert start.get("request_fingerprint_contains_tools") is False
    assert start.get("request_fingerprint_contains_response_format_legacy") is False
    assert start.get("request_fingerprint_contains_messages_legacy") is False
    assert start.get("request_fingerprint_schema_object_nodes_non_false_additional_properties") == 0
    assert start.get("request_fingerprint_schema_object_nodes_missing_required") == 0
    assert "system_prompt" not in start
    assert "user_prompt" not in start
    assert "raw_payload" not in start

    failure = failure_events[-1]
    assert failure.get("task_alias") == "migration_site_generation"
    assert failure.get("endpoint_path") == "/responses"
    assert failure.get("execution_mode") == "full"
    assert failure.get("web_search_enabled") is False
    assert failure.get("degraded_mode") is False
    assert failure.get("response_format_mode") == "json_schema"
    assert failure.get("request_body_mode") == "responses_text_format_json_schema"
    assert failure.get("request_shape_adjusted") is True
    assert failure.get("request_shape_adjustment_reason") == "ai_model_request_shape_unsupported"
    assert failure.get("failure_reason") == "malformed_response"
    assert failure.get("timeout_seconds") == 5
    assert failure.get("timeout_source") == "default"
    assert failure.get("request_fingerprint_model") == "gpt-5.1"
    assert failure.get("request_fingerprint_top_level_keys") == ["input", "model", "text"]
    assert failure.get("request_fingerprint_text_top_level_keys") == ["format"]
    assert failure.get("request_fingerprint_input_length_chars") > 0
    assert failure.get("request_fingerprint_has_null_optional_fields") is False
    assert failure.get("request_fingerprint_has_extra_request_options") is False
    assert failure.get("request_fingerprint_contains_response_format_legacy") is False
    assert failure.get("request_fingerprint_contains_messages_legacy") is False
    assert failure.get("request_fingerprint_schema_object_nodes_missing_required") == 0
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
