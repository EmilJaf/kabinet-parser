from __future__ import annotations

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

import uuid as _uuid

from fastapi import Response

from ...core.rate_limit import limiter
from ...db.models import Exam, User
from ...scraper.client import AuthError as UnecAuthError
from ...services import exams as exams_service
from ...services.unec_session import NoUnecCredentials
from ..deps import get_current_user, get_db, get_redis
from ..schemas import (
    ExamAnswerOptionOut,
    ExamOut,
    ExamQuestionDetailOut,
    ExamQuestionOut,
    ExamQuestionsOut,
    ExamsOut,
    UpcomingExamOut,
)

router = APIRouter(prefix="/exams", tags=["exams"])


def _to_response(view: exams_service.ExamsView) -> ExamsOut:
    return ExamsOut(
        edu_year_id=view.edu_year_id,
        edu_semester_id=view.edu_semester_id,
        last_synced_at=view.last_synced_at,
        sync_status=view.sync_status,
        sync_error=view.sync_error,
        exams=[ExamOut.model_validate(e) for e in view.exams],
    )


async def _sync_or_raise(
    *,
    user_id,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    edu_year_id: int | None,
    edu_semester_id: int | None,
) -> None:
    try:
        await exams_service.sync_exams(
            user_id=user_id,
            db_session=db_session,
            redis_client=redis_client,
            edu_year_id=edu_year_id,
            edu_semester_id=edu_semester_id,
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
    except RuntimeError as exc:
        message = str(exc)
        if "ignored the eyear filter" in message or "Historical years" in message:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="historical_years_unavailable",
            ) from exc
        raise


@router.get("", response_model=ExamsOut)
async def get_exams(
    year_id: int | None = Query(default=None),
    semester_id: int | None = Query(default=None),
    exam_type: str | None = Query(default=None, description="exam type label, e.g. 'Yekun imtahan'"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ExamsOut:
    view = await exams_service.get_user_exams(
        user_id=user.id,
        db_session=session,
        edu_year_id=year_id,
        edu_semester_id=semester_id,
        exam_type_name=exam_type,
    )
    if not view.exams and view.last_synced_at is None:
        await _sync_or_raise(
            user_id=user.id,
            db_session=session,
            redis_client=redis_client,
            edu_year_id=year_id,
            edu_semester_id=semester_id,
        )
        view = await exams_service.get_user_exams(
            user_id=user.id,
            db_session=session,
            edu_year_id=year_id,
            edu_semester_id=semester_id,
            exam_type_name=exam_type,
        )
    return _to_response(view)


@router.post("/refresh", response_model=ExamsOut)
@limiter.limit("10/minute")
async def refresh_exams(
    request: Request,
    year_id: int | None = Query(default=None),
    semester_id: int | None = Query(default=None),
    exam_type: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ExamsOut:
    await _sync_or_raise(
        user_id=user.id,
        db_session=session,
        redis_client=redis_client,
        edu_year_id=year_id,
        edu_semester_id=semester_id,
    )
    view = await exams_service.get_user_exams(
        user_id=user.id,
        db_session=session,
        edu_year_id=year_id,
        edu_semester_id=semester_id,
        exam_type_name=exam_type,
    )
    return _to_response(view)


@router.get("/{exam_id}/questions", response_model=ExamQuestionsOut)
async def exam_questions(
    exam_id: _uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ExamQuestionsOut:
    exam = await session.get(Exam, exam_id)
    if exam is None or exam.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="exam not found")

    if exam.unec_exam_id is None or exam.main_type is None:
        return ExamQuestionsOut(
            exam_id=exam.id,
            available=False,
            correct_count=0,
            wrong_count=0,
            unknown_count=0,
            questions=[],
        )

    try:
        parsed = await exams_service.fetch_exam_questions_enriched(
            user_id=user.id,
            exam=exam,
            db_session=session,
            redis_client=redis_client,
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

    correct = sum(1 for q in parsed if q.status == "correct")
    wrong = sum(1 for q in parsed if q.status == "wrong")
    unknown = sum(1 for q in parsed if q.status == "unknown")

    return ExamQuestionsOut(
        exam_id=exam.id,
        available=True,
        correct_count=correct,
        wrong_count=wrong,
        unknown_count=unknown,
        questions=[
            ExamQuestionOut(
                index=q.index,
                question_id=q.question_id,
                text=q.text,
                status=q.status,
                score=q.score,
                comment=q.comment,
            )
            for q in parsed
        ],
    )


@router.get("/{exam_id}/questions/{question_id}", response_model=ExamQuestionDetailOut)
async def question_detail(
    exam_id: _uuid.UUID,
    question_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ExamQuestionDetailOut:
    exam = await session.get(Exam, exam_id)
    if exam is None or exam.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="exam not found")

    try:
        parsed = await exams_service.fetch_question_detail(
            user_id=user.id,
            exam=exam,
            question_id=question_id,
            db_session=session,
            redis_client=redis_client,
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

    if parsed is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            detail="question detail not available for this exam",
        )

    return ExamQuestionDetailOut(
        kind=parsed.kind,
        question_text=parsed.question_text,
        question_image_path=parsed.question_image_path,
        options=[
            ExamAnswerOptionOut(
                text=o.text,
                image_path=o.image_path,
                is_correct=o.is_correct,
                is_user_choice=o.is_user_choice,
            )
            for o in parsed.options
        ],
        difficulty=parsed.difficulty,
        score=parsed.score,
        comment=parsed.comment,
        answer_images=parsed.answer_images,
    )


@router.get("/answer-image")
async def answer_image(
    ftp_path: str = Query(..., description="UNEC ftp_path of the image"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> Response:
    """Proxy UNEC's /az/getImage through our user-scoped session.

    UNEC's auth scope means each user can only ever read their own answer
    images, so passing arbitrary ftp_paths can't escalate to other students'
    data — we still validate that the path looks like an answer asset.
    """
    if not ftp_path.startswith("/ASEU/") and not ftp_path.startswith("/az/img/"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid ftp_path")
    if ".." in ftp_path:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="invalid ftp_path")

    try:
        content, content_type = await exams_service.fetch_unec_image(
            user_id=user.id,
            ftp_path=ftp_path,
            db_session=session,
            redis_client=redis_client,
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

    # UNEC returns 200 + empty body for image URLs that don't actually exist
    # (typical for /az/img/<id> placeholders attached to text-only questions).
    # Treat those as 404 so the client can hide the slot rather than render a
    # broken image.
    if not content or not content_type.startswith("image/"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="image not available")

    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/upcoming", response_model=list[UpcomingExamOut])
async def upcoming_exams(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> list[UpcomingExamOut]:
    """Live UNEC pull of /az/elist. Empty outside session periods."""
    try:
        rows = await exams_service.fetch_upcoming_exams(
            user_id=user.id,
            db_session=session,
            redis_client=redis_client,
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

    return [
        UpcomingExamOut(
            group_name=row.group_name,
            date=row.date,
            start_time=row.start_time,
            end_time=row.end_time,
            entry_score=row.entry_score,
            username=row.username,
            password=row.password,
            exam_type_name=row.exam_type_name,
            status=row.status,
            blocked=row.blocked,
        )
        for row in rows
    ]
