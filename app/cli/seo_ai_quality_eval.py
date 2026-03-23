from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

from app.api.deps import (
    get_seo_competitor_profile_generation_provider,
    get_seo_recommendation_narrative_provider,
)
from app.core.config import Settings, get_settings
from app.integrations import (
    MisconfiguredSEOCompetitorProfileGenerationProvider,
    MisconfiguredSEORecommendationNarrativeProvider,
    MockSEOCompetitorProfileGenerationProvider,
    MockSEORecommendationNarrativeProvider,
)
from app.services.seo_ai_evaluation_harness import (
    format_eval_reports_text,
    load_competitor_eval_cases,
    load_recommendation_eval_cases,
    reports_to_json,
    run_competitor_eval,
    run_recommendation_eval,
)
from app.services.seo_competitor_profile_prompt import SEO_COMPETITOR_PROFILE_PROMPT_VERSION
from app.services.seo_recommendation_narrative_prompt import SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION


logger = logging.getLogger(__name__)


def run_seo_ai_quality_eval(
    *,
    pipeline: str,
    fixtures_root: Path,
    mode: str,
    json_output: bool = False,
) -> dict[str, object]:
    settings = get_settings()
    competitor_provider, recommendation_provider = _resolve_eval_providers(
        mode=mode,
        settings=settings,
        pipeline=pipeline,
    )
    reports = []
    if pipeline in {"competitor", "all"}:
        competitor_cases = load_competitor_eval_cases(fixtures_root)
        if competitor_provider is None:
            raise RuntimeError("Competitor evaluation provider could not be resolved.")
        reports.append(run_competitor_eval(cases=competitor_cases, provider=competitor_provider, eval_mode=mode))
    if pipeline in {"recommendations", "all"}:
        recommendation_cases = load_recommendation_eval_cases(fixtures_root)
        if recommendation_provider is None:
            raise RuntimeError("Recommendation evaluation provider could not be resolved.")
        reports.append(
            run_recommendation_eval(
                cases=recommendation_cases,
                provider=recommendation_provider,
                eval_mode=mode,
            )
        )

    output_text = reports_to_json(reports) if json_output else format_eval_reports_text(reports)
    has_failure = any(report.failed_cases > 0 for report in reports)
    logger.info(
        "seo_ai_quality_eval_completed mode=%s pipeline=%s reports=%s has_failure=%s",
        mode,
        pipeline,
        len(reports),
        has_failure,
    )
    return {
        "pipeline": pipeline,
        "mode": mode,
        "fixtures_root": str(fixtures_root),
        "reports": [report.to_dict() for report in reports],
        "output_text": output_text,
        "has_failure": has_failure,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seo-ai-quality-eval",
        description="Run fixture-based AI quality evaluations for SEO competitor and recommendation pipelines.",
    )
    parser.add_argument(
        "--pipeline",
        choices=("competitor", "recommendations", "all"),
        default="all",
        help="Pipeline to evaluate.",
    )
    parser.add_argument(
        "--mode",
        choices=("mock", "real"),
        default="mock",
        help=(
            "Evaluation mode. mock is deterministic and CI-safe. "
            "real invokes configured external provider and requires explicit opt-in."
        ),
    )
    parser.add_argument(
        "--fixtures-root",
        default=str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ai_eval"),
        help="Directory containing competitor_cases.json and recommendation_cases.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output instead of plain text summary.",
    )
    parser.add_argument(
        "--output-file",
        help="Optional file path to write summary output (text or JSON based on --json).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        summary = run_seo_ai_quality_eval(
            pipeline=str(args.pipeline),
            mode=str(args.mode),
            fixtures_root=Path(str(args.fixtures_root)),
            json_output=bool(args.json),
        )
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    output_text = str(summary["output_text"])
    print(output_text)
    if args.output_file:
        output_path = Path(str(args.output_file))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
    return 1 if bool(summary["has_failure"]) else 0


def _resolve_eval_providers(*, mode: str, settings: Settings, pipeline: str):
    competitor_provider = None
    recommendation_provider = None

    if mode == "mock":
        if pipeline in {"competitor", "all"}:
            competitor_provider = MockSEOCompetitorProfileGenerationProvider(
                provider_name="mock",
                model_name="mock-seo-competitor-profile-v1",
                prompt_version=SEO_COMPETITOR_PROFILE_PROMPT_VERSION,
            )
        if pipeline in {"recommendations", "all"}:
            recommendation_provider = MockSEORecommendationNarrativeProvider(
                provider_name="mock",
                model_name="mock-seo-recommendation-narrative-v1",
                prompt_version=SEO_RECOMMENDATION_NARRATIVE_PROMPT_VERSION,
            )
        return competitor_provider, recommendation_provider

    if mode != "real":
        raise ValueError("mode must be 'mock' or 'real'.")

    _assert_real_mode_allowed(settings=settings)
    if pipeline in {"competitor", "all"}:
        competitor_provider = get_seo_competitor_profile_generation_provider()
        _assert_real_provider_ready(
            provider=competitor_provider,
            pipeline="competitor",
            settings=settings,
        )
    if pipeline in {"recommendations", "all"}:
        recommendation_provider = get_seo_recommendation_narrative_provider()
        _assert_real_provider_ready(
            provider=recommendation_provider,
            pipeline="recommendations",
            settings=settings,
        )
    logger.info(
        "seo_ai_quality_eval_real_mode_enabled provider=%s model=%s",
        settings.ai_provider_name,
        settings.ai_model_name,
    )
    return competitor_provider, recommendation_provider


def _assert_real_mode_allowed(*, settings: Settings) -> None:
    if not settings.ai_eval_allow_real_provider:
        raise RuntimeError(
            "Real-provider eval is disabled. Set AI_EVAL_ALLOW_REAL_PROVIDER=true and rerun with --mode real."
        )
    if _is_production_like_environment(settings=settings):
        raise RuntimeError(
            "Real-provider eval is blocked in production-like environments."
        )
    if (settings.ai_provider_name or "").strip().lower() == "mock":
        raise RuntimeError("Real-provider eval requires a non-mock AI_PROVIDER_NAME.")


def _is_production_like_environment(*, settings: Settings) -> bool:
    markers = {
        (settings.environment or "").strip().lower(),
        (settings.app_env or "").strip().lower(),
    }
    return bool(markers & {"production", "prod"})


def _assert_real_provider_ready(*, provider: object, pipeline: str, settings: Settings) -> None:
    if isinstance(
        provider,
        (MisconfiguredSEOCompetitorProfileGenerationProvider, MisconfiguredSEORecommendationNarrativeProvider),
    ):
        raise RuntimeError(
            f"Real-provider eval cannot start for {pipeline}: provider is misconfigured for '{settings.ai_provider_name}'."
        )
    provider_name = str(getattr(provider, "provider_name", "") or "").strip().lower()
    if not provider_name or provider_name == "mock":
        raise RuntimeError(
            f"Real-provider eval cannot start for {pipeline}: resolved provider is '{provider_name or 'unknown'}'."
        )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
