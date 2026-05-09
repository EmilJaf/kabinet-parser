from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import redis.asyncio as redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import (
    GradesSyncState,
    Mark,
    Subject,
    SubjectGradingDetails,
)
from ..scraper.client import AuthError as UnecAuthError
from ..scraper.client import UnecClient
from ..scraper.parsers.evaluation import (
    ParsedGradesPopup,
    ParsedOption,
    ParsedSubject,
    parse_filter_options,
    parse_grades_popup,
    parse_selected_filters,
    parse_semester_options,
    parse_subject_list,
)
from .unec_session import NoUnecCredentials, UnecSessionManager

logger = logging.getLogger(__name__)

# Throttle between popup requests so we don't hammer UNEC.
_POPUP_DELAY_S = 0.15


@dataclass(slots=True)
class GradesSyncResult:
    edu_year_id: int
    edu_semester_id: int
    subject_count: int
    mark_count: int
    last_synced_at: datetime


@dataclass(slots=True)
class SubjectView:
    subject: Subject
    marks_by_lesson_type: dict[int, list[Mark]]
    details_by_lesson_type: dict[int, SubjectGradingDetails]


@dataclass(slots=True)
class GradesView:
    edu_year_id: int | None
    edu_semester_id: int | None
    subjects: list[SubjectView]
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None


# ---------------- Sync ----------------


async def _lesson_types_for(
    client: UnecClient, *, year: int, semester: int
) -> list[ParsedOption]:
    """Hit the e-journal page with year+semester and return its lessonType options."""
    full = await client.get(
        "/az/studentEvaluation",
        params={"eduYear": year, "eduSemester": semester, "lessonType": ""},
    )
    return parse_filter_options(full)["lesson_types"]


def _is_summer_semester(opt: ParsedOption) -> bool:
    label = opt.label.lower()
    # UNEC's summer semester is labelled "Yay semestri" (az) or contains "yay".
    return "yay" in label


async def _resolve_year_and_semester(
    *,
    client: UnecClient,
    edu_year_id: int | None,
    edu_semester_id: int | None,
) -> tuple[int, int, list[ParsedOption]]:
    """Return (year_id, semester_id, lesson_type_options), filling defaults from UNEC."""
    if edu_year_id is None:
        page = await client.get("/az/studentEvaluation")
        selected = parse_selected_filters(page)
        edu_year_id = selected["edu_year_id"]
        if edu_year_id is None:
            # On a fresh visit the dropdown has no pre-selected year — UNEC
            # waits for the user to click. Fall back to the first option, which
            # is listed newest-first.
            year_options: list[ParsedOption] = parse_filter_options(page)["edu_years"]
            if not year_options:
                raise RuntimeError("no eduYear options on /az/studentEvaluation")
            edu_year_id = year_options[0].id

    if edu_semester_id is not None:
        # Caller picked a specific semester — trust them.
        lesson_type_options = await _lesson_types_for(
            client, year=edu_year_id, semester=edu_semester_id
        )
        return edu_year_id, edu_semester_id, lesson_type_options

    # No semester specified — probe all semesters and pick one the user is
    # actually enrolled in (= the one whose lessonType dropdown is non-empty).
    sem_html = await client.post(
        "/az/getEduSemester", data={"type": "eduYear", "id": str(edu_year_id)}
    )
    semesters = parse_semester_options(sem_html)
    if not semesters:
        raise RuntimeError(f"no semesters returned for eduYear={edu_year_id}")

    candidates: list[tuple[ParsedOption, list[ParsedOption]]] = []
    for sem in semesters:
        opts = await _lesson_types_for(client, year=edu_year_id, semester=sem.id)
        if opts:
            candidates.append((sem, opts))

    if not candidates:
        raise RuntimeError(
            f"no semester for eduYear={edu_year_id} has any enrollment data"
        )

    # Prefer regular semesters over the summer one; among regulars, pick the
    # most recent (highest id, since UNEC IDs are monotonically allocated).
    non_summer = [c for c in candidates if not _is_summer_semester(c[0])]
    chosen_sem, chosen_opts = max(
        non_summer or candidates, key=lambda c: c[0].id
    )
    return edu_year_id, chosen_sem.id, chosen_opts


