"""End-to-end test for /v1/schedule.

Skipped unless TEST_UNEC_USERNAME and TEST_UNEC_PASSWORD are set. Walks the
full multi-user happy path: register app user → store UNEC creds →
GET /schedule (cold cache, syncs inline) → POST /schedule/refresh.
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


async def test_schedule_round_trip(client: httpx.AsyncClient, fresh_email: str):
    register = await client.post(
        "/v1/auth/register", json={"email": fresh_email, "password": PASSWORD}
    )
    assert register.status_code == 201

    login = await client.post(
        "/v1/auth/login", json={"email": fresh_email, "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    # No creds yet → 409.
    cold = await client.get("/v1/schedule", headers=headers)
    assert cold.status_code == 409

    set_creds = await client.put(
        "/v1/unec/credentials",
        headers=headers,
        json={"username": UNEC_USERNAME, "password": UNEC_PASSWORD},
    )
    assert set_creds.status_code == 200

    # First call — cold cache, syncs inline, returns lessons.
    first = await client.get("/v1/schedule", headers=headers, timeout=30.0)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["edu_year_id"] is not None
    assert body["last_synced_at"] is not None
    assert body["sync_status"] == "ok"
    assert isinstance(body["lessons"], list)
    cold_count = len(body["lessons"])
    cold_synced = body["last_synced_at"]

    # Second call — should read from DB (last_synced_at unchanged).
    second = await client.get("/v1/schedule", headers=headers)
    assert second.status_code == 200
    assert second.json()["last_synced_at"] == cold_synced

    # Force refresh — last_synced_at advances.
    forced = await client.post("/v1/schedule/refresh", headers=headers, timeout=30.0)
    assert forced.status_code == 200, forced.text
    assert forced.json()["last_synced_at"] != cold_synced
    assert len(forced.json()["lessons"]) == cold_count
