from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Lesson, ScheduleSyncState
from ..scraper.client import AuthError as UnecAuthError
from ..scraper.client import UnecClient
from ..scraper.models import Lesson as ParsedLesson
from ..scraper.parsers.schedule import parse_education_year, parse_schedule
from .unec_session import NoUnecCredentials, UnecSessionManager


@dataclass(slots=True)
class ScheduleSyncResult:
    edu_year_id: int
    lesson_count: int
    last_synced_at: datetime


@dataclass(slots=True)
class ScheduleView:
    edu_year_id: int | None
    lessons: list[Lesson]
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None


def _to_orm(parsed: ParsedLesson, *, user_id: uuid.UUID, edu_year_id: int) -> Lesson:
    return Lesson(
        user_id=user_id,
        edu_year_id=edu_year_id,
        day=int(parsed.day),
        start=parsed.start,
        end=parsed.end,
        subject=parsed.subject,
        subject_code=parsed.subject_code,
        lesson_type=parsed.lesson_type,
        room=parsed.room,
        building=parsed.building,
        teacher=parsed.teacher,
        week_parity=parsed.week_parity.value,
        period_start=parsed.period_start,
        period_end=parsed.period_end,
    )


async def sync_schedule(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    edu_year_id: int | None = None,
) -> ScheduleSyncResult:
    """Pull the schedule HTML, parse it, and replace cached rows for (user, year)."""
    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient) -> str:
        params = {"eduYear": edu_year_id} if edu_year_id else None
        return await client.get("/az/schedule", params=params)

    html = await manager.fetch(user_id, db_session, fetcher)

    resolved_year = edu_year_id or parse_education_year(html)
    if resolved_year is None:
        raise RuntimeError("could not resolve eduYear from schedule HTML")

    parsed_lessons = parse_schedule(html)

    try:
        await db_session.execute(
            delete(Lesson).where(
                Lesson.user_id == user_id, Lesson.edu_year_id == resolved_year
            )
        )
        for parsed in parsed_lessons:
            db_session.add(_to_orm(parsed, user_id=user_id, edu_year_id=resolved_year))

        now = datetime.now(UTC)
        state = await db_session.get(ScheduleSyncState, (user_id, resolved_year))
        if state is None:
            state = ScheduleSyncState(
                user_id=user_id,
                edu_year_id=resolved_year,
                last_synced_at=now,
                status="ok",
                error_message=None,
            )
            db_session.add(state)
        else:
            state.last_synced_at = now
            state.status = "ok"
            state.error_message = None

        await db_session.commit()
    except Exception:
        await db_session.rollback()
        raise

    return ScheduleSyncResult(
        edu_year_id=resolved_year,
        lesson_count=len(parsed_lessons),
        last_synced_at=now,
    )


async def get_user_schedule(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    edu_year_id: int | None = None,
) -> ScheduleView:
    """Read cached schedule from DB. Does not trigger sync — caller decides."""
    if edu_year_id is None:
        # Pick the most recently synced year for this user.
        latest = await db_session.execute(
            select(ScheduleSyncState)
            .where(ScheduleSyncState.user_id == user_id)
            .order_by(ScheduleSyncState.last_synced_at.desc())
            .limit(1)
        )
        latest_state = latest.scalar_one_or_none()
        if latest_state is None:
            return ScheduleView(
                edu_year_id=None,
                lessons=[],
                last_synced_at=None,
                sync_status=None,
                sync_error=None,
            )
        edu_year_id = latest_state.edu_year_id
        sync_state = latest_state
    else:
        sync_state = await db_session.get(ScheduleSyncState, (user_id, edu_year_id))

    rows = await db_session.execute(
        select(Lesson)
        .where(Lesson.user_id == user_id, Lesson.edu_year_id == edu_year_id)
        .order_by(Lesson.day, Lesson.start)
    )
    lessons = list(rows.scalars().all())

    return ScheduleView(
        edu_year_id=edu_year_id,
        lessons=lessons,
        last_synced_at=sync_state.last_synced_at if sync_state else None,
        sync_status=sync_state.status if sync_state else None,
        sync_error=sync_state.error_message if sync_state else None,
    )


async def record_sync_failure(
    *,
    user_id: uuid.UUID,
    edu_year_id: int,
    db_session: AsyncSession,
    error: str,
) -> None:
    state = await db_session.get(ScheduleSyncState, (user_id, edu_year_id))
    now = datetime.now(UTC)
    if state is None:
        state = ScheduleSyncState(
            user_id=user_id,
            edu_year_id=edu_year_id,
            last_synced_at=now,
            status="error",
            error_message=error,
        )
        db_session.add(state)
    else:
        state.last_synced_at = now
        state.status = "error"
        state.error_message = error
    await db_session.commit()


__all__ = [
    "NoUnecCredentials",
    "ScheduleSyncResult",
    "ScheduleView",
    "UnecAuthError",
    "get_user_schedule",
    "record_sync_failure",
    "sync_schedule",
]
