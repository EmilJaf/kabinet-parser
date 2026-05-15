from __future__ import annotations

import httpx
from selectolax.parser import HTMLParser

# Fallback UA used when no Cloudflare-derived UA has been injected yet
# (e.g. tests, first boot before the worker has run a clearance solve).
# In production every request rides with the UA captured from Playwright
# so it matches the (UA, IP) pair Cloudflare bound the cf_clearance to.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)


class AuthError(RuntimeError):
    pass


class CloudflareBlocked(RuntimeError):
    """Raised when Cloudflare interrupts a request with a managed challenge.

    Detection: HTTP 403 + `cf-mitigated: challenge` header. Caller is
    expected to refresh the shared `cf_clearance` cookie and retry.
    """


def _is_cloudflare_block(resp: httpx.Response) -> bool:
    if resp.status_code != 403:
        return False
    return resp.headers.get("cf-mitigated", "").lower() == "challenge"


class UnecClient:
    def __init__(
        self,
        base_url: str = "https://kabinet.unec.edu.az",
        timeout: float = 30.0,
        *,
        cf_cookie: str | None = None,
        user_agent: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        # Pin the User-Agent to whatever Playwright used when solving the
        # last Cloudflare challenge — cf_clearance is bound to (UA, IP), so
        # ANY change here invalidates the cookie and triggers a re-challenge.
        self._user_agent = user_agent or USER_AGENT
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": self._user_agent, "Accept-Language": "az,en;q=0.8,ru;q=0.6"},
        )
        if cf_cookie:
            self._client.cookies.set(
                "cf_clearance", cf_cookie, domain=httpx.URL(self.base_url).host
            )

    async def __aenter__(self) -> "UnecClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def login(self, username: str, password: str) -> None:
        # Step 1: GET / to get csrf_token + initial PHPSESSID cookie
        resp = await self._client.get("/")
        if _is_cloudflare_block(resp):
            raise CloudflareBlocked("Cloudflare challenge on /")
        resp.raise_for_status()
        csrf = _extract_csrf_token(resp.text)
        if not csrf:
            raise AuthError("CSRF token not found on login page")

        # Step 2: POST / with credentials. httpx will follow redirects to /az/index → dashboard.
        post = await self._client.post(
            "/",
            data={
                "csrf_token": csrf,
                "LoginForm[username]": username,
                "LoginForm[password]": password,
                "yt0": "Daxil ol",
            },
            headers={
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        if _is_cloudflare_block(post):
            raise CloudflareBlocked("Cloudflare challenge on login POST")
        post.raise_for_status()

        # If we ended up back on the login form, credentials are wrong.
        if 'id="login-form"' in post.text:
            raise AuthError("Login failed — server returned the login form again")

        if not self.is_authenticated_html(post.text):
            raise AuthError("Login appeared to succeed but no logout link in response")

    @staticmethod
    def is_authenticated_html(html: str) -> bool:
        return "/az/logout" in html

    def dump_cookies(self) -> dict[str, str]:
        """Snapshot the current cookie jar as a flat name→value dict.

        UNEC only relies on PHPSESSID + SERVERID + lang, all flat strings, so
        this lossy serialization is fine for caching across processes.
        """
        return {cookie.name: cookie.value for cookie in self._client.cookies.jar}

    def set_cookies(self, cookies: dict[str, str]) -> None:
        """Replace the cookie jar with the given mapping (used for cache restore)."""
        self._client.cookies.clear()
        for name, value in cookies.items():
            self._client.cookies.set(name, value, domain=httpx.URL(self.base_url).host)

    async def get(self, path: str, params: dict | None = None) -> str:
        resp = await self._client.get(path, params=params)
        if _is_cloudflare_block(resp):
            raise CloudflareBlocked(f"Cloudflare challenge on GET {path}")
        resp.raise_for_status()
        if not self.is_authenticated_html(resp.text):
            raise AuthError(f"Session expired or unauthenticated when fetching {path}")
        return resp.text

    async def get_bytes(
        self, path: str, params: dict | None = None
    ) -> tuple[bytes, str]:
        """Fetch a binary asset (e.g. /az/getImage) — returns (content, mime).

        Sends a Referer pointing at /az/eresults — UNEC silently returns an
        empty 200 for /az/img/<id> URLs without a same-origin referer.
        """
        headers = {"Referer": f"{self.base_url}/az/eresults"}
        resp = await self._client.get(path, params=params, headers=headers)
        if _is_cloudflare_block(resp):
            raise CloudflareBlocked(f"Cloudflare challenge on GET {path}")
        resp.raise_for_status()
        return resp.content, resp.headers.get("content-type", "application/octet-stream")

    async def post(self, path: str, data: dict, *, xhr: bool = True) -> str:
        headers = {"Referer": f"{self.base_url}/az/studentEvaluation"}
        if xhr:
            headers["X-Requested-With"] = "XMLHttpRequest"
        resp = await self._client.post(path, data=data, headers=headers)
        if _is_cloudflare_block(resp):
            raise CloudflareBlocked(f"Cloudflare challenge on POST {path}")
        resp.raise_for_status()
        return resp.text

    async def post_multipart(
        self, path: str, fields: dict, *, referer: str | None = None
    ) -> str:
        """POST as multipart/form-data; matches UNEC's downloadFileForTheme.

        UNEC distinguishes form-urlencoded vs multipart for some endpoints —
        downloadFileForTheme refuses urlencoded payloads.
        """
        files = {k: (None, v) for k, v in fields.items()}
        headers = {
            "Referer": referer or f"{self.base_url}/az/files",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = await self._client.post(path, files=files, headers=headers)
        if _is_cloudflare_block(resp):
            raise CloudflareBlocked(f"Cloudflare challenge on POST {path}")
        resp.raise_for_status()
        return resp.text

    async def download(
        self, path: str, *, referer: str | None = None
    ) -> tuple[bytes, str, str | None]:
        """Fetch a file. Returns (body, content_type, filename_from_disposition)."""
        headers = {"Referer": referer or f"{self.base_url}/az/files"}
        resp = await self._client.get(path, headers=headers)
        if _is_cloudflare_block(resp):
            raise CloudflareBlocked(f"Cloudflare challenge on GET {path}")
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "application/octet-stream")
        filename: str | None = None
        cd = resp.headers.get("content-disposition", "")
        if "filename=" in cd:
            # Crude but enough for UNEC's `attachment; filename="..."`.
            raw = cd.split("filename=", 1)[1].strip()
            if raw.startswith('"') and raw.endswith('"'):
                raw = raw[1:-1]
            filename = raw or None
        return resp.content, ctype, filename


def _extract_csrf_token(html: str) -> str | None:
    tree = HTMLParser(html)
    node = tree.css_first('input[name="csrf_token"]')
    if node is None:
        return None
    return node.attributes.get("value")
