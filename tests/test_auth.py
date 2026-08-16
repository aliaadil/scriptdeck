import pytest
from argon2.exceptions import VerifyMismatchError

from scriptdeck.auth.passwords import hash_password, verify_password
from scriptdeck.auth.jwt import encode_jwt, decode_jwt
from scriptdeck.auth.users import create_user, get_by_email


def test_password_hash_and_verify():
    h = hash_password("hunter2")
    assert verify_password("hunter2", h)
    assert not verify_password("wrong", h)


def test_jwt_roundtrip():
    token, jti, exp = encode_jwt(user_id=1, role="admin", secret="x" * 32)
    payload = decode_jwt(token, secret="x" * 32)
    # PyJWT >=2.10 requires sub to be a string (RFC 7519); int() round-trips back.
    assert int(payload["sub"]) == 1
    assert payload["role"] == "admin"
    assert payload["jti"] == jti
    assert payload["exp"] == exp


def test_jwt_rejects_tampered():
    token, _, _ = encode_jwt(user_id=1, role="admin", secret="x" * 32)
    with pytest.raises(Exception):
        decode_jwt(token + "x", secret="x" * 32)


@pytest.mark.asyncio
async def test_create_and_get_user(tmp_db):
    from scriptdeck.db.engine import make_engine, session_factory
    from scriptdeck.db.migrations import run_migrations
    engine = make_engine(__import__("scriptdeck").config.Settings(db_path=str(tmp_db)))
    await run_migrations(engine)
    Session = session_factory(engine)
    async with Session() as s:
        u = await create_user(s, "a@b.com", "pw", role="admin")
        await s.commit()
        uid = u.id
    async with Session() as s:
        got = await get_by_email(s, "a@b.com")
        assert got is not None
        assert got.id == uid
        assert got.role == "admin"