from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...core.rate_limit import limiter
from ...db.models import User
from ...services import push as push_service
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/push", tags=["push"])


class VapidKeyOut(BaseModel):
    public_key: str


class SubscribeIn(BaseModel):
    endpoint: str
    p256dh: str
    auth: str


class UnsubscribeIn(BaseModel):
    endpoint: str


class PushStatusOut(BaseModel):
    enabled: bool
    subscription_count: int


@router.get("/vapid-key", response_model=VapidKeyOut)
async def vapid_key() -> VapidKeyOut:
    """Public VAPID key the browser needs when calling PushManager.subscribe."""
    settings = get_settings()
    if not settings.vapid_public_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "push not configured")
    return VapidKeyOut(public_key=settings.vapid_public_key)


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def subscribe(
    request: Request,
    payload: SubscribeIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    await push_service.register_subscription(
        session,
        user_id=user.id,
        endpoint=payload.endpoint,
        p256dh=payload.p256dh,
        auth=payload.auth,
    )


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def unsubscribe(
    request: Request,
    payload: UnsubscribeIn,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    await push_service.unregister_subscription(
        session, user_id=user.id, endpoint=payload.endpoint
    )


@router.get("/status", response_model=PushStatusOut)
async def status_endpoint(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> PushStatusOut:
    subs = await push_service.get_user_subscriptions(session, user.id)
    return PushStatusOut(enabled=len(subs) > 0, subscription_count=len(subs))
