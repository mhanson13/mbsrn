from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path

from app.integrations.seo_summary_provider import (
    SEOCompetitorProfileDraftCandidateOutput,
    SEOCompetitorProfileGenerationOutput,
    SEOCompetitorProfileGenerationProvider,
    SEORecommendationNarrativeOutput,
    SEORecommendationNarrativeProvider,
)
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.models.seo_site import SEOSite
from app.services.seo_competitor_profile_candidate_quality import (
    DEFAULT_BIG_BOX_PENALTY,
    DEFAULT_DIRECTORY_PENALTY,
    DEFAULT_LOCAL_ALIGNMENT_BONUS,
    DEFAULT_MIN_RELEVANCE_SCORE,
)


COMPETITOR_FIXTURE_FILE_NAME = "competitor_cases.json"
RECOMMENDATION_FIXTURE_FILE_NAME = "recommendation_cases.json"

COMPETITOR_PASS_THRESHOLD = 70
RECOMMENDATION_PASS_THRESHOLD = 70

_DEFAULT_FORBIDDEN_COMPETITOR_DOMAIN_SUBSTRINGS = (
    "yelp",
    "angi",
    "homeadvisor",
    "thumbtack",
    "yellowpages",
    "facebook",
    "instagram",
    "linkedin",
    "wikipedia",
    "reddit",
    "youtube",
)
_DEFAULT_GENERIC_RECOMMENDATION_PHRASES = (
    "as an ai language model",
    "lorem ipsum",
    "improve seo",
    "optimize your website",
    "best practices",
)


@dataclass(frozen=True)
class CompetitorEvalExpected:
    required_location_terms_any: list[str] = field(default_factory=list)
    required_service_terms_any: list[str] = field(default_factory=list)
    forbidden_domains: list[str] = field(default_factory=list)
    forbidden_domain_substrings: list[str] = field(default_factory=list)
    forbidden_competitor_types: list[str] = field(default_factory=list)
    known_good_domains_any: list[str] = field(default_factory=list)
    min_candidate_count: int = 1
    max_candidate_count: int = 5


@dataclass(frozen=True)
class CompetitorEvalInput:
    business_id: str
    site: SEOSite
    existing_domains: list[str]
    candidate_count: int


@dataclass(frozen=True)
class CompetitorEvalCase:
    case_id: str
    description: str
    input: CompetitorEvalInput
    expected: CompetitorEvalExpected


@dataclass(frozen=True)
class RecommendationEvalExpected:
    must_address_topics: list[str] = field(default_factory=list)
    forbidden_phrases: list[str] = field(default_factory=list)
    required_recommendation_ids_any: list[str] = field(default_factory=list)
    require_recommendation_references: bool = False
    max_next_actions: int = 8
    expect_non_empty_themes: bool = True
    min_narrative_chars: int = 80


@dataclass(frozen=True)
class RecommendationEvalInput:
    run: SEORecommendationRun
    recommendations: list[SEORecommendation]
    backlog_ids: list[str]
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_severity: dict[str, int]
    by_effort_bucket: dict[str, int]
    by_priority_band: dict[str, int]
    competitor_telemetry_summary: dict[str, object]
    current_tuning_values: dict[str, int]


@dataclass(frozen=True)
class RecommendationEvalCase:
    case_id: str
    description: str
    input: RecommendationEvalInput
    expected: RecommendationEvalExpected


@dataclass(frozen=True)
class EvalCaseResult:
    pipeline: str
    case_id: str
    description: str
    score: int
    passed: bool
    reasons: list[str]
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class EvalPipelineReport:
    pipeline: str
    eval_mode: str
    provider_name: str
    model_name: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    aggregate_score: float
    results: list[EvalCaseResult]

    def to_dict(self) -> dict[str, object]:
        return {
            "pipeline": self.pipeline,
            "eval_mode": self.eval_mode,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "aggregate_score": self.aggregate_score,
            "results": [asdict(item) for item in self.results],
        }


