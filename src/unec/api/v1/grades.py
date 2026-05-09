from __future__ import annotations

import redis.asyncio as redis
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...core.rate_limit import limiter
from ...db.models import User
from ...scraper.client import AuthError as UnecAuthError
from ...scraper.client import UnecClient
from ...scraper.parsers.evaluation import (
    parse_filter_options,
    parse_semester_options,
)
from ...services import grades as grades_service
from ...services.unec_session import NoUnecCredentials, UnecSessionManager
from ..deps import get_current_user, get_db, get_redis
from ..schemas import (
    GradesOut,
    LessonTypeMarksOut,
    MarkOut,
    SubjectOut,
)

router = APIRouter(prefix="/grades", tags=["grades"])


def _to_response(view: grades_service.GradesView) -> GradesOut:
    # UNEC sometimes splits one logical course into multiple Subject rows —
    # e.g. Physics with a separate "Fizika_Lab 2" subject for the lab section.
    # Group by (name, edu_form_id) so the user sees one row with combined
    # lecture / lab / seminar tabs.
    grouped: dict[tuple[str, int | None], list[grades_service.SubjectView]] = {}
    order: list[tuple[str, int | None]] = []
    for sv in view.subjects:
        key = (sv.subject.name, sv.subject.edu_form_id)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(sv)

    subjects: list[SubjectOut] = []
    for key in order:
        members = grouped[key]
        primary = members[0].subject

        # Merge marks and details across all member rows. Lesson types should
        # not overlap in practice (UNEC assigns lab marks to the lab subject,
        # lecture marks to the main subject), but on the off chance they do,
        # concatenate marks and let "last wins" decide for details.
        merged_marks: dict[int, list] = {}
        merged_details: dict[int, object] = {}
        for sv in members:
            for lt_id, marks in sv.marks_by_lesson_type.items():
                merged_marks.setdefault(lt_id, []).extend(marks)
            for lt_id, details in sv.details_by_lesson_type.items():
                merged_details[lt_id] = details

        all_lesson_type_ids = sorted(
            set(merged_marks.keys()) | set(merged_details.keys())
        )

        per_lesson_type: list[LessonTypeMarksOut] = []
        for lt_id in all_lesson_type_ids:
            marks = merged_marks.get(lt_id, [])
            details = merged_details.get(lt_id)
            per_lesson_type.append(
                LessonTypeMarksOut(
                    lesson_type_id=lt_id,
                    lesson_type_name=marks[0].lesson_type_name if marks else None,
                    marks=[MarkOut.model_validate(m) for m in marks],
                    final_eval=getattr(details, "final_eval", None),
                    scheme=getattr(details, "scheme", None),
                    course_work=getattr(details, "course_work", None),
                    independent_work=getattr(details, "independent_work", None),
                    writing=getattr(details, "writing", None),
                )
            )

        subjects.append(
            SubjectOut(
                id=primary.id,
                unec_subject_id=primary.unec_subject_id,
                name=primary.name,
                group_name=primary.group_name,
                credits=primary.credits,
                edu_form_id=primary.edu_form_id,
                by_lesson_type=per_lesson_type,
            )
        )

    return GradesOut(
        edu_year_id=view.edu_year_id,
        edu_semester_id=view.edu_semester_id,
        last_synced_at=view.last_synced_at,
        sync_status=view.sync_status,
        sync_error=view.sync_error,
        subjects=subjects,
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
        await grades_service.sync_grades(
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
        # Most common cause: UNEC ignored the eduYear filter and returned the
        # current year again. Surface as a 422 with a clear message.
        message = str(exc)
        if "ignored the eduYear filter" in message or "Historical years" in message:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="historical_years_unavailable",
            ) from exc
        raise


@router.get("/options")
async def get_options(
    year_id: int | None = Query(default=None, description="eduYear ID; defaults to current"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> dict:
    """Return the list of semesters UNEC offers for the given (or current) year.

    Semester IDs vary per academic year — they are NOT universal — so the
    client needs to ask UNEC each time the year filter changes.
    """
    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient) -> dict:
        target_year = year_id
        if target_year is None:
            page = await client.get("/az/studentEvaluation")
            year_options = parse_filter_options(page)["edu_years"]
            if not year_options:
                raise RuntimeError("no eduYear options on /az/studentEvaluation")
            target_year = year_options[0].id

        sem_html = await client.post(
            "/az/getEduSemester",
            data={"type": "eduYear", "id": str(target_year)},
        )
        semesters = parse_semester_options(sem_html)
        return {
            "year_id": target_year,
            "semesters": [{"id": s.id, "label": s.label} for s in semesters],
        }

    try:
        return await manager.fetch(user.id, session, fetcher)
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


@router.get("", response_model=GradesOut)
async def get_grades(
    year_id: int | None = Query(default=None, description="eduYear ID; defaults to last synced or current"),
    semester_id: int | None = Query(default=None, description="eduSemester ID; defaults to latest"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> GradesOut:
    view = await grades_service.get_user_grades(
        user_id=user.id,
        db_session=session,
        edu_year_id=year_id,
        edu_semester_id=semester_id,
    )
    if not view.subjects and view.last_synced_at is None:
        await _sync_or_raise(
            user_id=user.id,
            db_session=session,
            redis_client=redis_client,
            edu_year_id=year_id,
            edu_semester_id=semester_id,
        )
        view = await grades_service.get_user_grades(
            user_id=user.id,
            db_session=session,
            edu_year_id=year_id,
            edu_semester_id=semester_id,
        )
    return _to_response(view)


@router.post("/refresh", response_model=GradesOut)
@limiter.limit("10/minute")
async def refresh_grades(
    request: Request,
    year_id: int | None = Query(default=None),
    semester_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> GradesOut:
    await _sync_or_raise(
        user_id=user.id,
        db_session=session,
        redis_client=redis_client,
        edu_year_id=year_id,
        edu_semester_id=semester_id,
    )
    view = await grades_service.get_user_grades(
        user_id=user.id,
        db_session=session,
        edu_year_id=year_id,
        edu_semester_id=semester_id,
    )
    return _to_response(view)
