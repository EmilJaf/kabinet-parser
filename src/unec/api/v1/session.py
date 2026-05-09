from __future__ import annotations

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.rate_limit import limiter
from ...db.models import User
from ...scraper.client import AuthError as UnecAuthError
from ...services.unec_session import (
    NoUnecCredentials,
    UnecSessionManager,
)
from ..deps import get_current_user, get_db, get_redis

router = APIRouter(prefix="/unec/session", tags=["unec-session"])


@router.post("/test")
@limiter.limit("10/minute")
async def test_session(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> dict:
    """Probe the UNEC cabinet using the user's stored credentials.

    Logs in via the cached session if possible, otherwise re-authenticates and
    caches a new one. Returns whether the dashboard responded with our
    authenticated marker.
    """
    manager = UnecSessionManager(redis_client)

    async def fetcher(client):
        await client.get("/az/noteandannounce")
        return None

    try:
        await manager.fetch(user.id, session, fetcher)
    except NoUnecCredentials as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="UNEC credentials are not configured for this user",
        ) from exc
    except UnecAuthError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="UNEC rejected the session — credentials may have changed",
        ) from exc

    return {"ok": True}
