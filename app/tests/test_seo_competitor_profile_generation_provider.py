from __future__ import annotations

from io import BytesIO
import json
import logging
import urllib.error
import urllib.request

import pytest

from app.integrations.seo_competitor_profile_generation_provider import (
    OpenAISEOCompetitorProfileGenerationProvider,
    SEOCompetitorProfileProviderError,
)
from app.models.seo_site import SEOSite


class _FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _site() -> SEOSite:
    return SEOSite(
        id="site-1",
        business_id="biz-1",
        display_name="Client Site",
        base_url="https://client.example/",
        normalized_domain="client.example",
        is_active=True,
        is_primary=True,
    )


def _candidate_json_text() -> str:
    return json.dumps(
        {
            "candidates": [
                {
                    "name": "Competitor One",
                    "domain": "competitor-one.example",
                    "competitor_type": "direct",
                    "summary": "Direct overlap",
                    "why_competitor": "Competes on service intent",
                    "evidence": "Search result overlap",
                    "confidence_score": 0.81,
                }
            ]
        }
    )


def _responses_api_payload(*, model: str) -> dict[str, object]:
    return {
        "model": model,
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": _candidate_json_text(),
                    }
                ]
            }
        ],
    }


def _chat_completions_payload(*, model: str) -> dict[str, object]:
    return {
        "model": model,
        "choices": [
            {
                "message": {
                    "content": _candidate_json_text(),
                }
            }
        ],
    }


def _structured_event_records(caplog) -> list[dict[str, object]]:  # noqa: ANN001
    events: list[dict[str, object]] = []
    for record in caplog.records:
        message = record.getMessage()
        try:
            parsed = json.loads(message)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and isinstance(parsed.get("event"), str):
            events.append(parsed)
    return events


def test_gpt5_mini_uses_responses_api_with_web_search(monkeypatch) -> None:
    captured_url: str | None = None
    captured_payload: dict[str, object] = {}

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        nonlocal captured_url
        assert timeout == 20
        captured_url = request.full_url
        request_body = request.data.decode("utf-8") if isinstance(request.data, bytes) else "{}"
        captured_payload.update(json.loads(request_body))
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-5-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
        timeout_seconds=20,
    )

    output = provider.generate_competitor_profiles(
        site=_site(),
        existing_domains=["known.example"],
        candidate_count=1,
    )

    assert captured_url is not None
    assert captured_url.endswith("/responses")
    assert output.provider_name == "openai"
    assert output.model_name == "gpt-5-mini-2026-01-01"
    assert output.endpoint_path == "/responses"
    assert output.web_search_enabled is True
    assert output.request_duration_ms is not None
    assert output.request_duration_ms >= 0
    assert captured_payload["model"] == "gpt-5-mini"
    assert captured_payload["tools"] == [{"type": "web_search"}]
    assert captured_payload["text"]["format"]["type"] == "json_schema"
    assert captured_payload["text"]["format"]["name"] == "seo_competitor_profile_generation_response"
    assert captured_payload["text"]["format"]["strict"] is True
    assert "temperature" not in captured_payload
    assert "top_p" not in captured_payload
    assert "response_format" not in captured_payload
    input_items = captured_payload["input"]
    assert isinstance(input_items, list)
    assert input_items[0]["role"] == "system"
    assert input_items[1]["role"] == "user"


def test_response_parsing_still_returns_valid_candidates(monkeypatch) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 20
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
    )

    output = provider.generate_competitor_profiles(
        site=_site(),
        existing_domains=["known.example"],
        candidate_count=1,
    )

    assert output.provider_name == "openai"
    assert output.model_name == "gpt-4.1-mini-2026-01-01"
    assert output.prompt_version == "seo-competitor-profile-v1"
    assert output.endpoint_path == "/responses"
    assert output.web_search_enabled is True
    assert output.request_duration_ms is not None
    assert output.raw_response is not None
    assert len(output.candidates) == 1
    assert output.candidates[0].suggested_name == "Competitor One"
    assert output.candidates[0].suggested_domain == "competitor-one.example"


