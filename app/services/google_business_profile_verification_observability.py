from __future__ import annotations

from collections import Counter
from threading import Lock

_ALLOWED_EVENTS: frozenset[str] = frozenset(
    {
        "provider_state_unmapped",
        "provider_method_missing",
        "provider_method_unmapped",
        "provider_error_fallback",
        "option_token_invalid",
        "option_provider_method_unavailable",
        "option_destination_unavailable",
        "option_selected_method_unavailable",
        "verification_record_missing_fields",
        "guidance_fallback_unknown",
    }
)


class GoogleBusinessProfileVerificationObservability:
    """In-process counters for GBP verification normalization/guidance quality signals."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = Lock()

    def increment(self, event: str) -> None:
        if event not in _ALLOWED_EVENTS:
            return
        with self._lock:
            self._counts[event] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


verification_observability = GoogleBusinessProfileVerificationObservability()


def record_gbp_verification_observation(event: str) -> None:
    verification_observability.increment(event)

