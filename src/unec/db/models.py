from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Per-user Data Encryption Key, KEK-wrapped. Generated lazily on first
    # UNEC credential save so users that never link UNEC carry no key.
    encrypted_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Gates the /admin/* endpoints + the admin SPA view.
    is_admin: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    unec_credentials: Mapped["UnecCredentials | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    push_subscriptions: Mapped[list["PushSubscription"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class PushSubscription(Base):
    """Web Push (PWA) subscription for a user device.

    Browser produces the {endpoint, p256dh, auth} triple via PushManager;
    we store it so the worker can fan out push messages from the server.
    Same user across multiple devices = multiple rows. Endpoint is unique
    globally (it embeds a per-device push-service URL).
    """
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        Index("ix_push_subscriptions_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    p256dh: Mapped[str] = mapped_column(String(255), nullable=False)
    auth: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="push_subscriptions")


class UnecCredentials(Base):
    __tablename__ = "unec_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet ciphertext of the UNEC password, encrypted with the user's DEK
    # (which is itself stored KEK-wrapped on users.encrypted_dek).
    encrypted_password: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="unec_credentials")


class Lesson(Base):
    __tablename__ = "lessons"
    __table_args__ = (
        Index("ix_lessons_user_year_day", "user_id", "edu_year_id", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    edu_year_id: Mapped[int] = mapped_column(Integer, nullable=False)

    day: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1=Mon..7=Sun
    start: Mapped[time] = mapped_column(Time, nullable=False)
    end: Mapped[time] = mapped_column(Time, nullable=False)

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    subject_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lesson_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room: Mapped[str | None] = mapped_column(String(32), nullable=True)
    building: Mapped[str | None] = mapped_column(String(32), nullable=True)
    teacher: Mapped[str | None] = mapped_column(String(255), nullable=True)
    week_parity: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)


class ScheduleSyncState(Base):
    __tablename__ = "schedule_sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    edu_year_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "edu_year_id", "edu_semester_id", "unec_subject_id",
            name="uq_subjects_user_year_sem_unec_id",
        ),
        Index("ix_subjects_user_year_sem", "user_id", "edu_year_id", "edu_semester_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    edu_year_id: Mapped[int] = mapped_column(Integer, nullable=False)
    edu_semester_id: Mapped[int] = mapped_column(Integer, nullable=False)
    unec_subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    edu_form_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    name: Mapped[str] = mapped_column(Text, nullable=False)
    group_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    credits: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Mark(Base):
    __tablename__ = "marks"
    __table_args__ = (
        # No UNIQUE constraint on (subject, lesson_type, date, topic) —
        # UNEC legitimately returns several marks with the same key in one
        # day (e.g. numeric '10' alongside attendance flag 'i/e' for the
        # same seminar slot, or two 'i/e' rows for double-block seminars).
        # The grades sync uses delete-then-insert per (subject, lesson_type),
        # so there's no risk of true accidental duplicates.
        Index("ix_marks_subject_type", "subject_id", "lesson_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False
    )
    lesson_type_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lesson_type_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mark_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Inserted at first sight; never updated. Used by the worker to detect
    # marks added since the previous grades sync and push notifications.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SubjectGradingDetails(Base):
    __tablename__ = "subject_grading_details"

    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True
    )
    lesson_type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    final_eval: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scheme: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    course_work: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    independent_work: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    writing: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GradesSyncState(Base):
    __tablename__ = "grades_sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    edu_year_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edu_semester_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (
        Index("ix_exams_user_year_sem", "user_id", "edu_year_id", "edu_semester_id"),
        Index("ix_exams_user_date", "user_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    edu_year_id: Mapped[int] = mapped_column(Integer, nullable=False)
    edu_semester_id: Mapped[int] = mapped_column(Integer, nullable=False)

    exam_type_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exam_type_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # UNEC's internal exam ID (hidden cell). Null for paper exams.
    unec_exam_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Hidden col2 — UNEC needs this as `main=<n>` in the POST /az/subject body
    # to look up the exam's questions. 1=electronic MCQ, 3=paper, 5=written.
    main_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Subject info parsed out of the multi-line "Fənn" cell.
    subject_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subject_name: Mapped[str] = mapped_column(Text, nullable=False)
    subject_full: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Form: "Elektron imtahan" / "Yazili imtahan" / etc.
    form: Mapped[str | None] = mapped_column(String(64), nullable=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    # Scores (Giriş balı = score before exam, İmtahan balı = exam score itself).
    entry_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    exam_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)

    # Final result parsed from "83 B (Çox yaxşı)" → 83 / B / "Çox yaxşı".
    final_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    grade_letter: Mapped[str | None] = mapped_column(String(4), nullable=True)
    grade_label: Mapped[str | None] = mapped_column(String(64), nullable=True)


class FilesPageCache(Base):
    """Cached HTML of UNEC's /az/files page per (user, filter combination).

    Materials change rarely (~once per semester), so we persist them in
    Postgres rather than Redis to survive restarts and avoid arbitrary
    eviction. Reads check `last_synced_at` against an app-level TTL;
    `force=true` from the API rewrites the row regardless.
    """
    __tablename__ = "files_page_cache"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # SHA-256 hex (16-char prefix) of the canonical query string identifying
    # this filter combination — keeps the PK short and stable.
    params_hash: Mapped[str] = mapped_column(String(32), primary_key=True)
    html: Mapped[str] = mapped_column(Text, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ExamSyncState(Base):
    __tablename__ = "exam_sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    edu_year_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    edu_semester_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