def test_output_prompt_version_uses_resolved_prompt_marker_when_override_is_present(monkeypatch) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 20
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
        prompt_version="seo-competitor-profile-v1",
        prompt_text_competitor=(
            "PROMPT_VERSION: seo-competitor-profile-v4\n"
            "TASK: Use the business admin override as the primary instruction body.\n"
            "OUTPUT FORMAT:\n"
            '{"candidates":[{"domain":"hostname","competitor_type":"direct","confidence_score":0.0}]}\n'
        ),
        prompt_source="admin_config",
    )

    output = provider.generate_competitor_profiles(
        site=_site(),
        existing_domains=["known.example"],
        candidate_count=1,
    )

    assert output.prompt_version == "seo-competitor-profile-v4"


def test_output_prompt_version_falls_back_to_provider_version_without_prompt_marker(monkeypatch) -> None:
    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 20
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
        prompt_version="seo-competitor-profile-v1",
        prompt_text_competitor=(
            "TASK: Use the business admin override as the primary instruction body.\n"
            "OUTPUT FORMAT:\n"
            '{"candidates":[{"domain":"hostname","competitor_type":"direct","confidence_score":0.0}]}\n'
        ),
        prompt_source="admin_config",
    )

    output = provider.generate_competitor_profiles(
        site=_site(),
        existing_domains=["known.example"],
        candidate_count=1,
    )

    assert output.prompt_version == "seo-competitor-profile-v1"


def test_per_request_timeout_override_is_used_when_provided(monkeypatch) -> None:
    observed_timeouts: list[int] = []

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        observed_timeouts.append(timeout)
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=30,
    )

    output = provider.generate_competitor_profiles(
        site=_site(),
        existing_domains=["known.example"],
        candidate_count=1,
        timeout_seconds=12,
    )

    assert len(output.candidates) == 1
    assert observed_timeouts == [12]


def test_reduced_context_mode_builds_smaller_retry_prompt(monkeypatch) -> None:
    captured_user_prompt_lengths: list[int] = []
    captured_response_format_types: list[str | None] = []
    existing_domains = [f"example-{index}.example" for index in range(1, 140)]
    site = _site()
    site.service_areas_json = [f"service-area-{index}-{'x' * 80}" for index in range(1, 30)]

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 20
        payload = json.loads(request.data.decode("utf-8")) if isinstance(request.data, bytes) else {}
        text_payload = payload.get("text")
        response_format_type = None
        if isinstance(text_payload, dict):
            format_payload = text_payload.get("format")
            if isinstance(format_payload, dict):
                response_format_type = str(format_payload.get("type") or "")
        captured_response_format_types.append(response_format_type)
        input_items = payload.get("input")
        assert isinstance(input_items, list)
        user_prompt = input_items[1]["content"]
        captured_user_prompt_lengths.append(len(str(user_prompt)))
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
    )

    provider.generate_competitor_profiles(
        site=site,
        existing_domains=existing_domains,
        candidate_count=5,
        reduced_context_mode=False,
    )
    provider.generate_competitor_profiles(
        site=site,
        existing_domains=existing_domains,
        candidate_count=4,
        reduced_context_mode=True,
    )

    assert len(captured_user_prompt_lengths) == 2
    assert captured_user_prompt_lengths[1] < captured_user_prompt_lengths[0]
    assert captured_response_format_types == ["json_schema", "json_schema"]


def test_fallback_to_chat_completions_on_error(monkeypatch) -> None:
    call_urls: list[str] = []

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        call_urls.append(request.full_url)
        if request.full_url.endswith("/responses"):
            raise urllib.error.HTTPError(
                url=request.full_url,
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=BytesIO(
                    json.dumps(
                        {
                            "error": {
                                "type": "invalid_request_error",
                                "code": "unsupported_parameter",
                                "message": "web_search is not supported for this request.",
                            }
                        }
                    ).encode("utf-8")
                ),
            )
        assert request.full_url.endswith("/chat/completions")
        payload = json.loads(request.data.decode("utf-8")) if isinstance(request.data, bytes) else {}
        assert payload["response_format"]["type"] == "json_schema"
        return _FakeHTTPResponse(json.dumps(_chat_completions_payload(model="gpt-4.1-mini-2026-01-01")))

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
    )

    output = provider.generate_competitor_profiles(
        site=_site(),
        existing_domains=["known.example"],
        candidate_count=1,
    )

    assert output.model_name == "gpt-4.1-mini-2026-01-01"
    assert len(output.candidates) == 1
    assert output.endpoint_path == "/chat/completions"
    assert output.web_search_enabled is False
    assert output.request_duration_ms is not None
    assert call_urls == [
        "https://api.openai.com/v1/responses",
        "https://api.openai.com/v1/chat/completions",
    ]


