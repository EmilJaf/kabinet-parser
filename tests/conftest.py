"""Shared fixtures.

Integration tests against the API talk to the live `docker compose` stack on
localhost:8000 so they exercise real Postgres + Redis + JWT/Argon2/Fernet.
Each test uses a unique email so the dev database can stay populated.
"""
from __future__ import annotations

import os
import uuid

import httpx
import pytest

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def _api_reachable() -> bool:
    try:
        resp = httpx.get(f"{API_BASE_URL}/health", timeout=2.0)
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="session")
def api_base_url() -> str:
    if not _api_reachable():
        pytest.skip("API not reachable on " + API_BASE_URL + " (run `docker compose up`)")
    return API_BASE_URL


@pytest.fixture
async def client(api_base_url: str):
    # Rate limiting is keyed off X-Forwarded-For (see core/rate_limit.py).
    # Each test gets its own synthetic IP so tests don't share buckets and
    # don't collide with the developer's own dev session.
    fake_ip = ".".join(str(b) for b in uuid.uuid4().bytes[:4])
    headers = {"X-Forwarded-For": fake_ip}
    async with httpx.AsyncClient(base_url=api_base_url, timeout=10.0, headers=headers) as c:
        yield c


@pytest.fixture
def fresh_email() -> str:
    return f"test-{uuid.uuid4().hex[:12]}@example.com"
