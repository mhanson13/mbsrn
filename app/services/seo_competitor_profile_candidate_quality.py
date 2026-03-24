from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from app.models.seo_site import SEOSite


_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_LEGAL_SUFFIXES = {"llc", "inc", "ltd", "co", "corp", "company", "incorporated", "limited", "corporation"}
_PLACEHOLDER_NAME_TOKENS = {
    "business",
    "company",
    "competitor",
    "example",
    "generic",
    "na",
    "none",
    "placeholder",
    "unknown",
}
_DIRECTORY_DOMAIN_ROOTS = {
    "angi",
    "angieslist",
    "bbb",
    "facebook",
    "foursquare",
    "homeadvisor",
    "instagram",
    "linkedin",
    "manta",
    "nextdoor",
    "superpages",
    "thumbtack",
    "tripadvisor",
    "x",
    "yelp",
    "yellowpages",
}
_BIG_BOX_ROOTS = {
    "amazon",
    "bestbuy",
    "costco",
    "homedepot",
    "ikea",
    "lowes",
    "mcdonalds",
    "starbucks",
    "target",
    "walmart",
}
_MIN_LOCATION_TERM_LENGTH = 3
_MIN_INDUSTRY_TERM_LENGTH = 4

DEFAULT_MIN_RELEVANCE_SCORE = 35
DEFAULT_BIG_BOX_PENALTY = 20
DEFAULT_DIRECTORY_PENALTY = 35
DEFAULT_LOCAL_ALIGNMENT_BONUS = 10

MIN_RELEVANCE_SCORE_MIN = 0
MIN_RELEVANCE_SCORE_MAX = 100
BIG_BOX_PENALTY_MIN = 0
BIG_BOX_PENALTY_MAX = 50
DIRECTORY_PENALTY_MIN = 0
DIRECTORY_PENALTY_MAX = 50
LOCAL_ALIGNMENT_BONUS_MIN = 0
LOCAL_ALIGNMENT_BONUS_MAX = 50

EXCLUSION_REASON_DUPLICATE = "duplicate"
EXCLUSION_REASON_LOW_RELEVANCE = "low_relevance"
EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR = "directory_or_aggregator"
EXCLUSION_REASON_BIG_BOX_MISMATCH = "big_box_mismatch"
EXCLUSION_REASON_EXISTING_DOMAIN_MATCH = "existing_domain_match"
EXCLUSION_REASON_INVALID_CANDIDATE = "invalid_candidate"
EXCLUSION_REASON_KEYS: tuple[str, ...] = (
    EXCLUSION_REASON_DUPLICATE,
    EXCLUSION_REASON_LOW_RELEVANCE,
    EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR,
    EXCLUSION_REASON_BIG_BOX_MISMATCH,
    EXCLUSION_REASON_EXISTING_DOMAIN_MATCH,
    EXCLUSION_REASON_INVALID_CANDIDATE,
)

TUNING_EXCLUSION_REASON_BELOW_MINIMUM_RELEVANCE_SCORE = "below_minimum_relevance_score"
TUNING_EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR_PENALTY = "directory_or_aggregator_penalty"
TUNING_EXCLUSION_REASON_BIG_BOX_MISMATCH_PENALTY = "big_box_mismatch_penalty"
TUNING_EXCLUSION_REASON_INSUFFICIENT_LOCAL_ALIGNMENT = "insufficient_local_alignment"
TUNING_EXCLUSION_REASON_KEYS: tuple[str, ...] = (
    TUNING_EXCLUSION_REASON_BELOW_MINIMUM_RELEVANCE_SCORE,
    TUNING_EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR_PENALTY,
    TUNING_EXCLUSION_REASON_BIG_BOX_MISMATCH_PENALTY,
    TUNING_EXCLUSION_REASON_INSUFFICIENT_LOCAL_ALIGNMENT,
)

INELIGIBILITY_REASON_PARKED_DOMAIN = "parked_domain"
INELIGIBILITY_REASON_NO_LIVE_SITE = "no_live_site"
INELIGIBILITY_REASON_WEAK_BUSINESS_IDENTITY = "weak_business_identity"
INELIGIBILITY_REASON_OUT_OF_MARKET = "out_of_market"
INELIGIBILITY_REASON_EXCLUDED_DOMAIN_PATTERN = "excluded_domain_pattern"
INELIGIBILITY_REASON_INSUFFICIENT_OVERLAP_EVIDENCE = "insufficient_overlap_evidence"
INELIGIBILITY_REASON_KEYS: tuple[str, ...] = (
    INELIGIBILITY_REASON_PARKED_DOMAIN,
    INELIGIBILITY_REASON_NO_LIVE_SITE,
    INELIGIBILITY_REASON_WEAK_BUSINESS_IDENTITY,
    INELIGIBILITY_REASON_OUT_OF_MARKET,
    INELIGIBILITY_REASON_EXCLUDED_DOMAIN_PATTERN,
    INELIGIBILITY_REASON_INSUFFICIENT_OVERLAP_EVIDENCE,
)

