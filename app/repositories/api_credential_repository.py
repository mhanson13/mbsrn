from __future__ import annotations

import hashlib
import hmac
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.core.time import utc_now
from app.models.api_credential import APICredential
from app.models.principal import Principal


def hash_bearer_token(token: str, *, pepper: str | None = None) -> str:
    token_bytes = token.encode("utf-8")
    if pepper:
        return hmac.new(pepper.encode("utf-8"), token_bytes, hashlib.sha256).hexdigest()
    return hashlib.sha256(token_bytes).hexdigest()


class APICredentialRepository:
    def __init__(
        self,
        session: Session,
        *,
        token_hash_pepper: str | None = None,
        allow_legacy_hash_fallback: bool = False,
    ) -> None:
        self.session = session
        self.token_hash_pepper = token_hash_pepper
        self.allow_legacy_hash_fallback = allow_legacy_hash_fallback

    def hash_token(self, token: str) -> str:
        return hash_bearer_token(token, pepper=self.token_hash_pepper)

    def _hash_candidates(self, token: str) -> list[str]:
        primary = self.hash_token(token)
        candidates = [primary]
        if self.token_hash_pepper and self.allow_legacy_hash_fallback:
            legacy = hash_bearer_token(token, pepper=None)
            if legacy != primary:
                candidates.append(legacy)
        return candidates

    def create(self, credential: APICredential) -> APICredential:
        self.session.add(credential)
        self.session.flush()
        return credential

    def save(self, credential: APICredential) -> APICredential:
        self.session.add(credential)
        self.session.flush()
        return credential

    def mark_last_used(
        self,
        credential: APICredential,
        *,
        used_at: datetime | None = None,
    ) -> APICredential:
        credential.last_used_at = used_at or utc_now()
        self.session.add(credential)
        self.session.flush()
        return credential

    def get_for_business(self, business_id: str, credential_id: str) -> APICredential | None:
        stmt: Select[tuple[APICredential]] = (
            select(APICredential)
            .options(joinedload(APICredential.principal))
            .where(APICredential.business_id == business_id)
            .where(APICredential.id == credential_id)
        )
        return self.session.scalar(stmt)

    def list_for_business(self, business_id: str) -> list[APICredential]:
        stmt: Select[tuple[APICredential]] = (
            select(APICredential)
            .options(joinedload(APICredential.principal))
            .where(APICredential.business_id == business_id)
            .order_by(APICredential.created_at.desc(), APICredential.id.desc())
        )
        return list(self.session.scalars(stmt))

    def get_active_by_token(self, token: str) -> APICredential | None:
        for token_hash in self._hash_candidates(token):
            stmt: Select[tuple[APICredential]] = (
                select(APICredential)
                .join(
                    Principal,
                    (Principal.business_id == APICredential.business_id)
                    & (Principal.id == APICredential.principal_id),
                )
                .where(APICredential.token_hash == token_hash)
                .where(APICredential.is_active.is_(True))
                .where(APICredential.revoked_at.is_(None))
                .where(Principal.is_active.is_(True))
            )
            credential = self.session.scalar(stmt)
            if credential is not None:
                return credential
        return None
