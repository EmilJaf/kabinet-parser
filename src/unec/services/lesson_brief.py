"""Per-lesson summary used in push notifications.

Mirrors the calculation in frontend's GradesView.statsFor():
  - absence_pct = max over lesson_types of subject_grading_details.final_eval['Qaib faizi']
  - mark_count  = number of seminar marks whose mark_code is purely numeric
                  (e.g. "85", "9.5") — attendance flags like "i", "i/e",
                  "q", "q/b" don't count as scored marks.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Lesson, Mark, Subject, SubjectGradingDetails

_NUMERIC_MARK = re.compile(r"^\d+([.,]\d+)?$")


@dataclass(slots=True)
class LessonBrief:
    subject_name: str
    room: str | None
    teacher: str | None
    mark_count: int  # numeric seminar marks this semester
    absence_pct: float | None  # 0..100, max across lesson types


def _is_seminar(lesson_type_name: str | None) -> bool:
    return (lesson_type_name or "").lower().find("seminar") >= 0


def _is_numeric(code: str | None) -> bool:
    return bool(code and _NUMERIC_MARK.match(code.strip()))


async def build_lesson_brief(
    session: AsyncSession, *, user_id: uuid.UUID, lesson: Lesson
) -> LessonBrief:
    # Match the lesson to a Subject row by name within the user's most-recent
    # semester. Schedule and grades both come from UNEC; subject names match
    # exactly in practice.
    subj_stmt = (
        select(Subject)
        .where(Subject.user_id == user_id, Subject.name == lesson.subject)
        .order_by(Subject.edu_year_id.desc(), Subject.edu_semester_id.desc())
        .limit(1)
    )
    subject = (await session.execute(subj_stmt)).scalar_one_or_none()

    mark_count = 0
    absence_pct: float | None = None

    if subject is not None:
        # absence_pct from grading details — same field GradesView reads.
        details_stmt = select(SubjectGradingDetails).where(
            SubjectGradingDetails.subject_id == subject.id
        )
        for d in (await session.execute(details_stmt)).scalars():
            fe = d.final_eval or {}
            raw = fe.get("Qaib faizi")
            if raw:
                try:
                    pct = float(str(raw).replace(",", "."))
                    absence_pct = pct if absence_pct is None else max(absence_pct, pct)
                except ValueError:
                    pass

        # Numeric seminar marks — same filter as the frontend.
        marks_stmt = select(Mark).where(Mark.subject_id == subject.id)
        for m in (await session.execute(marks_stmt)).scalars():
            # We don't have lesson_type_name on Mark cleanly, but the frontend
            # relies on lesson_type_name containing 'seminar' AND mark being
            # numeric. mark.lesson_type_name carries it.
            if _is_seminar(m.lesson_type_name) and _is_numeric(m.mark_code):
                mark_count += 1

    return LessonBrief(
        subject_name=lesson.subject,
        room=lesson.room,
        teacher=lesson.teacher,
        mark_count=mark_count,
        absence_pct=absence_pct,
    )