_PARKED_DOMAIN_TEXT_MARKERS = (
    "domain is for sale",
    "this domain is for sale",
    "buy this domain",
    "buy now",
    "parked free",
    "parked domain",
    "domain parking",
    "sedo",
    "afternic",
    "hugedomains",
    "godaddy domain broker",
)
_EXCLUDED_DOMAIN_SUBSTRINGS = (
    "domainforsale",
    "for-sale-domain",
    "buy-this-domain",
    "sedoparking",
    "parkingcrew",
)
_BUSINESS_IDENTITY_CUES = {
    "about",
    "book",
    "call",
    "contact",
    "estimate",
    "hours",
    "location",
    "phone",
    "portfolio",
    "projects",
    "quote",
    "review",
    "services",
    "team",
    "testimonial",
}
_STATE_ABBREVIATIONS = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}
_STATE_NAME_TO_ABBREVIATION = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "new hampshire": "nh",
    "new jersey": "nj",
    "new mexico": "nm",
    "new york": "ny",
    "north carolina": "nc",
    "north dakota": "nd",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "rhode island": "ri",
    "south carolina": "sc",
    "south dakota": "sd",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virginia": "va",
    "washington": "wa",
    "west virginia": "wv",
    "wisconsin": "wi",
    "wyoming": "wy",
    "district of columbia": "dc",
}


@dataclass(frozen=True)
class CompetitorCandidateInput:
    suggested_name: str
    suggested_domain: str
    competitor_type: str
    summary: str | None
    why_competitor: str | None
    evidence: str | None
    confidence_score: float
    source_index: int


@dataclass(frozen=True)
class RankedCompetitorCandidate:
    suggested_name: str
    suggested_domain: str
    competitor_type: str
    summary: str | None
    why_competitor: str | None
    evidence: str | None
    confidence_score: float
    relevance_score: int
    normalized_name: str
    canonical_domain: str
    exclusion_reason: str | None
    source_index: int


@dataclass(frozen=True)
class CompetitorCandidateProcessingResult:
    included_candidates: list[RankedCompetitorCandidate]
    raw_candidate_count: int
    deduped_candidate_count: int
    excluded_candidate_count: int
    exclusion_counts_by_reason: dict[str, int]
    tuning_rejected_candidates: list["CompetitorCandidateTuningRejection"]
    tuning_rejection_reason_counts: dict[str, int]


@dataclass(frozen=True)
class CompetitorCandidateDomainProbeResult:
    status_code: int | None
    body_text: str | None
    fetch_error: str | None = None


CompetitorCandidateDomainProbe = Callable[[str], CompetitorCandidateDomainProbeResult | None]


@dataclass(frozen=True)
class CompetitorCandidateEligibilityDecision:
    candidate: CompetitorCandidateInput
    is_eligible: bool
    ineligibility_reasons: tuple[str, ...]


@dataclass(frozen=True)
class CompetitorCandidateEligibilityResult:
    eligible_candidates: list[CompetitorCandidateInput]
    decisions: list[CompetitorCandidateEligibilityDecision]
    ineligible_candidate_count: int
    ineligibility_counts_by_reason: dict[str, int]


@dataclass(frozen=True)
class CompetitorCandidateTuningRejection:
    suggested_domain: str
    reasons: tuple[str, ...]
    final_score: int | None
    summary: str | None


@dataclass(frozen=True)
class CompetitorCandidateQualityTuning:
    minimum_relevance_score: int = DEFAULT_MIN_RELEVANCE_SCORE
    big_box_penalty: int = DEFAULT_BIG_BOX_PENALTY
    directory_penalty: int = DEFAULT_DIRECTORY_PENALTY
    local_alignment_bonus: int = DEFAULT_LOCAL_ALIGNMENT_BONUS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "minimum_relevance_score",
            _validate_bounded_integer(
                "minimum_relevance_score",
                self.minimum_relevance_score,
                min_value=MIN_RELEVANCE_SCORE_MIN,
                max_value=MIN_RELEVANCE_SCORE_MAX,
            ),
        )
        object.__setattr__(
            self,
            "big_box_penalty",
            _validate_bounded_integer(
                "big_box_penalty",
                self.big_box_penalty,
                min_value=BIG_BOX_PENALTY_MIN,
                max_value=BIG_BOX_PENALTY_MAX,
            ),
        )
        object.__setattr__(
            self,
            "directory_penalty",
            _validate_bounded_integer(
                "directory_penalty",
                self.directory_penalty,
                min_value=DIRECTORY_PENALTY_MIN,
                max_value=DIRECTORY_PENALTY_MAX,
            ),
        )
        object.__setattr__(
            self,
            "local_alignment_bonus",
            _validate_bounded_integer(
                "local_alignment_bonus",
                self.local_alignment_bonus,
                min_value=LOCAL_ALIGNMENT_BONUS_MIN,
                max_value=LOCAL_ALIGNMENT_BONUS_MAX,
            ),
        )


