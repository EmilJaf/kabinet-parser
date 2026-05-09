from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import redis.asyncio as redis
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..core.security import InvalidTokenError, TokenType, decode_token
from ..db.base import get_session_factory
from ..db.models import User


async def get_db() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def get_redis(request: Request) -> redis.Redis:
    return request.app.state.redis


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the current user from the access cookie.

    For backwards compat (CLI, debugging) we also accept Bearer tokens in
    the Authorization header — but the SPA path is cookie-only.
    """
    settings = get_settings()
    token: str | None = request.cookies.get(settings.access_cookie_name)
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()

    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    try:
        payload = decode_token(token, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user = await session.get(User, uuid.UUID(payload.sub))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """Gate /v1/admin/* endpoints — must come AFTER auth resolution."""
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="admin only")
    return user
