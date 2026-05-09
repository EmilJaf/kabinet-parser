from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy import select

from ...config import get_settings
from ...db.base import get_session_factory
from ...db.models import UnecCredentials
from ...services import schedule as schedule_service
from ...services.unec_session import NoUnecCredentials

logger = logging.getLogger(__name__)


async def sync_user_schedule(
    ctx: dict, user_id: str, edu_year_id: int | None = None
) -> dict:
    """ARQ job: sync one user's schedule for the given (or current) edu year."""
    user_uuid = uuid.UUID(user_id)
    factory = get_session_factory()
    redis_client: redis.Redis = ctx["redis_client"]

    async with factory() as db_session:
        try:
            result = await schedule_service.sync_schedule(
                user_id=user_uuid,
                db_session=db_session,
                redis_client=redis_client,
                edu_year_id=edu_year_id,
            )
        except NoUnecCredentials:
            logger.info("Skipping sync for user %s — no UNEC credentials", user_uuid)
            return {"status": "skipped", "reason": "no_credentials"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Schedule sync failed for user %s", user_uuid)
            year_for_error = edu_year_id or 0
            try:
                await schedule_service.record_sync_failure(
                    user_id=user_uuid,
                    edu_year_id=year_for_error,
                    db_session=db_session,
                    error=str(exc),
                )
            except Exception:
                logger.exception("Could not record sync failure for user %s", user_uuid)
            return {"status": "error", "error": str(exc)}

    return {
        "status": "ok",
        "edu_year_id": result.edu_year_id,
        "lesson_count": result.lesson_count,
    }


async def sync_all_active_users(ctx: dict) -> dict:
    """ARQ cron: enqueue per-user sync for everyone with UNEC creds.

    "Active" right now means "has UNEC credentials configured" — we'll narrow
    this to recent app activity once we track it.
    """
    factory = get_session_factory()
    enqueued = 0

    async with factory() as db_session:
        result = await db_session.execute(select(UnecCredentials.user_id))
        user_ids = [row[0] for row in result.all()]

    for user_id in user_ids:
        await ctx["enqueue_job"]("sync_user_schedule", str(user_id))
        enqueued += 1

    return {"enqueued": enqueued, "ts": datetime.now(UTC).isoformat()}
