"""Lesson-reminder push notifications.

Daily cron at 06:00 Baku scans every active user's schedule and enqueues a
deferred `send_lesson_reminder` job for each of today's lessons, scheduled
to fire 10 minutes before the lesson starts.

`send_lesson_reminder` itself runs in the worker, builds the brief, and
delivers Web Push to all the user's subscribed devices.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.base import get_session_factory
from ...db.models import Lesson, PushSubscription
from ...services import push as push_service
from ...services.lesson_brief import build_lesson_brief

logger = logging.getLogger(__name__)

REMINDER_LEAD_MIN = 10


async def send_lesson_reminder(ctx: dict, user_id: str, lesson_id: str) -> dict:
    """Build the brief and push to all of this user's devices."""
    user_uuid = uuid.UUID(user_id)
    lesson_uuid = uuid.UUID(lesson_id)
    factory = get_session_factory()

    async with factory() as session:
        lesson = await session.get(Lesson, lesson_uuid)
        if lesson is None:
            return {"status": "skipped", "reason": "lesson_gone"}

        brief = await build_lesson_brief(session, user_id=user_uuid, lesson=lesson)
        title = f"Через {REMINDER_LEAD_MIN} минут: {brief.subject_name}"
        line2 = " · ".join(filter(None, [brief.room, brief.teacher]))
        line3_parts: list[str] = []
        if brief.mark_count:
            line3_parts.append(f"{brief.mark_count} оценок")
        if brief.absence_pct is not None:
            line3_parts.append(f"{brief.absence_pct:g}% пропусков")
        body = "\n".join(filter(None, [line2, " · ".join(line3_parts)]))

        try:
            sent = await push_service.send_push(
                session,
                user_id=user_uuid,
                payload=push_service.PushPayload(
                    title=title,
                    body=body or brief.subject_name,
                    url="/dashboard",
                    tag=f"lesson:{lesson_id}",
                ),
            )
        except push_service.VapidNotConfigured as exc:
            logger.warning("VAPID not configured, can't push: %s", exc)
            return {"status": "skipped", "reason": "no_vapid"}
        except Exception:  # noqa: BLE001
            logger.exception("push delivery failed for user %s", user_uuid)
            return {"status": "error"}

    return {"status": "ok", "delivered": sent}


async def send_morning_brief(ctx: dict, user_id: str) -> dict:
    """Push the user a heads-up about today's first lesson at ~07:30."""
    user_uuid = uuid.UUID(user_id)
    factory = get_session_factory()

    today_local = datetime.now().date()
    today_dow = today_local.isoweekday()

    async with factory() as session:
        first_lesson = (
            await session.execute(
                select(Lesson)
                .where(Lesson.user_id == user_uuid, Lesson.day == today_dow)
                .order_by(Lesson.start.asc())
            )
        ).scalars().first()

        if first_lesson is None or not _lesson_runs_today(first_lesson, today_local):
            return {"status": "skipped", "reason": "no_lessons_today"}

        title = f"Сегодня в {first_lesson.start.strftime('%H:%M')}: {first_lesson.subject}"
        body_parts: list[str] = []
        if first_lesson.room:
            body_parts.append(first_lesson.room)
        if first_lesson.teacher:
            body_parts.append(first_lesson.teacher)
        body = " · ".join(body_parts) or first_lesson.subject

        try:
            sent = await push_service.send_push(
                session,
                user_id=user_uuid,
                payload=push_service.PushPayload(
                    title=title,
                    body=body,
                    url="/dashboard",
                    tag=f"morning:{today_local.isoformat()}",
                ),
            )
        except push_service.VapidNotConfigured:
            return {"status": "skipped", "reason": "no_vapid"}
        except Exception:  # noqa: BLE001
            logger.exception("morning push failed for user %s", user_uuid)
            return {"status": "error"}

    return {"status": "ok", "delivered": sent, "lesson_start": str(first_lesson.start)}


async def enqueue_morning_briefs(ctx: dict) -> dict:
    """Cron at 07:30 Baku — fan out the morning brief to every push-enabled user."""
    factory = get_session_factory()
    enqueued = 0

    async with factory() as session:
        rows = (
            await session.execute(select(PushSubscription.user_id).distinct())
        ).all()
        for (user_id,) in rows:
            await ctx["enqueue_job"]("send_morning_brief", str(user_id))
            enqueued += 1

    return {"enqueued": enqueued, "ts": datetime.now(UTC).isoformat()}


async def enqueue_today_reminders(ctx: dict) -> dict:
    """Cron: schedule today's lesson reminders for everyone with push subs.

    Runs once a day. ARQ deferred jobs persist in Redis, so a worker restart
    after this fires won't lose the queue (jobs fire when their `_defer_until`
    arrives regardless of who's running).
    """
    factory = get_session_factory()
    enqueued = 0
    skipped_past = 0

    today_local = datetime.now().date()  # TZ=Asia/Baku in container env
    today_dow = today_local.isoweekday()  # 1=Mon..7=Sun, matches Lesson.day
    now_local = datetime.now()

    async with factory() as session:
        # Users with at least one push subscription — anyone else has nothing
        # to deliver to.
        sub_stmt = select(PushSubscription.user_id).distinct()
        user_ids = [r[0] for r in (await session.execute(sub_stmt)).all()]

        for user_id in user_ids:
            lessons = (
                await session.execute(
                    select(Lesson).where(
                        Lesson.user_id == user_id,
                        Lesson.day == today_dow,
                    )
                )
            ).scalars().all()

            for lesson in lessons:
                # Build the reminder fire time from today's date + lesson start.
                if not _lesson_runs_today(lesson, today_local):
                    continue
                fire_at = datetime.combine(today_local, lesson.start) - timedelta(
                    minutes=REMINDER_LEAD_MIN
                )
                if fire_at <= now_local:
                    skipped_past += 1
                    continue

                await ctx["enqueue_job"](
                    "send_lesson_reminder",
                    str(user_id),
                    str(lesson.id),
                    _defer_until=fire_at,
                    _job_id=f"reminder:{user_id}:{lesson.id}:{today_local.isoformat()}",
                )
                enqueued += 1

    return {
        "enqueued": enqueued,
        "skipped_past": skipped_past,
        "ts": datetime.now(UTC).isoformat(),
    }


def _lesson_runs_today(lesson: Lesson, today: date) -> bool:
    """Filter out lessons whose period_start/period_end excludes today."""
    if lesson.period_start and today < lesson.period_start:
        return False
    if lesson.period_end and today > lesson.period_end:
        return False
    # week_parity (upper/lower) is also a thing in UNEC schedules but we'd
    # need a reference week to compute parity reliably. v1 ignores it —
    # worst case the user gets one extra reminder for a lesson that didn't
    # actually run that week.
    return True
