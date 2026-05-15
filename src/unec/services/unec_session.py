"""Per-user UNEC session management.

The UNEC cabinet authenticates with a sticky `PHPSESSID` cookie (plus the
load-balancer's `SERVERID`). We cache that cookie jar in Redis per app user so
we don't have to re-login on every request. When the cached session is missing
or rejected by the cabinet, we fetch the user's encrypted UNEC credentials
from Postgres, log in, and store the fresh jar back in Redis.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TypeVar

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..scraper.client import AuthError as UnecAuthError
from ..scraper.client import CloudflareBlocked, UnecClient
from . import cloudflare as cf_service
from . import unec_credentials as creds_service


T = TypeVar("T")


class UnecSessionError(Exception):
    pass


class NoUnecCredentials(UnecSessionError):
    """User has not configured their UNEC credentials yet."""


def _session_key(user_id: uuid.UUID) -> str:
    return f"unec:session:{user_id}"


def _lock_key(user_id: uuid.UUID) -> str:
    return f"unec:session:{user_id}:lock"


class UnecSessionManager:
    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    async def _load_cookies(self, user_id: uuid.UUID) -> dict[str, str] | None:
        raw = await self._redis.get(_session_key(user_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            await self._redis.delete(_session_key(user_id))
            return None

    async def _save_cookies(self, user_id: uuid.UUID, cookies: dict[str, str]) -> None:
        ttl_seconds = get_settings().unec_session_ttl_min * 60
        await self._redis.set(_session_key(user_id), json.dumps(cookies), ex=ttl_seconds)

    async def invalidate(self, user_id: uuid.UUID) -> None:
        await self._redis.delete(_session_key(user_id))

    async def _do_login_with_cf_retry(
        self, username: str, password: str, base_url: str
    ) -> dict[str, str]:
        """Run the UNEC login flow, refreshing the shared cf_clearance once on
        a Cloudflare challenge mid-flight."""
        for attempt in range(2):
            bundle = await cf_service.get_clearance(self._redis, force=attempt == 1)
            async with UnecClient(
                base_url=base_url,
                cf_cookie=bundle.cookie,
                user_agent=bundle.user_agent,
            ) as client:
                try:
                    await client.login(username, password)
                except CloudflareBlocked:
                    if attempt == 1:
                        raise
                    continue
                return client.dump_cookies()
        raise RuntimeError("unreachable")

    async def _login_and_cache(
        self, user_id: uuid.UUID, db_session: AsyncSession
    ) -> dict[str, str]:
        creds = await creds_service.get_decrypted_password(db_session, user_id)
        if creds is None:
            raise NoUnecCredentials(str(user_id))
        username, password = creds

        settings = get_settings()
        cookies = await self._do_login_with_cf_retry(username, password, settings.unec_base_url)

        await self._save_cookies(user_id, cookies)

        # Best-effort touch of last_login_at; not critical if it fails.
        stored = await creds_service.get_credentials(db_session, user_id)
        if stored is not None:
            stored.last_login_at = datetime.now(UTC)
            await db_session.commit()

        return cookies

    async def _acquire_login_lock(self, user_id: uuid.UUID) -> str:
        """Lock-free coordination so concurrent requests don't all hammer UNEC.

        First arrival sets the lock with a unique token; others poll for the
        cookie cache to appear. Lock expires after 30s as a safety net.
        """
        token = secrets.token_hex(8)
        key = _lock_key(user_id)
        for _ in range(30):
            if await self._redis.set(key, token, ex=30, nx=True):
                return token
            await asyncio.sleep(0.2)
        # Timeout — proceed anyway; worst case we double-login.
        return token

    async def _release_login_lock(self, user_id: uuid.UUID, token: str) -> None:
        key = _lock_key(user_id)
        # Only delete if it still belongs to us.
        current = await self._redis.get(key)
        if current == token:
            await self._redis.delete(key)

    async def _ensure_cookies(
        self, user_id: uuid.UUID, db_session: AsyncSession, *, force: bool = False
    ) -> tuple[dict[str, str], bool]:
        """Return (cookies, from_cache)."""
        if not force:
            cached = await self._load_cookies(user_id)
            if cached:
                return cached, True

        token = await self._acquire_login_lock(user_id)
        try:
            # Re-check after acquiring the lock — another request may have just
            # populated the cache.
            if not force:
                cached = await self._load_cookies(user_id)
                if cached:
                    return cached, True
            cookies = await self._login_and_cache(user_id, db_session)
            return cookies, False
        finally:
            await self._release_login_lock(user_id, token)

    @asynccontextmanager
    async def client_for(self, user_id: uuid.UUID, db_session: AsyncSession):
        """Yield a logged-in UnecClient for the given user.

        Does NOT auto-retry on session expiry — use :meth:`fetch` for that, or
        catch ``UnecAuthError`` and call :meth:`invalidate` yourself.
        """
        cookies, _ = await self._ensure_cookies(user_id, db_session)
        settings = get_settings()
        bundle = await cf_service.get_clearance(self._redis)
        async with UnecClient(
            base_url=settings.unec_base_url,
            cf_cookie=bundle.cookie,
            user_agent=bundle.user_agent,
        ) as client:
            client.set_cookies({**cookies, "cf_clearance": bundle.cookie})
            yield client
            # Persist any updated cookies (UNEC may rotate PHPSESSID).
            # cf_clearance is shared in Redis, so strip it from per-user cache.
            jar = client.dump_cookies()
            jar.pop("cf_clearance", None)
            await self._save_cookies(user_id, jar)

    async def fetch(
        self,
        user_id: uuid.UUID,
        db_session: AsyncSession,
        fetcher: Callable[[UnecClient], Awaitable[T]],
    ) -> T:
        """Run ``fetcher(client)`` with auto-retry on session/Cloudflare expiry.

        Three failure shapes are handled:
        - ``UnecAuthError``: PHPSESSID expired → drop the per-user cache, log
          back in, retry once.
        - ``CloudflareBlocked``: shared cf_clearance is dead → force-refresh
          via Playwright, retry once.
        - Anything else: propagate.
        """
        settings = get_settings()
        for attempt in range(2):
            force_user = attempt == 1
            cookies, _ = await self._ensure_cookies(user_id, db_session, force=force_user)
            bundle = await cf_service.get_clearance(self._redis, force=False)
            async with UnecClient(
                base_url=settings.unec_base_url,
                cf_cookie=bundle.cookie,
                user_agent=bundle.user_agent,
            ) as client:
                client.set_cookies({**cookies, "cf_clearance": bundle.cookie})
                try:
                    result = await fetcher(client)
                except CloudflareBlocked:
                    # Shared clearance is stale. Refresh it and retry with the
                    # SAME per-user PHPSESSID (no need to re-login UNEC).
                    await cf_service.get_clearance(self._redis, force=True)
                    if attempt == 1:
                        raise
                    continue
                except UnecAuthError:
                    await self.invalidate(user_id)
                    if attempt == 1:
                        raise
                    continue
                jar = client.dump_cookies()
                jar.pop("cf_clearance", None)
                await self._save_cookies(user_id, jar)
                return result
        # Unreachable — the loop either returns or re-raises.
        raise RuntimeError("unreachable")
