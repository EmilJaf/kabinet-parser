from datetime import date, time
from pathlib import Path

import pytest

from unec.scraper.models import DayOfWeek, WeekParity
from unec.scraper.parsers.schedule import parse_education_year, parse_schedule

FIXTURE = Path(__file__).parent / "fixtures" / "schedule_2025-26.html"


@pytest.fixture(scope="module")
def lessons():
    return parse_schedule(FIXTURE.read_text())


def test_lesson_count(lessons):
    # 3 time slots; rows have these counts of non-empty cells:
    #   row 1: Mon, Tue, Wed, Fri = 4
    #   row 2: Mon (×2 — Alt + Üst), Tue, Wed, Fri = 5
    #   row 3: Mon, Wed, Fri = 3
    assert len(lessons) == 12


def test_first_lesson_fields(lessons):
    first = lessons[0]
    assert first.day is DayOfWeek.MON
    assert first.start == time(8, 30)
    assert first.end == time(9, 50)
    assert first.subject == "Sahibkarlığın əsasları və biznesə giriş"
    assert first.subject_code == "10_24_02_574-R_00758"
    assert first.lesson_type == "Mühazirə"
    assert first.room == "117"
    assert first.building == "III"
    assert first.teacher == "M.Sevda"
    assert first.week_parity is WeekParity.NORMAL
    assert first.period_start == date(2026, 2, 16)
    assert first.period_end == date(2026, 5, 29)


def test_alternating_weeks_in_one_cell(lessons):
    monday_10 = [
        lesson
        for lesson in lessons
        if lesson.day is DayOfWeek.MON and lesson.start == time(10, 0)
    ]
    assert len(monday_10) == 2

    parities = {lesson.week_parity for lesson in monday_10}
    assert parities == {WeekParity.LOWER, WeekParity.UPPER}

    subjects = {lesson.subject for lesson in monday_10}
    assert subjects == {
        "Sahibkarlığın əsasları və biznesə giriş",
        "Diferensial tənliklər",
    }


def test_thursday_is_empty(lessons):
    thursday = [lesson for lesson in lessons if lesson.day is DayOfWeek.THU]
    assert thursday == []


def test_education_year():
    html = FIXTURE.read_text()
    assert parse_education_year(html) == 1000048
