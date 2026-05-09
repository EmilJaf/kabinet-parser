"""Pure-Python tests of the parser → ORM mapping inside services.schedule.

No DB, no UNEC — just verifies that the in-memory ParsedLesson maps onto the
SQLAlchemy `Lesson` model with the right fields.
"""
from __future__ import annotations

import uuid
from datetime import date, time
from pathlib import Path

from unec.scraper.parsers.schedule import parse_schedule
from unec.services.schedule import _to_orm

FIXTURE = Path(__file__).parent / "fixtures" / "schedule_2025-26.html"


def test_parser_to_orm_maps_all_fields():
    parsed = parse_schedule(FIXTURE.read_text())
    user_id = uuid.uuid4()

    rows = [_to_orm(p, user_id=user_id, edu_year_id=1000048) for p in parsed]
    assert len(rows) == len(parsed)

    first = rows[0]
    assert first.user_id == user_id
    assert first.edu_year_id == 1000048
    assert first.day == 1  # Monday
    assert first.start == time(8, 30)
    assert first.end == time(9, 50)
    assert first.subject == "Sahibkarlığın əsasları və biznesə giriş"
    assert first.subject_code == "10_24_02_574-R_00758"
    assert first.lesson_type == "Mühazirə"
    assert first.room == "117"
    assert first.building == "III"
    assert first.teacher == "M.Sevda"
    assert first.week_parity == "normal"
    assert first.period_start == date(2026, 2, 16)
    assert first.period_end == date(2026, 5, 29)


def test_alternating_weeks_preserved():
    parsed = parse_schedule(FIXTURE.read_text())
    user_id = uuid.uuid4()
    rows = [_to_orm(p, user_id=user_id, edu_year_id=1000048) for p in parsed]

    monday_10 = [r for r in rows if r.day == 1 and r.start == time(10, 0)]
    assert {r.week_parity for r in monday_10} == {"upper", "lower"}
