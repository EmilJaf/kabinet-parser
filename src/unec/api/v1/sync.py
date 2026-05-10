"""Per-user sync status — drives the 'loading your data' banner in the SPA."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
