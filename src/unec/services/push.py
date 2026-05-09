"""Web Push delivery + subscription management."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from functools import lru_cache

from py_vapid import Vapid01
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import PushSubscription

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PushPayload:
    title: str
    body: str
    # Where notificationclick should navigate; passed through to the SW.
    url: str = "/dashboard"
    # Stable string so re-sending replaces a prior notification instead of
    # stacking up. None = let the browser stack.
    tag: str | None = None


class VapidNotConfigured(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _vapid() -> Vapid01:
    """Parse the PEM private key into a Vapid object once and cache it.

    pywebpush.webpush(vapid_private_key=<str>) expects URL-safe base64 of
    the raw DER, not a PEM string. Passing PEM as a string makes it try
    to base64-decode the entire `-----BEGIN PRIVATE KEY-----...` blob and
    blow up with ASN.1 parse errors. Vapid01.from_pem accepts the PEM bytes
    we have on disk and returns an object pywebpush understands directly.
    """
    settings = get_settings()
    if settings.vapid_private_key is None:
        raise VapidNotConfigured("VAPID private key not configured")
    pem_str = settings.vapid_private_key.get_secret_value()
    return Vapid01.from_pem(pem_str.encode("utf-8"))


async def register_subscription(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> PushSubscription:
    """Idempotent: re-subscribing the same endpoint refreshes its keys."""
    stmt = (
        pg_insert(PushSubscription)
        .values(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        .on_conflict_do_update(
            index_elements=[PushSubscription.endpoint],
            set_={
                "user_id": user_id,
                "p256dh": p256dh,
                "auth": auth,
            },
        )
        .returning(PushSubscription)
    )
    row = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return row


async def unregister_subscription(
    session: AsyncSession, *, user_id: uuid.UUID, endpoint: str
) -> bool:
    stmt = delete(PushSubscription).where(
        PushSubscription.user_id == user_id,
        PushSubscription.endpoint == endpoint,
    )
    result = await session.execute(stmt)
    await session.commit()
    return (result.rowcount or 0) > 0


async def get_user_subscriptions(
    session: AsyncSession, user_id: uuid.UUID
) -> list[PushSubscription]:
    stmt = select(PushSubscription).where(PushSubscription.user_id == user_id)
    return list((await session.execute(stmt)).scalars().all())


async def send_push(
    session: AsyncSession, *, user_id: uuid.UUID, payload: PushPayload
) -> int:
    """Send `payload` to every subscription this user has.

    Returns the number of successful deliveries. Subscriptions the push
    service rejects with 404/410 (Gone — endpoint unregistered) are
    deleted automatically.
    """
    settings = get_settings()
    if settings.vapid_public_key is None or settings.vapid_private_key is None:
        raise VapidNotConfigured("VAPID keys not configured")

    vapid_obj = _vapid()
    vapid_claims = {"sub": settings.vapid_subject}

    subs = await get_user_subscriptions(session, user_id)
    if not subs:
        return 0

    body = json.dumps(
        {
            "title": payload.title,
            "body": payload.body,
            "url": payload.url,
            "tag": payload.tag,
        }
    )
    delivered = 0
    stale_endpoints: list[str] = []

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=body,
                vapid_private_key=vapid_obj,
                vapid_claims=vapid_claims,
            )
            delivered += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                stale_endpoints.append(sub.endpoint)
                logger.info(
                    "push: endpoint gone for user %s, will GC: %s", user_id, sub.endpoint[:60]
                )
            else:
                logger.warning("push: delivery failed (status=%s): %s", status, exc)

    if stale_endpoints:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint.in_(stale_endpoints))
        )
        await session.commit()

    return delivered
