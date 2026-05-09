"""End-to-end test for /v1/grades.

Skipped unless TEST_UNEC_USERNAME and TEST_UNEC_PASSWORD are set. Note: this
test makes 6 subjects × 5 lesson types = 30 popup requests against UNEC, with
a 150ms sleep between each, so it takes ~10s. Pytest timeout is generous.
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


async def test_grades_round_trip(client: httpx.AsyncClient, fresh_email: str):
    register = await client.post(
        "/v1/auth/register", json={"email": fresh_email, "password": PASSWORD}
    )
    assert register.status_code == 201

    login = await client.post(
        "/v1/auth/login", json={"email": fresh_email, "password": PASSWORD}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    no_creds = await client.get("/v1/grades", headers=headers)
    assert no_creds.status_code == 409

    set_creds = await client.put(
        "/v1/unec/credentials",
        headers=headers,
        json={"username": UNEC_USERNAME, "password": UNEC_PASSWORD},
    )
    assert set_creds.status_code == 200

    cold = await client.get("/v1/grades", headers=headers, timeout=120.0)
    assert cold.status_code == 200, cold.text
    body = cold.json()
    assert body["edu_year_id"] is not None
    assert body["edu_semester_id"] is not None
    assert body["sync_status"] == "ok"
    assert isinstance(body["subjects"], list)

    if body["subjects"]:
        first = body["subjects"][0]
        assert "name" in first
        assert "by_lesson_type" in first

    # Second call — DB hit, last_synced_at unchanged.
    second = await client.get("/v1/grades", headers=headers)
    assert second.status_code == 200
    assert second.json()["last_synced_at"] == body["last_synced_at"]
