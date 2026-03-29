from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from typing import Protocol
import urllib.error
import urllib.parse
import urllib.request


logger = logging.getLogger(__name__)

_DEFAULT_GOOGLE_PLACES_API_BASE_URL = "https://places.googleapis.com/v1"
_GOOGLE_PLACES_TEXT_SEARCH_PATH = "/places:searchText"
_GOOGLE_PLACES_MIN_TIMEOUT_SECONDS = 1
_GOOGLE_PLACES_MAX_TIMEOUT_SECONDS = 30
_GOOGLE_PLACES_MIN_RESULTS = 1
_GOOGLE_PLACES_MAX_RESULTS = 20
_GOOGLE_PLACES_MAX_QUERY_LENGTH = 160
_GOOGLE_PLACES_MAX_NAME_LENGTH = 140
_GOOGLE_PLACES_MAX_ADDRESS_LENGTH = 220
_GOOGLE_PLACES_MAX_TYPE_LENGTH = 64
_GOOGLE_PLACES_MAX_TYPES = 8
_GOOGLE_PLACES_MAX_PLACE_ID_LENGTH = 255
_GOOGLE_PLACES_WEBSITE_MAX_LENGTH = 1024
_GOOGLE_PLACES_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName.text",
        "places.formattedAddress",
        "places.primaryType",
        "places.types",
        "places.websiteUri",
    )
)


@dataclass(frozen=True)
class GooglePlacesSeedCandidate:
    source: str
    place_id: str
    name: str
    formatted_address: str | None
    locality: str | None
    primary_type: str | None
    types: tuple[str, ...]
    website_domain: str | None


class GooglePlacesSeedDiscoveryClient(Protocol):
    def discover_seed_candidates(
        self,
        *,
        queries: list[str],
        max_results: int,
    ) -> list[GooglePlacesSeedCandidate]: ...


class DisabledGooglePlacesSeedDiscoveryClient:
    def discover_seed_candidates(
        self,
        *,
        queries: list[str],
        max_results: int,
    ) -> list[GooglePlacesSeedCandidate]:
        del queries, max_results
        return []


class GooglePlacesTextSearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        api_base_url: str = _DEFAULT_GOOGLE_PLACES_API_BASE_URL,
        timeout_seconds: int = 8,
    ) -> None:
        normalized_key = (api_key or "").strip()
        if not normalized_key:
            raise ValueError("Google Places API key is required")
        normalized_base = (api_base_url or _DEFAULT_GOOGLE_PLACES_API_BASE_URL).rstrip("/")
        if not normalized_base:
            normalized_base = _DEFAULT_GOOGLE_PLACES_API_BASE_URL
        self.api_key = normalized_key
        self.api_base_url = normalized_base
        bounded_timeout = int(timeout_seconds)
        bounded_timeout = max(_GOOGLE_PLACES_MIN_TIMEOUT_SECONDS, bounded_timeout)
        self.timeout_seconds = min(_GOOGLE_PLACES_MAX_TIMEOUT_SECONDS, bounded_timeout)

    def discover_seed_candidates(
        self,
        *,
        queries: list[str],
        max_results: int,
    ) -> list[GooglePlacesSeedCandidate]:
        normalized_queries = self._normalize_queries(queries)
        if not normalized_queries:
            return []
        bounded_max_results = max(_GOOGLE_PLACES_MIN_RESULTS, min(_GOOGLE_PLACES_MAX_RESULTS, int(max_results)))
        discovered: list[GooglePlacesSeedCandidate] = []
        seen_place_ids: set[str] = set()

        for query in normalized_queries:
            if len(discovered) >= bounded_max_results:
                break
            remaining = max(1, bounded_max_results - len(discovered))
            for candidate in self._search_text_query(query=query, max_results=remaining):
                place_key = candidate.place_id.lower()
                if place_key in seen_place_ids:
                    continue
                seen_place_ids.add(place_key)
                discovered.append(candidate)
                if len(discovered) >= bounded_max_results:
                    break

        return discovered

    def _search_text_query(
        self,
        *,
        query: str,
        max_results: int,
    ) -> list[GooglePlacesSeedCandidate]:
        bounded_results = max(_GOOGLE_PLACES_MIN_RESULTS, min(_GOOGLE_PLACES_MAX_RESULTS, int(max_results)))
        body = {
            "textQuery": query,
            "maxResultCount": bounded_results,
            "languageCode": "en",
        }
        endpoint = f"{self.api_base_url}{_GOOGLE_PLACES_TEXT_SEARCH_PATH}"
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url=endpoint,
            data=data,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": _GOOGLE_PLACES_FIELD_MASK,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.warning(
                "google_places_seed_query_failed reason=http_error status_code=%s query=%s",
                exc.code,
                query,
            )
            return []
        except urllib.error.URLError as exc:
            logger.warning(
                "google_places_seed_query_failed reason=url_error query=%s detail=%s",
                query,
                str(getattr(exc, "reason", exc)),
            )
            return []
        except TimeoutError:
            logger.warning("google_places_seed_query_failed reason=timeout query=%s", query)
            return []
        except json.JSONDecodeError:
            logger.warning("google_places_seed_query_failed reason=invalid_json query=%s", query)
            return []
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "google_places_seed_query_failed reason=unexpected query=%s detail=%s",
                query,
                str(exc),
            )
            return []

        places = payload.get("places")
        if not isinstance(places, list):
            return []

        candidates: list[GooglePlacesSeedCandidate] = []
        for raw_item in places:
            parsed = self._parse_place_candidate(raw_item)
            if parsed is None:
                continue
            candidates.append(parsed)
            if len(candidates) >= bounded_results:
                break
        return candidates

    def _parse_place_candidate(self, raw_item: object) -> GooglePlacesSeedCandidate | None:
        if not isinstance(raw_item, dict):
            return None

        place_id = _clean_optional(raw_item.get("id"), max_length=_GOOGLE_PLACES_MAX_PLACE_ID_LENGTH)
        display_name = raw_item.get("displayName")
        if isinstance(display_name, dict):
            name = _clean_optional(display_name.get("text"), max_length=_GOOGLE_PLACES_MAX_NAME_LENGTH)
        else:
            name = _clean_optional(display_name, max_length=_GOOGLE_PLACES_MAX_NAME_LENGTH)
        if not place_id or not name:
            return None

        formatted_address = _clean_optional(
            raw_item.get("formattedAddress"), max_length=_GOOGLE_PLACES_MAX_ADDRESS_LENGTH
        )
        locality = self._derive_locality_from_formatted_address(formatted_address)
        primary_type = _clean_optional(raw_item.get("primaryType"), max_length=_GOOGLE_PLACES_MAX_TYPE_LENGTH)

        types: list[str] = []
        raw_types = raw_item.get("types")
        if isinstance(raw_types, list):
            seen: set[str] = set()
            for raw_type in raw_types:
                normalized = _clean_optional(raw_type, max_length=_GOOGLE_PLACES_MAX_TYPE_LENGTH)
                if not normalized:
                    continue
                lowered = normalized.lower()
                if lowered in seen:
                    continue
                seen.add(lowered)
                types.append(lowered)
                if len(types) >= _GOOGLE_PLACES_MAX_TYPES:
                    break

        website_domain = _extract_domain(raw_item.get("websiteUri"))

        return GooglePlacesSeedCandidate(
            source="google_places",
            place_id=place_id,
            name=name,
            formatted_address=formatted_address,
            locality=locality,
            primary_type=primary_type.lower() if primary_type else None,
            types=tuple(types),
            website_domain=website_domain,
        )

    def _normalize_queries(self, raw_queries: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_query in raw_queries:
            cleaned = _clean_optional(raw_query, max_length=_GOOGLE_PLACES_MAX_QUERY_LENGTH)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized.append(cleaned)
        return normalized

    @staticmethod
    def _derive_locality_from_formatted_address(formatted_address: str | None) -> str | None:
        if not formatted_address:
            return None
        parts = [segment.strip() for segment in formatted_address.split(",") if segment.strip()]
        if len(parts) < 2:
            return None
        return _clean_optional(parts[1], max_length=96)


def _clean_optional(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        return normalized[:max_length]
    return normalized


def _extract_domain(value: object) -> str | None:
    cleaned = _clean_optional(value, max_length=_GOOGLE_PLACES_WEBSITE_MAX_LENGTH)
    if not cleaned:
        return None
    candidate = cleaned
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        parsed = urllib.parse.urlsplit(candidate)
    except ValueError:
        return None
    host = (parsed.netloc or "").strip().lower()
    if not host:
        return None
    if host.startswith("www."):
        host = host[4:]
    return host or None
