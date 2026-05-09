from __future__ import annotations

import redis.asyncio as redis
from arq.connections import RedisSettings
from arq.cron import cron

from ..config import get_settings
from ..core.logging_config import setup_logging
from .jobs.exams import sync_user_exams
from .jobs.grades import sync_all_active_users_grades, sync_user_grades
from .jobs.reminders import (
    enqueue_morning_briefs,
    enqueue_today_reminders,
    send_lesson_reminder,
    send_morning_brief,
)
from .jobs.schedule import sync_all_active_users, sync_user_schedule


async def startup(ctx: dict) -> None:
    setup_logging("worker")
    settings = get_settings()
    ctx["redis_client"] = redis.from_url(settings.redis_url, decode_responses=True)
    # Provide a tiny enqueue helper so cron jobs can fan out via the same redis.
    arq_redis = ctx["redis"]

    async def _enqueue(name: str, *args, **kwargs):
        await arq_redis.enqueue_job(name, *args, **kwargs)

    ctx["enqueue_job"] = _enqueue


async def shutdown(ctx: dict) -> None:
    redis_client: redis.Redis | None = ctx.get("redis_client")
    if redis_client is not None:
        await redis_client.aclose()


async def ping(ctx: dict) -> str:
    """Health placeholder — kept so we can poke the worker from outside."""
    return "pong"


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


class WorkerSettings:
    functions = [
        ping,
        sync_user_schedule,
        sync_all_active_users,
        sync_user_grades,
        sync_all_active_users_grades,
        sync_user_exams,
        send_lesson_reminder,
        enqueue_today_reminders,
        send_morning_brief,
        enqueue_morning_briefs,
    ]
    cron_jobs = [
        # Schedule changes ~once a semester. Sync on the 1st of Jan/Apr/Jul/Oct
        # at 03:00 — quarterly cadence, well before students wake up.
        cron(
            sync_all_active_users,
            month={1, 4, 7, 10},
            day=1,
            hour=3,
            minute=0,
        ),
        # Grades / journal — daily at 13:00 and 19:00. Two snapshots per day
        # so a freshly-posted mark is visible within ~6 hours either way.
        cron(
            sync_all_active_users_grades,
            hour={13, 19},
            minute=0,
        ),
        # Lesson reminders — daily at 06:00 Baku, schedule deferred jobs for
        # each of today's lessons (start - 10 min). 06:00 is early enough that
        # even the user's first class is reachable from this scan.
        cron(
            enqueue_today_reminders,
            hour=6,
            minute=0,
        ),
        # Morning brief about the first lesson of the day — 07:30 Baku.
        # Catches "проспал" cases where the per-lesson reminder fires too
        # late for the user to react.
        cron(
            enqueue_morning_briefs,
            hour=7,
            minute=30,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = _redis_settings()