def test_openai_provider_timeout_is_normalized(monkeypatch) -> None:
    def _timeout_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _timeout_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "timeout"
    assert exc_info.value.raw_output is not None
    raw_debug_payload = json.loads(exc_info.value.raw_output)
    assert raw_debug_payload["failure_kind"] == "timeout"
    assert raw_debug_payload["timeout_type"] == "read"
    assert raw_debug_payload["endpoint_path"] == "/responses"
    assert isinstance(raw_debug_payload.get("request_debug"), dict)
    assert raw_debug_payload["request_debug"]["prompt_total_chars"] >= 1
    assert raw_debug_payload["request_debug"]["timeout_seconds"] == provider.timeout_seconds
    assert isinstance(raw_debug_payload["request_debug"]["web_search_enabled"], bool)
    assert isinstance(raw_debug_payload["request_debug"]["reduced_context_mode"], bool)
    assert raw_debug_payload["request_debug"]["user_prompt_chars"] >= 1
    assert raw_debug_payload["request_debug"]["request_duration_ms"] >= 0


def test_openai_provider_auth_error_is_normalized(monkeypatch) -> None:
    def _unauthorized_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":"invalid_api_key"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _unauthorized_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "provider_auth_config"


def test_openai_provider_malformed_content_is_normalized(monkeypatch) -> None:
    call_urls: list[str] = []

    def _invalid_content_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        call_urls.append(request.full_url)
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": "not-json"}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _invalid_content_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "invalid_output"
    assert exc_info.value.raw_output is not None
    raw_debug_payload = json.loads(exc_info.value.raw_output)
    assert raw_debug_payload["failure_kind"] == "malformed_output"
    assert raw_debug_payload["malformed_output_reason"] == "json_decode_error"
    assert call_urls == ["https://api.openai.com/v1/responses"]


def test_openai_provider_recovers_json_wrapped_in_markdown_fence(monkeypatch) -> None:
    wrapped = f"```json\n{_candidate_json_text()}\n```"

    def _wrapped_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": wrapped}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _wrapped_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert len(output.candidates) == 1
    assert output.candidates[0].suggested_domain == "competitor-one.example"


def test_openai_provider_recovers_json_wrapped_in_prose(monkeypatch) -> None:
    wrapped = f"Here is the requested payload:\n{_candidate_json_text()}\nThanks."

    def _wrapped_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": wrapped}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _wrapped_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert len(output.candidates) == 1
    assert output.candidates[0].suggested_name == "Competitor One"


def test_openai_provider_salvages_valid_candidates_from_partially_malformed_payload(monkeypatch) -> None:
    partial_payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "Competitor One",
                    "domain": "competitor-one.example",
                    "competitor_type": "direct",
                    "summary": "Direct overlap",
                    "why_competitor": "Competes on service intent",
                    "evidence": "Search result overlap",
                    "confidence_score": 0.81,
                },
                {
                    "name": 12345,
                    "domain": None,
                    "competitor_type": 7,
                    "summary": {"invalid": True},
                    "why_competitor": ["invalid"],
                    "evidence": None,
                    "confidence_score": "not-a-number",
                },
            ]
        }
    )

    def _partial_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": partial_payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _partial_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=2)

    assert len(output.candidates) == 1
    assert output.candidates[0].suggested_domain == "competitor-one.example"


def test_openai_provider_filters_empty_candidate_objects_without_failing_run(monkeypatch) -> None:
    payload = json.dumps({"candidates": [{}]})

    def _partial_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _partial_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=2)

    assert output.candidates == []


def test_openai_provider_accepts_explicit_empty_candidate_list(monkeypatch) -> None:
    payload = json.dumps({"candidates": []})

    def _partial_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _partial_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=2)

    assert output.candidates == []


def test_openai_provider_filters_blank_name_and_domain_candidates_without_failing_run(monkeypatch) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "",
                    "domain": "",
                    "competitor_type": "direct",
                    "summary": None,
                    "why_competitor": None,
                    "evidence": None,
                    "confidence_score": 0.5,
                }
            ]
        }
    )

    def _partial_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _partial_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=2)

    assert output.candidates == []