@dataclass(frozen=True)
class _SiteScoringContext:
    domain: str
    industry_terms: set[str]
    location_terms: set[str]
    has_local_context: bool


@dataclass(frozen=True)
class _EligibilitySiteContext:
    industry_terms: set[str]
    location_terms: set[str]
    state_tokens: set[str]
    has_local_context: bool


@dataclass(frozen=True)
class _ScoredCandidateState:
    suggested_name: str
    suggested_domain: str
    competitor_type: str
    summary: str | None
    why_competitor: str | None
    evidence: str | None
    confidence_score: float
    relevance_score: int
    normalized_name: str
    normalized_name_compact: str
    canonical_domain: str
    domain_root: str
    location_terms_found: set[str]
    is_directory_domain: bool
    is_big_box_candidate: bool
    source_index: int


def filter_eligible_competitor_candidates(
    *,
    site: SEOSite,
    candidates: list[CompetitorCandidateInput],
    domain_probe: CompetitorCandidateDomainProbe | None = None,
) -> CompetitorCandidateEligibilityResult:
    context = _build_eligibility_context(site)
    eligible_candidates: list[CompetitorCandidateInput] = []
    decisions: list[CompetitorCandidateEligibilityDecision] = []
    reason_counts = _new_ineligibility_reason_counts()
    probe_cache: dict[str, CompetitorCandidateDomainProbeResult | None] = {}

    for candidate in candidates:
        domain = _canonicalize_domain(candidate.suggested_domain)
        domain_probe_result = _resolve_domain_probe_result(
            domain=domain,
            domain_probe=domain_probe,
            cache=probe_cache,
        )
        reasons = _determine_ineligibility_reasons(
            candidate=candidate,
            context=context,
            domain=domain,
            domain_probe_result=domain_probe_result,
        )
        if reasons:
            for reason in reasons:
                reason_counts[reason] += 1
            decisions.append(
                CompetitorCandidateEligibilityDecision(
                    candidate=candidate,
                    is_eligible=False,
                    ineligibility_reasons=tuple(reasons),
                )
            )
            continue

        eligible_candidates.append(candidate)
        decisions.append(
            CompetitorCandidateEligibilityDecision(
                candidate=candidate,
                is_eligible=True,
                ineligibility_reasons=tuple(),
            )
        )

    ineligible_count = sum(1 for item in decisions if not item.is_eligible)
    return CompetitorCandidateEligibilityResult(
        eligible_candidates=eligible_candidates,
        decisions=decisions,
        ineligible_candidate_count=ineligible_count,
        ineligibility_counts_by_reason=reason_counts,
    )


def process_competitor_candidates(
    *,
    site: SEOSite,
    candidates: list[CompetitorCandidateInput],
    existing_domains: list[str],
    minimum_relevance_score: int = DEFAULT_MIN_RELEVANCE_SCORE,
    quality_tuning: CompetitorCandidateQualityTuning | None = None,
) -> CompetitorCandidateProcessingResult:
    if quality_tuning is None:
        tuning = CompetitorCandidateQualityTuning(minimum_relevance_score=minimum_relevance_score)
    else:
        tuning = quality_tuning
    context = _build_site_context(site)
    existing_domain_set = {_canonicalize_domain(value) for value in existing_domains if value.strip()}
    exclusion_counts_by_reason = _new_exclusion_reason_counts()
    tuning_rejection_reason_counts = _new_tuning_exclusion_reason_counts()
    tuning_rejected_candidates: list[CompetitorCandidateTuningRejection] = []

    scored_candidates = [
        _to_scored_state(
            candidate=candidate,
            context=context,
            existing_domain_set=existing_domain_set,
            tuning=tuning,
        )
        for candidate in candidates
    ]

    deduped_candidates, duplicate_count = _dedupe_scored_candidates(
        scored_candidates,
        context=context,
        tuning=tuning,
    )
    exclusion_counts_by_reason[EXCLUSION_REASON_DUPLICATE] = duplicate_count
    included: list[RankedCompetitorCandidate] = []
    for candidate in deduped_candidates:
        exclusion_reason = _determine_exclusion_reason(
            candidate=candidate,
            minimum_relevance_score=tuning.minimum_relevance_score,
            existing_domain_set=existing_domain_set,
            site_context=context,
        )
        if exclusion_reason:
            exclusion_counts_by_reason[exclusion_reason] += 1
            tuning_reasons = _derive_tuning_exclusion_reasons(
                candidate=candidate,
                exclusion_reason=exclusion_reason,
                minimum_relevance_score=tuning.minimum_relevance_score,
                site_context=context,
            )
            if tuning_reasons:
                for tuning_reason in tuning_reasons:
                    tuning_rejection_reason_counts[tuning_reason] += 1
                tuning_rejected_candidates.append(
                    CompetitorCandidateTuningRejection(
                        suggested_domain=candidate.canonical_domain,
                        reasons=tuning_reasons,
                        final_score=candidate.relevance_score,
                        summary=_candidate_tuning_rejection_summary(candidate),
                    )
                )
            continue
        included.append(
            RankedCompetitorCandidate(
                suggested_name=candidate.suggested_name,
                suggested_domain=candidate.suggested_domain,
                competitor_type=candidate.competitor_type,
                summary=candidate.summary,
                why_competitor=candidate.why_competitor,
                evidence=candidate.evidence,
                confidence_score=candidate.confidence_score,
                relevance_score=candidate.relevance_score,
                normalized_name=candidate.normalized_name,
                canonical_domain=candidate.canonical_domain,
                exclusion_reason=None,
                source_index=candidate.source_index,
            )
        )

    included.sort(
        key=lambda item: (
            -item.relevance_score,
            item.normalized_name,
            item.canonical_domain,
            item.source_index,
        )
    )
    excluded_candidate_count = sum(exclusion_counts_by_reason.values())
    return CompetitorCandidateProcessingResult(
        included_candidates=included,
        raw_candidate_count=len(candidates),
        deduped_candidate_count=len(deduped_candidates),
        excluded_candidate_count=excluded_candidate_count,
        exclusion_counts_by_reason=exclusion_counts_by_reason,
        tuning_rejected_candidates=tuning_rejected_candidates,
        tuning_rejection_reason_counts=tuning_rejection_reason_counts,
    )


