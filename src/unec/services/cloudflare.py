"""Cloudflare Managed Challenge bypass via headless Chromium.

`kabinet.unec.edu.az` sits behind Cloudflare's Managed Challenge — a 403
page that runs JS to fingerprint the client, then issues a `cf_clearance`
cookie once the challenge passes. Plain HTTP clients (httpx, curl) can't
execute that JS, so they get a permanent 403.

This service runs Playwright with a stealth-patched Chromium periodically,
lets the challenge solve itself in-browser, scrapes `cf_clearance` +
the exact User-Agent Chromium used, and parks them in Redis. The existing
`UnecClient` (httpx) then attaches both to every request alongside the
per-user `PHPSESSID` / `SERVERID`. Cloudflare binds the cookie to (source
IP, UA), so one harvested cookie serves every user behind this server.

Refresh policy:
- TTL in Redis: 50 minutes (CF cookies live ~1 hour, refresh preemptively)
- Worker cron: every 45 minutes
- On-demand refresh under a Redis lock if any caller hits a 403 from CF
- Failures fall back to whatever's currently cached; only fully empty
  cache propagates as `CloudflareClearanceUnavailable`
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass

import redis.asyncio as redis

from ..config import get_settings

logger = logging.getLogger(__name__)

# Cookie cache key in Redis. Single global key — Cloudflare binds clearance
# to source IP + UA, and the whole app shares one outbound IP, so one cookie
# is correct for every user.
_CACHE_KEY = "unec:cf_clearance"
# Lock to avoid two parallel Chromium spawns when several callers notice
# a stale cache at the same time. 60s comfortably covers a worst-case
# solve (launch 15 + nav 15 + challenge 20 + slack).
_LOCK_KEY = "unec:cf_clearance:lock"
_LOCK_TTL_SECONDS = 60
# Stored 50 min — Cloudflare's `cf_clearance` typically lives 60 min. We
# bias toward refreshing slightly early so we never serve a freshly-expired
# cookie on a real user request.
_CACHE_TTL_SECONDS = 50 * 60
# Per-step timeouts. Wrapped via asyncio.wait_for around each Playwright
# call — our first prod deploy hung silently inside Playwright and dragged
# every concurrent request down with it. Per-step timeouts make the hang
# point visible in logs and let the Redis lock be released on schedule.
_LAUNCH_TIMEOUT_SECONDS = 15
_NAV_TIMEOUT_SECONDS = 15
_CHALLENGE_TIMEOUT_SECONDS = 20
# Loser-wait deadline: how long a caller polls the cache while another
# refresh is in flight. Comfortably less than the lock TTL so that, if
# the lock disappears before this deadline, we can detect a failed solve
# explicitly instead of waiting the full TTL.
_LOSER_WAIT_SECONDS = 50


class CloudflareError(RuntimeError):
    pass


class CloudflareClearanceUnavailable(CloudflareError):
    """No clearance cookie is currently cached and a fresh fetch failed."""


@dataclass(frozen=True)
class ClearanceBundle:
    cookie: str
    user_agent: str
    fetched_at: float  # unix seconds

    @property
    def age_seconds(self) -> int:
        return int(time.time() - self.fetched_at)

    def to_json(self) -> str:
        return json.dumps(
            {"cookie": self.cookie, "user_agent": self.user_agent, "fetched_at": self.fetched_at}
        )

    @classmethod
    def from_json(cls, raw: str) -> "ClearanceBundle | None":
        try:
            data = json.loads(raw)
            return cls(
                cookie=str(data["cookie"]),
                user_agent=str(data["user_agent"]),
                fetched_at=float(data["fetched_at"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None


async def load_cached(redis_client: redis.Redis) -> ClearanceBundle | None:
    raw = await redis_client.get(_CACHE_KEY)
    if raw is None:
        return None
    return ClearanceBundle.from_json(raw)


async def store(redis_client: redis.Redis, bundle: ClearanceBundle) -> None:
    await redis_client.set(_CACHE_KEY, bundle.to_json(), ex=_CACHE_TTL_SECONDS)


async def invalidate(redis_client: redis.Redis) -> None:
    await redis_client.delete(_CACHE_KEY)


async def _acquire_lock(redis_client: redis.Redis) -> str | None:
    """Try to grab the refresh lock. Returns the token on success, None if
    someone else already holds it. The caller polls when None."""
    token = secrets.token_hex(8)
    ok = await redis_client.set(_LOCK_KEY, token, ex=_LOCK_TTL_SECONDS, nx=True)
    return token if ok else None


async def _release_lock(redis_client: redis.Redis, token: str) -> None:
    current = await redis_client.get(_LOCK_KEY)
    if current == token:
        await redis_client.delete(_LOCK_KEY)


async def get_clearance(
    redis_client: redis.Redis, *, force: bool = False
) -> ClearanceBundle:
    """Return a fresh clearance bundle, refreshing via Chromium if needed.

    - `force=False`: return cached if present, otherwise refresh.
    - `force=True`: drop the cache and refresh.

    Concurrent callers share a single Chromium spawn: the first arrival
    holds a Redis lock and refreshes; the rest poll for the cache to fill.
    """
    if force:
        await invalidate(redis_client)

    cached = await load_cached(redis_client)
    if cached is not None:
        return cached

    # No cache — race to refresh. Winner runs Chromium, losers poll.
    token = await _acquire_lock(redis_client)
    if token is None:
        return await _wait_for_cache(redis_client)

    try:
        bundle = await _solve_in_browser()
        await store(redis_client, bundle)
        logger.info(
            "cloudflare: harvested clearance (cookie=%s…, ua=%s)",
            bundle.cookie[:12],
            bundle.user_agent[:48],
        )
        return bundle
    except Exception:
        logger.exception("cloudflare: solve failed")
        # Surface the latest cache if a parallel caller managed to fill it
        # between our entry and the failure.
        cached = await load_cached(redis_client)
        if cached is not None:
            return cached
        raise CloudflareClearanceUnavailable("Cloudflare challenge solve failed")
    finally:
        await _release_lock(redis_client, token)


async def _wait_for_cache(redis_client: redis.Redis) -> ClearanceBundle:
    """Poll the cache while another worker refreshes.

    Two exit conditions for failure:
    - The deadline expires (winner is taking too long or genuinely hung).
    - The lock disappears but the cache is still empty (winner gave up).

    The second case is the important one — previously losers waited the
    full deadline even after the winner had already failed.
    """
    deadline = time.monotonic() + _LOSER_WAIT_SECONDS
    while time.monotonic() < deadline:
        cached = await load_cached(redis_client)
        if cached is not None:
            return cached
        # Solver order is: store(bundle) → release(lock). If the lock is
        # gone we'd expect the cache to be filled within a few ms; if not,
        # the solver crashed without publishing.
        if not await redis_client.exists(_LOCK_KEY):
            await asyncio.sleep(0.3)
            cached = await load_cached(redis_client)
            if cached is not None:
                return cached
            raise CloudflareClearanceUnavailable(
                "Cloudflare solver finished without publishing a clearance cookie"
            )
        await asyncio.sleep(0.4)
    raise CloudflareClearanceUnavailable(
        "Timed out waiting for parallel Cloudflare refresh"
    )


async def _solve_in_browser() -> ClearanceBundle:
    """Spawn Chromium, navigate to the cabinet, scrape cf_clearance.

    Imports patchright lazily so the rest of the app still boots in
    environments where Chromium isn't installed (e.g. unit tests on CI).

    Each Playwright step is wrapped in asyncio.wait_for: in our first prod
    deploy the entire solve hung silently and dragged every concurrent
    request down with it. Per-step timeouts surface the hang point in
    logs immediately and let the lock release on schedule.
    """
    # patchright exposes the same async_api as upstream playwright — only
    # the import path differs. The patched Chromium binary is what makes
    # this version pass CF's CDP-detection step.
    from patchright.async_api import async_playwright

    settings = get_settings()
    target_url = settings.unec_base_url.rstrip("/") + "/"

    logger.info("cloudflare: solve start (target=%s)", target_url)
    async with async_playwright() as pw:
        logger.info("cloudflare: playwright driver ready")
        browser = await asyncio.wait_for(
            pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            ),
            timeout=_LAUNCH_TIMEOUT_SECONDS,
        )
        logger.info("cloudflare: chromium launched")
        try:
            # patchright's docs explicitly recommend NOT calling
            # context.add_init_script — JS-level patches mutate the runtime
            # in CDP-detectable ways and have been a tell on managed
            # challenge since late 2024. The patched Chromium itself
            # already handles navigator.webdriver, plugins, etc.
            context = await browser.new_context(
                locale="az-AZ",
                timezone_id="Asia/Baku",
                no_viewport=True,
            )
            page = await context.new_page()
            logger.info("cloudflare: navigating")

            await asyncio.wait_for(
                page.goto(
                    target_url,
                    wait_until="domcontentloaded",
                    timeout=_NAV_TIMEOUT_SECONDS * 1000,
                ),
                timeout=_NAV_TIMEOUT_SECONDS + 5,
            )
            logger.info("cloudflare: initial nav done (title=%r)", await page.title())

            await asyncio.wait_for(
                _wait_for_clearance(context, page),
                timeout=_CHALLENGE_TIMEOUT_SECONDS,
            )

            cookies = await context.cookies(target_url)
            cf_value: str | None = None
            for c in cookies:
                if c.get("name") == "cf_clearance":
                    cf_value = c.get("value")
                    break
            if not cf_value:
                raise CloudflareError(
                    "Challenge appeared to pass but no cf_clearance cookie was set"
                )

            ua = await page.evaluate("() => navigator.userAgent")
            logger.info("cloudflare: solve done")
            return ClearanceBundle(
                cookie=str(cf_value),
                user_agent=str(ua),
                fetched_at=time.time(),
            )
        finally:
            try:
                await asyncio.wait_for(browser.close(), timeout=5)
            except Exception:
                logger.warning("cloudflare: browser close hung; abandoning")


async def _wait_for_clearance(context, page) -> None:
    """Poll cookies/title until the challenge resolves.

    Outer-bounded by the asyncio.wait_for in the caller; this loop just
    runs until that fires or the cookie shows up.
    """
    target = page.url
    iterations = 0
    while True:
        for c in await context.cookies(target):
            if c.get("name") == "cf_clearance" and c.get("value"):
                logger.info("cloudflare: cf_clearance cookie observed")
                return
        if iterations == 0 or iterations % 8 == 0:
            try:
                title = await page.title()
            except Exception:
                title = "?"
            logger.info("cloudflare: still waiting (title=%r, iter=%d)", title, iterations)
        iterations += 1
        await asyncio.sleep(0.6)
