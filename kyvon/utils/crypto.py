"""Symmetric encryption for secrets stored in the database (OAuth tokens)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CryptoError(RuntimeError):
    pass


class SecretBox:
    """Fernet (AES-128-CBC + HMAC-SHA256). The key comes from KYVON_ENCRYPTION_KEY."""

    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as error:
            raise CryptoError(
                "KYVON_ENCRYPTION_KEY is not a valid Fernet key. "
                "Generate one with: flask --app wsgi kyvon generate-key"
            ) from error

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as error:
            raise CryptoError(
                "Stored secret could not be decrypted (was KYVON_ENCRYPTION_KEY changed?)."
            ) from error


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")