def test_openai_provider_normalizes_domain_hostname_before_candidate_validation(monkeypatch) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "ABC",
                    "domain": "https://abc.com/",
                    "competitor_type": "direct",
                    "summary": "Domain has a scheme.",
                    "why_competitor": "Valid competitor.",
                    "evidence": "Public site.",
                    "confidence_score": 0.8,
                }
            ]
        }
    )

    def _partial_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _partial_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    output = provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=2)

    assert len(output.candidates) == 1
    assert output.candidates[0].suggested_name == "ABC"
    assert output.candidates[0].suggested_domain == "abc.com"


def test_openai_provider_reports_partial_json_reason_when_no_recovery_is_possible(monkeypatch) -> None:
    truncated_payload = '{"candidates":[{"name":"Broken Candidate"'

    def _partial_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": truncated_payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _partial_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "invalid_output"
    assert exc_info.value.raw_output is not None
    raw_debug_payload = json.loads(exc_info.value.raw_output)
    assert raw_debug_payload["failure_kind"] == "malformed_output"
    assert raw_debug_payload["malformed_output_reason"] == "partial_json"


def test_openai_provider_logs_prompt_resolution_without_raw_prompt_text(monkeypatch, caplog) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini")))

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        prompt_text_competitor="SENSITIVE_COMPETITOR_PROMPT_TEXT",
        prompt_source="split",
        prompt_config_key="ai_prompt_text_competitor",
        legacy_config_used=False,
    )

    with caplog.at_level(logging.INFO):
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert "ai_prompt_resolution pipeline=competitor" in caplog.text
    assert "prompt_source=split" in caplog.text
    assert "legacy_config_used=False" in caplog.text
    assert "SENSITIVE_COMPETITOR_PROMPT_TEXT" not in caplog.text
    assert "ai_prompt_legacy_fallback pipeline=competitor" not in caplog.text


def test_openai_provider_warns_on_legacy_fallback_without_raw_prompt_text(monkeypatch, caplog) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini")))

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        prompt_text_competitor="SENSITIVE_LEGACY_PROMPT_TEXT",
        prompt_source="legacy_fallback",
        prompt_config_key="ai_prompt_text_competitor",
        legacy_config_used=True,
    )

    with caplog.at_level(logging.WARNING):
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert "ai_prompt_legacy_fallback pipeline=competitor" in caplog.text
    assert "prompt_source=legacy_fallback" in caplog.text
    assert "SENSITIVE_LEGACY_PROMPT_TEXT" not in caplog.text


def test_openai_provider_logs_bounded_provider_error_details(monkeypatch, caplog) -> None:
    def _bad_request_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "unsupported_parameter",
                            "message": "Unsupported parameter: 'temperature' is not supported with this model.",
                        }
                    }
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _bad_request_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
            provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "provider_request"
    assert exc_info.value.raw_output is not None
    raw_debug_payload = json.loads(exc_info.value.raw_output)
    assert raw_debug_payload["failure_kind"] == "provider_request"
    assert raw_debug_payload["endpoint_path"] == "/responses"
    assert "SEO competitor provider HTTP error status=400" in caplog.text
    assert "model_name=gpt-5-mini" in caplog.text
    assert "endpoint=/responses" in caplog.text
    assert "error_type=invalid_request_error" in caplog.text
    assert "error_code=unsupported_parameter" in caplog.text
    assert "Unsupported parameter: 'temperature' is not supported with this model." in caplog.text


def test_non_web_search_request_error_does_not_fallback_to_chat(monkeypatch) -> None:
    call_urls: list[str] = []

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        call_urls.append(request.full_url)
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "unsupported_parameter",
                            "message": "temperature is not supported for this request.",
                        }
                    }
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=["known.example"],
            candidate_count=1,
        )

    assert exc_info.value.code == "provider_request"
    assert call_urls == ["https://api.openai.com/v1/responses"]


def test_explicit_tool_enabled_call_does_not_legacy_fallback_on_web_search_unsupported(monkeypatch) -> None:
    call_urls: list[str] = []

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        call_urls.append(request.full_url)
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "unsupported_parameter",
                            "message": "web_search is not supported for this request.",
                        }
                    }
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        timeout_seconds=20,
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=["known.example"],
            candidate_count=1,
            execution_mode="full",
            provider_call_type="tool_enabled",
            web_search_enabled=True,
        )

    assert exc_info.value.code == "provider_request"
    # Service path supplies explicit call-type intent; legacy auto-fallback must not trigger.
    assert call_urls == ["https://api.openai.com/v1/responses"]


