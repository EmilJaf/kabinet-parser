from __future__ import annotations

import redis.asyncio as redis
from arq.connections import RedisSettings
from arq.cron import cron

from ..config import get_settings
from ..core.logging_config import setup_logging
from .jobs.cloudflare import refresh_cloudflare_clearance
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

    # Warm the Cloudflare clearance cache before any sync job runs. force=False
    # so a still-valid cookie inherited from a previous worker survives the
    # restart instead of being clobbered.
    await arq_redis.enqueue_job("refresh_cloudflare_clearance", force=False)


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
        refresh_cloudflare_clearance,
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
        # Cloudflare's cf_clearance cookie lives ~60 min. We refresh on a
        # cron that fires at :00 and :45 of every hour — so the longest gap
        # between two refreshes is 45 min, still comfortably inside the 60-min
        # cookie lifetime. All users share the same cookie (CF binds to
        # source IP + UA), so one job suffices for the whole server.
        cron(
            refresh_cloudflare_clearance,
            minute={0, 45},
        ),
        # Schedule changes ~once a semester. Sync on the 1st of Jan/Apr/Jul/Oct
        # at 03:00 — quarterly cadence, well before students wake up.
        cron(
            sync_all_active_users,
            month={1, 4, 7, 10},
            day=1,
            hour=3,
            minute=0,
        ),
        # Grades / journal — every 30 min during the AZ workday window
        # (Mon–Fri 08:00–20:30 Baku). Holidays are filtered inside the job.
        # Catches a freshly-posted mark within ~30 min and the per-user job
        # diffs and pushes web-push notifications for each new numeric mark.
        cron(
            sync_all_active_users_grades,
            weekday={0, 1, 2, 3, 4},
            hour={8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20},
            minute={0, 30},
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