def normalize_competitor_name_for_matching(value: str) -> str:
    normalized = _normalize_text(value).lower()
    if not normalized:
        return ""
    tokens = [token for token in _NON_ALNUM_RE.split(normalized) if token]
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens).strip()


def canonicalize_domain(value: str) -> str:
    return _canonicalize_domain(value)


def normalize_location_for_matching(value: str) -> str:
    return _normalize_text(value).lower()


def default_exclusion_reason_counts() -> dict[str, int]:
    return _new_exclusion_reason_counts()


def _build_site_context(site: SEOSite) -> _SiteScoringContext:
    industry_terms = _extract_terms(
        _normalize_text(site.industry or "").lower(),
        minimum_length=_MIN_INDUSTRY_TERM_LENGTH,
    )

    location_values = []
    if site.primary_location:
        location_values.append(site.primary_location)
    if site.service_areas_json:
        location_values.extend([item for item in site.service_areas_json if isinstance(item, str)])
    location_terms = set()
    for value in location_values:
        location_terms.update(
            _extract_terms(
                _normalize_text(value).lower(),
                minimum_length=_MIN_LOCATION_TERM_LENGTH,
            )
        )

    return _SiteScoringContext(
        domain=_canonicalize_domain(site.normalized_domain or ""),
        industry_terms=industry_terms,
        location_terms=location_terms,
        has_local_context=bool(location_terms),
    )


def _to_scored_state(
    *,
    candidate: CompetitorCandidateInput,
    context: _SiteScoringContext,
    existing_domain_set: set[str],
    tuning: CompetitorCandidateQualityTuning,
) -> _ScoredCandidateState:
    normalized_name = normalize_competitor_name_for_matching(candidate.suggested_name)
    normalized_name_compact = normalized_name.replace(" ", "")
    canonical_domain = _canonicalize_domain(candidate.suggested_domain)
    domain_root = canonical_domain.split(".", 1)[0]
    text_blob = " ".join(
        value
        for value in [
            candidate.suggested_name,
            candidate.summary or "",
            candidate.why_competitor or "",
            candidate.evidence or "",
        ]
        if value
    ).lower()
    location_terms_found = context.location_terms.intersection(
        _extract_terms(text_blob, minimum_length=_MIN_LOCATION_TERM_LENGTH)
    )
    is_directory_domain = _is_directory_domain(canonical_domain, domain_root)
    is_big_box_candidate = _is_big_box_candidate(normalized_name, domain_root)

    relevance_score = _score_candidate(
        candidate=candidate,
        normalized_name=normalized_name,
        canonical_domain=canonical_domain,
        domain_root=domain_root,
        context=context,
        location_terms_found=location_terms_found,
        is_directory_domain=is_directory_domain,
        is_big_box_candidate=is_big_box_candidate,
        existing_domain_set=existing_domain_set,
        tuning=tuning,
    )

    return _ScoredCandidateState(
        suggested_name=candidate.suggested_name,
        suggested_domain=canonical_domain,
        competitor_type=candidate.competitor_type,
        summary=candidate.summary,
        why_competitor=candidate.why_competitor,
        evidence=candidate.evidence,
        confidence_score=candidate.confidence_score,
        relevance_score=relevance_score,
        normalized_name=normalized_name,
        normalized_name_compact=normalized_name_compact,
        canonical_domain=canonical_domain,
        domain_root=domain_root,
        location_terms_found=location_terms_found,
        is_directory_domain=is_directory_domain,
        is_big_box_candidate=is_big_box_candidate,
        source_index=candidate.source_index,
    )