def load_competitor_eval_cases(fixtures_root: Path) -> list[CompetitorEvalCase]:
    payload = _load_cases_payload(fixtures_root / COMPETITOR_FIXTURE_FILE_NAME)
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("competitor fixture payload must include a 'cases' list.")

    cases: list[CompetitorEvalCase] = []
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise ValueError(f"competitor case at index {index} must be an object.")
        case_id = _require_str(raw_case, "case_id", f"competitor[{index}]")
        description = _require_str(raw_case, "description", f"competitor[{index}]")
        input_payload = _require_dict(raw_case, "input", f"competitor[{index}]")
        expected_payload = _require_dict(raw_case, "expected", f"competitor[{index}]")

        site_payload = _require_dict(input_payload, "site", f"competitor[{index}].input")
        site = SEOSite(
            id=_optional_str(site_payload.get("id")) or f"eval-site-{case_id}",
            business_id=_optional_str(input_payload.get("business_id")) or "eval-business",
            display_name=_require_str(site_payload, "display_name", f"competitor[{index}].input.site"),
            base_url=_require_str(site_payload, "base_url", f"competitor[{index}].input.site"),
            normalized_domain=_require_str(site_payload, "normalized_domain", f"competitor[{index}].input.site"),
            industry=_optional_str(site_payload.get("industry")),
            primary_location=_optional_str(site_payload.get("primary_location")),
            service_areas_json=_optional_list_of_str(site_payload.get("service_areas")),
            is_active=True,
            is_primary=False,
        )
        eval_input = CompetitorEvalInput(
            business_id=_optional_str(input_payload.get("business_id")) or site.business_id,
            site=site,
            existing_domains=_optional_list_of_str(input_payload.get("existing_domains")),
            candidate_count=_coerce_int(
                input_payload.get("candidate_count"),
                f"competitor[{index}].input.candidate_count",
                minimum=1,
                maximum=20,
                default=5,
            ),
        )
        expected = CompetitorEvalExpected(
            required_location_terms_any=_optional_list_of_str(expected_payload.get("required_location_terms_any")),
            required_service_terms_any=_optional_list_of_str(expected_payload.get("required_service_terms_any")),
            forbidden_domains=_optional_list_of_str(expected_payload.get("forbidden_domains")),
            forbidden_domain_substrings=_optional_list_of_str(expected_payload.get("forbidden_domain_substrings"))
            or list(_DEFAULT_FORBIDDEN_COMPETITOR_DOMAIN_SUBSTRINGS),
            forbidden_competitor_types=_optional_list_of_str(expected_payload.get("forbidden_competitor_types")),
            known_good_domains_any=_optional_list_of_str(expected_payload.get("known_good_domains_any")),
            min_candidate_count=_coerce_int(
                expected_payload.get("min_candidate_count"),
                f"competitor[{index}].expected.min_candidate_count",
                minimum=1,
                maximum=20,
                default=1,
            ),
            max_candidate_count=_coerce_int(
                expected_payload.get("max_candidate_count"),
                f"competitor[{index}].expected.max_candidate_count",
                minimum=1,
                maximum=20,
                default=5,
            ),
        )
        if expected.min_candidate_count > expected.max_candidate_count:
            raise ValueError(
                f"competitor[{index}].expected.min_candidate_count cannot exceed max_candidate_count."
            )
        cases.append(
            CompetitorEvalCase(
                case_id=case_id,
                description=description,
                input=eval_input,
                expected=expected,
            )
        )
    return cases


