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
# a stale cache at the same time. 60s is well over a normal refresh.
_LOCK_KEY = "unec:cf_clearance:lock"
_LOCK_TTL_SECONDS = 60
# Stored 50 min — Cloudflare's `cf_clearance` typically lives 60 min. We
# bias toward refreshing slightly early so we never serve a freshly-expired
# cookie on a real user request.
_CACHE_TTL_SECONDS = 50 * 60
# Hard ceiling on how long a single challenge solve may take. The actual
# challenge resolves in 3–8 seconds; the long tail is network jitter +
# Chromium cold-start.
_SOLVE_TIMEOUT_SECONDS = 45


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
    """Poll the cache while another worker refreshes. Bounded by the lock TTL."""
    deadline = time.monotonic() + _LOCK_TTL_SECONDS + 5
    while time.monotonic() < deadline:
        cached = await load_cached(redis_client)
        if cached is not None:
            return cached
        await asyncio.sleep(0.5)
    raise CloudflareClearanceUnavailable(
        "Timed out waiting for parallel Cloudflare refresh"
    )


# Minimal stealth init script. Cloudflare's Managed Challenge sniffs these
# values; setting them to "real Chrome" defaults gets us past the obvious
# automation tells. Heavier patches (WebGL vendor spoof, audio fingerprint)
# aren't needed in practice — they're what stealth libraries add, but for
# a residential-traffic-volume bypass like ours, this minimum is enough.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', {
  get: () => [
    { name: 'PDF Viewer' },
    { name: 'Chrome PDF Viewer' },
    { name: 'Chromium PDF Viewer' },
  ],
});
Object.defineProperty(navigator, 'languages', { get: () => ['az-AZ', 'az', 'en-US', 'en'] });
window.chrome = window.chrome || { runtime: {} };
const origQuery = window.navigator.permissions && window.navigator.permissions.query;
if (origQuery) {
  window.navigator.permissions.query = (parameters) =>
    parameters && parameters.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : origQuery(parameters);
}
"""


async def _solve_in_browser() -> ClearanceBundle:
    """Spawn Chromium, navigate to the cabinet, scrape cf_clearance.

    Imports playwright lazily so the rest of the app still boots in
    environments where Chromium isn't installed (e.g. unit tests on CI).
    """
    from playwright.async_api import async_playwright

    settings = get_settings()
    target_url = settings.unec_base_url.rstrip("/") + "/"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                # Reduces detection surface — these flags strip the
                # "automation banner" signals that headless Chrome leaks.
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        try:
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                locale="az-AZ",
                timezone_id="Asia/Baku",
            )
            # Inject stealth patches before any page script runs.
            await context.add_init_script(_STEALTH_SCRIPT)
            page = await context.new_page()

            await page.goto(target_url, wait_until="domcontentloaded", timeout=_SOLVE_TIMEOUT_SECONDS * 1000)

            # The challenge replaces the document once solved. Wait until
            # either cf_clearance shows up in cookies (canonical signal) or
            # the page title stops being "Just a moment..." (visual signal).
            await _wait_for_clearance(context, page)

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
            return ClearanceBundle(
                cookie=str(cf_value),
                user_agent=str(ua),
                fetched_at=time.time(),
            )
        finally:
            await browser.close()


async def _wait_for_clearance(context, page) -> None:
    """Poll cookies/title for ~45 s until the challenge resolves."""
    deadline = time.monotonic() + _SOLVE_TIMEOUT_SECONDS
    target = page.url
    while time.monotonic() < deadline:
        for c in await context.cookies(target):
            if c.get("name") == "cf_clearance" and c.get("value"):
                return
        title = await page.title()
        if title and "moment" not in title.lower():
            # Page swapped to real content but cookie hasn't appeared in our
            # snapshot yet — give it a beat then check cookies one more time.
            await asyncio.sleep(0.5)
            for c in await context.cookies(target):
                if c.get("name") == "cf_clearance" and c.get("value"):
                    return
        await asyncio.sleep(0.8)
    raise CloudflareError("Timed out waiting for Cloudflare challenge to resolve")