def _dedupe_scored_candidates(
    candidates: list[_ScoredCandidateState],
    *,
    context: _SiteScoringContext,
    tuning: CompetitorCandidateQualityTuning,
) -> tuple[list[_ScoredCandidateState], int]:
    deduped: list[_ScoredCandidateState] = []
    duplicate_count = 0
    for candidate in candidates:
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(deduped)
                if _are_duplicate_candidates(candidate, existing, site_context=context)
            ),
            None,
        )
        if duplicate_index is None:
            deduped.append(candidate)
            continue
        merged = _merge_duplicate_candidates(
            primary=deduped[duplicate_index],
            secondary=candidate,
            site_context=context,
            tuning=tuning,
        )
        deduped[duplicate_index] = merged
        duplicate_count += 1
    return deduped, duplicate_count


def _are_duplicate_candidates(
    left: _ScoredCandidateState,
    right: _ScoredCandidateState,
    *,
    site_context: _SiteScoringContext,
) -> bool:
    if left.canonical_domain and left.canonical_domain == right.canonical_domain:
        return True

    if left.normalized_name and left.normalized_name == right.normalized_name:
        if left.location_terms_found and right.location_terms_found:
            return bool(left.location_terms_found.intersection(right.location_terms_found))
        return True

    if _strong_name_similarity(left, right) and _domain_roots_correspond(left.domain_root, right.domain_root):
        return True

    if site_context.has_local_context and left.normalized_name and left.normalized_name == right.normalized_name:
        return True

    return False


def _strong_name_similarity(left: _ScoredCandidateState, right: _ScoredCandidateState) -> bool:
    if not left.normalized_name_compact or not right.normalized_name_compact:
        return False
    if left.normalized_name_compact == right.normalized_name_compact:
        return True
    shorter, longer = sorted(
        [left.normalized_name_compact, right.normalized_name_compact],
        key=len,
    )
    if len(shorter) < 8:
        return False
    return longer.startswith(shorter) and (len(longer) - len(shorter) <= 3)


def _domain_roots_correspond(left_root: str, right_root: str) -> bool:
    if not left_root or not right_root:
        return False
    if left_root == right_root:
        return True
    shorter, longer = sorted([left_root, right_root], key=len)
    if len(shorter) < 6:
        return False
    return longer.startswith(shorter) or shorter.startswith(longer)


def _merge_duplicate_candidates(
    *,
    primary: _ScoredCandidateState,
    secondary: _ScoredCandidateState,
    site_context: _SiteScoringContext,
    tuning: CompetitorCandidateQualityTuning,
) -> _ScoredCandidateState:
    stronger = _stronger_candidate(primary, secondary)
    weaker = secondary if stronger is primary else primary

    merged_name = _prefer_better_name(stronger.suggested_name, weaker.suggested_name)
    merged_domain = _prefer_better_domain(stronger.canonical_domain, weaker.canonical_domain)
    merged_competitor_type = _prefer_competitor_type(stronger.competitor_type, weaker.competitor_type)
    merged_summary = _prefer_richer_text(stronger.summary, weaker.summary)
    merged_why = _prefer_richer_text(stronger.why_competitor, weaker.why_competitor)
    merged_evidence = _prefer_richer_text(stronger.evidence, weaker.evidence)
    merged_confidence = max(stronger.confidence_score, weaker.confidence_score)
    merged_source_index = min(stronger.source_index, weaker.source_index)

    merged_input = CompetitorCandidateInput(
        suggested_name=merged_name,
        suggested_domain=merged_domain,
        competitor_type=merged_competitor_type,
        summary=merged_summary,
        why_competitor=merged_why,
        evidence=merged_evidence,
        confidence_score=merged_confidence,
        source_index=merged_source_index,
    )
    return _to_scored_state(
        candidate=merged_input,
        context=site_context,
        existing_domain_set=set(),
        tuning=tuning,
    )


def _stronger_candidate(left: _ScoredCandidateState, right: _ScoredCandidateState) -> _ScoredCandidateState:
    left_rank = (
        left.relevance_score,
        left.confidence_score,
        0 if left.is_directory_domain else 1,
        _filled_optional_count(left),
        -left.source_index,
    )
    right_rank = (
        right.relevance_score,
        right.confidence_score,
        0 if right.is_directory_domain else 1,
        _filled_optional_count(right),
        -right.source_index,
    )
    if left_rank >= right_rank:
        return left
    return right


def _filled_optional_count(candidate: _ScoredCandidateState) -> int:
    return int(bool(candidate.summary)) + int(bool(candidate.why_competitor)) + int(bool(candidate.evidence))


