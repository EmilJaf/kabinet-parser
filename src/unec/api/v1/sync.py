"""Per-user sync status — drives the 'loading your data' banner in the SPA."""
from __future__ import annotations

from datetime import datetime

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request
from fastapi import status as http_status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...core.rate_limit import limiter
from ...db.models import (
    ExamSyncState,
    GradesSyncState,
    ScheduleSyncState,
    User,
)
from ..deps import get_current_user, get_db

router = APIRouter(prefix="/sync", tags=["sync"])


class SyncSectionStatus(BaseModel):
    last_synced_at: datetime | None = None
    status: str | None = None  # 'ok' | 'error' | None (never synced)
    error: str | None = None


class SyncStatusOut(BaseModel):
    schedule: SyncSectionStatus
    grades: SyncSectionStatus
    exams: SyncSectionStatus
    all_synced: bool
    any_pending: bool


async def _latest_state(db_session, model, user_id) -> SyncSectionStatus:
    """Return the freshest row for the given sync_state model + user.

    Schedule keys on (user, year), grades on (user, year, semester), exams
    on (user, year, semester). For "did this user ever sync this section?"
    we want the most recent row regardless of year/semester.
    """
    row = (
        await db_session.execute(
            select(model)
            .where(model.user_id == user_id)
            .order_by(model.last_synced_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return SyncSectionStatus()
    return SyncSectionStatus(
        last_synced_at=row.last_synced_at,
        status=row.status,
        error=row.error_message,
    )


@router.get("/status", response_model=SyncStatusOut)
async def status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> SyncStatusOut:
    schedule = await _latest_state(session, ScheduleSyncState, user.id)
    grades = await _latest_state(session, GradesSyncState, user.id)
    exams = await _latest_state(session, ExamSyncState, user.id)

    sections = (schedule, grades, exams)
    all_synced = all(s.status == "ok" for s in sections)
    any_pending = any(s.status is None for s in sections)
    return SyncStatusOut(
        schedule=schedule,
        grades=grades,
        exams=exams,
        all_synced=all_synced,
        any_pending=any_pending,
    )


@router.post("/grades", status_code=http_status.HTTP_202_ACCEPTED)
@limiter.limit("4/minute")
async def trigger_grades_sync(
    request: Request,
    user: User = Depends(get_current_user),
) -> dict:
    """Kick a grades sync for the calling user.

    Called by the SPA when the dashboard mounts, so a user who just got a
    new mark sees it without waiting for the next 30-min cron tick. ARQ's
    job_id dedup means rapid re-mounts don't pile up jobs — if one is
    already queued under the same id, the new enqueue is a no-op.
    """
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await pool.enqueue_job(
            "sync_user_grades",
            str(user.id),
            _job_id=f"manual-grades:{user.id}",
        )
    finally:
        await pool.close()
    return {"enqueued": job is not None, "job_id": job.job_id if job else None}
