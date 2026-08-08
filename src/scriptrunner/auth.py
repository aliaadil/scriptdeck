"""Single-user HTTP Basic authentication backed by bcrypt."""

from __future__ import annotations

import base64
import binascii
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class BasicAuth:
    """Configured Basic auth credentials for one user.

    ``password_hash`` is a bcrypt hash, never a plaintext password.  bcrypt's
    password verification is deliberately expensive and timing-resistant; the
    username comparison also uses ``compare_digest`` and we still verify the
    password when the username is wrong to avoid a cheap username oracle.
    """

    username: str
    password_hash: str

    def check(self, authorization: str | None) -> bool:
        credentials = decode_authorization(authorization)
        if credentials is None:
            return False

        username, password = credentials
        username_matches = hmac.compare_digest(
            username.encode("utf-8"), self.username.encode("utf-8")
        )
        try:
            import bcrypt

            password_matches = bcrypt.checkpw(password, self.password_hash.encode("ascii"))
        except (ImportError, ValueError, TypeError):
            # A bad optional-dependency installation or malformed configured
            # hash must fail closed rather than turn into an open endpoint.
            password_matches = False
        return username_matches and password_matches


def decode_authorization(value: str | None) -> tuple[str, bytes] | None:
    """Decode a Basic Authorization header into username and password bytes."""

    if not value:
        return None
    scheme, separator, encoded = value.partition(" ")
    if not separator or scheme.lower() != "basic" or not encoded:
        return None
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None
    username, separator, password = decoded.partition(b":")
    if not separator:
        return None
    try:
        return username.decode("utf-8"), password
    except UnicodeDecodeError:
        return None


def parse_basic_auth(value: str | None) -> BasicAuth | None:
    """Parse ``SCRIPTDECK_BASIC_AUTH`` in ``username:bcrypt_hash`` format."""

    if value is None:
        return None
    username, separator, password_hash = value.partition(":")
    if not separator or not username or not password_hash:
        raise ValueError("SCRIPTDECK_BASIC_AUTH must use username:bcrypt_hash format")
    if not password_hash.startswith(("$2a$", "$2b$", "$2y$")):
        raise ValueError("SCRIPTDECK_BASIC_AUTH must contain a bcrypt hash")
    return BasicAuth(username=username, password_hash=password_hash)