def load_recommendation_eval_cases(fixtures_root: Path) -> list[RecommendationEvalCase]:
    payload = _load_cases_payload(fixtures_root / RECOMMENDATION_FIXTURE_FILE_NAME)
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("recommendation fixture payload must include a 'cases' list.")

    cases: list[RecommendationEvalCase] = []
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise ValueError(f"recommendation case at index {index} must be an object.")
        case_id = _require_str(raw_case, "case_id", f"recommendations[{index}]")
        description = _require_str(raw_case, "description", f"recommendations[{index}]")
        input_payload = _require_dict(raw_case, "input", f"recommendations[{index}]")
        expected_payload = _require_dict(raw_case, "expected", f"recommendations[{index}]")

        business_id = _optional_str(input_payload.get("business_id")) or "eval-business"
        site_id = _optional_str(input_payload.get("site_id")) or f"eval-site-{case_id}"
        run_payload = _require_dict(input_payload, "run", f"recommendations[{index}].input")
        run = SEORecommendationRun(
            id=_optional_str(run_payload.get("id")) or f"eval-run-{case_id}",
            business_id=business_id,
            site_id=site_id,
            audit_run_id=_optional_str(run_payload.get("audit_run_id")) or f"eval-audit-{case_id}",
            comparison_run_id=_optional_str(run_payload.get("comparison_run_id")),
            status=_optional_str(run_payload.get("status")) or "completed",
            total_recommendations=_coerce_int(
                run_payload.get("total_recommendations"),
                f"recommendations[{index}].input.run.total_recommendations",
                minimum=0,
                maximum=500,
                default=0,
            ),
            critical_recommendations=_coerce_int(
                run_payload.get("critical_recommendations"),
                f"recommendations[{index}].input.run.critical_recommendations",
                minimum=0,
                maximum=500,
                default=0,
            ),
            warning_recommendations=_coerce_int(
                run_payload.get("warning_recommendations"),
                f"recommendations[{index}].input.run.warning_recommendations",
                minimum=0,
                maximum=500,
                default=0,
            ),
            info_recommendations=_coerce_int(
                run_payload.get("info_recommendations"),
                f"recommendations[{index}].input.run.info_recommendations",
                minimum=0,
                maximum=500,
                default=0,
            ),
        )
        recommendations_payload = input_payload.get("recommendations")
        if not isinstance(recommendations_payload, list) or not recommendations_payload:
            raise ValueError(f"recommendations[{index}].input.recommendations must be a non-empty list.")
        recommendations = _build_recommendations(
            recommendations_payload=recommendations_payload,
            business_id=business_id,
            site_id=site_id,
            run_id=run.id,
            case_path=f"recommendations[{index}].input.recommendations",
        )
        backlog_ids = _optional_list_of_str(input_payload.get("backlog_ids"))
        if not backlog_ids:
            backlog_ids = [
                item.id
                for item in sorted(
                    recommendations,
                    key=lambda rec: (-int(rec.priority_score or 0), rec.id),
                )
                if item.status in {"open", "in_progress"}
            ]
        rollups = _build_rollups(recommendations)

        eval_input = RecommendationEvalInput(
            run=run,
            recommendations=recommendations,
            backlog_ids=backlog_ids,
            by_status=_optional_count_map(input_payload.get("by_status")) or rollups["by_status"],
            by_category=_optional_count_map(input_payload.get("by_category")) or rollups["by_category"],
            by_severity=_optional_count_map(input_payload.get("by_severity")) or rollups["by_severity"],
            by_effort_bucket=_optional_count_map(input_payload.get("by_effort_bucket")) or rollups["by_effort_bucket"],
            by_priority_band=_optional_count_map(input_payload.get("by_priority_band")) or rollups["by_priority_band"],
            competitor_telemetry_summary=_optional_dict(input_payload.get("competitor_telemetry_summary"))
            or {
                "lookback_days": 30,
                "total_runs": 1,
                "total_raw_candidate_count": 10,
                "total_included_candidate_count": 7,
                "total_excluded_candidate_count": 3,
                "exclusion_counts_by_reason": {},
            },
            current_tuning_values=_optional_int_map(input_payload.get("current_tuning_values"))
            or {
                "competitor_candidate_min_relevance_score": DEFAULT_MIN_RELEVANCE_SCORE,
                "competitor_candidate_big_box_penalty": DEFAULT_BIG_BOX_PENALTY,
                "competitor_candidate_directory_penalty": DEFAULT_DIRECTORY_PENALTY,
                "competitor_candidate_local_alignment_bonus": DEFAULT_LOCAL_ALIGNMENT_BONUS,
            },
        )
        expected = RecommendationEvalExpected(
            must_address_topics=_optional_list_of_str(expected_payload.get("must_address_topics")),
            forbidden_phrases=_optional_list_of_str(expected_payload.get("forbidden_phrases"))
            or list(_DEFAULT_GENERIC_RECOMMENDATION_PHRASES),
            required_recommendation_ids_any=_optional_list_of_str(
                expected_payload.get("required_recommendation_ids_any")
            ),
            require_recommendation_references=bool(expected_payload.get("require_recommendation_references", False)),
            max_next_actions=_coerce_int(
                expected_payload.get("max_next_actions"),
                f"recommendations[{index}].expected.max_next_actions",
                minimum=1,
                maximum=20,
                default=8,
            ),
            expect_non_empty_themes=bool(expected_payload.get("expect_non_empty_themes", True)),
            min_narrative_chars=_coerce_int(
                expected_payload.get("min_narrative_chars"),
                f"recommendations[{index}].expected.min_narrative_chars",
                minimum=1,
                maximum=2000,
                default=80,
            ),
        )
        cases.append(
            RecommendationEvalCase(
                case_id=case_id,
                description=description,
                input=eval_input,
                expected=expected,
            )
        )
    return cases