async def _fetch_subject_list_for_lesson_type(
    client: UnecClient, *, year: int, semester: int, lesson_type_id: int
) -> list[ParsedSubject]:
    """Per-lesson-type subject list — UNEC only populates the table when filtered."""
    html = await client.get(
        "/az/studentEvaluation",
        params={"eduYear": year, "eduSemester": semester, "lessonType": lesson_type_id},
    )
    return parse_subject_list(html)


async def _fetch_popup(
    client: UnecClient,
    *,
    unec_subject_id: int,
    lesson_type_id: int,
    edu_form_id: int | None,
) -> ParsedGradesPopup:
    html = await client.post(
        "/az/studentEvaluationPopup",
        data={
            "id": str(unec_subject_id),
            "lessonType": str(lesson_type_id),
            "edu_form_id": str(edu_form_id or 0),
        },
    )
    return parse_grades_popup(html)


async def _upsert_subject(
    db_session: AsyncSession,
    *,
    user_id: uuid.UUID,
    edu_year_id: int,
    edu_semester_id: int,
    parsed: ParsedSubject,
) -> Subject:
    stmt = select(Subject).where(
        Subject.user_id == user_id,
        Subject.edu_year_id == edu_year_id,
        Subject.edu_semester_id == edu_semester_id,
        Subject.unec_subject_id == parsed.unec_subject_id,
    )
    existing = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        subject = Subject(
            user_id=user_id,
            edu_year_id=edu_year_id,
            edu_semester_id=edu_semester_id,
            unec_subject_id=parsed.unec_subject_id,
            edu_form_id=parsed.edu_form_id,
            name=parsed.name,
            group_name=parsed.group_name,
            credits=parsed.credits,
        )
        db_session.add(subject)
        await db_session.flush()
        return subject

    existing.name = parsed.name
    existing.group_name = parsed.group_name
    existing.credits = parsed.credits
    existing.edu_form_id = parsed.edu_form_id
    return existing


async def _replace_marks_for_lesson_type(
    db_session: AsyncSession,
    *,
    subject: Subject,
    lesson_type_id: int,
    lesson_type_name: str | None,
    popup: ParsedGradesPopup,
) -> int:
    # Safety: don't wipe existing marks if the new pull is empty AND we had data
    # before. UNEC sometimes returns an empty popup on transient errors.
    if not popup.marks:
        existing_count = (
            await db_session.execute(
                select(Mark.id).where(
                    Mark.subject_id == subject.id, Mark.lesson_type_id == lesson_type_id
                )
            )
        ).all()
        if existing_count:
            logger.warning(
                "Empty popup for subject=%s lesson_type=%s but DB has %d marks; keeping old",
                subject.id, lesson_type_id, len(existing_count),
            )
            return 0
        return 0

    await db_session.execute(
        delete(Mark).where(
            Mark.subject_id == subject.id, Mark.lesson_type_id == lesson_type_id
        )
    )
    for parsed_mark in popup.marks:
        db_session.add(
            Mark(
                subject_id=subject.id,
                lesson_type_id=lesson_type_id,
                lesson_type_name=lesson_type_name,
                date=parsed_mark.date,
                topic=parsed_mark.topic,
                mark_code=parsed_mark.mark_code,
            )
        )
    return len(popup.marks)


async def _upsert_grading_details(
    db_session: AsyncSession,
    *,
    subject: Subject,
    lesson_type_id: int,
    popup: ParsedGradesPopup,
) -> None:
    # UNEC duplicates `final_eval` and `scheme` across every lesson_type popup,
    # so they don't prove this lesson type is real. We only persist details
    # when there's actual per-lesson-type content: marks, course work,
    # independent work, or writing scores. If we already have a stale row from
    # an older sync, drop it.
    has_content = bool(popup.marks) or any(
        _dict_has_meaningful_values(d)
        for d in (popup.course_work, popup.independent_work, popup.writing)
    )
    existing = await db_session.get(SubjectGradingDetails, (subject.id, lesson_type_id))

    if not has_content:
        if existing is not None:
            await db_session.delete(existing)
        return

    if existing is None:
        db_session.add(
            SubjectGradingDetails(
                subject_id=subject.id,
                lesson_type_id=lesson_type_id,
                final_eval=popup.final_eval,
                scheme=popup.scheme,
                course_work=popup.course_work,
                independent_work=popup.independent_work,
                writing=popup.writing,
            )
        )
    else:
        existing.final_eval = popup.final_eval
        existing.scheme = popup.scheme
        existing.course_work = popup.course_work
        existing.independent_work = popup.independent_work
        existing.writing = popup.writing


