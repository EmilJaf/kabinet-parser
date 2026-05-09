from __future__ import annotations

import uuid
from dataclasses import dataclass

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.security import (
    InvalidTokenError,
    TokenType,
    decode_token,
    hash_password,
    issue_access_token,
    issue_refresh_token,
    verify_password,
)
from ..db.models import User


class AuthError(Exception):
    pass


class EmailAlreadyTaken(AuthError):
    pass


class InvalidCredentials(AuthError):
    pass


class InvalidRefreshToken(AuthError):
    pass


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def _refresh_key(jti: str) -> str:
    return f"auth:refresh:{jti}"


async def register_user(session: AsyncSession, *, email: str, password: str) -> User:
    user = User(email=email.lower(), password_hash=hash_password(password))
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise EmailAlreadyTaken(email) from exc
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    stmt = select(User).where(User.email == email.lower())
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials()
    return user


async def get_user_by_email(session: AsyncSession, *, email: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    return (await session.execute(stmt)).scalar_one_or_none()


async def issue_token_pair(redis_client: redis.Redis, user_id: uuid.UUID) -> TokenPair:
    access_token, _ = issue_access_token(user_id)
    refresh_token, refresh_payload = issue_refresh_token(user_id)

    ttl_seconds = max(int((refresh_payload.exp - refresh_payload.iat).total_seconds()), 1)
    await redis_client.set(_refresh_key(refresh_payload.jti), str(user_id), ex=ttl_seconds)

    return TokenPair(access_token=access_token, refresh_token=refresh_token)


async def rotate_refresh_token(redis_client: redis.Redis, refresh_token: str) -> TokenPair:
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise InvalidRefreshToken(str(exc)) from exc

    stored_user = await redis_client.get(_refresh_key(payload.jti))
    if stored_user is None or stored_user != payload.sub:
        raise InvalidRefreshToken("refresh token revoked or unknown")

    # Single-use refresh — delete current jti before issuing new pair.
    await redis_client.delete(_refresh_key(payload.jti))
    return await issue_token_pair(redis_client, uuid.UUID(payload.sub))


async def revoke_refresh_token(redis_client: redis.Redis, refresh_token: str) -> None:
    """Best-effort logout. Silently no-ops on invalid/expired tokens."""
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except InvalidTokenError:
        return
    await redis_client.delete(_refresh_key(payload.jti))
