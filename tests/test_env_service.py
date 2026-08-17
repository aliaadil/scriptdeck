import base64
import pytest

from kindling.services.env_service import EnvService


@pytest.fixture
def svc():
    key = base64.b64encode(b"k" * 32).decode()
    return EnvService(key)


def test_encrypt_decrypt_roundtrip(svc):
    ct, nonce = svc.encrypt(b"FOO=bar\nBAZ=qux\n")
    assert svc.decrypt(ct, nonce) == b"FOO=bar\nBAZ=qux\n"


def test_decrypt_lines(svc):
    ct, nonce = svc.encrypt(b"FOO=bar\nBAZ=qux\n")
    assert svc.decrypt_lines(ct, nonce) == {"FOO": "bar", "BAZ": "qux"}


def test_wrong_key_fails():
    k1 = base64.b64encode(b"a" * 32).decode()
    k2 = base64.b64encode(b"b" * 32).decode()
    s1 = EnvService(k1)
    s2 = EnvService(k2)
    ct, nonce = s1.encrypt(b"x=1")
    with pytest.raises(Exception):
        s2.decrypt(ct, nonce)


def test_invalid_key_length():
    with pytest.raises(ValueError):
        EnvService(base64.b64encode(b"short").decode())