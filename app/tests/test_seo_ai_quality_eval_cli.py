from __future__ import annotations

from pathlib import Path

import pytest

from app.cli.seo_ai_quality_eval import _build_parser, run_seo_ai_quality_eval
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _fixtures_root() -> Path:
    return Path(__file__).resolve().parent / "fixtures" / "ai_eval"


def test_cli_parser_defaults_to_mock_mode() -> None:
    parser = _build_parser()
    args = parser.parse_args([])
    assert args.mode == "mock"


def test_real_mode_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.delenv("AI_EVAL_ALLOW_REAL_PROVIDER", raising=False)

    with pytest.raises(RuntimeError, match="AI_EVAL_ALLOW_REAL_PROVIDER=true"):
        run_seo_ai_quality_eval(
            pipeline="competitor",
            mode="real",
            fixtures_root=_fixtures_root(),
        )


def test_real_mode_rejects_mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "mock")
    monkeypatch.setenv("AI_EVAL_ALLOW_REAL_PROVIDER", "true")

    with pytest.raises(RuntimeError, match="requires a non-mock AI_PROVIDER_NAME"):
        run_seo_ai_quality_eval(
            pipeline="competitor",
            mode="real",
            fixtures_root=_fixtures_root(),
        )


def test_real_mode_blocked_in_production_like_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROVIDER_NAME", "openai")
    monkeypatch.setenv("AI_PROVIDER_API_KEY", "sk-test")
    monkeypatch.setenv("AI_EVAL_ALLOW_REAL_PROVIDER", "true")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_TOKEN_HASH_PEPPER", "test-pepper")

    with pytest.raises(RuntimeError, match="blocked in production-like environments"):
        run_seo_ai_quality_eval(
            pipeline="competitor",
            mode="real",
            fixtures_root=_fixtures_root(),
        )


def test_mock_mode_report_includes_mode_provider_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_PROMPT_TEXT_COMPETITOR", "SENSITIVE_PROMPT_TEXT")
    summary = run_seo_ai_quality_eval(
        pipeline="competitor",
        mode="mock",
        fixtures_root=_fixtures_root(),
    )
    assert summary["mode"] == "mock"
    report = summary["reports"][0]
    assert report["pipeline"] == "competitor"
    assert report["eval_mode"] == "mock"
    assert report["provider_name"] == "mock"
    assert "model_name" in report
    output_text = str(summary["output_text"])
    assert "mode=mock" in output_text
    assert "provider=mock" in output_text
    assert "SENSITIVE_PROMPT_TEXT" not in output_text


def test_mock_mode_json_output_has_comparable_metadata() -> None:
    summary = run_seo_ai_quality_eval(
        pipeline="all",
        mode="mock",
        fixtures_root=_fixtures_root(),
        json_output=True,
    )
    assert summary["mode"] == "mock"
    assert len(summary["reports"]) == 2
    for report in summary["reports"]:
        assert report["eval_mode"] == "mock"
        assert "provider_name" in report
        assert "model_name" in report
        assert "aggregate_score" in report


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode must be 'mock' or 'real'"):
        run_seo_ai_quality_eval(
            pipeline="competitor",
            mode="invalid",
            fixtures_root=_fixtures_root(),
        )