# Meta keys that aren't real grades — student name, row number, etc.
_META_GRADING_KEYS = {"№", "Soyad Ad Ata adı", "Fənn"}


def _dict_has_meaningful_values(d: dict | None) -> bool:
    if not d:
        return False
    return any(
        isinstance(v, str) and v.strip() != ""
        for k, v in d.items()
        if k not in _META_GRADING_KEYS
    )


async def sync_grades(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    redis_client: redis.Redis,
    edu_year_id: int | None = None,
    edu_semester_id: int | None = None,
) -> GradesSyncResult:
    manager = UnecSessionManager(redis_client)
    lesson_type_name_by_id: dict[int, str] = {}

    async def fetch_all(
        client: UnecClient,
    ) -> tuple[int, int, dict[int, ParsedSubject], list[tuple[int, int, ParsedGradesPopup]]]:
        year, semester, lesson_type_options = await _resolve_year_and_semester(
            client=client,
            edu_year_id=edu_year_id,
            edu_semester_id=edu_semester_id,
        )

        # The subject table is only populated when a specific lessonType filter
        # is applied. So iterate per type — and along the way we naturally
        # discover which (subject, lesson_type) pairs actually exist, which
        # avoids fetching empty popups for combinations the user isn't enrolled
        # in.
        seen_subjects: dict[int, ParsedSubject] = {}
        popup_pairs: list[tuple[int, int, ParsedGradesPopup]] = []

        for opt in lesson_type_options:
            lesson_type_name_by_id[opt.id] = opt.label
            subjects_here = await _fetch_subject_list_for_lesson_type(
                client, year=year, semester=semester, lesson_type_id=opt.id
            )
            for s in subjects_here:
                seen_subjects.setdefault(s.unec_subject_id, s)
                popup = await _fetch_popup(
                    client,
                    unec_subject_id=s.unec_subject_id,
                    lesson_type_id=opt.id,
                    edu_form_id=s.edu_form_id,
                )
                popup_pairs.append((s.unec_subject_id, opt.id, popup))
                await asyncio.sleep(_POPUP_DELAY_S)

        return year, semester, seen_subjects, popup_pairs

    year, semester, parsed_subjects_by_id, popup_pairs = await manager.fetch(
        user_id, db_session, fetch_all
    )

    # Sanity check: UNEC sometimes ignores the eduYear filter and returns the
    # current year's subjects no matter what. Detect that by checking whether
    # any of the freshly-fetched unec_subject_id values already live under a
    # *different* (user, year) — if so, refuse to write the duplicate.
    if parsed_subjects_by_id:
        unec_ids = list(parsed_subjects_by_id.keys())
        clash = await db_session.execute(
            select(Subject.edu_year_id, Subject.unec_subject_id)
            .where(
                Subject.user_id == user_id,
                Subject.edu_year_id != year,
                Subject.unec_subject_id.in_(unec_ids),
            )
            .limit(1)
        )
        clashing = clash.first()
        if clashing is not None:
            raise RuntimeError(
                f"UNEC returned subjects already known under year {clashing[0]} "
                f"— it likely ignored the eduYear filter. "
                f"Historical years are not accessible through automated requests."
            )

    try:
        subject_by_unec_id: dict[int, Subject] = {}
        for parsed in parsed_subjects_by_id.values():
            subject = await _upsert_subject(
                db_session,
                user_id=user_id,
                edu_year_id=year,
                edu_semester_id=semester,
                parsed=parsed,
            )
            subject_by_unec_id[parsed.unec_subject_id] = subject

        total_marks = 0
        for unec_subject_id, lesson_type_id, popup in popup_pairs:
            subject = subject_by_unec_id.get(unec_subject_id)
            if subject is None:
                continue
            inserted = await _replace_marks_for_lesson_type(
                db_session,
                subject=subject,
                lesson_type_id=lesson_type_id,
                lesson_type_name=lesson_type_name_by_id.get(lesson_type_id),
                popup=popup,
            )
            total_marks += inserted
            await _upsert_grading_details(
                db_session,
                subject=subject,
                lesson_type_id=lesson_type_id,
                popup=popup,
            )

        now = datetime.now(UTC)
        state = await db_session.get(GradesSyncState, (user_id, year, semester))
        if state is None:
            state = GradesSyncState(
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

    return GradesSyncResult(
        edu_year_id=year,
        edu_semester_id=semester,
        subject_count=len(parsed_subjects_by_id),
        mark_count=total_marks,
        last_synced_at=now,
    )


# ---------------- Read ----------------


async def get_user_grades(
    *,
    user_id: uuid.UUID,
    db_session: AsyncSession,
    edu_year_id: int | None = None,
    edu_semester_id: int | None = None,
) -> GradesView:
    if edu_year_id is None or edu_semester_id is None:
        latest = await db_session.execute(
            select(GradesSyncState)
            .where(GradesSyncState.user_id == user_id)
            .order_by(GradesSyncState.last_synced_at.desc())
            .limit(1)
        )
        latest_state = latest.scalar_one_or_none()
        if latest_state is None:
            return GradesView(
                edu_year_id=None,
                edu_semester_id=None,
                subjects=[],
                last_synced_at=None,
                sync_status=None,
                sync_error=None,
            )
        edu_year_id = edu_year_id or latest_state.edu_year_id
        edu_semester_id = edu_semester_id or latest_state.edu_semester_id
        sync_state = latest_state
    else:
        sync_state = await db_session.get(
            GradesSyncState, (user_id, edu_year_id, edu_semester_id)
        )

    subjects_rows = await db_session.execute(
        select(Subject)
        .where(
            Subject.user_id == user_id,
            Subject.edu_year_id == edu_year_id,
            Subject.edu_semester_id == edu_semester_id,
        )
        .order_by(Subject.name)
    )
    subjects = list(subjects_rows.scalars().all())
    subject_ids = [s.id for s in subjects]

    marks_by_subject: dict[uuid.UUID, dict[int, list[Mark]]] = {sid: {} for sid in subject_ids}
    if subject_ids:
        marks_rows = await db_session.execute(
            select(Mark)
            .where(Mark.subject_id.in_(subject_ids))
            .order_by(Mark.date.desc())
        )
        for mark in marks_rows.scalars():
            marks_by_subject.setdefault(mark.subject_id, {}).setdefault(mark.lesson_type_id, []).append(mark)

    details_by_subject: dict[uuid.UUID, dict[int, SubjectGradingDetails]] = {
        sid: {} for sid in subject_ids
    }
    if subject_ids:
        detail_rows = await db_session.execute(
            select(SubjectGradingDetails).where(
                SubjectGradingDetails.subject_id.in_(subject_ids)
            )
        )
        for detail in detail_rows.scalars():
            details_by_subject.setdefault(detail.subject_id, {})[detail.lesson_type_id] = detail

    views = [
        SubjectView(
            subject=s,
            marks_by_lesson_type=marks_by_subject.get(s.id, {}),
            details_by_lesson_type=details_by_subject.get(s.id, {}),
        )
        for s in subjects
    ]

    return GradesView(
        edu_year_id=edu_year_id,
        edu_semester_id=edu_semester_id,
        subjects=views,
        last_synced_at=sync_state.last_synced_at if sync_state else None,
        sync_status=sync_state.status if sync_state else None,
        sync_error=sync_state.error_message if sync_state else None,
    )


async def record_sync_failure(
    *,
    user_id: uuid.UUID,
    edu_year_id: int,
    edu_semester_id: int,
    db_session: AsyncSession,
    error: str,
) -> None:
    state = await db_session.get(
        GradesSyncState, (user_id, edu_year_id, edu_semester_id)
    )
    now = datetime.now(UTC)
    if state is None:
        state = GradesSyncState(
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
    "GradesSyncResult",
    "GradesView",
    "NoUnecCredentials",
    "SubjectView",
    "UnecAuthError",
    "get_user_grades",
    "record_sync_failure",
    "sync_grades",
]