def test_structured_provider_logs_include_start_and_complete_trace_fields(monkeypatch, caplog) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(json.dumps(_responses_api_payload(model="gpt-4.1-mini")))

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
        prompt_text_competitor="SENSITIVE_PROMPT_BLOCK",
    )

    with caplog.at_level(logging.INFO):
        provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=1,
            reduced_context_mode=True,
            run_id="run-structured-123",
            attempt_number=2,
            degraded_mode=True,
        )

    structured_events = _structured_event_records(caplog)
    start_event = next(item for item in structured_events if item.get("event") == "competitor_provider_request_start")
    complete_event = next(
        item for item in structured_events if item.get("event") == "competitor_provider_request_complete"
    )

    assert start_event["run_id"] == "run-structured-123"
    assert start_event["attempt_number"] == 2
    assert start_event["endpoint_path"] == "/responses"
    assert start_event["execution_mode"] == "degraded"
    assert start_event["provider_call_type"] == "tool_enabled"
    assert start_event["web_search_enabled"] is True
    assert start_event["degraded_mode"] is True
    assert start_event["reduced_context_mode"] is True
    assert start_event["prompt_chars"] >= 1

    assert complete_event["run_id"] == "run-structured-123"
    assert complete_event["attempt_number"] == 2
    assert complete_event["endpoint_path"] == "/responses"
    assert complete_event["execution_mode"] == "degraded"
    assert complete_event["provider_call_type"] == "tool_enabled"
    assert complete_event["web_search_enabled"] is True
    assert complete_event["degraded_mode"] is True
    assert complete_event["parsed_candidate_count"] == 1
    assert complete_event["discovery_candidate_count"] == 1
    assert complete_event["post_parse_candidate_count"] == 1
    assert complete_event["duration_ms"] >= 0

    assert "SENSITIVE_PROMPT_BLOCK" not in caplog.text
    assert _candidate_json_text() not in caplog.text


def test_structured_provider_logs_include_malformed_reason_without_raw_response_text(monkeypatch, caplog) -> None:
    malformed_response_text = "MALFORMED_RESPONSE_BODY_SHOULD_NOT_BE_LOGGED"

    def _invalid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": malformed_response_text}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _invalid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with caplog.at_level(logging.INFO):
        with pytest.raises(SEOCompetitorProfileProviderError):
            provider.generate_competitor_profiles(
                site=_site(),
                existing_domains=[],
                candidate_count=1,
                run_id="run-malformed-1",
                attempt_number=1,
                degraded_mode=False,
            )

    structured_events = _structured_event_records(caplog)
    error_event = next(item for item in structured_events if item.get("event") == "competitor_provider_request_error")

    assert error_event["run_id"] == "run-malformed-1"
    assert error_event["attempt_number"] == 1
    assert error_event["endpoint_path"] == "/responses"
    assert error_event["execution_mode"] == "full"
    assert error_event["provider_call_type"] == "tool_enabled"
    assert error_event["web_search_enabled"] is True
    assert error_event["failure_kind"] == "malformed_output"
    assert error_event["malformed_output_reason"] == "json_decode_error"
    assert error_event["error_type"] == "invalid_output"
    assert error_event["duration_ms"] >= 0
    assert malformed_response_text not in caplog.text


