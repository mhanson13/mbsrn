from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.principal import Principal, PrincipalRole
from app.models.principal_identity import PrincipalIdentity
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_identity_repository import PrincipalIdentityRepository
from app.repositories.principal_repository import PrincipalRepository

GOOGLE_PROVIDER = "google"
BOOTSTRAP_ACTOR = "bootstrap-admin-script"


@dataclass(frozen=True)
class BootstrapAdminResult:
    principal_id: str
    business_id: str
    role: PrincipalRole
    principal_action: str
    identity_action: str


def run_bootstrap_admin(*, email: str, role: PrincipalRole) -> BootstrapAdminResult:
    normalized_email = _normalize_email(email)
    settings = get_settings()
    default_business_id = settings.default_business_id.strip()
    if not default_business_id:
        raise RuntimeError("DEFAULT_BUSINESS_ID is required.")

    try:
        with SessionLocal() as session:
            business_repository = BusinessRepository(session)
            principal_repository = PrincipalRepository(session)
            principal_identity_repository = PrincipalIdentityRepository(session)

            principal, principal_action = _upsert_principal(
                email=normalized_email,
                role=role,
                default_business_id=default_business_id,
                business_repository=business_repository,
                principal_repository=principal_repository,
                principal_identity_repository=principal_identity_repository,
            )
            identity_action = _upsert_google_identity(
                principal=principal,
                email=normalized_email,
                principal_identity_repository=principal_identity_repository,
            )

            session.commit()
            return BootstrapAdminResult(
                principal_id=principal.id,
                business_id=principal.business_id,
                role=principal.role,
                principal_action=principal_action,
                identity_action=identity_action,
            )
    except SQLAlchemyError as exc:
        raise RuntimeError(f"Database operation failed: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    role = PrincipalRole(args.role)
    configured_default_admin_email = get_settings().default_admin_email
    resolved_email = args.email or configured_default_admin_email
    if not resolved_email:
        print(
            "bootstrap_admin failed: email is required via --email or DEFAULT_ADMIN_EMAIL.",
            file=sys.stderr,
        )
        return 1

    try:
        result = run_bootstrap_admin(email=resolved_email, role=role)
    except (RuntimeError, ValueError) as exc:
        print(f"bootstrap_admin failed: {exc}", file=sys.stderr)
        return 1

    normalized_email = resolved_email.strip().lower()
    if result.principal_action == "created":
        print(f"created principal {normalized_email} with role {result.role.value}")
    elif result.principal_action == "updated":
        print(f"updated principal {normalized_email} to role {result.role.value}")
    else:
        print("principal already exists with correct role")

    if result.identity_action == "created":
        print("created google identity placeholder mapping for first-login subject binding")
    elif result.identity_action == "updated":
        print("updated google identity mapping")

    print(f"business_id={result.business_id} principal_id={result.principal_id}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.scripts.bootstrap_admin",
        description="Create or update a bootstrap principal for first admin access.",
    )
    parser.add_argument(
        "--email",
        required=False,
        help="Principal email used for bootstrap identity mapping. "
        "Defaults to DEFAULT_ADMIN_EMAIL when omitted.",
    )
    parser.add_argument(
        "--role",
        default=PrincipalRole.ADMIN.value,
        choices=[PrincipalRole.ADMIN.value, PrincipalRole.OPERATOR.value],
        help="Principal role (default: admin).",
    )
    return parser


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("email is required.")
    if len(normalized) > 320:
        raise ValueError("email must be 320 characters or fewer.")
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("email must be a valid address.")
    return normalized


def _upsert_principal(
    *,
    email: str,
    role: PrincipalRole,
    default_business_id: str,
    business_repository: BusinessRepository,
    principal_repository: PrincipalRepository,
    principal_identity_repository: PrincipalIdentityRepository,
) -> tuple[Principal, str]:
    identities = principal_identity_repository.list_for_provider_email(provider=GOOGLE_PROVIDER, email=email)
    identity_keys = {(identity.business_id, identity.principal_id) for identity in identities}
    if len(identity_keys) > 1:
        raise RuntimeError(
            f"Email '{email}' is mapped to multiple principals. "
            "Resolve duplicate principal identity mappings before running bootstrap."
        )

    principal: Principal | None
    if identity_keys:
        business_id, principal_id = next(iter(identity_keys))
        principal = principal_repository.get_for_business(business_id, principal_id)
        if principal is None:
            raise RuntimeError(
                f"Identity mapping exists for business_id='{business_id}' principal_id='{principal_id}' "
                "but principal record is missing."
            )
    else:
        principal = principal_repository.get_for_business(default_business_id, email)

    if principal is None:
        if business_repository.get(default_business_id) is None:
            raise RuntimeError(
                f"Default business '{default_business_id}' was not found. "
                "Apply migrations and seed business data before bootstrapping."
            )
        created = Principal(
            business_id=default_business_id,
            id=email,
            display_name=email,
            created_by_principal_id=BOOTSTRAP_ACTOR,
            updated_by_principal_id=BOOTSTRAP_ACTOR,
            role=role,
            is_active=True,
        )
        principal_repository.create(created)
        return created, "created"

    updated = False
    if principal.role != role:
        principal.role = role
        updated = True
    if not principal.is_active:
        principal.is_active = True
        updated = True
    if updated:
        principal.updated_by_principal_id = BOOTSTRAP_ACTOR
        principal_repository.save(principal)
        return principal, "updated"
    return principal, "noop"


def _upsert_google_identity(
    *,
    principal: Principal,
    email: str,
    principal_identity_repository: PrincipalIdentityRepository,
) -> str:
    identities = principal_identity_repository.list_for_business_principal(
        business_id=principal.business_id,
        principal_id=principal.id,
    )
    google_identity = next((identity for identity in identities if identity.provider == GOOGLE_PROVIDER), None)

    if google_identity is None:
        placeholder = principal_identity_repository.get_by_provider_subject(
            provider=GOOGLE_PROVIDER,
            provider_subject=email,
        )
        if placeholder is not None:
            if placeholder.business_id != principal.business_id or placeholder.principal_id != principal.id:
                raise RuntimeError(
                    f"Provider subject placeholder '{email}' is already assigned to a different principal."
                )
            google_identity = placeholder
        else:
            principal_identity_repository.create(
                PrincipalIdentity(
                    id=str(uuid4()),
                    provider=GOOGLE_PROVIDER,
                    provider_subject=email,
                    business_id=principal.business_id,
                    principal_id=principal.id,
                    email=email,
                    email_verified=False,
                    is_active=True,
                )
            )
            return "created"

    updated = False
    if google_identity.email != email:
        google_identity.email = email
        updated = True
    if not google_identity.is_active:
        google_identity.is_active = True
        updated = True
    if updated:
        principal_identity_repository.save(google_identity)
        return "updated"
    return "noop"


if __name__ == "__main__":
    raise SystemExit(main())
