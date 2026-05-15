from __future__ import annotations

import os
import uuid
from collections import deque
from datetime import datetime
from typing import Literal

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict

from ...core.rate_limit import limiter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.logging_config import LOG_DIR

from ...config import get_settings
from ...db.models import (
    ExamSyncState,
    GradesSyncState,
    PushSubscription,
    ScheduleSyncState,
    UnecCredentials,
    User,
)
from ...i18n import t
from ...services import cloudflare as cf_service
from ...services import push as push_service
from ..deps import get_db, require_admin

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ─── Schemas ────────────────────────────────────────────────────────────────


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool
    created_at: datetime
    unec_username: str | None
    unec_last_login_at: datetime | None
    schedule_last_synced_at: datetime | None
    grades_last_synced_at: datetime | None
    exams_last_synced_at: datetime | None
    push_subscription_count: int


class AdminStatsOut(BaseModel):
    user_count: int
    admin_count: int
    unec_linked_count: int
    push_enabled_count: int


class AdminLogsOut(BaseModel):
    service: str
    available: bool
    file_size_bytes: int
    lines: list[str]


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _arq_pool() -> ArqRedis:
    """Open a one-shot ARQ pool to enqueue from the request lifecycle."""
    return await create_pool(RedisSettings.from_dsn(get_settings().redis_url))


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(session: AsyncSession = Depends(get_db)) -> list[AdminUserOut]:
    """Single query that joins everything we want to show in the admin table."""
    # Per-user latest sync timestamps (max across years/semesters).
    sched_sub = (
        select(
            ScheduleSyncState.user_id,
            func.max(ScheduleSyncState.last_synced_at).label("last"),
        )
        .group_by(ScheduleSyncState.user_id)
        .subquery()
    )
    grades_sub = (
        select(
            GradesSyncState.user_id,
            func.max(GradesSyncState.last_synced_at).label("last"),
        )
        .group_by(GradesSyncState.user_id)
        .subquery()
    )
    exams_sub = (
        select(
            ExamSyncState.user_id,
            func.max(ExamSyncState.last_synced_at).label("last"),
        )
        .group_by(ExamSyncState.user_id)
        .subquery()
    )
    push_sub = (
        select(
            PushSubscription.user_id,
            func.count(PushSubscription.id).label("cnt"),
        )
        .group_by(PushSubscription.user_id)
        .subquery()
    )

    stmt = (
        select(
            User.id,
            User.email,
            User.is_admin,
            User.created_at,
            UnecCredentials.username.label("unec_username"),
            UnecCredentials.last_login_at.label("unec_last_login_at"),
            sched_sub.c.last.label("schedule_last_synced_at"),
            grades_sub.c.last.label("grades_last_synced_at"),
            exams_sub.c.last.label("exams_last_synced_at"),
            func.coalesce(push_sub.c.cnt, 0).label("push_subscription_count"),
        )
        .outerjoin(UnecCredentials, UnecCredentials.user_id == User.id)
        .outerjoin(sched_sub, sched_sub.c.user_id == User.id)
        .outerjoin(grades_sub, grades_sub.c.user_id == User.id)
        .outerjoin(exams_sub, exams_sub.c.user_id == User.id)
        .outerjoin(push_sub, push_sub.c.user_id == User.id)
        .order_by(User.created_at.desc())
    )
    rows = (await session.execute(stmt)).mappings().all()
    return [AdminUserOut(**dict(r)) for r in rows]


@router.get("/stats", response_model=AdminStatsOut)
async def stats(session: AsyncSession = Depends(get_db)) -> AdminStatsOut:
    user_count = (await session.execute(select(func.count(User.id)))).scalar_one()
    admin_count = (
        await session.execute(select(func.count(User.id)).where(User.is_admin))
    ).scalar_one()
    unec_linked = (
        await session.execute(select(func.count(UnecCredentials.user_id)))
    ).scalar_one()
    push_users = (
        await session.execute(
            select(func.count(func.distinct(PushSubscription.user_id)))
        )
    ).scalar_one()
    return AdminStatsOut(
        user_count=user_count,
        admin_count=admin_count,
        unec_linked_count=unec_linked,
        push_enabled_count=push_users,
    )


