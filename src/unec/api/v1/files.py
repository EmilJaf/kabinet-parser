from __future__ import annotations

import urllib.parse
from datetime import datetime

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.models import User
from ...scraper.client import AuthError as UnecAuthError
from ...services import files as files_service
from ...services.unec_session import NoUnecCredentials
from ..deps import get_current_user, get_db, get_redis

router = APIRouter(prefix="/files", tags=["files"])


# ─── Schemas ────────────────────────────────────────────────────────────────


class FilesOptionOut(BaseModel):
    value: str
    label: str
    selected: bool = False


class FilesSubjectOut(BaseModel):
    value: str
    subj_id: str
    label: str
    selected: bool = False


class FilesTeacherOut(BaseModel):
    value: str
    name: str
    sylabus_path: str | None = None
    selected: bool = False


class FilesThemeOut(BaseModel):
    theme_id: str
    subj_id: str
    topic: str
    has_lecture: bool
    has_presentation: bool
    has_test: bool
    has_seminar: bool
    has_other: bool


class FilesPageOut(BaseModel):
    years: list[FilesOptionOut]
    semesters: list[FilesOptionOut]
    subjects: list[FilesSubjectOut]
    teachers: list[FilesTeacherOut]
    themes: list[FilesThemeOut]
    # When the response came from cache, this is the moment we fetched it
    # from UNEC; null means the user is looking at a live response.
    last_synced_at: datetime | None = None


# ─── Endpoints ──────────────────────────────────────────────────────────────


@router.get("", response_model=FilesPageOut)
async def get_options(
    edu_year_id: str | None = Query(None),
    edu_semester_id: str | None = Query(None),
    subject: str | None = Query(None),
    subj_id: str | None = Query(None),
    teacher: str | None = Query(None),
    force: bool = Query(False, description="Skip the 1-hour Redis cache and re-fetch from UNEC"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> FilesPageOut:
    """Cascading filter state. Pass whatever the user has selected so far;
    each successive selection reveals the next dropdown's options."""
    try:
        page, last_synced_at = await files_service.list_options(
            session,
            redis_client,
            user_id=user.id,
            edu_year_id=edu_year_id,
            edu_semester_id=edu_semester_id,
            subject=subject,
            subj_id=subj_id,
            teacher=teacher,
            force=force,
        )
    except NoUnecCredentials as exc:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, "unec_creds_missing") from exc
    except UnecAuthError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"UNEC auth: {exc}") from exc
    out = FilesPageOut.model_validate(page, from_attributes=True)
    out.last_synced_at = last_synced_at
    return out


@router.get("/download/{theme_id}/{file_type}")
async def download_file(
    theme_id: str,
    file_type: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Response:
    """Stream the actual file, with Content-Disposition forcing a download."""
    try:
        file = await files_service.download_theme_file(
            session,
            redis_client,
            user_id=user.id,
            theme_id=theme_id,
            file_type=file_type,
        )
    except NoUnecCredentials as exc:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, "unec_creds_missing") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except UnecAuthError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"UNEC auth: {exc}") from exc

    return Response(
        content=file.body,
        media_type=file.content_type,
        headers={
            # Use RFC 5987 filename* to support non-ASCII names safely.
            "Content-Disposition": (
                f'attachment; filename="{file.filename}"; '
                f"filename*=UTF-8''{urllib.parse.quote(file.filename)}"
            )
        },
    )


@router.get("/download-path")
async def download_by_path(
    path: str = Query(..., description="UNEC absolute path, e.g. /ASEU/TEACHERFILE/...docx"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Response:
    """Download a UNEC file by absolute path — used for teacher syllabus links."""
    try:
        file = await files_service.download_arbitrary(
            session, redis_client, user_id=user.id, path=path
        )
    except NoUnecCredentials as exc:
        raise HTTPException(status.HTTP_412_PRECONDITION_FAILED, "unec_creds_missing") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except UnecAuthError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"UNEC auth: {exc}") from exc

    return Response(
        content=file.body,
        media_type=file.content_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{file.filename}"; '
                f"filename*=UTF-8''{urllib.parse.quote(file.filename)}"
            )
        },
    )