def run_competitor_eval(
    *,
    cases: list[CompetitorEvalCase],
    provider: SEOCompetitorProfileGenerationProvider,
    eval_mode: str = "mock",
    pass_threshold: int = COMPETITOR_PASS_THRESHOLD,
) -> EvalPipelineReport:
    results: list[EvalCaseResult] = []
    provider_name = _provider_name(provider, default="unknown-provider")
    model_name = _provider_model_name(provider, default="unknown-model")
    for case in cases:
        try:
            output = provider.generate_competitor_profiles(
                site=case.input.site,
                existing_domains=case.input.existing_domains,
                candidate_count=case.input.candidate_count,
            )
            score, reasons, hard_fail = score_competitor_output(
                output=output,
                case=case,
            )
            passed = score >= pass_threshold and not hard_fail
            metadata = {
                "candidate_count": len(output.candidates),
                "model_name": output.model_name,
                "provider_name": output.provider_name,
                "prompt_version": output.prompt_version,
            }
        except Exception as exc:  # noqa: BLE001
            score = 0
            reasons = [f"provider_error:{type(exc).__name__}"]
            passed = False
            metadata = {"candidate_count": 0}
        results.append(
            EvalCaseResult(
                pipeline="competitor",
                case_id=case.case_id,
                description=case.description,
                score=score,
                passed=passed,
                reasons=reasons,
                metadata=metadata,
            )
        )
    return _build_report(
        "competitor",
        results,
        eval_mode=eval_mode,
        provider_name=provider_name,
        model_name=model_name,
    )


def run_recommendation_eval(
    *,
    cases: list[RecommendationEvalCase],
    provider: SEORecommendationNarrativeProvider,
    eval_mode: str = "mock",
    pass_threshold: int = RECOMMENDATION_PASS_THRESHOLD,
) -> EvalPipelineReport:
    results: list[EvalCaseResult] = []
    provider_name = _provider_name(provider, default="unknown-provider")
    model_name = _provider_model_name(provider, default="unknown-model")
    for case in cases:
        try:
            backlog = _build_backlog(case.input.recommendations, case.input.backlog_ids)
            output = provider.generate_narrative(
                run=case.input.run,
                recommendations=case.input.recommendations,
                by_status=case.input.by_status,
                by_category=case.input.by_category,
                by_severity=case.input.by_severity,
                by_effort_bucket=case.input.by_effort_bucket,
                by_priority_band=case.input.by_priority_band,
                backlog=backlog,
                competitor_telemetry_summary=case.input.competitor_telemetry_summary,
                current_tuning_values=case.input.current_tuning_values,
            )
            score, reasons, hard_fail = score_recommendation_output(
                output=output,
                case=case,
            )
            passed = score >= pass_threshold and not hard_fail
            metadata = {
                "model_name": output.model_name,
                "provider_name": output.provider_name,
                "prompt_version": output.prompt_version,
            }
        except Exception as exc:  # noqa: BLE001
            score = 0
            reasons = [f"provider_error:{type(exc).__name__}"]
            passed = False
            metadata = {}
        results.append(
            EvalCaseResult(
                pipeline="recommendations",
                case_id=case.case_id,
                description=case.description,
                score=score,
                passed=passed,
                reasons=reasons,
                metadata=metadata,
            )
        )
    return _build_report(
        "recommendations",
        results,
        eval_mode=eval_mode,
        provider_name=provider_name,
        model_name=model_name,
    )


