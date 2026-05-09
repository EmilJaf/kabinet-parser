from __future__ import annotations

import httpx

PASSWORD = "Test1234!"

ACCESS_COOKIE = "kabinet_access"
REFRESH_COOKIE = "kabinet_refresh"


async def _register(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> dict:
    resp = await client.post("/v1/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _login(client: httpx.AsyncClient, email: str, password: str = PASSWORD) -> dict:
    resp = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    assert ACCESS_COOKIE in resp.cookies
    assert REFRESH_COOKIE in resp.cookies
    return resp.json()


async def test_register_returns_user(client: httpx.AsyncClient, fresh_email: str):
    user = await _register(client, fresh_email)
    assert user["email"] == fresh_email
    assert "id" in user
    assert "created_at" in user


async def test_register_duplicate_email_returns_201(
    client: httpx.AsyncClient, fresh_email: str
):
    """Registering an existing email must look identical from the outside —
    no 409, no different latency — so an attacker can't enumerate accounts."""
    first = await _register(client, fresh_email)
    resp = await client.post(
        "/v1/auth/register",
        json={"email": fresh_email, "password": PASSWORD},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == fresh_email
    assert body["id"] == first["id"]


async def test_login_with_wrong_password_rejected(
    client: httpx.AsyncClient, fresh_email: str
):
    await _register(client, fresh_email)
    resp = await client.post(
        "/v1/auth/login", json={"email": fresh_email, "password": "wrong-pass"}
    )
    assert resp.status_code == 401
    assert ACCESS_COOKIE not in resp.cookies


async def test_login_unknown_user_rejected_same_shape(
    client: httpx.AsyncClient, fresh_email: str
):
    """Unknown emails return the same 401 shape as wrong-password — no
    timing or response distinction."""
    resp = await client.post(
        "/v1/auth/login",
        json={"email": fresh_email, "password": PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid credentials"}


async def test_full_auth_flow(client: httpx.AsyncClient, fresh_email: str):
    await _register(client, fresh_email)
    user = await _login(client, fresh_email)
    assert user["email"] == fresh_email

    # Cookies set on the AsyncClient automatically by httpx; subsequent
    # requests carry them.
    me = await client.get("/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == fresh_email

    original_access = client.cookies.get(ACCESS_COOKIE)
    original_refresh = client.cookies.get(REFRESH_COOKIE)

    refreshed = await client.post("/v1/auth/refresh")
    assert refreshed.status_code == 200
    # New cookie pair issued.
    assert client.cookies.get(ACCESS_COOKIE) != original_access
    assert client.cookies.get(REFRESH_COOKIE) != original_refresh

    # Old refresh is single-use — replay it via a separate client.
    async with httpx.AsyncClient(
        base_url=str(client.base_url),
        timeout=client.timeout,
        headers=client.headers,
    ) as replay:
        replay.cookies.set(REFRESH_COOKIE, original_refresh, path="/v1/auth")
        reuse = await replay.post("/v1/auth/refresh")
        assert reuse.status_code == 401

    # Logout revokes the current refresh token.
    logout = await client.post("/v1/auth/logout")
    assert logout.status_code == 204

    after_logout = await client.post("/v1/auth/refresh")
    assert after_logout.status_code == 401


async def test_me_requires_auth(client: httpx.AsyncClient):
    resp = await client.get("/v1/auth/me")
    assert resp.status_code == 401


async def test_credentials_endpoints_round_trip(
    client: httpx.AsyncClient, fresh_email: str
):
    await _register(client, fresh_email)
    await _login(client, fresh_email)

    initial = await client.get("/v1/unec/credentials")
    assert initial.status_code == 200
    assert initial.json() == {
        "configured": False,
        "username": None,
        "last_login_at": None,
        "updated_at": None,
    }

    upserted = await client.put(
        "/v1/unec/credentials",
        json={
            "username": "fake-test-user",
            "password": "fake-test-password",
            "skip_validation": True,
        },
    )
    assert upserted.status_code == 200, upserted.text
    body = upserted.json()
    assert body["configured"] is True
    assert body["username"] == "fake-test-user"

    deleted = await client.delete("/v1/unec/credentials")
    assert deleted.status_code == 204

    after_delete = await client.get("/v1/unec/credentials")
    assert after_delete.json()["configured"] is False
