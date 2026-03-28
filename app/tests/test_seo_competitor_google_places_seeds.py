from __future__ import annotations

import json
import urllib.request

from app.integrations.google_places import GooglePlacesTextSearchClient


class _FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        del exc_type, exc, tb
        return None


def test_google_places_seed_client_parses_minimal_fields(monkeypatch) -> None:
    def _urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        assert request.full_url.endswith("/places:searchText")
        assert timeout == 8
        field_mask = (
            request.headers.get("X-Goog-FieldMask")
            or request.headers.get("X-goog-fieldmask")
            or request.headers.get("x-goog-fieldmask")
        )
        assert field_mask == (
            "places.id,places.displayName.text,places.formattedAddress,"
            "places.primaryType,places.types,places.websiteUri"
        )
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["textQuery"] == "fire protection near 80501"
        assert payload["maxResultCount"] == 2
        return _FakeHTTPResponse(
            {
                "places": [
                    {
                        "id": "places/123",
                        "displayName": {"text": "Front Range Fire"},
                        "formattedAddress": "100 Main St, Longmont, CO 80501, USA",
                        "primaryType": "fire_protection_service",
                        "types": ["fire_protection_service", "point_of_interest"],
                        "websiteUri": "https://www.frfire.example/services",
                    }
                ]
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    client = GooglePlacesTextSearchClient(
        api_key="test-key",
        timeout_seconds=8,
    )
    results = client.discover_seed_candidates(
        queries=["fire protection near 80501"],
        max_results=2,
    )
    assert len(results) == 1
    item = results[0]
    assert item.source == "google_places"
    assert item.place_id == "places/123"
    assert item.name == "Front Range Fire"
    assert item.formatted_address == "100 Main St, Longmont, CO 80501, USA"
    assert item.locality == "Longmont"
    assert item.primary_type == "fire_protection_service"
    assert item.types == ("fire_protection_service", "point_of_interest")
    assert item.website_domain == "frfire.example"


def test_google_places_seed_client_dedupes_and_drops_invalid_entries(monkeypatch) -> None:
    def _urlopen(request: urllib.request.Request, timeout: int):  # noqa: ANN001
        del request, timeout
        return _FakeHTTPResponse(
            {
                "places": [
                    {"id": "places/1", "displayName": {"text": "Valid One"}},
                    {"id": "places/1", "displayName": {"text": "Duplicate Id"}},
                    {"id": "places/2", "displayName": {"text": ""}},
                    {"id": "", "displayName": {"text": "Missing Id"}},
                    {"displayName": {"text": "Missing Id Field"}},
                ]
            }
        )

    monkeypatch.setattr(urllib.request, "urlopen", _urlopen)
    client = GooglePlacesTextSearchClient(api_key="test-key")
    results = client.discover_seed_candidates(
        queries=["q1", "q1", "   "],
        max_results=5,
    )
    assert len(results) == 1
    assert results[0].place_id == "places/1"
    assert results[0].name == "Valid One"
