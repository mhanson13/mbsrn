from __future__ import annotations

from dataclasses import dataclass
import re


_MIN_TOKEN_SET_SIZE_FOR_SIMILARITY = 3
_NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.7

_ACTION_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "trust_social_proof": (
        "review",
        "reviews",
        "testimonial",
        "testimonials",
        "trust",
        "proof",
        "badge",
        "badges",
        "credibility",
        "social proof",
    ),
    "service_clarity": (
        "service",
        "services",
        "offering",
        "offerings",
        "scope",
        "pricing",
        "clarify",
        "clarity",
    ),
    "local_seo_location": (
        "local",
        "location",
        "locations",
        "city",
        "cities",
        "area",
        "areas",
        "nearby",
        "gmb",
        "gbp",
        "nap",
        "map",
        "maps",
    ),
    "conversion_contact_ux": (
        "contact",
        "call",
        "phone",
        "form",
        "book",
        "booking",
        "quote",
        "cta",
        "conversion",
    ),
    "content_pages": (
        "content",
        "page",
        "pages",
        "faq",
        "guide",
        "blog",
        "copy",
        "title",
        "heading",
        "headings",
        "meta",
    ),
}

_COMPETITOR_SPECIFICITY_TERMS = (
    "competitor",
    "competitors",
    "nearby",
    "local",
    "against",
    "versus",
    "outperform",
)

_STOP_TOKENS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "with",
    "your",
}


@dataclass(frozen=True)
class _ActionCandidate:
    text: str
    normalized: str
    tokens: set[str]
    theme: str
    specificity_score: int
    index: int


def normalize_recommendation_narrative_sections(
    sections: dict[str, object] | None,
    *,
    next_action_limit: int,
    next_action_max_length: int,
    recommendation_reference_limit: int,
) -> dict[str, object] | None:
    if sections is None:
        return None
    if not isinstance(sections, dict):
        return {}

    normalized = dict(sections)
    normalized["next_actions"] = normalize_recommendation_next_actions(
        _to_string_list(normalized.get("next_actions")),
        limit=next_action_limit,
        max_length=next_action_max_length,
    )
    normalized["recommendation_references"] = _normalize_recommendation_references(
        normalized.get("recommendation_references"),
        limit=recommendation_reference_limit,
    )
    return normalized


def normalize_recommendation_next_actions(
    actions: list[str] | None,
    *,
    limit: int,
    max_length: int,
) -> list[str]:
    """Normalize narrative next actions with bounded de-duplication and diversity.

    This helper intentionally uses deterministic lightweight heuristics:
    - collapse exact and near-duplicate actions
    - keep the more specific action variant when overlap is high
    - preserve stable output order for downstream operator workflows
    """
    if not actions or limit <= 0 or max_length <= 0:
        return []

    candidates: list[_ActionCandidate] = []
    for index, raw in enumerate(actions):
        cleaned = _clean_text(raw, max_length=max_length)
        if not cleaned:
            continue
        normalized = cleaned.lower()
        tokens = _tokens_for_similarity(normalized)
        theme = _classify_theme(normalized)
        specificity_score = _specificity_score(normalized, tokens=tokens)
        candidates.append(
            _ActionCandidate(
                text=cleaned,
                normalized=normalized,
                tokens=tokens,
                theme=theme,
                specificity_score=specificity_score,
                index=index,
            )
        )

    if not candidates:
        return []

    deduped: list[_ActionCandidate] = []
    for candidate in candidates:
        duplicate_index = _find_near_duplicate_index(deduped, candidate)
        if duplicate_index is None:
            deduped.append(candidate)
            continue
        existing = deduped[duplicate_index]
        if _prefer_candidate(candidate, existing):
            deduped[duplicate_index] = _ActionCandidate(
                text=candidate.text,
                normalized=candidate.normalized,
                tokens=candidate.tokens,
                theme=candidate.theme,
                specificity_score=candidate.specificity_score,
                index=existing.index,
            )

    return [item.text for item in deduped[:limit]]


def _to_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _normalize_recommendation_references(
    value: object,
    *,
    limit: int,
) -> list[str]:
    if not isinstance(value, list) or limit <= 0:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        cleaned = " ".join(str(item or "").split()).strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
        if len(normalized) >= limit:
            break
    return normalized


def _clean_text(value: object, *, max_length: int) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    if not normalized:
        return ""
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _tokens_for_similarity(normalized_text: str) -> set[str]:
    tokens = {token for token in re.split(r"[^a-z0-9]+", normalized_text) if token and token not in _STOP_TOKENS}
    return tokens


def _classify_theme(normalized_text: str) -> str:
    for theme, keywords in _ACTION_THEME_KEYWORDS.items():
        if any(keyword in normalized_text for keyword in keywords):
            return theme
    return "other"


def _specificity_score(normalized_text: str, *, tokens: set[str]) -> int:
    score = min(len(tokens), 12)
    if len(normalized_text) >= 80:
        score += 2
    elif len(normalized_text) >= 50:
        score += 1
    if any(term in normalized_text for term in _COMPETITOR_SPECIFICITY_TERMS):
        score += 2
    if any(character.isdigit() for character in normalized_text):
        score += 1
    return score


def _find_near_duplicate_index(
    existing: list[_ActionCandidate],
    candidate: _ActionCandidate,
) -> int | None:
    for index, current in enumerate(existing):
        if current.normalized == candidate.normalized:
            return index
        if _is_near_duplicate(current, candidate):
            return index
    return None


def _is_near_duplicate(left: _ActionCandidate, right: _ActionCandidate) -> bool:
    if left.theme != right.theme:
        return False

    if not left.tokens or not right.tokens:
        return False

    overlap = left.tokens & right.tokens
    if overlap == left.tokens or overlap == right.tokens:
        if min(len(left.tokens), len(right.tokens)) >= _MIN_TOKEN_SET_SIZE_FOR_SIMILARITY:
            return True

    union = left.tokens | right.tokens
    if len(union) < _MIN_TOKEN_SET_SIZE_FOR_SIMILARITY:
        return False

    jaccard = len(overlap) / len(union)
    return jaccard >= _NEAR_DUPLICATE_JACCARD_THRESHOLD


def _prefer_candidate(candidate: _ActionCandidate, existing: _ActionCandidate) -> bool:
    if candidate.specificity_score != existing.specificity_score:
        return candidate.specificity_score > existing.specificity_score
    if len(candidate.tokens) != len(existing.tokens):
        return len(candidate.tokens) > len(existing.tokens)
    if len(candidate.text) != len(existing.text):
        return len(candidate.text) > len(existing.text)
    return candidate.index < existing.index