def _prefer_better_name(left: str, right: str) -> str:
    left_normalized = normalize_competitor_name_for_matching(left)
    right_normalized = normalize_competitor_name_for_matching(right)
    if _is_placeholder_name(left_normalized) and not _is_placeholder_name(right_normalized):
        return right
    if _is_placeholder_name(right_normalized) and not _is_placeholder_name(left_normalized):
        return left
    if len(right_normalized) > len(left_normalized):
        return right
    return left


def _prefer_better_domain(left: str, right: str) -> str:
    left_root = left.split(".", 1)[0]
    right_root = right.split(".", 1)[0]
    left_directory = _is_directory_domain(left, left_root)
    right_directory = _is_directory_domain(right, right_root)
    if left_directory and not right_directory:
        return right
    if right_directory and not left_directory:
        return left
    if len(right) < len(left):
        return right
    return left


def _prefer_competitor_type(left: str, right: str) -> str:
    priority = {"direct": 4, "local": 3, "indirect": 2, "marketplace": 1, "informational": 1, "unknown": 0}
    if priority.get(right, 0) > priority.get(left, 0):
        return right
    return left


def _prefer_richer_text(left: str | None, right: str | None) -> str | None:
    left_cleaned = _normalize_text(left or "")
    right_cleaned = _normalize_text(right or "")
    if not left_cleaned:
        return right_cleaned or None
    if not right_cleaned:
        return left_cleaned
    if len(right_cleaned) > len(left_cleaned):
        return right_cleaned
    return left_cleaned


def _determine_exclusion_reason(
    *,
    candidate: _ScoredCandidateState,
    minimum_relevance_score: int,
    existing_domain_set: set[str],
    site_context: _SiteScoringContext,
) -> str | None:
    if candidate.canonical_domain in existing_domain_set:
        return EXCLUSION_REASON_EXISTING_DOMAIN_MATCH
    if candidate.is_directory_domain:
        return EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR
    if (
        site_context.has_local_context
        and candidate.is_big_box_candidate
        and not candidate.location_terms_found
        and candidate.competitor_type in {"direct", "local", "unknown"}
    ):
        return EXCLUSION_REASON_BIG_BOX_MISMATCH
    if candidate.relevance_score < minimum_relevance_score:
        return EXCLUSION_REASON_LOW_RELEVANCE
    return None


def _build_eligibility_context(site: SEOSite) -> _EligibilitySiteContext:
    scoring_context = _build_site_context(site)
    location_values = []
    if site.primary_location:
        location_values.append(site.primary_location)
    if site.service_areas_json:
        location_values.extend([item for item in site.service_areas_json if isinstance(item, str)])
    state_tokens: set[str] = set()
    for value in location_values:
        normalized_value = _normalize_text(value).lower()
        for token in _extract_terms(normalized_value, minimum_length=2):
            if token in _STATE_ABBREVIATIONS:
                state_tokens.add(token)
        for state_name, abbreviation in _STATE_NAME_TO_ABBREVIATION.items():
            if re.search(rf"\b{re.escape(state_name)}\b", normalized_value):
                state_tokens.add(abbreviation)
    return _EligibilitySiteContext(
        industry_terms=scoring_context.industry_terms,
        location_terms=scoring_context.location_terms,
        state_tokens=state_tokens,
        has_local_context=scoring_context.has_local_context,
    )


def _resolve_domain_probe_result(
    *,
    domain: str,
    domain_probe: CompetitorCandidateDomainProbe | None,
    cache: dict[str, CompetitorCandidateDomainProbeResult | None],
) -> CompetitorCandidateDomainProbeResult | None:
    if domain_probe is None or not domain:
        return None
    if domain in cache:
        return cache[domain]
    try:
        result = domain_probe(domain)
    except Exception as exc:  # noqa: BLE001
        result = CompetitorCandidateDomainProbeResult(
            status_code=None,
            body_text=None,
            fetch_error=f"probe_error:{type(exc).__name__}",
        )
    cache[domain] = result
    return result


def _determine_ineligibility_reasons(
    *,
    candidate: CompetitorCandidateInput,
    context: _EligibilitySiteContext,
    domain: str,
    domain_probe_result: CompetitorCandidateDomainProbeResult | None,
) -> list[str]:
    reasons: list[str] = []
    candidate_text = _candidate_text_blob(candidate)
    probe_text = _normalize_text((domain_probe_result.body_text if domain_probe_result else "") or "").lower()
    combined_text = f"{candidate_text} {probe_text}".strip()

    if _has_excluded_domain_pattern(domain):
        reasons.append(INELIGIBILITY_REASON_EXCLUDED_DOMAIN_PATTERN)

    if _contains_parked_markers(f"{domain} {combined_text}".strip()):
        reasons.append(INELIGIBILITY_REASON_PARKED_DOMAIN)

    if _is_no_live_site(domain_probe_result):
        reasons.append(INELIGIBILITY_REASON_NO_LIVE_SITE)
    elif domain_probe_result is not None and _has_weak_business_identity(combined_text):
        reasons.append(INELIGIBILITY_REASON_WEAK_BUSINESS_IDENTITY)

    if _is_out_of_market_candidate(context=context, combined_text=combined_text):
        reasons.append(INELIGIBILITY_REASON_OUT_OF_MARKET)

    if domain_probe_result is not None and _has_insufficient_overlap_evidence(
        candidate=candidate,
        context=context,
        combined_text=combined_text,
    ):
        reasons.append(INELIGIBILITY_REASON_INSUFFICIENT_OVERLAP_EVIDENCE)

    return _dedupe_reasons(reasons)


