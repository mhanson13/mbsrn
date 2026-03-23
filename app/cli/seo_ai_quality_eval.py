from __future__ import annotations

import argparse
from pathlib import Path
import sys

from app.api.deps import (
    get_seo_competitor_profile_generation_provider,
    get_seo_recommendation_narrative_provider,
)
from app.services.seo_ai_evaluation_harness import (
    format_eval_reports_text,
    load_competitor_eval_cases,
    load_recommendation_eval_cases,
    reports_to_json,
    run_competitor_eval,
    run_recommendation_eval,
)


def run_seo_ai_quality_eval(
    *,
    pipeline: str,
    fixtures_root: Path,
    json_output: bool = False,
) -> dict[str, object]:
    reports = []
    if pipeline in {"competitor", "all"}:
        competitor_cases = load_competitor_eval_cases(fixtures_root)
        competitor_provider = get_seo_competitor_profile_generation_provider()
        reports.append(run_competitor_eval(cases=competitor_cases, provider=competitor_provider))
    if pipeline in {"recommendations", "all"}:
        recommendation_cases = load_recommendation_eval_cases(fixtures_root)
        recommendation_provider = get_seo_recommendation_narrative_provider()
        reports.append(run_recommendation_eval(cases=recommendation_cases, provider=recommendation_provider))

    output_text = reports_to_json(reports) if json_output else format_eval_reports_text(reports)
    has_failure = any(report.failed_cases > 0 for report in reports)
    return {
        "pipeline": pipeline,
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
        "--fixtures-root",
        default=str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "ai_eval"),
        help="Directory containing competitor_cases.json and recommendation_cases.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print JSON output instead of plain text summary.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    summary = run_seo_ai_quality_eval(
        pipeline=str(args.pipeline),
        fixtures_root=Path(str(args.fixtures_root)),
        json_output=bool(args.json),
    )
    print(summary["output_text"])
    return 1 if bool(summary["has_failure"]) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
