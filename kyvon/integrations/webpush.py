"""Web Push (RFC 8030) with VAPID (RFC 8292) and aes128gcm payload encryption (RFC 8291).

Implemented directly on ``cryptography``. The payload encryption is checked against the
RFC 8291 test vector in the test suite; delivery to real push services (Apple, Google,
Mozilla) has not been exercised from this repository.

Safety: the server POSTs to an address the *client* provided, so an endpoint is only
accepted when it is https and belongs to a known push service (see ``ALLOWED_HOST_SUFFIXES``).
Without that check the subscribe API would be a way to make the server call arbitrary URLs.
"""

from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ALLOWED_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
    "wns.windows.com",
)
RECORD_SIZE = 4096
TTL_SECONDS = 24 * 3600


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def is_allowed_endpoint(endpoint: str) -> bool:
    parsed = urlparse(endpoint or "")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        return False
    if parsed.port not in (None, 443):
        return False
    return any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES)


def generate_vapid_keys() -> tuple[str, str]:
    """(public, private) as URL-safe base64: the uncompressed public point and the raw scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return b64e(public), b64e(private)


def _private_from_raw(raw_b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64d(raw_b64), "big"), ec.SECP256R1())


def vapid_authorization(
    endpoint: str, subject: str, public_key: str, private_key: str, *, now: float | None = None
) -> str:
    parsed = urlparse(endpoint)
    claims = {
        "aud": f"{parsed.scheme}://{parsed.netloc}",
        "exp": int((now or time.time()) + 12 * 3600),
        "sub": subject,
    }
    signing_input = (
        b64e(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
        + "."
        + b64e(json.dumps(claims, separators=(",", ":")).encode())
    )
    der = _private_from_raw(private_key).sign(
        signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256())
    )
    r, s = decode_dss_signature(der)
    token = signing_input + "." + b64e(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={public_key}"


def encrypt_payload(
    plaintext: bytes,
    ua_public_b64: str,
    auth_secret_b64: str,
    *,
    salt: bytes | None = None,
    server_private: ec.EllipticCurvePrivateKey | None = None,
) -> bytes:
    """aes128gcm body for one push message (RFC 8291 section 3)."""
    if len(plaintext) > RECORD_SIZE - 17:
        raise ValueError("Push payloads are limited to about 4 KB.")
    ua_public_bytes = b64d(ua_public_b64)
    auth_secret = b64d(auth_secret_b64)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public_bytes)
    server_private = server_private or ec.generate_private_key(ec.SECP256R1())
    as_public = server_private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    salt = salt or os.urandom(16)

    shared = server_private.exchange(ec.ECDH(), ua_public)
    ikm = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=auth_secret,
        info=b"WebPush: info\x00" + ua_public_bytes + as_public,
    ).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext + b"\x02", None)  # 0x02: last record
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public + ciphertext


class WebPushError(Exception):
    def __init__(self, status: int):
        super().__init__(f"push service returned HTTP {status}")
        self.status = status

    @property
    def gone(self) -> bool:
        return self.status in (404, 410)  # the subscription no longer exists


class WebPushSender:
    """Sends one encrypted message to one subscription."""

    def __init__(self, http: Any, *, public_key: str, private_key: str, subject: str):
        self._http = http
        self._public = public_key
        self._private = private_key
        self._subject = subject

    def send(self, endpoint: str, keys: dict, message: dict) -> None:
        if not is_allowed_endpoint(endpoint):
            raise WebPushError(400)
        body = encrypt_payload(json.dumps(message).encode("utf-8"), keys["p256dh"], keys["auth"])
        response = self._http.request(
            "POST",
            endpoint,
            data=body,
            headers={
                "Authorization": vapid_authorization(
                    endpoint, self._subject, self._public, self._private
                ),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                "Urgency": "normal",
            },
            timeout=10,
        )
        if response.status_code >= 400:
            raise WebPushError(response.status_code)