def test_structured_provider_error_log_includes_endpoint_and_search_metadata(monkeypatch, caplog) -> None:
    def _bad_request_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del timeout
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=BytesIO(
                json.dumps(
                    {
                        "error": {
                            "type": "invalid_request_error",
                            "code": "unsupported_parameter",
                            "message": "web_search is not supported for this request.",
                        }
                    }
                ).encode("utf-8")
            ),
        )

    monkeypatch.setattr(urllib.request, "urlopen", _bad_request_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
        prompt_text_competitor="SENSITIVE_PROVIDER_PROMPT_TEXT",
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(SEOCompetitorProfileProviderError):
            provider.generate_competitor_profiles(
                site=_site(),
                existing_domains=[],
                candidate_count=1,
                run_id="run-provider-error-1",
                attempt_number=1,
                degraded_mode=False,
            )

    structured_events = _structured_event_records(caplog)
    error_event = next(item for item in structured_events if item.get("event") == "competitor_provider_request_error")

    assert error_event["run_id"] == "run-provider-error-1"
    assert error_event["attempt_number"] == 1
    assert error_event["endpoint_path"] == "/responses"
    assert error_event["execution_mode"] == "full"
    assert error_event["provider_call_type"] == "tool_enabled"
    assert error_event["web_search_enabled"] is True
    assert error_event["failure_kind"] == "provider_request"
    assert error_event["error_type"] == "invalid_request_error"
    assert error_event["duration_ms"] >= 0
    assert "SENSITIVE_PROVIDER_PROMPT_TEXT" not in caplog.text


def test_structured_provider_timeout_error_log_includes_timeout_type(monkeypatch, caplog) -> None:
    def _timeout_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _timeout_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.WARNING):
        with pytest.raises(SEOCompetitorProfileProviderError):
            provider.generate_competitor_profiles(
                site=_site(),
                existing_domains=[],
                candidate_count=1,
                run_id="run-timeout-1",
                attempt_number=1,
                degraded_mode=False,
                execution_mode="full",
                provider_call_type="tool_enabled",
            )

    structured_events = _structured_event_records(caplog)
    error_event = next(item for item in structured_events if item.get("event") == "competitor_provider_request_error")
    assert error_event["run_id"] == "run-timeout-1"
    assert error_event["failure_kind"] == "timeout"
    assert error_event["timeout_type"] == "read"


def test_structured_provider_logs_allow_attempt_zero_non_tool_fast_path(monkeypatch, caplog) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/chat/completions")
        return _FakeHTTPResponse(json.dumps(_chat_completions_payload(model="gpt-4.1-mini")))

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with caplog.at_level(logging.INFO):
        provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=1,
            reduced_context_mode=True,
            run_id="run-fast-path-0",
            attempt_number=0,
            degraded_mode=False,
            execution_mode="fast_path",
            provider_call_type="non_tool",
            web_search_enabled=False,
        )

    structured_events = _structured_event_records(caplog)
    start_event = next(item for item in structured_events if item.get("event") == "competitor_provider_request_start")
    complete_event = next(
        item for item in structured_events if item.get("event") == "competitor_provider_request_complete"
    )

    assert start_event["run_id"] == "run-fast-path-0"
    assert start_event["attempt_number"] == 0
    assert start_event["execution_mode"] == "fast_path"
    assert start_event["provider_call_type"] == "non_tool"
    assert start_event["endpoint_path"] == "/chat/completions"
    assert start_event["web_search_enabled"] is False

    assert complete_event["run_id"] == "run-fast-path-0"
    assert complete_event["attempt_number"] == 0
    assert complete_event["execution_mode"] == "fast_path"
    assert complete_event["provider_call_type"] == "non_tool"
    assert complete_event["endpoint_path"] == "/chat/completions"
    assert complete_event["web_search_enabled"] is False
    assert complete_event["duration_ms"] >= 0


def test_structured_candidate_pipeline_log_reports_raw_valid_and_dropped_counts(monkeypatch, caplog) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "ABC",
                    "domain": "abc.com",
                    "competitor_type": "direct",
                    "summary": "valid",
                    "why_competitor": "valid",
                    "evidence": "valid",
                    "confidence_score": 0.9,
                },
                {},
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        assert request.full_url.endswith("/responses")
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-4.1-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=2,
            run_id="run-candidate-pipeline",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) == 1
    structured_events = _structured_event_records(caplog)
    pipeline_event = next(item for item in structured_events if item.get("event") == "competitor_candidate_pipeline")
    assert pipeline_event["run_id"] == "run-candidate-pipeline"
    assert pipeline_event["raw_count"] == 2
    assert pipeline_event["valid_count"] == 1
    assert pipeline_event["dropped_missing_fields"] == 1