def _candidate_text_blob(candidate: CompetitorCandidateInput) -> str:
    return " ".join(
        value
        for value in [
            candidate.suggested_name,
            candidate.suggested_domain,
            candidate.summary or "",
            candidate.why_competitor or "",
            candidate.evidence or "",
        ]
        if value
    ).lower()


def _has_excluded_domain_pattern(domain: str) -> bool:
    if not domain:
        return False
    return any(pattern in domain for pattern in _EXCLUDED_DOMAIN_SUBSTRINGS)


def _contains_parked_markers(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _PARKED_DOMAIN_TEXT_MARKERS)


def _is_no_live_site(domain_probe_result: CompetitorCandidateDomainProbeResult | None) -> bool:
    if domain_probe_result is None:
        return False
    if domain_probe_result.fetch_error:
        return True
    if domain_probe_result.status_code is not None and domain_probe_result.status_code >= 400:
        return True
    body = _normalize_text(domain_probe_result.body_text or "")
    return len(body) < 40


def _has_weak_business_identity(combined_text: str) -> bool:
    terms = _extract_terms(combined_text, minimum_length=3)
    if len(terms) < 20:
        return True
    cue_hits = len(terms.intersection(_BUSINESS_IDENTITY_CUES))
    return cue_hits < 2


def _is_out_of_market_candidate(*, context: _EligibilitySiteContext, combined_text: str) -> bool:
    if not context.has_local_context:
        return False
    candidate_terms = _extract_terms(combined_text, minimum_length=2)
    if context.location_terms.intersection(candidate_terms):
        return False
    candidate_state_tokens = _extract_explicit_state_tokens(combined_text)
    if not candidate_state_tokens:
        return False
    if not context.state_tokens:
        return False
    return candidate_state_tokens.isdisjoint(context.state_tokens)


def _has_insufficient_overlap_evidence(
    *,
    candidate: CompetitorCandidateInput,
    context: _EligibilitySiteContext,
    combined_text: str,
) -> bool:
    text_terms = _extract_terms(combined_text, minimum_length=3)
    has_industry_overlap = bool(context.industry_terms.intersection(text_terms))
    has_location_overlap = bool(context.location_terms.intersection(text_terms))
    rationale_length = len(_normalize_text(candidate.why_competitor or "")) + len(
        _normalize_text(candidate.evidence or "")
    )
    if has_industry_overlap or has_location_overlap:
        return False
    if rationale_length >= 40:
        return False
    return candidate.confidence_score < 0.55


