from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis
from sqlalchemy import select

from ...db.base import get_session_factory
from ...db.models import Mark, Subject, UnecCredentials
from ...services import grades as grades_service
from ...services import push as push_service
from ...services.unec_session import NoUnecCredentials

logger = logging.getLogger(__name__)

# Cap how many "new mark" notifications a single sync emits to avoid
# spamming a user the very first time we run (when literally everything
# is "new"). Beyond this, send a single summary push.
_MAX_INDIVIDUAL_PUSHES = 5
_NUMERIC_MARK = re.compile(r"^\d+([.,]\d+)?$")


async def sync_user_grades(
    ctx: dict,
    user_id: str,
    edu_year_id: int | None = None,
    edu_semester_id: int | None = None,
) -> dict:
    user_uuid = uuid.UUID(user_id)
    factory = get_session_factory()
    redis_client: redis.Redis = ctx["redis_client"]

    # Snapshot the cutoff a few seconds back to absorb clock drift between
    # API container, worker, and Postgres — anything inserted at or after
    # this is considered "new" relative to the start of this sync.
    threshold = datetime.now(UTC) - timedelta(seconds=5)

    async with factory() as db_session:
        try:
            result = await grades_service.sync_grades(
                user_id=user_uuid,
                db_session=db_session,
                redis_client=redis_client,
                edu_year_id=edu_year_id,
                edu_semester_id=edu_semester_id,
            )
        except NoUnecCredentials:
            logger.info("Skipping grades sync for user %s — no UNEC credentials", user_uuid)
            return {"status": "skipped", "reason": "no_credentials"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Grades sync failed for user %s", user_uuid)
            if edu_year_id and edu_semester_id:
                try:
                    await grades_service.record_sync_failure(
                        user_id=user_uuid,
                        edu_year_id=edu_year_id,
                        edu_semester_id=edu_semester_id,
                        db_session=db_session,
                        error=str(exc),
                    )
                except Exception:
                    logger.exception(
                        "Could not record grades sync failure for user %s", user_uuid
                    )
            return {"status": "error", "error": str(exc)}

        # After the sync committed: find marks inserted during this run
        # and notify the user. Joins to Subject for the human name; only
        # numeric mark codes count (attendance flags like 'i', 'q' aren't
        # graded scores).
        new_marks_pushes = await _push_new_marks(
            db_session, user_id=user_uuid, threshold=threshold
        )

    return {
        "status": "ok",
        "edu_year_id": result.edu_year_id,
        "edu_semester_id": result.edu_semester_id,
        "subject_count": result.subject_count,
        "mark_count": result.mark_count,
        "new_marks_pushed": new_marks_pushes,
    }


async def _push_new_marks(
    db_session, *, user_id: uuid.UUID, threshold: datetime
) -> int:
    """Send a push for every numeric mark inserted at/after `threshold`.

    Returns how many push messages were attempted (0 if user has no
    subscriptions, no new marks, or VAPID isn't configured).
    """
    stmt = (
        select(Mark, Subject)
        .join(Subject, Mark.subject_id == Subject.id)
        .where(Subject.user_id == user_id, Mark.created_at >= threshold)
        .order_by(Mark.date.desc(), Mark.created_at.desc())
    )
    rows = (await db_session.execute(stmt)).all()
    new_numeric = [
        (mark, subject)
        for mark, subject in rows
        if mark.mark_code and _NUMERIC_MARK.match(mark.mark_code.strip())
    ]
    if not new_numeric:
        return 0

    sent_count = 0
    try:
        if len(new_numeric) > _MAX_INDIVIDUAL_PUSHES:
            await push_service.send_push(
                db_session,
                user_id=user_id,
                payload=push_service.PushPayload(
                    title="Журнал",
                    body=f"{len(new_numeric)} новых оценок",
                    url="/grades",
                    tag="grades-batch",
                ),
            )
            sent_count = 1
        else:
            for mark, subject in new_numeric:
                topic = (mark.topic or "").strip()
                body = mark.mark_code or "—"
                if topic:
                    body = f"{body} · {topic[:60]}"
                await push_service.send_push(
                    db_session,
                    user_id=user_id,
                    payload=push_service.PushPayload(
                        title=f"Журнал: {subject.name}",
                        body=body,
                        url="/grades",
                        tag=f"mark:{mark.id}",
                    ),
                )
                sent_count += 1
    except push_service.VapidNotConfigured:
        logger.info("VAPID not configured — skipping new-mark pushes for %s", user_id)
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("Sending new-mark push failed for user %s", user_id)
    return sent_count


async def sync_all_active_users_grades(ctx: dict) -> dict:
    """ARQ cron: enqueue per-user grades sync for everyone with UNEC creds.

    Mirrors sync_all_active_users for schedule. The per-user job picks the
    current edu year/semester from UNEC when arguments are omitted.
    """
    factory = get_session_factory()
    enqueued = 0

    async with factory() as db_session:
        result = await db_session.execute(select(UnecCredentials.user_id))
        user_ids = [row[0] for row in result.all()]

    for user_id in user_ids:
        await ctx["enqueue_job"]("sync_user_grades", str(user_id))
        enqueued += 1

    return {"enqueued": enqueued, "ts": datetime.now(UTC).isoformat()}
