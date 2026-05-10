"""Tiny helper to enqueue ARQ jobs from request lifecycles.

The web process doesn't run the worker, so it doesn't get the
`ctx['enqueue_job']` callback that lives inside the worker context.
Open a one-shot pool, enqueue, close. Pools are cheap enough.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from ..config import get_settings


@asynccontextmanager
async def arq_pool() -> AsyncIterator[ArqRedis]:
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        yield pool
    finally:
        await pool.close()


async def enqueue_initial_sync_for(user_id) -> None:
    """Kick off all three syncs for a user — used right after they add
    their UNEC credentials so the dashboard isn't empty when they open it."""
    async with arq_pool() as pool:
        for job_name in ("sync_user_schedule", "sync_user_grades", "sync_user_exams"):
            await pool.enqueue_job(job_name, str(user_id))