_SYNC_JOBS = {
    "schedule": "sync_user_schedule",
    "grades": "sync_user_grades",
    "exams": "sync_user_exams",
}


@router.post("/users/{user_id}/sync/{kind}", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("30/minute")
async def trigger_sync(
    request: Request,
    user_id: uuid.UUID,
    kind: str,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Enqueue a sync job for `user_id`. kind ∈ {schedule, grades, exams}."""
    if kind not in _SYNC_JOBS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"unknown kind: {kind}")
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")

    pool = await _arq_pool()
    try:
        job = await pool.enqueue_job(_SYNC_JOBS[kind], str(user_id))
    finally:
        await pool.close()
    return {"enqueued": True, "job_id": job.job_id if job else None, "kind": kind}


@router.post("/users/{user_id}/push/test", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def test_push(
    request: Request,
    user_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Send a test notification to every device the user has subscribed."""
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="user not found")
    try:
        delivered = await push_service.send_push(
            session,
            user_id=user_id,
            payload=push_service.PushPayload(
                title=t("push.admin_test_title", target.language),
                body=t("push.admin_test_body", target.language),
                url="/dashboard",
                tag="admin-test",
            ),
        )
    except push_service.VapidNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return {"delivered": delivered}


class CloudflareStatusOut(BaseModel):
    cached: bool
    age_seconds: int | None
    cookie_prefix: str | None
    user_agent: str | None


@router.get("/cloudflare", response_model=CloudflareStatusOut)
async def cloudflare_status(request: Request) -> CloudflareStatusOut:
    """Current state of the shared Cloudflare clearance cookie."""
    redis_client = request.app.state.redis
    bundle = await cf_service.load_cached(redis_client)
    if bundle is None:
        return CloudflareStatusOut(cached=False, age_seconds=None, cookie_prefix=None, user_agent=None)
    return CloudflareStatusOut(
        cached=True,
        age_seconds=bundle.age_seconds,
        cookie_prefix=bundle.cookie[:16],
        user_agent=bundle.user_agent,
    )


@router.post("/cloudflare/refresh", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("6/minute")
async def cloudflare_refresh(request: Request) -> dict:
    """Enqueue a Cloudflare clearance refresh in the worker."""
    pool = await _arq_pool()
    try:
        job = await pool.enqueue_job("refresh_cloudflare_clearance", force=True)
    finally:
        await pool.close()
    return {"enqueued": True, "job_id": job.job_id if job else None}


@router.get("/logs", response_model=AdminLogsOut)
async def get_logs(
    service: Literal["api", "worker"] = "api",
    lines: int = Query(500, ge=10, le=5000),
    q: str | None = Query(None, max_length=200),
) -> AdminLogsOut:
    """Tail of the rotating log file for `service`. Optional substring filter.

    Files live at /app/logs/<service>.log, mounted from ./logs/ on the host
    so they survive container recreation. We don't read the rotated
    .log.1 / .log.2 backups — recent activity only.
    """
    path = os.path.join(LOG_DIR, f"{service}.log")
    if not os.path.exists(path):
        return AdminLogsOut(service=service, available=False, file_size_bytes=0, lines=[])

    size = os.path.getsize(path)
    needle = q.lower() if q else None
    with open(path, encoding="utf-8", errors="replace") as f:
        if needle:
            tail = list(deque((ln for ln in f if needle in ln.lower()), maxlen=lines))
        else:
            tail = list(deque(f, maxlen=lines))

    return AdminLogsOut(
        service=service,
        available=True,
        file_size_bytes=size,
        lines=[ln.rstrip("\n") for ln in tail],
    )
