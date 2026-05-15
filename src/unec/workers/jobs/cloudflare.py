"""Periodic Cloudflare clearance refresh.

Runs in the worker. Spawns headless Chromium, harvests `cf_clearance`,
stores it in Redis. Every user request reads the same cookie.

Schedule (in `arq_app.py`):
- Every 45 minutes (Cloudflare cookies live ~60 min; refresh preemptively)
- Once on worker startup so the cache is warm before the first user request
"""
from __future__ import annotations

import logging

import redis.asyncio as redis

from ...services import cloudflare as cf_service

logger = logging.getLogger(__name__)


async def refresh_cloudflare_clearance(ctx: dict, *, force: bool = True) -> dict:
    """ARQ job: harvest a fresh Cloudflare clearance cookie.

    Forces a refresh by default — cron callers want a freshly-issued
    cookie, not whatever happens to be cached. Pass ``force=False`` for
    the startup warm-up (don't overwrite a still-valid cookie inherited
    from the previous worker run).
    """
    redis_client: redis.Redis = ctx["redis_client"]
    try:
        bundle = await cf_service.get_clearance(redis_client, force=force)
    except cf_service.CloudflareError as exc:
        logger.warning("cloudflare refresh failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "cookie_prefix": bundle.cookie[:12],
        "user_agent": bundle.user_agent,
        "age_seconds": bundle.age_seconds,
    }
