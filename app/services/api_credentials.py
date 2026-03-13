from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.api_credential import APICredential
from app.repositories.api_credential_repository import APICredentialRepository
from app.repositories.business_repository import BusinessRepository


class APICredentialNotFoundError(ValueError):
    pass


class APICredentialValidationError(ValueError):
    pass


@dataclass(frozen=True)
class IssuedAPICredential:
    credential: APICredential
    token: str


class APICredentialService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        api_credential_repository: APICredentialRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.api_credential_repository = api_credential_repository

    def list_for_business(self, *, business_id: str) -> list[APICredential]:
        self._ensure_business_exists(business_id)
        return self.api_credential_repository.list_for_business(business_id)

    def create_credential(self, *, business_id: str, principal_id: str) -> IssuedAPICredential:
        self._ensure_business_exists(business_id)
        normalized_principal_id = self._normalize_principal_id(principal_id)
        return self._issue_new_credential(
            business_id=business_id,
            principal_id=normalized_principal_id,
        )

    def disable_credential(self, *, business_id: str, credential_id: str) -> APICredential:
        credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
        credential.is_active = False
        self.api_credential_repository.save(credential)
        self.session.commit()
        self.session.refresh(credential)
        return credential

    def revoke_credential(self, *, business_id: str, credential_id: str) -> APICredential:
        credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
        if credential.revoked_at is None:
            credential.revoked_at = utc_now()
        credential.is_active = False
        self.api_credential_repository.save(credential)
        self.session.commit()
        self.session.refresh(credential)
        return credential

    def rotate_credential(self, *, business_id: str, credential_id: str) -> IssuedAPICredential:
        credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
        if credential.revoked_at is not None:
            raise APICredentialValidationError("Credential is already revoked and cannot be rotated.")

        for _ in range(3):
            token = secrets.token_urlsafe(32)
            replacement = APICredential(
                id=str(uuid4()),
                business_id=business_id,
                principal_id=credential.principal_id,
                token_hash=self.api_credential_repository.hash_token(token),
                is_active=True,
                revoked_at=None,
            )
            try:
                credential.is_active = False
                credential.revoked_at = utc_now()
                self.api_credential_repository.save(credential)
                self.api_credential_repository.create(replacement)
                self.session.commit()
                self.session.refresh(replacement)
                return IssuedAPICredential(credential=replacement, token=token)
            except IntegrityError:
                self.session.rollback()
                credential = self._get_for_business(business_id=business_id, credential_id=credential_id)
                if credential.revoked_at is not None:
                    raise APICredentialValidationError("Credential is already revoked and cannot be rotated.")

        raise APICredentialValidationError("Unable to rotate credential token. Retry request.")

    def _issue_new_credential(
        self,
        *,
        business_id: str,
        principal_id: str,
    ) -> IssuedAPICredential:
        # Token is generated once and only returned at issue/rotate time.
        for _ in range(3):
            token = secrets.token_urlsafe(32)
            credential = APICredential(
                id=str(uuid4()),
                business_id=business_id,
                principal_id=principal_id,
                token_hash=self.api_credential_repository.hash_token(token),
                is_active=True,
                revoked_at=None,
            )
            try:
                self.api_credential_repository.create(credential)
                self.session.commit()
                self.session.refresh(credential)
                return IssuedAPICredential(credential=credential, token=token)
            except IntegrityError:
                self.session.rollback()
                continue
        raise APICredentialValidationError("Unable to issue credential token. Retry request.")

    def _normalize_principal_id(self, principal_id: str) -> str:
        normalized = principal_id.strip()
        if not normalized:
            raise APICredentialValidationError("principal_id is required.")
        if len(normalized) > 64:
            raise APICredentialValidationError("principal_id must be 64 characters or fewer.")
        return normalized

    def _ensure_business_exists(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise APICredentialNotFoundError("Business not found")

    def _get_for_business(self, *, business_id: str, credential_id: str) -> APICredential:
        self._ensure_business_exists(business_id)
        credential = self.api_credential_repository.get_for_business(business_id, credential_id)
        if credential is None:
            raise APICredentialNotFoundError("API credential not found")
        return credential
