from __future__ import annotations

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
_MIN_RELEVANCE_SCORE = 35


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


@dataclass(frozen=True)
class _SiteScoringContext:
    domain: str
    industry_terms: set[str]
    location_terms: set[str]
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


def process_competitor_candidates(
    *,
    site: SEOSite,
    candidates: list[CompetitorCandidateInput],
    existing_domains: list[str],
    minimum_relevance_score: int = _MIN_RELEVANCE_SCORE,
) -> CompetitorCandidateProcessingResult:
    minimum_relevance_score = max(0, min(100, int(minimum_relevance_score)))
    context = _build_site_context(site)
    existing_domain_set = {_canonicalize_domain(value) for value in existing_domains if value.strip()}

    scored_candidates = [
        _to_scored_state(
            candidate=candidate,
            context=context,
            existing_domain_set=existing_domain_set,
        )
        for candidate in candidates
    ]

    deduped_candidates = _dedupe_scored_candidates(scored_candidates, context=context)
    included: list[RankedCompetitorCandidate] = []
    for candidate in deduped_candidates:
        exclusion_reason = _determine_exclusion_reason(
            candidate=candidate,
            minimum_relevance_score=minimum_relevance_score,
            existing_domain_set=existing_domain_set,
            site_context=context,
        )
        if exclusion_reason:
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
    return CompetitorCandidateProcessingResult(
        included_candidates=included,
        raw_candidate_count=len(candidates),
        deduped_candidate_count=len(deduped_candidates),
        excluded_candidate_count=len(deduped_candidates) - len(included),
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
) -> list[_ScoredCandidateState]:
    deduped: list[_ScoredCandidateState] = []
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
        merged = _merge_duplicate_candidates(primary=deduped[duplicate_index], secondary=candidate, site_context=context)
        deduped[duplicate_index] = merged
    return deduped


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
        return "excluded_existing_domain"
    if candidate.is_directory_domain:
        return "excluded_directory_domain"
    if (
        site_context.has_local_context
        and candidate.is_big_box_candidate
        and not candidate.location_terms_found
        and candidate.competitor_type in {"direct", "local", "unknown"}
    ):
        return "excluded_big_box_mismatch"
    if candidate.relevance_score < minimum_relevance_score:
        return "excluded_low_relevance"
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
) -> int:
    score = 25
    score += max(0, min(20, int(round(candidate.confidence_score * 20))))

    if canonical_domain:
        score += 22
    if canonical_domain in existing_domain_set:
        score -= 25

    if is_directory_domain:
        score -= 35
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
        score += 10

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
        score -= 20

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