def score_competitor_output(
    *,
    output: SEOCompetitorProfileGenerationOutput,
    case: CompetitorEvalCase,
) -> tuple[int, list[str], bool]:
    reasons: list[str] = []
    hard_fail = False
    score = 100
    candidates = output.candidates
    expected = case.expected

    if len(candidates) < expected.min_candidate_count:
        score -= 20
        reasons.append("too_few_candidates")
    if len(candidates) > expected.max_candidate_count:
        score -= 10
        reasons.append("too_many_candidates")

    site_domain = _normalize_domain(case.input.site.normalized_domain)
    existing_domains = {_normalize_domain(value) for value in case.input.existing_domains}
    forbidden_domains = {_normalize_domain(value) for value in expected.forbidden_domains}
    forbidden_substrings = {
        value.strip().lower()
        for value in expected.forbidden_domain_substrings
        if value and value.strip()
    }
    forbidden_types = {
        value.strip().lower()
        for value in expected.forbidden_competitor_types
        if value and value.strip()
    }
    known_good_domains = {_normalize_domain(value) for value in expected.known_good_domains_any}

    combined_text: list[str] = []
    known_good_found = False
    for candidate in candidates:
        domain = _normalize_domain(candidate.suggested_domain)
        combined_text.append(_candidate_combined_text(candidate))
        if domain in forbidden_domains:
            score -= 40
            hard_fail = True
            reasons.append(f"forbidden_domain:{domain}")
        if domain == site_domain or domain in existing_domains:
            score -= 35
            hard_fail = True
            reasons.append(f"existing_or_site_domain:{domain}")
        for substring in forbidden_substrings:
            if substring and substring in domain:
                score -= 25
                hard_fail = True
                reasons.append(f"forbidden_domain_substring:{substring}")
                break
        candidate_type = (candidate.competitor_type or "").strip().lower()
        if candidate_type and candidate_type in forbidden_types:
            score -= 20
            reasons.append(f"forbidden_type:{candidate_type}")
        if domain in known_good_domains:
            known_good_found = True

    if known_good_domains and known_good_found:
        score += 10
        reasons.append("known_good_domain_match")

    text_blob = "\n".join(combined_text).lower()
    if expected.required_location_terms_any:
        if not _contains_any_term(text_blob, expected.required_location_terms_any):
            score -= 20
            reasons.append("missing_required_location_signal")
    if expected.required_service_terms_any:
        if not _contains_any_term(text_blob, expected.required_service_terms_any):
            score -= 20
            reasons.append("missing_required_service_signal")

    return _clamp_score(score), _dedupe_preserve_order(reasons), hard_fail


def score_recommendation_output(
    *,
    output: SEORecommendationNarrativeOutput,
    case: RecommendationEvalCase,
) -> tuple[int, list[str], bool]:
    reasons: list[str] = []
    hard_fail = False
    score = 100
    expected = case.expected
    sections = output.sections if isinstance(output.sections, dict) else {}

    narrative_text = _normalize_whitespace(output.narrative_text)
    top_themes = _normalize_string_list(output.top_themes)
    next_actions = _normalize_string_list(sections.get("next_actions"))
    references = {
        value.strip()
        for value in _normalize_string_list(sections.get("recommendation_references"))
        if value.strip()
    }
    corpus = "\n".join([narrative_text, *top_themes, *next_actions]).lower()

    if len(narrative_text) < expected.min_narrative_chars:
        score -= 15
        reasons.append("narrative_too_short")
    if expected.expect_non_empty_themes and not top_themes:
        score -= 15
        reasons.append("missing_top_themes")
    if len(next_actions) > expected.max_next_actions:
        score -= 10
        reasons.append("too_many_next_actions")

    for phrase in expected.forbidden_phrases:
        normalized_phrase = phrase.strip().lower()
        if normalized_phrase and normalized_phrase in corpus:
            score -= 25
            reasons.append(f"generic_phrase:{normalized_phrase}")
            hard_fail = True

    missing_topics = [
        topic
        for topic in expected.must_address_topics
        if topic.strip() and topic.strip().lower() not in corpus
    ]
    if missing_topics:
        score -= min(45, len(missing_topics) * 15)
        reasons.append("missing_topics:" + ",".join(sorted({topic.lower() for topic in missing_topics})))

    if expected.require_recommendation_references and not references:
        score -= 20
        reasons.append("missing_recommendation_references")
    if expected.required_recommendation_ids_any:
        expected_ids = {value.strip() for value in expected.required_recommendation_ids_any if value.strip()}
        if expected_ids and references.isdisjoint(expected_ids):
            score -= 20
            reasons.append("missing_expected_reference_ids")

    if _has_duplicates(top_themes):
        score -= 10
        reasons.append("duplicate_top_themes")
    if _has_duplicates(next_actions):
        score -= 10
        reasons.append("duplicate_next_actions")

    return _clamp_score(score), _dedupe_preserve_order(reasons), hard_fail


