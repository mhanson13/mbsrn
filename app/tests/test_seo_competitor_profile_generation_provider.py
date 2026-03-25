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


def test_openai_provider_parses_structured_response(monkeypatch) -> None:
    captured_payload: dict[str, object] = {}

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 20
        request_body = request.data.decode("utf-8") if isinstance(request.data, bytes) else "{}"
        captured_payload.update(json.loads(request_body))
        response = {
            "model": "gpt-4.1-mini-2026-01-01",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
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
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

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
    assert output.raw_response is not None
    assert len(output.candidates) == 1
    assert output.candidates[0].suggested_name == "Competitor One"
    assert output.candidates[0].suggested_domain == "competitor-one.example"
    assert captured_payload["model"] == "gpt-4.1-mini"
    assert captured_payload["temperature"] == 0
    assert captured_payload["response_format"]["type"] == "json_schema"


def test_openai_provider_omits_temperature_for_gpt5_mini(monkeypatch) -> None:
    captured_payload: dict[str, object] = {}

    def _fake_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert timeout == 20
        request_body = request.data.decode("utf-8") if isinstance(request.data, bytes) else "{}"
        captured_payload.update(json.loads(request_body))
        response = {
            "model": "gpt-5-mini-2026-01-01",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
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
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

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

    assert output.provider_name == "openai"
    assert output.model_name == "gpt-5-mini-2026-01-01"
    assert captured_payload["model"] == "gpt-5-mini"
    assert "temperature" not in captured_payload
    assert captured_payload["response_format"]["type"] == "json_schema"


def test_openai_provider_timeout_is_normalized(monkeypatch) -> None:
    def _timeout_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise TimeoutError("timeout")

    monkeypatch.setattr(urllib.request, "urlopen", _timeout_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "timeout"


def test_openai_provider_auth_error_is_normalized(monkeypatch) -> None:
    def _unauthorized_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
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
    def _invalid_content_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [{"message": {"content": "not-json"}}],
        }
        return _FakeHTTPResponse(json.dumps(response))

    monkeypatch.setattr(urllib.request, "urlopen", _invalid_content_urlopen)
    provider = OpenAISEOCompetitorProfileGenerationProvider(
        api_key="sk-test",
        model_name="gpt-4.1-mini",
    )

    with pytest.raises(SEOCompetitorProfileProviderError) as exc_info:
        provider.generate_competitor_profiles(site=_site(), existing_domains=[], candidate_count=1)

    assert exc_info.value.code == "invalid_output"


def test_openai_provider_logs_prompt_resolution_without_raw_prompt_text(monkeypatch, caplog) -> None:
    def _valid_urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
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
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

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
        response = {
            "model": "gpt-4.1-mini",
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
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
                    }
                }
            ],
        }
        return _FakeHTTPResponse(json.dumps(response))

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
        del request, timeout
        raise urllib.error.HTTPError(
            url="https://api.openai.com/v1/chat/completions",
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
    assert "SEO competitor provider HTTP error status=400" in caplog.text
    assert "model_name=gpt-5-mini" in caplog.text
    assert "error_type=invalid_request_error" in caplog.text
    assert "error_code=unsupported_parameter" in caplog.text
    assert "Unsupported parameter: 'temperature' is not supported with this model." in caplog.text
