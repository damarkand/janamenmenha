import pytest

from app.core.config import Settings
from app.core.errors import AuthError
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_hash_uses_random_salt_and_verifies():
    h1, h2 = hash_password("secret"), hash_password("secret")
    assert h1 != h2 and h1.startswith("pbkdf2_sha256$")
    assert verify_password("secret", h1) and verify_password("secret", h2)
    assert not verify_password("wrong", h1)


def test_verify_rejects_malformed_hash():
    assert not verify_password("secret", "not-a-hash")


def test_token_roundtrip(settings):
    token, ttl = create_access_token("u-1", "hr", settings)
    payload = decode_access_token(token, settings)
    assert payload["sub"] == "u-1" and payload["role"] == "hr"
    assert ttl == settings.jwt_ttl_minutes * 60


def test_expired_token_rejected(settings):
    settings.jwt_ttl_minutes = -1
    token, _ = create_access_token("u-1", "hr", settings)
    with pytest.raises(AuthError, match="истёк"):
        decode_access_token(token, settings)


def test_token_signed_with_other_secret_rejected(settings):
    token, _ = create_access_token("u-1", "hr", settings)
    other = Settings()
    other.jwt_secret = "completely-different-secret-for-tests-0123456789"
    with pytest.raises(AuthError, match="Недействительный"):
        decode_access_token(token, other)


def test_garbage_token_rejected(settings):
    with pytest.raises(AuthError):
        decode_access_token("garbage", settings)
