from __future__ import annotations

import re
from datetime import date, datetime, time

from selectolax.parser import HTMLParser, Node

from ..models import WEEK_PARITY_AZ, DayOfWeek, Lesson, WeekParity

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$")
_ROOM_RE = re.compile(r"Otaq:\s*(\S+)\s*(?:\(\s*([^)]+?)\s*\))?")
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})\s*-\s*(\d{2})\.(\d{2})\.(\d{4})")
_TEACHER_PREFIX = "Müəllim:"
_SUBJECT_CODE_RE = re.compile(r"^([\w\-]+_\d+)_(.+)$")

DAY_COLUMNS = (
    DayOfWeek.MON,
    DayOfWeek.TUE,
    DayOfWeek.WED,
    DayOfWeek.THU,
    DayOfWeek.FRI,
    DayOfWeek.SAT,
    DayOfWeek.SUN,
)


def parse_schedule(html: str) -> list[Lesson]:
    tree = HTMLParser(html)
    table = tree.css_first("table.newTable")
    if table is None:
        return []

    lessons: list[Lesson] = []
    for row in table.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < 2:
            continue
        time_text = (cells[0].text() or "").strip()
        time_match = _TIME_RE.match(time_text)
        if not time_match:
            continue
        start = time(int(time_match.group(1)), int(time_match.group(2)))
        end = time(int(time_match.group(3)), int(time_match.group(4)))

        for col_idx, cell in enumerate(cells[1:]):
            if col_idx >= len(DAY_COLUMNS):
                break
            day = DAY_COLUMNS[col_idx]
            div = cell.css_first("div")
            if div is None:
                continue
            for partial in _split_cell_into_lessons(div):
                lesson = _build_lesson(day=day, start=start, end=end, fields=partial)
                if lesson is not None:
                    lessons.append(lesson)
    return lessons


def _split_cell_into_lessons(div: Node) -> list[dict]:
    """Walk children of a schedule cell <div> and yield a dict per lesson.

    Lessons are delimited by the date range in <b><span>…</span></b>. A new
    lesson is opened on the first text/span seen after the previous date.
    """
    lessons: list[dict] = []
    current: dict = {}

    for child in div.iter(include_text=True):
        tag = child.tag
        if tag == "br":
            continue
        if tag == "-text":
            text = (child.text() or "").strip()
            if text:
                current["subject_raw"] = text
            continue
        if tag == "span":
            cls = (child.attributes.get("class") or "").strip()
            text = (child.text() or "").strip()
            if not text:
                continue
            if "spangreen" in cls:
                current["room_raw"] = text
            elif "spanorange" in cls:
                current["lesson_type"] = text
            elif text.startswith(_TEACHER_PREFIX):
                current["teacher"] = text[len(_TEACHER_PREFIX):].strip()
            elif text in WEEK_PARITY_AZ:
                current["week_parity"] = WEEK_PARITY_AZ[text]
            continue
        if tag == "b":
            text = (child.text() or "").strip()
            current["date_raw"] = text
            if current.get("subject_raw"):
                lessons.append(current)
            current = {}
            continue
    return lessons


def _build_lesson(*, day: DayOfWeek, start: time, end: time, fields: dict) -> Lesson | None:
    subject_raw: str | None = fields.get("subject_raw")
    if not subject_raw:
        return None

    subject_code: str | None = None
    subject = subject_raw
    code_match = _SUBJECT_CODE_RE.match(subject_raw)
    if code_match:
        subject_code = code_match.group(1)
        subject = code_match.group(2)

    room: str | None = None
    building: str | None = None
    if room_raw := fields.get("room_raw"):
        room_match = _ROOM_RE.search(room_raw)
        if room_match:
            room = room_match.group(1)
            building = room_match.group(2)

    period_start: date | None = None
    period_end: date | None = None
    if date_raw := fields.get("date_raw"):
        date_match = _DATE_RE.search(date_raw)
        if date_match:
            d1, m1, y1, d2, m2, y2 = (int(g) for g in date_match.groups())
            period_start = date(y1, m1, d1)
            period_end = date(y2, m2, d2)

    return Lesson(
        day=day,
        start=start,
        end=end,
        subject=subject,
        subject_code=subject_code,
        lesson_type=fields.get("lesson_type"),
        room=room,
        building=building,
        teacher=fields.get("teacher"),
        week_parity=fields.get("week_parity", WeekParity.NORMAL),
        period_start=period_start,
        period_end=period_end,
    )


def parse_education_year(html: str) -> int | None:
    """Return the currently selected eduYear ID from the schedule page filter."""
    tree = HTMLParser(html)
    node = tree.css_first("select[name='eduYear'] option[selected]")
    if node is None:
        return None
    value = node.attributes.get("value")
    return int(value) if value and value.isdigit() else None
