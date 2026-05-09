"""Parsers for the UNEC e-journal pages.

Three things are parsed here:
1. ``parse_subject_list``  — table on /az/studentEvaluation
2. ``parse_grades_popup``  — modal returned by POST /az/studentEvaluationPopup
3. ``parse_semester_options`` — the raw <option> HTML returned by the
   getEduSemester XHR

All return plain dataclasses; mapping to ORM rows happens in services.grades.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from selectolax.parser import HTMLParser, Node


@dataclass(slots=True)
class ParsedSubject:
    unec_subject_id: int
    name: str
    credits: int | None
    group_name: str | None
    edu_form_id: int | None


@dataclass(slots=True)
class ParsedMark:
    date: date
    topic: str
    mark_code: str | None


@dataclass(slots=True)
class ParsedGradesPopup:
    marks: list[ParsedMark] = field(default_factory=list)
    final_eval: dict | None = None
    scheme: dict | None = None
    course_work: dict | None = None
    independent_work: dict | None = None
    writing: dict | None = None


@dataclass(slots=True)
class ParsedOption:
    id: int
    label: str
    selected: bool = False


_DATE_RE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")


# ---------------- Subject list ----------------


def parse_subject_list(html: str) -> list[ParsedSubject]:
    tree = HTMLParser(html)
    grid = tree.css_first("#studentEvaluation-grid table")
    if grid is None:
        return []

    subjects: list[ParsedSubject] = []
    for row in grid.css("tbody tr"):
        cells = row.css("td")
        # Empty-state row uses colspan=6 + class="empty" — skip it.
        if len(cells) < 6:
            continue
        unec_id_text = (cells[1].text() or "").strip()
        if not unec_id_text.isdigit():
            continue
        edu_form_text = (cells[5].text() or "").strip()
        credits_text = (cells[3].text() or "").strip()
        subjects.append(
            ParsedSubject(
                unec_subject_id=int(unec_id_text),
                name=(cells[2].text() or "").strip(),
                credits=int(credits_text) if credits_text.isdigit() else None,
                group_name=(cells[4].text() or "").strip() or None,
                edu_form_id=int(edu_form_text) if edu_form_text.isdigit() else None,
            )
        )
    return subjects


def parse_selected_filters(html: str) -> dict[str, int | None]:
    """Return the currently selected eduYear / eduSemester / lessonType from the form."""
    tree = HTMLParser(html)
    return {
        "edu_year_id": _selected_int(tree, "select[name='eduYear']"),
        "edu_semester_id": _selected_int(tree, "select[name='eduSemester']"),
        "lesson_type_id": _selected_int(tree, "select[name='lessonType']"),
    }


def parse_filter_options(html: str) -> dict[str, list[ParsedOption]]:
    """Return the available year / semester / lesson_type options from the form."""
    tree = HTMLParser(html)
    return {
        "edu_years": _options(tree, "select[name='eduYear']"),
        "edu_semesters": _options(tree, "select[name='eduSemester']"),
        "lesson_types": _options(tree, "select[name='lessonType']"),
    }


def _selected_int(tree: HTMLParser, selector: str) -> int | None:
    select = tree.css_first(selector)
    if select is None:
        return None
    selected = select.css_first("option[selected]")
    if selected is None:
        return None
    value = (selected.attributes.get("value") or "").strip()
    return int(value) if value.isdigit() else None


def _options(tree: HTMLParser, selector: str) -> list[ParsedOption]:
    select = tree.css_first(selector)
    if select is None:
        return []
    out: list[ParsedOption] = []
    for opt in select.css("option"):
        value = (opt.attributes.get("value") or "").strip()
        if not value.isdigit():
            continue
        out.append(
            ParsedOption(
                id=int(value),
                label=(opt.text() or "").strip(),
                selected="selected" in opt.attributes,
            )
        )
    return out


# ---------------- Semester options (XHR) ----------------


def parse_semester_options(html_fragment: str) -> list[ParsedOption]:
    """Parse the bare ``<option>`` list returned by POST /az/getEduSemester.

    The response isn't a full document — it's a sequence of options, possibly
    starting with the empty placeholder. We feed it into selectolax wrapped in
    a synthetic <select> so CSS selection works.
    """
    tree = HTMLParser(f"<select>{html_fragment}</select>")
    return _options(tree, "select")


# ---------------- Grades popup ----------------


def parse_grades_popup(html: str) -> ParsedGradesPopup:
    tree = HTMLParser(html)
    return ParsedGradesPopup(
        marks=_parse_marks(tree),
        final_eval=_parse_table_to_dict(tree, "#finalEval"),
        scheme=_parse_table_to_dict(tree, "#forma"),
        course_work=_parse_table_to_dict(tree, "#generalWork"),
        independent_work=_parse_table_to_dict(tree, "#indepWork"),
        writing=_parse_table_to_dict(tree, "#writting"),
    )


def _parse_marks(tree: HTMLParser) -> list[ParsedMark]:
    container = tree.css_first("#evaluation")
    if container is None:
        return []
    marks: list[ParsedMark] = []
    for row in container.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < 4:
            continue
        date_text = (cells[1].text() or "").strip()
        date_match = _DATE_RE.match(date_text)
        if not date_match:
            continue
        d, m, y = (int(g) for g in date_match.groups())
        topic_raw = cells[2].text() or ""
        mark_raw = (cells[3].text() or "").strip() or None
        marks.append(
            ParsedMark(
                date=date(y, m, d),
                topic=topic_raw.strip(),
                mark_code=mark_raw,
            )
        )
    return marks


def _parse_table_to_dict(tree: HTMLParser, container_selector: str) -> dict | None:
    """Extract a single-row table inside a tab as ``{leaf_header: cell_value}``.

    Returns None if the tab has no body rows (empty section). Multi-row headers
    (rowspan/colspan) are flattened — we keep the header text from whichever
    cell maps positionally to the data cell.
    """
    container = tree.css_first(container_selector)
    if container is None:
        return None
    table = container.css_first("table")
    if table is None:
        return None
    headers = _flatten_headers(table)
    body_rows = table.css("tbody tr")
    if not body_rows:
        return None
    # Single-row tables are the common case in this UI; if there are multiple
    # rows, return a list.
    parsed_rows: list[dict] = []
    for row in body_rows:
        values = [(c.text() or "").strip() for c in row.css("td")]
        if not values:
            continue
        parsed_rows.append(_zip_padded(headers, values))
    if not parsed_rows:
        return None
    if len(parsed_rows) == 1:
        return parsed_rows[0]
    return {"rows": parsed_rows}


def _flatten_headers(table: Node) -> list[str]:
    """Walk thead and produce a flat list of leaf header labels.

    Handles ``rowspan``/``colspan`` by pre-allocating a 2D grid and filling it,
    then taking the bottom row as the canonical labels.
    """
    head_rows = table.css("thead tr")
    if not head_rows:
        return []

    # First pass: figure out grid width from the first row's spans.
    width = 0
    for cell in head_rows[0].css("th"):
        width += int(cell.attributes.get("colspan") or 1)
    if width == 0:
        return []

    grid: list[list[str | None]] = [[None] * width for _ in head_rows]

    for r_idx, row in enumerate(head_rows):
        col = 0
        for cell in row.css("th"):
            # Skip already-filled slots from a rowspan above.
            while col < width and grid[r_idx][col] is not None:
                col += 1
            if col >= width:
                break
            label = (cell.text() or "").strip()
            colspan = int(cell.attributes.get("colspan") or 1)
            rowspan = int(cell.attributes.get("rowspan") or 1)
            for dr in range(rowspan):
                for dc in range(colspan):
                    if r_idx + dr < len(grid) and col + dc < width:
                        grid[r_idx + dr][col + dc] = label
            col += colspan

    # Bottom row carries the leaf labels.
    return [cell or "" for cell in grid[-1]]


def _zip_padded(headers: list[str], values: list[str]) -> dict:
    out: dict[str, str] = {}
    for i, value in enumerate(values):
        key = headers[i] if i < len(headers) else f"col_{i}"
        if not key:
            key = f"col_{i}"
        out[key] = value
    return out