def test_malformed_candidate_fields_are_recoverable_warning_with_diagnostics(monkeypatch, caplog) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "ABC",
                    "domain": "abc.com",
                    "competitor_type": "direct",
                    "summary": "valid",
                    "why_competitor": "valid",
                    "evidence": "valid",
                    "confidence_score": 0.9,
                },
                {
                    "name": "Malformed Confidence Candidate",
                    "domain": "malformed-confidence.example",
                    "competitor_type": "direct",
                    "summary": "valid domain and name",
                    "why_competitor": "type drift on confidence",
                    "evidence": "deterministic mismatch",
                    "confidence_score": {"unexpected": "shape"},
                },
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=2,
            run_id="run-schema-drift-recoverable",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) == 2
    structured_events = _structured_event_records(caplog)
    diagnostics_event = next(
        item for item in structured_events if item.get("event") == "competitor_candidate_schema_diagnostics"
    )
    assert diagnostics_event["run_id"] == "run-schema-drift-recoverable"
    assert diagnostics_event["valid_candidate_count"] == 2
    assert diagnostics_event["invalid_candidate_count"] == 1
    assert diagnostics_event["invalid_field_type_count"] == 1
    assert diagnostics_event["invalid_candidate_indexes"] == [1]
    assert diagnostics_event["recoverable"] is True
    invalid_fields = diagnostics_event["invalid_fields"]
    assert isinstance(invalid_fields, list)
    assert invalid_fields
    assert invalid_fields[0]["candidate_index"] == 1
    assert invalid_fields[0]["field_name"] == "confidence_score"
    assert invalid_fields[0]["expected_type"] == "number"
    assert invalid_fields[0]["actual_type"] == "object"
    assert invalid_fields[0]["required_or_optional"] == "required"
    diagnostics_records = [
        record
        for record in caplog.records
        if isinstance(getattr(record, "json_fields", None), dict)
        and record.json_fields.get("event") == "competitor_candidate_schema_diagnostics"
    ]
    assert diagnostics_records
    assert all(record.levelno < logging.ERROR for record in diagnostics_records)


def test_malformed_candidate_diagnostics_capture_multiple_invalid_indexes(monkeypatch, caplog) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "Valid Candidate",
                    "domain": "valid-candidate.example",
                    "competitor_type": "direct",
                    "summary": "valid",
                    "why_competitor": "valid",
                    "evidence": "valid",
                    "confidence_score": 0.8,
                },
                {
                    "name": "Invalid Confidence Dict",
                    "domain": "invalid-confidence-dict.example",
                    "competitor_type": "direct",
                    "summary": "invalid confidence",
                    "why_competitor": "invalid confidence type",
                    "evidence": "dict",
                    "confidence_score": {"raw": "bad"},
                },
                {},
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=3,
            run_id="run-schema-drift-multi",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) >= 1
    structured_events = _structured_event_records(caplog)
    diagnostics_event = next(
        item for item in structured_events if item.get("event") == "competitor_candidate_schema_diagnostics"
    )
    assert diagnostics_event["invalid_candidate_count"] == 2
    assert diagnostics_event["invalid_field_type_count"] >= 2
    assert diagnostics_event["invalid_candidate_indexes"] == [1, 2]


def test_fully_invalid_candidate_entries_emit_error_severity_diagnostics(monkeypatch, caplog) -> None:
    payload = json.dumps({"candidates": [{}, {}]})

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=2,
            run_id="run-schema-drift-unrecoverable",
            attempt_number=1,
            execution_mode="full",
        )

    assert output.candidates == []
    structured_events = _structured_event_records(caplog)
    diagnostics_event = next(
        item for item in structured_events if item.get("event") == "competitor_candidate_schema_diagnostics"
    )
    assert diagnostics_event["valid_candidate_count"] == 0
    assert diagnostics_event["invalid_candidate_count"] == 2
    assert diagnostics_event["invalid_field_type_count"] >= 2
    assert diagnostics_event["recoverable"] is False
    diagnostics_records = [
        record
        for record in caplog.records
        if isinstance(getattr(record, "json_fields", None), dict)
        and record.json_fields.get("event") == "competitor_candidate_schema_diagnostics"
    ]
    assert diagnostics_records
    assert any(record.levelno >= logging.ERROR for record in diagnostics_records)


def test_confidence_score_list_is_normalized_without_invalid_field_type_drift(monkeypatch, caplog) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "Array Confidence Candidate",
                    "domain": "array-confidence.example",
                    "competitor_type": "direct",
                    "summary": "confidence list drift",
                    "why_competitor": "confidence_score as single-item array",
                    "evidence": "deterministic model drift",
                    "confidence_score": ["0.73"],
                }
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=1,
            run_id="run-confidence-array-normalized",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) == 1
    assert output.candidates[0].confidence_score == pytest.approx(0.73)
    structured_events = _structured_event_records(caplog)
    assert not any(
        item.get("event") == "competitor_candidate_schema_diagnostics" for item in structured_events
    )


