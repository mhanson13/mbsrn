from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from app.core.config import Settings, get_settings
from app.core.token_cipher import FernetTokenCipher, TokenCipherError
from app.db.session import SessionLocal
from app.jobs.google_business_profile_token_rewrap import GoogleBusinessProfileTokenRewrapJob
from app.repositories.auth_audit_repository import AuthAuditRepository
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_repository import PrincipalRepository
from app.repositories.provider_connection_repository import ProviderConnectionRepository
from app.repositories.provider_oauth_state_repository import ProviderOAuthStateRepository
from app.services.auth_audit import AuthAuditService
from app.services.google_business_profile_connection import (
    GoogleBusinessProfileConnectionConfigurationError,
    GoogleBusinessProfileConnectionService,
    GoogleBusinessProfileConnectionValidationError,
)


class _NoopOAuthWebClient:
    """Rewrap job does not require outbound Google OAuth calls."""

    def build_auth_url(self, **_: object) -> str:
        raise RuntimeError("OAuth auth URL generation is unavailable in the token rewrap CLI.")

    def exchange_code_for_tokens(self, **_: object) -> object:
        raise RuntimeError("OAuth token exchange is unavailable in the token rewrap CLI.")

    def refresh_access_token(self, **_: object) -> object:
        raise RuntimeError("OAuth refresh is unavailable in the token rewrap CLI.")

    def revoke_token(self, **_: object) -> bool:
        raise RuntimeError("OAuth token revocation is unavailable in the token rewrap CLI.")


def run_rewrap_gbp_tokens(
    *,
    dry_run: bool,
    all_connections: bool,
    business_id: str | None,
    tenant_id: str | None,
    batch_size: int = 100,
) -> dict[str, object]:
    normalized_business_id, normalized_tenant_id = _resolve_scope_filters(
        all_connections=all_connections,
        business_id=business_id,
        tenant_id=tenant_id,
    )
    settings = get_settings()
    token_cipher = _build_token_cipher(settings)

    with SessionLocal() as session:
        service = _build_connection_service(
            session=session,
            settings=settings,
            token_cipher=token_cipher,
        )
        job = GoogleBusinessProfileTokenRewrapJob(connection_service=service)
        summary = job.run(
            dry_run=dry_run,
            business_id=normalized_business_id,
            tenant_id=normalized_tenant_id,
            batch_size=batch_size,
        )
        if dry_run:
            session.rollback()
        return summary.to_dict()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_rewrap_gbp_tokens(
            dry_run=args.dry_run,
            all_connections=args.all,
            business_id=args.business_id,
            tenant_id=args.tenant_id,
            batch_size=args.batch_size,
        )
    except (
        GoogleBusinessProfileConnectionValidationError,
        GoogleBusinessProfileConnectionConfigurationError,
        TokenCipherError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2

    print(json.dumps(summary, indent=2))
    if not args.dry_run and int(summary.get("failed", 0)) > 0:
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.rewrap_gbp_tokens",
        description="Re-encrypt Google Business Profile provider tokens with the active key version.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview candidate rows without modifying the database.")
    parser.add_argument("--all", action="store_true", help="Process all businesses.")
    parser.add_argument("--business-id", help="Limit processing to one business UUID.")
    parser.add_argument("--tenant-id", help="Optional tenant UUID alias for business scope.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Fetch size for provider connection iteration (default: 100).",
    )
    return parser


def _resolve_scope_filters(
    *,
    all_connections: bool,
    business_id: str | None,
    tenant_id: str | None,
) -> tuple[str | None, str | None]:
    normalized_business_id = (business_id or "").strip() or None
    normalized_tenant_id = (tenant_id or "").strip() or None
    if normalized_business_id and normalized_tenant_id and normalized_business_id != normalized_tenant_id:
        raise ValueError("business_id and tenant_id must match when both are provided.")
    if all_connections and (normalized_business_id or normalized_tenant_id):
        raise ValueError("Choose either --all or a scoped --business-id/--tenant-id filter.")
    if not all_connections and not normalized_business_id and not normalized_tenant_id:
        raise ValueError("Scope is required: pass --all or --business-id/--tenant-id.")
    return normalized_business_id, normalized_tenant_id


def _build_token_cipher(settings: Settings) -> FernetTokenCipher:
    keyring = settings.google_oauth_token_encryption_keys
    if not keyring:
        raise RuntimeError("GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON must be configured for token rewrap operations.")
    return FernetTokenCipher(
        active_key_version=settings.google_oauth_token_encryption_key_version,
        keyring=keyring,
    )


def _build_connection_service(
    *,
    session,
    settings: Settings,
    token_cipher: FernetTokenCipher,
) -> GoogleBusinessProfileConnectionService:
    business_repository = BusinessRepository(session)
    return GoogleBusinessProfileConnectionService(
        session=session,
        business_repository=business_repository,
        principal_repository=PrincipalRepository(session),
        provider_connection_repository=ProviderConnectionRepository(session),
        provider_oauth_state_repository=ProviderOAuthStateRepository(session),
        oauth_client=_NoopOAuthWebClient(),  # type: ignore[arg-type]
        token_cipher=token_cipher,
        auth_audit_service=AuthAuditService(
            session=session,
            business_repository=business_repository,
            auth_audit_repository=AuthAuditRepository(session),
        ),
        redirect_uri=(settings.google_business_profile_redirect_uri or "https://localhost/_unused"),
        state_ttl_seconds=settings.google_business_profile_state_ttl_seconds,
        refresh_skew_seconds=settings.google_oauth_refresh_skew_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
