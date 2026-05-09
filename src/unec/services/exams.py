from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Exam, ExamSyncState
from ..scraper.client import AuthError as UnecAuthError
from ..scraper.client import UnecClient
from ..scraper.parsers.exams import (
    ParsedExamQuestion,
    ParsedExamResult,
    ParsedQuestionDetail,
    parse_exam_questions,
    parse_exam_results,
    parse_question_detail,
    parse_upcoming_exams,
)
from .grades import _is_summer_semester  # reuse semester probing helper
from .unec_session import NoUnecCredentials, UnecSessionManager

logger = logging.getLogger(__name__)

# Throttle between paged GETs.
_PAGE_DELAY_S = 0.15
# Hard upper bound — the most pages we'll ever follow per (year, sem, examType).
_MAX_PAGES = 30


@dataclass(slots=True)
class ExamSyncResult:
    edu_year_id: int
    edu_semester_id: int
    exam_count: int
    last_synced_at: datetime


@dataclass(slots=True)
class ExamsView:
    edu_year_id: int | None
    edu_semester_id: int | None
    exams: list[Exam]
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None


# ---------------- Sync ----------------


async def _fetch_all_pages(
    client: UnecClient, *, year: int, semester: int
) -> list[ParsedExamResult]:
    """Walk pages of /az/eresults until we run out. Stops on empty page or
    once we have collected `total_count` rows (whichever comes first)."""
    rows: list[ParsedExamResult] = []
    seen_total: int | None = None

    for page in range(1, _MAX_PAGES + 1):
        path = "/az/eresults" if page == 1 else f"/az/eresults/page/{page}"
        html = await client.get(
            path, params={"eyear": year, "term": semester, "examType": ""}
        )
        parsed = parse_exam_results(html)
        if not parsed.rows:
            break
        rows.extend(parsed.rows)
        if seen_total is None and parsed.total_count is not None:
            seen_total = parsed.total_count
        if seen_total is not None and len(rows) >= seen_total:
            break
        await asyncio.sleep(_PAGE_DELAY_S)

    return rows


async def _resolve_year_and_semester_for_exams(
    *,
    client: UnecClient,
    edu_year_id: int | None,
    edu_semester_id: int | None,
) -> tuple[int, int]:
    """Mirror of the grades resolver but tuned for /az/eresults filters.

    Trusts the caller when both IDs are passed; otherwise picks the most-recent
    non-summer year+semester that returns any exam rows.
    """
    from ..scraper.parsers.exams import parse_exam_filters

    if edu_year_id is None or edu_semester_id is None:
        page = await client.get("/az/eresults")
        filters = parse_exam_filters(page)
        years = filters["edu_years"]
        if not years:
            raise RuntimeError("no eduYear options on /az/eresults")
        if edu_year_id is None:
            # Year IDs are listed newest-first. Pick the topmost.
            selected_year = next((o for o in years if o.selected), None)
            edu_year_id = selected_year.id if selected_year else years[0].id

    if edu_semester_id is None:
        # Probe semesters for this year — but only if we have to.
        from ..scraper.parsers.evaluation import parse_semester_options

        sem_html = await client.post(
            "/az/getEduSemester", data={"type": "eduYear", "id": str(edu_year_id)}
        )
        semesters = parse_semester_options(sem_html)
        if not semesters:
            raise RuntimeError(f"no semesters for eduYear={edu_year_id}")
        non_summer = [s for s in semesters if not _is_summer_semester(s)]
        edu_semester_id = max((non_summer or semesters), key=lambda s: s.id).id

    return edu_year_id, edu_semester_id


