from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from ..config import get_settings

_hasher = PasswordHasher()


# ---------------- App password hashing ----------------


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False


def password_needs_rehash(hashed: str) -> bool:
    return _hasher.check_needs_rehash(hashed)


# ---------------- KEK (Key Encryption Key) — wraps per-user DEKs ----------------


def _load_kek_keys() -> list[str]:
    """Resolve the KEK material from settings.

    Priority: FERNET_KEYS (csv, primary first) > FERNET_KEY (single).
    The first key is used for encryption; all keys are tried for decryption,
    which is what enables zero-downtime rotation.
    """
    settings = get_settings()
    if settings.fernet_keys is not None:
        raw = settings.fernet_keys.get_secret_value()
        keys = [k.strip() for k in raw.split(",") if k.strip()]
        if not keys:
            raise RuntimeError("FERNET_KEYS is set but empty")
        return keys
    if settings.fernet_key is not None:
        return [settings.fernet_key.get_secret_value()]
    raise RuntimeError("FERNET_KEY / FERNET_KEYS is not configured")


@lru_cache(maxsize=1)
def _kek() -> MultiFernet:
    return MultiFernet([Fernet(k.encode()) for k in _load_kek_keys()])


def reset_kek_cache() -> None:
    """Clear the cached KEK. Call after settings change (e.g. in tests)."""
    _kek.cache_clear()


def kek_encrypt(plain: bytes) -> bytes:
    return _kek().encrypt(plain)


def kek_decrypt(token: bytes) -> bytes:
    try:
        return _kek().decrypt(token)
    except InvalidToken as exc:
        raise RuntimeError(
            "KEK decrypt failed — none of FERNET_KEYS could read this ciphertext"
        ) from exc


def kek_rewrap(token: bytes) -> bytes:
    """Re-encrypt a KEK-encrypted blob with the *current* primary key.

    Used during rotation: walk every encrypted_dek in the DB, call rewrap,
    save back. Old keys can then be dropped from FERNET_KEYS safely.
    """
    return _kek().rotate(token)


# ---------------- DEK (per-user Data Encryption Key) ----------------
#
# Each user gets one randomly-generated Fernet key (the DEK). The DEK is
# stored on the user row, encrypted with the KEK ("envelope encryption").
# Compromising the KEK alone does not reveal UNEC passwords; compromising
# the DB alone does not either. Both must leak together.


def generate_dek() -> bytes:
    """Return a fresh raw Fernet key (urlsafe-base64, 32 bytes of entropy)."""
    return Fernet.generate_key()


def wrap_dek(raw_dek: bytes) -> bytes:
    """Encrypt a DEK with the KEK for storage in the users table."""
    return kek_encrypt(raw_dek)


def unwrap_dek(wrapped: bytes) -> bytes:
    """Decrypt a stored DEK with the KEK."""
    return kek_decrypt(wrapped)


def encrypt_with_dek(raw_dek: bytes, plain: str) -> bytes:
    return Fernet(raw_dek).encrypt(plain.encode())


def decrypt_with_dek(raw_dek: bytes, token: bytes) -> str:
    try:
        return Fernet(raw_dek).decrypt(token).decode()
    except InvalidToken as exc:
        raise RuntimeError("DEK decrypt failed — DEK/ciphertext mismatch") from exc


# ---------------- JWT ----------------


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


class InvalidTokenError(Exception):
    pass


@dataclass(slots=True)
class TokenPayload:
    sub: str  # user id (uuid as string)
    type: TokenType
    jti: str
    exp: datetime
    iat: datetime


def _jwt_secret() -> str:
    settings = get_settings()
    if settings.secret_key is None:
        raise RuntimeError("SECRET_KEY is not configured")
    return settings.secret_key.get_secret_value()


def _encode(*, sub: str, token_type: TokenType, ttl: timedelta, jti: str | None = None) -> tuple[str, TokenPayload]:
    settings = get_settings()
    now = datetime.now(UTC)
    exp = now + ttl
    payload_jti = jti or uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": sub,
        "type": token_type.value,
        "jti": payload_jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=settings.jwt_algorithm)
    return token, TokenPayload(sub=sub, type=token_type, jti=payload_jti, exp=exp, iat=now)


def issue_access_token(user_id: uuid.UUID) -> tuple[str, TokenPayload]:
    settings = get_settings()
    return _encode(
        sub=str(user_id),
        token_type=TokenType.ACCESS,
        ttl=timedelta(minutes=settings.access_token_ttl_min),
    )


def issue_refresh_token(user_id: uuid.UUID, *, jti: str | None = None) -> tuple[str, TokenPayload]:
    settings = get_settings()
    return _encode(
        sub=str(user_id),
        token_type=TokenType.REFRESH,
        ttl=timedelta(days=settings.refresh_token_ttl_days),
        jti=jti,
    )


def decode_token(token: str, *, expected_type: TokenType) -> TokenPayload:
    settings = get_settings()
    try:
        raw = jwt.decode(token, _jwt_secret(), algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise InvalidTokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if raw.get("type") != expected_type.value:
        raise InvalidTokenError(f"expected {expected_type.value} token, got {raw.get('type')}")

    return TokenPayload(
        sub=raw["sub"],
        type=TokenType(raw["type"]),
        jti=raw["jti"],
        exp=datetime.fromtimestamp(raw["exp"], tz=UTC),
        iat=datetime.fromtimestamp(raw["iat"], tz=UTC),
    )
