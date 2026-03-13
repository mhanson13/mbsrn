from __future__ import annotations

import hashlib

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models.api_credential import APICredential


def hash_bearer_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class APICredentialRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, credential: APICredential) -> APICredential:
        self.session.add(credential)
        self.session.flush()
        return credential

    def get_active_by_token(self, token: str) -> APICredential | None:
        token_hash = hash_bearer_token(token)
        stmt: Select[tuple[APICredential]] = (
            select(APICredential)
            .where(APICredential.token_hash == token_hash)
            .where(APICredential.is_active.is_(True))
            .where(APICredential.revoked_at.is_(None))
        )
        return self.session.scalar(stmt)