async def sync_exams(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    edu_year_id: int | None = None,
    edu_semester_id: int | None = None,
) -> ExamSyncResult:
    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient) -> tuple[int, int, list[ParsedExamResult]]:
        year, semester = await _resolve_year_and_semester_for_exams(
            client=client,
            edu_year_id=edu_year_id,
            edu_semester_id=edu_semester_id,
        )
        rows = await _fetch_all_pages(client, year=year, semester=semester)
        return year, semester, rows

    year, semester, parsed_rows = await manager.fetch(user_id, db_session, fetcher)

    # Safety: if we just got back a list of unec_exam_ids that already live
    # under a *different* (user, year), UNEC ignored the eduYear filter.
    fresh_unec_ids = [r.unec_exam_id for r in parsed_rows if r.unec_exam_id is not None]
    if fresh_unec_ids:
        clash = await db_session.execute(
            select(Exam.edu_year_id, Exam.unec_exam_id)
            .where(
                Exam.user_id == user_id,
                Exam.edu_year_id != year,
                Exam.unec_exam_id.in_(fresh_unec_ids),
            )
            .limit(1)
        )
        clashing = clash.first()
        if clashing is not None:
            raise RuntimeError(
                f"UNEC returned exams already known under year {clashing[0]} "
                f"— it likely ignored the eyear filter. "
                f"Historical years are not accessible through automated requests."
            )

    try:
        # Replace-all for (user, year, semester). Exam history is regenerated
        # from UNEC each sync — there's no per-row UI state to preserve.
        await db_session.execute(
            delete(Exam).where(
                Exam.user_id == user_id,
                Exam.edu_year_id == year,
                Exam.edu_semester_id == semester,
            )
        )
        for parsed in parsed_rows:
            db_session.add(
                Exam(
                    user_id=user_id,
                    edu_year_id=year,
                    edu_semester_id=semester,
                    exam_type_id=None,
                    exam_type_name=parsed.exam_type_name,
                    unec_exam_id=parsed.unec_exam_id,
                    main_type=parsed.main_type,
                    subject_code=parsed.subject_code,
                    subject_name=parsed.subject_name,
                    subject_full=parsed.subject_full,
                    form=parsed.form,
                    date=parsed.date,
                    start_time=parsed.start_time,
                    end_time=parsed.end_time,
                    entry_score=parsed.entry_score,
                    exam_score=parsed.exam_score,
                    final_score=parsed.final_score,
                    grade_letter=parsed.grade_letter,
                    grade_label=parsed.grade_label,
                )
            )

        now = datetime.now(UTC)
        state = await db_session.get(ExamSyncState, (user_id, year, semester))
        if state is None:
            state = ExamSyncState(
                user_id=user_id,
                edu_year_id=year,
                edu_semester_id=semester,
                last_synced_at=now,
                status="ok",
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

    return ExamSyncResult(
        edu_year_id=year,
        edu_semester_id=semester,
        exam_count=len(parsed_rows),
        last_synced_at=now,
    )


# ---------------- Read ----------------


async def get_user_exams(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    edu_year_id: int | None = None,
    edu_semester_id: int | None = None,
    exam_type_name: str | None = None,
) -> ExamsView:
    if edu_year_id is None or edu_semester_id is None:
        latest = await db_session.execute(
            select(ExamSyncState)
            .where(ExamSyncState.user_id == user_id)
            .order_by(ExamSyncState.last_synced_at.desc())
            .limit(1)
        )
        latest_state = latest.scalar_one_or_none()
        if latest_state is None:
            return ExamsView(
                edu_year_id=None,
                edu_semester_id=None,
                exams=[],
                last_synced_at=None,
                sync_status=None,
                sync_error=None,
            )
        edu_year_id = edu_year_id or latest_state.edu_year_id
        edu_semester_id = edu_semester_id or latest_state.edu_semester_id
        sync_state = latest_state
    else:
        sync_state = await db_session.get(
            ExamSyncState, (user_id, edu_year_id, edu_semester_id)
        )

    stmt = (
        select(Exam)
        .where(
            Exam.user_id == user_id,
            Exam.edu_year_id == edu_year_id,
            Exam.edu_semester_id == edu_semester_id,
        )
        .order_by(Exam.date.desc().nulls_last(), Exam.subject_name)
    )
    if exam_type_name:
        stmt = stmt.where(Exam.exam_type_name == exam_type_name)
    rows = await db_session.execute(stmt)
    exams = list(rows.scalars().all())

    return ExamsView(
        edu_year_id=edu_year_id,
        edu_semester_id=edu_semester_id,
        exams=exams,
        last_synced_at=sync_state.last_synced_at if sync_state else None,
        sync_status=sync_state.status if sync_state else None,
        sync_error=sync_state.error_message if sync_state else None,
    )


async def fetch_exam_questions(
    *,
    user_id: uuid.UUID,
    exam: Exam,
    db_session: AsyncSession,
    redis_client: redis.Redis,
) -> list[ParsedExamQuestion]:
    """Fetch the question list for an exam from POST /az/subject.

    Requires `exam.unec_exam_id` and `exam.main_type` — paper exams (with no
    UNEC id) and exams synced before the main_type migration return [].
    """
    if exam.unec_exam_id is None or exam.main_type is None:
        return []

    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient):
        html = await client.post(
            "/az/subject",
            data={"id": str(exam.unec_exam_id), "main": str(exam.main_type)},
        )
        return parse_exam_questions(html)

    return await manager.fetch(user_id, db_session, fetcher)


