from __future__ import annotations

from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionService,
    GoogleBusinessProfileTokenRewrapSummary,
)


class GoogleBusinessProfileTokenRewrapJob:
    """Admin-only wrapper for GBP provider token key rotation rewrap execution."""

    def __init__(self, connection_service: GoogleBusinessProfileConnectionService) -> None:
        self.connection_service = connection_service

    def run(
        self,
        *,
        dry_run: bool,
        business_id: str | None = None,
        tenant_id: str | None = None,
        batch_size: int = 100,
    ) -> GoogleBusinessProfileTokenRewrapSummary:
        return self.connection_service.run_token_rewrap_job(
            dry_run=dry_run,
            business_id=business_id,
            tenant_id=tenant_id,
            batch_size=batch_size,
        )
