from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EnvService:
    """AES-GCM encrypt/decrypt for per-script .env blobs."""

    def __init__(self, key_b64: str) -> None:
        try:
            key = base64.b64decode(key_b64)
        except Exception as exc:
            raise ValueError(f"invalid base64 key: {exc}") from exc
        if len(key) != 32:
            raise ValueError("env_encryption_key must decode to 32 bytes")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: bytes) -> tuple[str, str]:
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext, associated_data=None)
        return base64.b64encode(ct).decode(), base64.b64encode(nonce).decode()

    def decrypt(self, ct_b64: str, nonce_b64: str) -> bytes:
        ct = base64.b64decode(ct_b64)
        nonce = base64.b64decode(nonce_b64)
        return self._aes.decrypt(nonce, ct, associated_data=None)

    def decrypt_lines(self, ct_b64: str, nonce_b64: str) -> dict[str, str]:
        raw = self.decrypt(ct_b64, nonce_b64).decode("utf-8")
        out: dict[str, str] = {}
        for line in raw.splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
        return out
