from __future__ import annotations

import base64
import hashlib
from typing import Mapping

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - handled at runtime when feature is configured
    Fernet = None  # type: ignore[assignment]

    class InvalidToken(Exception):  # type: ignore[override]
        pass


class TokenCipherError(ValueError):
    pass


class FernetTokenCipher:
    """Symmetric encryption helper for provider access/refresh token persistence."""

    def __init__(
        self,
        *,
        active_key_version: str | None = None,
        keyring: Mapping[str, str] | None = None,
        secret: str | None = None,
        key_version: str = "v1",
    ) -> None:
        active_version = (active_key_version or key_version).strip()
        if not active_version:
            raise TokenCipherError("Token cipher active key version is required.")

        normalized_keyring: dict[str, str] = {}
        if keyring:
            for version, material in keyring.items():
                normalized_version = str(version).strip()
                normalized_material = str(material).strip()
                if not normalized_version:
                    continue
                if not normalized_material:
                    raise TokenCipherError(f"Token cipher key material is empty for version '{normalized_version}'.")
                normalized_keyring[normalized_version] = normalized_material
        elif secret:
            normalized_secret = secret.strip()
            if not normalized_secret:
                raise TokenCipherError("Token cipher secret is required.")
            normalized_keyring[active_version] = normalized_secret

        if not normalized_keyring:
            raise TokenCipherError("Token cipher keyring is required.")
        if active_version not in normalized_keyring:
            raise TokenCipherError(
                f"Token cipher active key version '{active_version}' is not present in the configured keyring."
            )
        if Fernet is None:
            raise TokenCipherError("cryptography package is required for encrypted provider token persistence.")

        self.active_key_version = active_version
        self._fernets_by_version: dict[str, Fernet] = {}
        for version, material in normalized_keyring.items():
            key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
            self._fernets_by_version[version] = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        normalized = plaintext.strip()
        if not normalized:
            raise TokenCipherError("Cannot encrypt an empty token value.")
        return self._fernets_by_version[self.active_key_version].encrypt(normalized.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str, *, key_version: str) -> str:
        normalized = ciphertext.strip()
        normalized_key_version = key_version.strip()
        if not normalized:
            raise TokenCipherError("Cannot decrypt an empty token value.")
        if not normalized_key_version:
            raise TokenCipherError("Token key version is required for decryption.")
        fernet = self._fernets_by_version.get(normalized_key_version)
        if fernet is None:
            raise TokenCipherError(f"Token key version '{normalized_key_version}' is not available in the keyring.")
        try:
            return fernet.decrypt(normalized.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenCipherError("Encrypted provider token is invalid or corrupted.") from exc