def _dedupe_reasons(reasons: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return ordered


def _extract_explicit_state_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.findall(r",\s*([a-z]{2})\b", value.lower()):
        if match in _STATE_ABBREVIATIONS:
            tokens.add(match)
    lowered = value.lower()
    for state_name, abbreviation in _STATE_NAME_TO_ABBREVIATION.items():
        if re.search(rf"\b{re.escape(state_name)}\b", lowered):
            tokens.add(abbreviation)
    return tokens


def _new_exclusion_reason_counts() -> dict[str, int]:
    return {reason: 0 for reason in EXCLUSION_REASON_KEYS}


def _new_ineligibility_reason_counts() -> dict[str, int]:
    return {reason: 0 for reason in INELIGIBILITY_REASON_KEYS}


def _new_tuning_exclusion_reason_counts() -> dict[str, int]:
    return {reason: 0 for reason in TUNING_EXCLUSION_REASON_KEYS}


def _derive_tuning_exclusion_reasons(
    *,
    candidate: _ScoredCandidateState,
    exclusion_reason: str,
    minimum_relevance_score: int,
    site_context: _SiteScoringContext,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if exclusion_reason == EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR:
        reasons.append(TUNING_EXCLUSION_REASON_DIRECTORY_OR_AGGREGATOR_PENALTY)
    elif exclusion_reason == EXCLUSION_REASON_BIG_BOX_MISMATCH:
        reasons.append(TUNING_EXCLUSION_REASON_BIG_BOX_MISMATCH_PENALTY)
    elif exclusion_reason == EXCLUSION_REASON_LOW_RELEVANCE:
        if candidate.relevance_score < minimum_relevance_score:
            reasons.append(TUNING_EXCLUSION_REASON_BELOW_MINIMUM_RELEVANCE_SCORE)
        if site_context.has_local_context and not candidate.location_terms_found:
            reasons.append(TUNING_EXCLUSION_REASON_INSUFFICIENT_LOCAL_ALIGNMENT)

    deduped: list[str] = []
    seen: set[str] = set()
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return tuple(deduped)


def _candidate_tuning_rejection_summary(candidate: _ScoredCandidateState) -> str | None:
    for value in (candidate.why_competitor, candidate.summary, candidate.evidence):
        normalized = _normalize_text(value or "")
        if normalized:
            return normalized
    return None


def _score_candidate(
    *,
    candidate: CompetitorCandidateInput,
    normalized_name: str,
    canonical_domain: str,
    domain_root: str,
    context: _SiteScoringContext,
    location_terms_found: set[str],
    is_directory_domain: bool,
    is_big_box_candidate: bool,
    existing_domain_set: set[str],
    tuning: CompetitorCandidateQualityTuning,
) -> int:
    score = 25
    score += max(0, min(20, int(round(candidate.confidence_score * 20))))

    if canonical_domain:
        score += 22
    if canonical_domain in existing_domain_set:
        score -= 25

    if is_directory_domain:
        score -= tuning.directory_penalty
    else:
        score += 8

    if _is_placeholder_name(normalized_name):
        score -= 20
    else:
        score += 8

    competitor_type = (candidate.competitor_type or "").strip().lower()
    if competitor_type in {"direct", "local"}:
        score += 10
    elif competitor_type == "indirect":
        score += 6
    elif competitor_type in {"marketplace", "informational"}:
        score += 2

    text_blob = " ".join(
        value
        for value in [
            candidate.suggested_name,
            candidate.summary or "",
            candidate.why_competitor or "",
            candidate.evidence or "",
            canonical_domain,
        ]
        if value
    ).lower()
    text_terms = _extract_terms(text_blob, minimum_length=3)

    if context.industry_terms and context.industry_terms.intersection(text_terms):
        score += 10
    if location_terms_found:
        score += tuning.local_alignment_bonus

    specific_fields = sum(
        1
        for value in [candidate.summary, candidate.why_competitor, candidate.evidence]
        if _is_specific_text(value)
    )
    score += specific_fields * 6
    if specific_fields == 0:
        score -= 10

    populated_optional_fields = sum(
        1 for value in [candidate.summary, candidate.why_competitor, candidate.evidence] if _normalize_text(value or "")
    )
    if populated_optional_fields >= 2:
        score += 4
    if populated_optional_fields == 0:
        score -= 8

    if context.has_local_context and is_big_box_candidate and not location_terms_found:
        score -= tuning.big_box_penalty

    if context.domain and domain_root and domain_root != context.domain.split(".", 1)[0]:
        score += 2

    return max(0, min(100, score))


def _is_specific_text(value: str | None) -> bool:
    normalized = _normalize_text(value or "")
    if len(normalized) < 35:
        return False
    terms = _extract_terms(normalized.lower(), minimum_length=3)
    return len(terms) >= 6


def _is_placeholder_name(normalized_name: str) -> bool:
    if not normalized_name:
        return True
    tokens = [item for item in normalized_name.split(" ") if item]
    if not tokens:
        return True
    if len(tokens) == 1 and tokens[0] in _PLACEHOLDER_NAME_TOKENS:
        return True
    return all(token in _PLACEHOLDER_NAME_TOKENS for token in tokens)


def _is_directory_domain(canonical_domain: str, domain_root: str) -> bool:
    if not canonical_domain:
        return False
    if domain_root in _DIRECTORY_DOMAIN_ROOTS:
        return True
    if canonical_domain.endswith(".google.com"):
        return True
    return False


def _is_big_box_candidate(normalized_name: str, domain_root: str) -> bool:
    if domain_root in _BIG_BOX_ROOTS:
        return True
    tokens = set(normalized_name.split(" "))
    return bool(tokens.intersection(_BIG_BOX_ROOTS))


def _extract_terms(value: str, *, minimum_length: int) -> set[str]:
    terms = set()
    for term in _NON_ALNUM_RE.split(value.lower()):
        if len(term) >= minimum_length:
            terms.add(term)
    return terms


def _normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value.strip())


def _canonicalize_domain(value: str) -> str:
    candidate = _normalize_text(value).lower()
    if not candidate:
        return ""
    parsed = urlsplit(candidate if "://" in candidate else f"https://{candidate}")
    host = (parsed.hostname or candidate).strip().lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def default_competitor_candidate_quality_tuning() -> CompetitorCandidateQualityTuning:
    return CompetitorCandidateQualityTuning()


def _validate_bounded_integer(name: str, value: int, *, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"{name} must be between {min_value} and {max_value}")
    return parsed