async def _fetch_question_score(
    client: UnecClient, *, exam_id_unec: int, question_id: int, main_type: int
) -> tuple[int | None, str | None]:
    html = await client.post(
        "/az/subject",
        data={
            "id": str(question_id),
            "eid": str(exam_id_unec),
            "open": "",
            "main": str(main_type),
        },
    )
    detail = parse_question_detail(html)
    return detail.score, detail.comment


async def fetch_exam_questions_enriched(
    *,
    user_id: uuid.UUID,
    exam: Exam,
    db_session: AsyncSession,
    redis_client: redis.Redis,
) -> list[ParsedExamQuestion]:
    """Like fetch_exam_questions, but for written exams (main=5) it also pulls
    each question's score in parallel — letting the UI show the per-question
    bal without an extra click."""
    if exam.unec_exam_id is None or exam.main_type is None:
        return []

    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient):
        html = await client.post(
            "/az/subject",
            data={"id": str(exam.unec_exam_id), "main": str(exam.main_type)},
        )
        questions = parse_exam_questions(html)
        if exam.main_type == 5 and questions:
            scores = await asyncio.gather(
                *[
                    _fetch_question_score(
                        client,
                        exam_id_unec=exam.unec_exam_id,  # type: ignore[arg-type]
                        question_id=q.question_id,
                        main_type=exam.main_type,  # type: ignore[arg-type]
                    )
                    for q in questions
                ],
                return_exceptions=True,
            )
            for q, result in zip(questions, scores):
                if isinstance(result, BaseException):
                    continue
                score, comment = result
                q.score = score
                q.comment = comment
        return questions

    return await manager.fetch(user_id, db_session, fetcher)


async def fetch_question_detail(
    *,
    user_id: uuid.UUID,
    exam: Exam,
    question_id: int,
    db_session: AsyncSession,
    redis_client: redis.Redis,
) -> ParsedQuestionDetail | None:
    """Fetch the per-question detail popup. Returns None if the exam can't be
    queried (paper exam / pre-migration row)."""
    if exam.unec_exam_id is None or exam.main_type is None:
        return None

    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient):
        html = await client.post(
            "/az/subject",
            data={
                "id": str(question_id),
                "eid": str(exam.unec_exam_id),
                "open": "",
                "main": str(exam.main_type),
            },
        )
        return parse_question_detail(html)

    return await manager.fetch(user_id, db_session, fetcher)


async def fetch_unec_image(
    *,
    user_id: uuid.UUID,
    ftp_path: str,
    db_session: AsyncSession,
    redis_client: redis.Redis,
) -> tuple[bytes, str]:
    """Proxy a UNEC image through the user's session.

    Two endpoint shapes:
      • /az/img/<id> and /az/img/answer/<id> — direct images (MCQ question /
        option assets). Fetched as-is.
      • /ASEU/STUDENT_ANSWERS/...           — written answer scans, served
        through /az/getImage?ftp_path=...
    """
    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient):
        if ftp_path.startswith("/az/"):
            return await client.get_bytes(ftp_path)
        return await client.get_bytes("/az/getImage", params={"ftp_path": ftp_path})

    return await manager.fetch(user_id, db_session, fetcher)


async def fetch_upcoming_exams(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    redis_client: redis.Redis,
) -> list:
    """Live fetch of /az/elist — schedule of upcoming exams during a session.

    Doesn't persist; just returns what UNEC says right now. The list is empty
    outside session windows.
    """
    manager = UnecSessionManager(redis_client)

    async def fetcher(client: UnecClient):
        html = await client.get("/az/elist")
        return parse_upcoming_exams(html)

    return await manager.fetch(user_id, db_session, fetcher)


async def record_sync_failure(
    *,
    user_id: uuid.UUID,
    edu_year_id: int,
    edu_semester_id: int,
    db_session: AsyncSession,
    error: str,
) -> None:
    state = await db_session.get(ExamSyncState, (user_id, edu_year_id, edu_semester_id))
    now = datetime.now(UTC)
    if state is None:
        state = ExamSyncState(
            user_id=user_id,
            edu_year_id=edu_year_id,
            edu_semester_id=edu_semester_id,
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
    "ExamSyncResult",
    "ExamsView",
    "NoUnecCredentials",
    "UnecAuthError",
    "fetch_upcoming_exams",
    "get_user_exams",
    "record_sync_failure",
    "sync_exams",
]
