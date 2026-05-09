from __future__ import annotations

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.rate_limit import limiter
from ...db.models import User
from ...scraper.client import AuthError as UnecAuthError
from ...services import schedule as schedule_service
from ...services.unec_session import NoUnecCredentials
from ..deps import get_current_user, get_db, get_redis
from ..schemas import LessonOut, ScheduleOut

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _to_response(view: schedule_service.ScheduleView) -> ScheduleOut:
    return ScheduleOut(
        edu_year_id=view.edu_year_id,
        last_synced_at=view.last_synced_at,
        sync_status=view.sync_status,
        sync_error=view.sync_error,
        lessons=[LessonOut.model_validate(lesson) for lesson in view.lessons],
    )


async def _sync_or_raise(
    *,
    user_id,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    edu_year_id: int | None,
) -> None:
    try:
        await schedule_service.sync_schedule(
            user_id=user_id,
            db_session=db_session,
            redis_client=redis_client,
            edu_year_id=edu_year_id,
        )
    except NoUnecCredentials as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="UNEC credentials are not configured for this user",
        ) from exc
    except UnecAuthError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"UNEC rejected the session: {exc}",
        ) from exc


@router.get("", response_model=ScheduleOut)
async def get_schedule(
    year_id: int | None = Query(default=None, description="eduYear ID; defaults to last synced or current"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ScheduleOut:
    """Return the cached schedule. Sync inline on first call (cold cache)."""
    view = await schedule_service.get_user_schedule(
        user_id=user.id, db_session=session, edu_year_id=year_id
    )
    if not view.lessons and view.last_synced_at is None:
        # Cold cache — sync inline so the user sees data on first call.
        await _sync_or_raise(
            user_id=user.id,
            db_session=session,
            redis_client=redis_client,
            edu_year_id=year_id,
        )
        view = await schedule_service.get_user_schedule(
            user_id=user.id, db_session=session, edu_year_id=year_id
        )
    return _to_response(view)


@router.post("/refresh", response_model=ScheduleOut)
@limiter.limit("10/minute")
async def refresh_schedule(
    request: Request,
    year_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ScheduleOut:
    """Force a sync against UNEC, then return the freshly stored data."""
    await _sync_or_raise(
        user_id=user.id,
        db_session=session,
        redis_client=redis_client,
        edu_year_id=year_id,
    )
    view = await schedule_service.get_user_schedule(
        user_id=user.id, db_session=session, edu_year_id=year_id
    )
    return _to_response(view)
