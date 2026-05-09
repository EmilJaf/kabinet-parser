from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenPairOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshIn(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    created_at: datetime
    is_admin: bool = False


class UnecCredentialsIn(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)
    skip_validation: bool = False


class UnecCredentialsStatus(BaseModel):
    configured: bool
    username: str | None = None
    last_login_at: datetime | None = None
    updated_at: datetime | None = None


class LessonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    day: int
    start: time
    end: time
    subject: str
    subject_code: str | None
    lesson_type: str | None
    room: str | None
    building: str | None
    teacher: str | None
    week_parity: str
    period_start: date | None
    period_end: date | None


class ScheduleOut(BaseModel):
    edu_year_id: int | None
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None
    lessons: list[LessonOut]


class MarkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    date: date
    topic: str
    mark_code: str | None


class LessonTypeMarksOut(BaseModel):
    lesson_type_id: int
    lesson_type_name: str | None = None
    marks: list[MarkOut] = Field(default_factory=list)
    final_eval: dict | None = None
    scheme: dict | None = None
    course_work: dict | None = None
    independent_work: dict | None = None
    writing: dict | None = None


class SubjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    unec_subject_id: int
    name: str
    group_name: str | None
    credits: int | None
    edu_form_id: int | None
    by_lesson_type: list[LessonTypeMarksOut] = Field(default_factory=list)


class GradesOut(BaseModel):
    edu_year_id: int | None
    edu_semester_id: int | None
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None
    subjects: list[SubjectOut]


class ExamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_type_name: str
    unec_exam_id: int | None
    subject_code: str | None
    subject_name: str
    subject_full: str | None
    form: str | None
    date: date | None
    start_time: time | None
    end_time: time | None
    entry_score: int | None
    exam_score: int | None
    final_score: int | None
    grade_letter: str | None
    grade_label: str | None


class ExamsOut(BaseModel):
    edu_year_id: int | None
    edu_semester_id: int | None
    last_synced_at: datetime | None
    sync_status: str | None
    sync_error: str | None
    exams: list[ExamOut]


class ExamQuestionOut(BaseModel):
    index: int
    question_id: int
    text: str
    status: str  # 'correct' | 'wrong' | 'unknown'
    score: int | None = None  # populated for written exams
    comment: str | None = None


class ExamQuestionsOut(BaseModel):
    exam_id: uuid.UUID
    available: bool  # false if exam can't be queried (paper / pre-migration row)
    correct_count: int
    wrong_count: int
    unknown_count: int
    questions: list[ExamQuestionOut]


class ExamAnswerOptionOut(BaseModel):
    text: str
    image_path: str | None
    is_correct: bool
    is_user_choice: bool


class ExamQuestionDetailOut(BaseModel):
    kind: str  # 'mcq' | 'written' | 'unknown'
    question_text: str
    question_image_path: str | None = None
    options: list[ExamAnswerOptionOut] = Field(default_factory=list)
    difficulty: str | None = None
    score: int | None = None
    comment: str | None = None
    answer_images: list[str] = Field(default_factory=list)


class UpcomingExamOut(BaseModel):
    group_name: str
    date: date | None
    start_time: time | None
    end_time: time | None
    entry_score: int | None
    username: str | None
    password: str | None
    exam_type_name: str
    status: str | None
    blocked: bool