def format_eval_report_text(report: EvalPipelineReport) -> str:
    lines = [
        (
            f"[{report.pipeline}] mode={report.eval_mode} provider={report.provider_name} model={report.model_name} "
            f"total={report.total_cases} passed={report.passed_cases} "
            f"failed={report.failed_cases} aggregate_score={report.aggregate_score:.1f}"
        ),
        "case_id | status | score | reasons",
    ]
    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        reasons = ", ".join(result.reasons[:3]) if result.reasons else "ok"
        lines.append(f"{result.case_id} | {status} | {result.score} | {reasons}")
    return "\n".join(lines)


def format_eval_reports_text(reports: list[EvalPipelineReport]) -> str:
    if not reports:
        return "No evaluation reports generated."
    return "\n\n".join(format_eval_report_text(report) for report in reports)


def reports_to_json(reports: list[EvalPipelineReport]) -> str:
    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "reports": [report.to_dict() for report in reports],
    }
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)

def _build_report(
    pipeline: str,
    results: list[EvalCaseResult],
    *,
    eval_mode: str,
    provider_name: str,
    model_name: str,
) -> EvalPipelineReport:
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    failed = total - passed
    aggregate_score = round(sum(item.score for item in results) / total, 2) if total else 0.0
    return EvalPipelineReport(
        pipeline=pipeline,
        eval_mode=eval_mode,
        provider_name=provider_name,
        model_name=model_name,
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        aggregate_score=aggregate_score,
        results=results,
    )


def _build_recommendations(
    *,
    recommendations_payload: list[object],
    business_id: str,
    site_id: str,
    run_id: str,
    case_path: str,
) -> list[SEORecommendation]:
    recommendations: list[SEORecommendation] = []
    for index, raw_recommendation in enumerate(recommendations_payload):
        if not isinstance(raw_recommendation, dict):
            raise ValueError(f"{case_path}[{index}] must be an object.")
        recommendation = SEORecommendation(
            id=_require_str(raw_recommendation, "id", f"{case_path}[{index}]"),
            business_id=business_id,
            site_id=site_id,
            recommendation_run_id=run_id,
            audit_run_id=_optional_str(raw_recommendation.get("audit_run_id")) or f"{run_id}-audit",
            comparison_run_id=_optional_str(raw_recommendation.get("comparison_run_id")),
            rule_key=_require_str(raw_recommendation, "rule_key", f"{case_path}[{index}]"),
            category=_require_str(raw_recommendation, "category", f"{case_path}[{index}]"),
            severity=_require_str(raw_recommendation, "severity", f"{case_path}[{index}]"),
            title=_require_str(raw_recommendation, "title", f"{case_path}[{index}]"),
            rationale=_require_str(raw_recommendation, "rationale", f"{case_path}[{index}]"),
            priority_score=_coerce_int(
                raw_recommendation.get("priority_score"),
                f"{case_path}[{index}].priority_score",
                minimum=0,
                maximum=1000,
                default=0,
            ),
            priority_band=_optional_str(raw_recommendation.get("priority_band")) or "medium",
            effort_bucket=_optional_str(raw_recommendation.get("effort_bucket")) or "MEDIUM",
            status=_optional_str(raw_recommendation.get("status")) or "open",
        )
        recommendations.append(recommendation)
    return recommendations


