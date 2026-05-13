from __future__ import annotations

import asyncio

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...core.rate_limit import limiter
from ...core.security import hash_password, verify_password
from ...db.models import User
from ...services import auth as auth_service
from ..deps import get_current_user, get_db, get_redis
from ..schemas import LoginIn, RegisterIn, UserOut, UserPreferencesIn

router = APIRouter(prefix="/auth", tags=["auth"])

# Pre-computed dummy hash so login() runs argon2 verify even when the email
# doesn't exist — keeps response time roughly constant and prevents user
# enumeration via timing.
_DUMMY_HASH = hash_password("__placeholder__used_for_constant_time_login__")


def _set_auth_cookies(response: Response, tokens: auth_service.TokenPair) -> None:
    settings = get_settings()
    common = {
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": settings.cookie_samesite,
        "domain": settings.cookie_domain,
    }
    response.set_cookie(
        key=settings.access_cookie_name,
        value=tokens.access_token,
        max_age=settings.access_token_ttl_min * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=tokens.refresh_token,
        max_age=settings.refresh_token_ttl_days * 24 * 3600,
        path="/v1/auth",  # only sent to auth endpoints (refresh, logout)
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.access_cookie_name, path="/", domain=settings.cookie_domain)
    response.delete_cookie(
        settings.refresh_cookie_name, path="/v1/auth", domain=settings.cookie_domain
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/hour")
async def register(
    request: Request,
    payload: RegisterIn,
    session: AsyncSession = Depends(get_db),
) -> UserOut:
    """Create a new account.

    Returns 201 whether or not the email was already registered — keeps the
    response shape constant so attackers can't enumerate registered emails.
    """
    try:
        user = await auth_service.register_user(
            session, email=payload.email, password=payload.password
        )
        return UserOut.model_validate(user)
    except auth_service.EmailAlreadyTaken:
        # Mirror the timing of a real registration (argon2 is the slow part).
        await asyncio.sleep(0)
        # Fetch the existing user so we can return the same shape — but we do
        # NOT log them in or expose anything they couldn't already see.
        existing = await auth_service.get_user_by_email(session, email=payload.email)
        if existing is not None:
            return UserOut.model_validate(existing)
        # Fallback: synthesize a placeholder response (shouldn't happen).
        raise HTTPException(status.HTTP_201_CREATED, detail="created")


@router.post("/login", response_model=UserOut)
@limiter.limit("5/15minutes")
async def login(
    request: Request,
    response: Response,
    payload: LoginIn,
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> UserOut:
    """Authenticate and set HttpOnly auth cookies.

    Always runs an argon2 verify (against a dummy hash if the user doesn't
    exist) so timing doesn't leak account existence.
    """
    user = await auth_service.get_user_by_email(session, email=payload.email)
    valid_user = (
        user is not None
        and verify_password(payload.password, user.password_hash)
    )
    if user is None:
        # Constant-time decoy verify.
        verify_password(payload.password, _DUMMY_HASH)

    if not valid_user or user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")

    tokens = await auth_service.issue_token_pair(redis_client, user.id)
    _set_auth_cookies(response, tokens)
    return UserOut.model_validate(user)


@router.post("/refresh", response_model=UserOut)
@limiter.limit("30/minute")
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> UserOut:
    settings = get_settings()
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="missing refresh token")
    try:
        tokens = await auth_service.rotate_refresh_token(redis_client, refresh_token)
    except auth_service.InvalidRefreshToken as exc:
        _clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_auth_cookies(response, tokens)

    # Return current user so the client can refresh its in-memory profile.
    from uuid import UUID

    from ...core.security import TokenType, decode_token

    payload = decode_token(tokens.access_token, expected_type=TokenType.ACCESS)
    user = await session.get(User, UUID(payload.sub))
    if user is None:
        _clear_auth_cookies(response)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return UserOut.model_validate(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    redis_client: redis.Redis = Depends(get_redis),
) -> None:
    settings = get_settings()
    refresh_token = request.cookies.get(settings.refresh_cookie_name)
    if refresh_token:
        await auth_service.revoke_refresh_token(redis_client, refresh_token)
    _clear_auth_cookies(response)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
@limiter.limit("20/minute")
async def update_me(
    request: Request,
    payload: UserPreferencesIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserOut:
    """Update the calling user's editable preferences (currently just
    language). Only fields present in the payload are touched."""
    if payload.language is not None:
        user.language = payload.language
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)
