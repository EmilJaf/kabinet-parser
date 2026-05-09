from __future__ import annotations

import logging
import uuid

import redis.asyncio as redis
from sqlalchemy import select

from ...db.base import get_session_factory
from ...db.models import Exam
from ...services import exams as exams_service
from ...services import push as push_service
from ...services.unec_session import NoUnecCredentials

logger = logging.getLogger(__name__)

# Limit how many individual exam pushes we send per sync. If a backlog of
# results lands at once (e.g. first sync ever), one summary message instead.
_MAX_INDIVIDUAL_PUSHES = 5


async def sync_user_exams(
    ctx: dict,
    user_id: str,
    edu_year_id: int | None = None,
    edu_semester_id: int | None = None,
) -> dict:
    user_uuid = uuid.UUID(user_id)
    factory = get_session_factory()
    redis_client: redis.Redis = ctx["redis_client"]

    async with factory() as db_session:
        # Snapshot previous final_score per exam so we can diff after sync.
        prev_scores = await _exam_score_snapshot(db_session, user_id=user_uuid)

        try:
            result = await exams_service.sync_exams(
                user_id=user_uuid,
                db_session=db_session,
                redis_client=redis_client,
                edu_year_id=edu_year_id,
                edu_semester_id=edu_semester_id,
            )
        except NoUnecCredentials:
            return {"status": "skipped", "reason": "no_credentials"}
        except Exception as exc:  # noqa: BLE001
            logger.exception("Exam sync failed for user %s", user_uuid)
            if edu_year_id and edu_semester_id:
                try:
                    await exams_service.record_sync_failure(
                        user_id=user_uuid,
                        edu_year_id=edu_year_id,
                        edu_semester_id=edu_semester_id,
                        db_session=db_session,
                        error=str(exc),
                    )
                except Exception:
                    logger.exception("Could not record exam sync failure for %s", user_uuid)
            return {"status": "error", "error": str(exc)}

        # After commit: pick up exams whose final_score appeared during this
        # sync (was null/missing, now non-null), notify the user.
        pushed = await _push_new_results(db_session, user_id=user_uuid, prev_scores=prev_scores)

    return {
        "status": "ok",
        "edu_year_id": result.edu_year_id,
        "edu_semester_id": result.edu_semester_id,
        "exam_count": result.exam_count,
        "results_pushed": pushed,
    }


async def _exam_score_snapshot(
    db_session, *, user_id: uuid.UUID
) -> dict[uuid.UUID, int | None]:
    rows = (
        await db_session.execute(
            select(Exam.id, Exam.final_score).where(Exam.user_id == user_id)
        )
    ).all()
    return {row[0]: row[1] for row in rows}


async def _push_new_results(
    db_session,
    *,
    user_id: uuid.UUID,
    prev_scores: dict[uuid.UUID, int | None],
) -> int:
    """Push for every exam whose final_score went from null → set.

    Returns the number of push messages sent (0 if no new results, no
    subscriptions, or VAPID isn't configured).
    """
    rows = (
        await db_session.execute(
            select(Exam).where(Exam.user_id == user_id, Exam.final_score.is_not(None))
        )
    ).scalars().all()

    new_results = [
        e
        for e in rows
        if e.final_score is not None and prev_scores.get(e.id) is None
    ]
    if not new_results:
        return 0

    sent = 0
    try:
        if len(new_results) > _MAX_INDIVIDUAL_PUSHES:
            await push_service.send_push(
                db_session,
                user_id=user_id,
                payload=push_service.PushPayload(
                    title="Экзамены",
                    body=f"{len(new_results)} новых результатов",
                    url="/exams",
                    tag="exams-batch",
                ),
            )
            sent = 1
        else:
            for exam in new_results:
                grade_bits: list[str] = [str(exam.final_score)]
                if exam.grade_letter:
                    grade_bits.append(exam.grade_letter)
                if exam.grade_label:
                    grade_bits.append(exam.grade_label)
                await push_service.send_push(
                    db_session,
                    user_id=user_id,
                    payload=push_service.PushPayload(
                        title=f"Экзамен: {exam.subject_name}",
                        body=" · ".join(grade_bits),
                        url="/exams",
                        tag=f"exam:{exam.id}",
                    ),
                )
                sent += 1
    except push_service.VapidNotConfigured:
        logger.info("VAPID not configured — skipping exam-result pushes for %s", user_id)
        return 0
    except Exception:  # noqa: BLE001
        logger.exception("Sending exam-result push failed for user %s", user_id)
    return sent