def _build_rollups(recommendations: list[SEORecommendation]) -> dict[str, dict[str, int]]:
    by_status: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_effort_bucket: dict[str, int] = {}
    by_priority_band: dict[str, int] = {}
    for recommendation in recommendations:
        _increment(by_status, recommendation.status)
        _increment(by_category, recommendation.category)
        _increment(by_severity, recommendation.severity)
        _increment(by_effort_bucket, recommendation.effort_bucket)
        _increment(by_priority_band, recommendation.priority_band)
    return {
        "by_status": by_status,
        "by_category": by_category,
        "by_severity": by_severity,
        "by_effort_bucket": by_effort_bucket,
        "by_priority_band": by_priority_band,
    }


def _build_backlog(recommendations: list[SEORecommendation], backlog_ids: list[str]) -> list[SEORecommendation]:
    if not backlog_ids:
        return []
    backlog_order = {value: index for index, value in enumerate(backlog_ids)}
    backlog = [item for item in recommendations if item.id in backlog_order]
    backlog.sort(key=lambda item: backlog_order[item.id])
    return backlog


def _candidate_combined_text(candidate: SEOCompetitorProfileDraftCandidateOutput) -> str:
    parts = [
        candidate.suggested_name,
        candidate.suggested_domain,
        candidate.summary or "",
        candidate.why_competitor or "",
        candidate.evidence or "",
    ]
    return _normalize_whitespace(" ".join(parts))


def _normalize_domain(value: str | None) -> str:
    if not value:
        return ""
    candidate = value.strip().lower()
    if "://" in candidate:
        candidate = candidate.split("://", 1)[1]
    candidate = candidate.split("/", 1)[0]
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate.strip(". ")


def _normalize_whitespace(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _normalize_whitespace(str(item))
        if text:
            normalized.append(text)
    return normalized


def _contains_any_term(text: str, terms: list[str]) -> bool:
    for term in terms:
        normalized = term.strip().lower()
        if normalized and normalized in text:
            return True
    return False


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _has_duplicates(values: list[str]) -> bool:
    lowered = [item.lower() for item in values]
    return len(lowered) != len(set(lowered))


def _increment(bucket: dict[str, int], key: str | None) -> None:
    normalized_key = _optional_str(key)
    if not normalized_key:
        return
    bucket[normalized_key] = bucket.get(normalized_key, 0) + 1


def _load_cases_payload(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(f"fixture file not found: {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"fixture file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"fixture file root must be an object: {path}")
    return payload


def _require_str(payload: dict[str, object], key: str, path: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}.{key} must be a non-empty string.")
    return value.strip()


def _require_dict(payload: dict[str, object], key: str, path: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"{path}.{key} must be an object.")
    return value


def _optional_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _optional_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(key, str):
            normalized[key] = item
    return normalized


def _optional_list_of_str(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            normalized.append(text)
    return normalized


def _optional_count_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        try:
            count = int(raw_count)
        except (TypeError, ValueError):
            continue
        if count < 0:
            continue
        result[key.strip()] = count
    return result


def _optional_int_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw_value in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        try:
            result[key.strip()] = int(raw_value)
        except (TypeError, ValueError):
            continue
    return result


def _coerce_int(
    value: object,
    path: str,
    *,
    minimum: int,
    maximum: int,
    default: int,
) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} must be an integer.") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{path} must be between {minimum} and {maximum}.")
    return parsed


def _clamp_score(score: int) -> int:
    if score < 0:
        return 0
    if score > 100:
        return 100
    return score


def _provider_name(provider: object, *, default: str) -> str:
    raw = getattr(provider, "provider_name", None)
    if raw is None:
        return default
    normalized = str(raw).strip()
    return normalized or default


def _provider_model_name(provider: object, *, default: str) -> str:
    raw = getattr(provider, "model_name", None)
    if raw is None:
        return default
    normalized = str(raw).strip()
    return normalized or default
