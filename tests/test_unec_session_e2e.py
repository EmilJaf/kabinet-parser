"""End-to-end smoke test for the UNEC session manager.

Skipped unless TEST_UNEC_USERNAME and TEST_UNEC_PASSWORD are set in the
environment. When set, walks the full happy path:
  register app user → login → store UNEC creds → POST /v1/unec/session/test
"""
from __future__ import annotations

import os

import httpx
import pytest

UNEC_USERNAME = os.environ.get("TEST_UNEC_USERNAME")
UNEC_PASSWORD = os.environ.get("TEST_UNEC_PASSWORD")

pytestmark = pytest.mark.skipif(
    not (UNEC_USERNAME and UNEC_PASSWORD),
    reason="set TEST_UNEC_USERNAME and TEST_UNEC_PASSWORD to run live UNEC tests",
)


PASSWORD = "Test1234!"


async def test_session_test_endpoint_round_trip(
    client: httpx.AsyncClient, fresh_email: str
):
    register = await client.post(
        "/v1/auth/register", json={"email": fresh_email, "password": PASSWORD}
    )
    assert register.status_code == 201

    login = await client.post(
        "/v1/auth/login", json={"email": fresh_email, "password": PASSWORD}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # Without configured creds, /unec/session/test should 409.
    no_creds = await client.post("/v1/unec/session/test", headers=headers)
    assert no_creds.status_code == 409

    set_creds = await client.put(
        "/v1/unec/credentials",
        headers=headers,
        json={"username": UNEC_USERNAME, "password": UNEC_PASSWORD},
    )
    assert set_creds.status_code == 200, set_creds.text

    # First call — cold cache, should still succeed (login under the hood).
    first = await client.post("/v1/unec/session/test", headers=headers)
    assert first.status_code == 200, first.text
    assert first.json() == {"ok": True}

    # Second call — should reuse the cached session.
    second = await client.post("/v1/unec/session/test", headers=headers)
    assert second.status_code == 200
