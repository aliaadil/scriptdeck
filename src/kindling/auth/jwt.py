from __future__ import annotations

import time
import uuid
from threading import Lock

import jwt

_revocation_lock = Lock()
_revoked: dict[str, int] = {}  # jti -> exp epoch seconds


def encode_jwt(user_id: int, role: str, secret: str, ttl: int = 86400) -> tuple[str, str, int]:
    now = int(time.time())
    exp = now + ttl
    jti = uuid.uuid4().hex
    # RFC 7519 requires sub to be a string; encode as str and let callers parse back.
    payload = {"sub": str(user_id), "role": role, "iat": now, "exp": exp, "jti": jti}
    token = jwt.encode(payload, secret, algorithm="HS256")
    return token, jti, exp


def decode_jwt(token: str, secret: str) -> dict:
    payload = jwt.decode(token, secret, algorithms=["HS256"])
    with _revocation_lock:
        if payload.get("jti") in _revoked:
            raise jwt.InvalidTokenError("token revoked")
    return payload


def revoke(jti: str, exp: int) -> None:
    with _revocation_lock:
        _revoked[jti] = exp


def cleanup_revoked(now: int | None = None) -> int:
    """Drop expired entries. Returns count removed."""
    if now is None:
        now = int(time.time())
    with _revocation_lock:
        expired = [k for k, v in _revoked.items() if v <= now]
        for k in expired:
            del _revoked[k]
    return len(expired)
