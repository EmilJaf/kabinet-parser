"""Rate limiting setup for the FastAPI app.

Uses SlowAPI with Redis as the storage backend so limits are shared across
worker processes. Limits are intentionally tight on auth endpoints — these
are the only realistic brute-force surfaces.
"""
from __future__ import annotations

from fastapi import Request, Response
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from ..config import get_settings


def _client_key(request: Request) -> str:
    """Per-IP key. Honours X-Forwarded-For when running behind a reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=_client_key,
    storage_uri=get_settings().redis_url,
    strategy="fixed-window",
)


def too_many_requests_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Friendly JSON response on 429 — same shape as our other API errors."""
    detail = (
        "Слишком много запросов. Подождите немного и попробуйте снова."
    )
    return JSONResponse(
        status_code=429,
        content={"detail": detail, "limit": str(exc.detail)},
        headers={"Retry-After": "60"},
    )