@pytest.mark.parametrize(
    ("wrapper_key", "expected_score"),
    [
        ("confidence_score", 0.67),
        ("confidence", 0.68),
        ("score", 0.69),
        ("value", 0.70),
    ],
)
def test_confidence_score_object_wrapper_keys_are_normalized_without_diagnostics(
    monkeypatch,
    caplog,
    wrapper_key: str,
    expected_score: float,
) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "Object Confidence Wrapper Candidate",
                    "domain": "object-confidence-wrapper.example",
                    "competitor_type": "direct",
                    "summary": "confidence object wrapper drift",
                    "why_competitor": "tests supported confidence wrapper key normalization",
                    "evidence": "deterministic drift fixture",
                    "confidence_score": {wrapper_key: str(expected_score)},
                }
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=1,
            run_id=f"run-confidence-object-{wrapper_key}",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) == 1
    assert output.candidates[0].confidence_score == pytest.approx(expected_score)
    structured_events = _structured_event_records(caplog)
    assert not any(
        item.get("event") == "competitor_candidate_schema_diagnostics" for item in structured_events
    )


def test_confidence_score_unsupported_object_wrapper_emits_schema_diagnostics(monkeypatch, caplog) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "Unsupported Confidence Wrapper Candidate",
                    "domain": "unsupported-confidence-wrapper.example",
                    "competitor_type": "direct",
                    "summary": "unsupported confidence wrapper",
                    "why_competitor": "should emit diagnostics",
                    "evidence": "deterministic drift fixture",
                    "confidence_score": {"unexpected": "shape"},
                }
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=1,
            run_id="run-confidence-unsupported-object",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) == 1
    structured_events = _structured_event_records(caplog)
    diagnostics_event = next(
        item for item in structured_events if item.get("event") == "competitor_candidate_schema_diagnostics"
    )
    assert diagnostics_event["recoverable"] is True
    assert diagnostics_event["invalid_candidate_count"] == 1
    assert diagnostics_event["invalid_field_type_count"] == 1
    invalid_fields = diagnostics_event["invalid_fields"]
    assert isinstance(invalid_fields, list)
    assert invalid_fields[0]["field_name"] == "confidence_score"
    assert invalid_fields[0]["expected_type"] == "number"
    assert invalid_fields[0]["actual_type"] == "object"


def test_non_confidence_collection_type_drift_emits_schema_diagnostics(monkeypatch, caplog) -> None:
    payload = json.dumps(
        {
            "candidates": [
                {
                    "name": "Non Confidence Drift Candidate",
                    "domain": "non-confidence-drift.example",
                    "competitor_type": "direct",
                    "summary": {"unexpected": "shape"},
                    "why_competitor": "non-confidence malformed field should be visible",
                    "evidence": "deterministic drift fixture",
                    "confidence_score": 0.72,
                }
            ]
        }
    )

    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 30
        return _FakeHTTPResponse(
            json.dumps(
                {
                    "model": "gpt-5-mini",
                    "output": [{"content": [{"type": "output_text", "text": payload}]}],
                }
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", _valid_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-5-mini",
    )

    with caplog.at_level(logging.INFO):
        output = provider.generate_competitor_profiles(
            site=_site(),
            existing_domains=[],
            candidate_count=1,
            run_id="run-non-confidence-drift",
            attempt_number=1,
            execution_mode="full",
        )

    assert len(output.candidates) == 1
    structured_events = _structured_event_records(caplog)
    diagnostics_event = next(
        item for item in structured_events if item.get("event") == "competitor_candidate_schema_diagnostics"
    )
    assert diagnostics_event["recoverable"] is True
    assert diagnostics_event["invalid_candidate_count"] == 1
    assert diagnostics_event["invalid_field_type_count"] == 1
    invalid_fields = diagnostics_event["invalid_fields"]
    assert isinstance(invalid_fields, list)
    assert invalid_fields[0]["field_name"] == "summary"
    assert invalid_fields[0]["expected_type"] == "string|null"
    assert invalid_fields[0]["actual_type"] == "object"
