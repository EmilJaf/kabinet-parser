"""Parsers for the exam-related UNEC pages.

Two pages:
  /az/elist     — upcoming exam schedule (during sessions)
  /az/eresults  — past exam results, paginated, filterable by year/semester/type

Plus the popup at POST /az/subject (exam-question detail) — not parsed yet,
deferred to a later iteration.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time

from selectolax.parser import HTMLParser

from .evaluation import ParsedOption, _options  # reuse


# ---------------- DTOs ----------------


@dataclass(slots=True)
class ParsedExamResult:
    unec_exam_id: int | None
    main_type: int | None  # hidden col2: 1=electronic MCQ, 3=paper, 5=written
    subject_code: str | None
    subject_name: str
    subject_full: str
    exam_type_name: str
    form: str | None
    date: date | None
    start_time: time | None
    end_time: time | None
    entry_score: int | None
    exam_score: int | None
    final_score: int | None
    grade_letter: str | None
    grade_label: str | None


@dataclass(slots=True)
class ParsedExamQuestion:
    index: int
    question_id: int
    main_type: int | None
    exam_id: int | None
    text: str
    status: str  # 'correct' | 'wrong' | 'unknown'
    # Optional — populated by the service for written exams via the per-question
    # detail call (main=5 questions don't carry their score in the list popup).
    score: int | None = None
    comment: str | None = None


@dataclass(slots=True)
class ParsedAnswerOption:
    text: str
    image_path: str | None
    is_correct: bool
    is_user_choice: bool


@dataclass(slots=True)
class ParsedQuestionDetail:
    question_text: str
    # MCQ-specific
    question_image_path: str | None = None
    options: list[ParsedAnswerOption] = field(default_factory=list)
    # Written-specific
    difficulty: str | None = None
    score: int | None = None
    comment: str | None = None
    answer_images: list[str] = field(default_factory=list)
    kind: str = "unknown"  # 'mcq' | 'written' | 'unknown'


@dataclass(slots=True)
class ParsedUpcomingExam:
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


@dataclass(slots=True)
class ParsedExamResultsPage:
    rows: list[ParsedExamResult] = field(default_factory=list)
    total_count: int | None = None  # from "Məlumat 1 - 9 / 50"
    page_count: int | None = None
    current_page: int = 1


# ---------------- Regexes ----------------

_DATE_DMY = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$")
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$")
# Subject cell layout: "00010 Fizika <br/> 10_24_02_574-R_00010_Fizika"
# Code prefix in second line: GROUP_RR_CCCCC_…
_SUBJECT_CODE_RE = re.compile(r"^([\w-]+_\d+)_(.+)$")
# Grade like "83 B (Çox yaxşı)"
_GRADE_RE = re.compile(r"^\s*(\d+)\s+([A-Za-zƏəÇçŞşÜüÖöĞğİıЁё]+)?\s*(?:\(([^)]+)\))?\s*$")
_INFO_RE = re.compile(r"Məlumat\s+\d+\s*-\s*\d+\s*/\s*(\d+)")


def _clean(s: str) -> str:
    return (s or "").replace("\xa0", " ").strip()


def _parse_date(raw: str) -> date | None:
    m = _DATE_DMY.match(_clean(raw))
    if not m:
        return None
    d, mth, y = (int(x) for x in m.groups())
    return date(y, mth, d)


def _parse_time(raw: str) -> time | None:
    m = _TIME.match(_clean(raw))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    s = int(m.group(3)) if m.group(3) else 0
    return time(h, mi, s)


def _parse_int(raw: str) -> int | None:
    s = _clean(raw)
    if not s.isdigit():
        return None
    return int(s)


def _split_subject_cell(cell_html: str, cell_text: str) -> tuple[str | None, str, str]:
    """Subject cell has two lines split by <br/>:
        line 1: "00010 Fizika"  (display)
        line 2: "10_24_02_574-R_00010_Fizika"  (group code prefix + name)

    Returns (subject_code, subject_name, subject_full).
    """
    full = _clean(cell_text)
    # Split on the literal newline produced by <br/> via selectolax text().
    parts = [_clean(p) for p in full.split("\n") if _clean(p)]
    display = parts[0] if parts else full
    code_line = parts[1] if len(parts) > 1 else display

    code: str | None = None
    name = display
    code_match = _SUBJECT_CODE_RE.match(code_line)
    if code_match:
        code = code_match.group(1)
    # Display "00010 Fizika" → strip the leading code-number for nicer name.
    if " " in display:
        head, tail = display.split(" ", 1)
        if head.isdigit() or re.fullmatch(r"[\w-]+", head):
            name = tail
    return code, name, display


def _split_grade_cell(raw: str) -> tuple[int | None, str | None, str | None]:
    """ '83 B (Çox yaxşı)' → (83, 'B', 'Çox yaxşı'). Empty cell → all None. """
    m = _GRADE_RE.match(_clean(raw))
    if not m:
        return None, None, None
    score = int(m.group(1))
    letter = m.group(2)
    label = m.group(3)
    return score, letter, label


# ---------------- /az/eresults parser ----------------


def parse_exam_results(html: str) -> ParsedExamResultsPage:
    tree = HTMLParser(html)
    grid = tree.css_first("#eresults-grid table")
    if grid is None:
        return ParsedExamResultsPage()

    rows: list[ParsedExamResult] = []
    for row in grid.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < 12:
            continue

        # cells layout (visible + hidden):
        # 0: №           (visible)
        # 1: hidden id   (display:none)
        # 2: hidden col2 (display:none)
        # 3: Fənn        (multi-line)
        # 4: İmtahan növü
        # 5: Keçirilmə forması
        # 6: Tarix
        # 7: hidden start (display:none)
        # 8: hidden end   (display:none)
        # 9: Giriş balı
        # 10: İmtahan balı
        # 11: Nəticə      (with <font color>)
        # 12: hidden last (display:none)

        unec_id = _parse_int(cells[1].text())
        main_type = _parse_int(cells[2].text())
        code, name, full = _split_subject_cell(cells[3].html or "", cells[3].text() or "")
        exam_type = _clean(cells[4].text())
        form = _clean(cells[5].text()) or None
        d = _parse_date(cells[6].text())
        st = _parse_time(cells[7].text())
        en = _parse_time(cells[8].text())
        entry = _parse_int(cells[9].text())
        score = _parse_int(cells[10].text())
        final, letter, label = _split_grade_cell(cells[11].text())

        rows.append(
            ParsedExamResult(
                unec_exam_id=unec_id,
                main_type=main_type,
                subject_code=code,
                subject_name=name,
                subject_full=full,
                exam_type_name=exam_type,
                form=form,
                date=d,
                start_time=st,
                end_time=en,
                entry_score=entry,
                exam_score=score,
                final_score=final,
                grade_letter=letter,
                grade_label=label,
            )
        )

    total: int | None = None
    info = tree.css_first("#eresults-grid .dataTables_info")
    if info is not None:
        m = _INFO_RE.search(info.text() or "")
        if m:
            total = int(m.group(1))

    # Current page from selected pager item, default 1.
    current_page = 1
    selected = tree.css_first("#eresults-grid .pagination li.selected a")
    if selected is not None:
        try:
            current_page = int((selected.text() or "1").strip())
        except ValueError:
            pass

    return ParsedExamResultsPage(rows=rows, total_count=total, current_page=current_page)


def parse_exam_filters(html: str) -> dict[str, list[ParsedOption]]:
    """Year / semester / exam-type options from the eresults filter form."""
    tree = HTMLParser(html)
    return {
        "edu_years": _options(tree, "select[name='eyear']"),
        "edu_semesters": _options(tree, "select[name='term']"),
        "exam_types": _options(tree, "select[name='examType']"),
    }


# ---------------- /az/elist parser ----------------


def parse_exam_questions(html: str) -> list[ParsedExamQuestion]:
    """Parse the modal returned by POST /az/subject (exam question list).

    Each question is a `<label>` carrying `data-id`, `data-eid`, `data-main`,
    plus a status cell with text "Düzgün cavab" / "Səhv cavab".
    """
    tree = HTMLParser(html)
    rows = tree.css("#modal2 tbody tr, #modal3 tbody tr")
    questions: list[ParsedExamQuestion] = []
    for row in rows:
        cells = row.css("td")
        if len(cells) < 3:
            continue
        idx_text = (cells[0].text() or "").strip()
        if not idx_text.isdigit():
            continue
        label = cells[1].css_first("label")
        if label is None:
            continue
        attrs = label.attributes
        qid_raw = (attrs.get("data-id") or "").strip()
        if not qid_raw.isdigit():
            continue
        eid_raw = (attrs.get("data-eid") or "").strip()
        main_raw = (attrs.get("data-main") or "").strip()
        text = _clean(label.text())
        status_text = _clean(cells[2].text()).lower()
        if "düzgün" in status_text or "duzgun" in status_text:
            status = "correct"
        elif "səhv" in status_text or "sehv" in status_text:
            status = "wrong"
        else:
            status = "unknown"
        questions.append(
            ParsedExamQuestion(
                index=int(idx_text),
                question_id=int(qid_raw),
                main_type=int(main_raw) if main_raw.isdigit() else None,
                exam_id=int(eid_raw) if eid_raw.isdigit() else None,
                text=text,
                status=status,
            )
        )
    return questions


_FTP_PATH_RE = re.compile(r"ftp_path=([^&\"'\s]+)")
_IMG_SRC_RE = re.compile(r'src="([^"]+)"')


def _extract_ftp_path(src: str | None) -> str | None:
    if not src:
        return None
    m = _FTP_PATH_RE.search(src)
    if m:
        # Decode common URL escapes (UNEC paths are mostly ASCII so this is safe).
        from urllib.parse import unquote
        return unquote(m.group(1))
    return None


def parse_question_detail(html: str) -> ParsedQuestionDetail:
    """Parse the modal4 returned by POST /az/subject with a question id.

    Two distinct shapes:
      • MCQ — has <ul class="answers"> with radio inputs (colored-success =
        correct, checked + colored-danger = user's choice).
      • Written/scanned — has #writtenAnswerText blocks with answer images,
        plus difficulty / score / comment fields.
    """
    tree = HTMLParser(html)
    body = tree.css_first("#modal4 .modal-body") or tree

    # ── MCQ branch ────────────────────────────────────────────────────────
    answers_ul = body.css_first("ul.answers")
    if answers_ul is not None:
        question_text = ""
        # In MCQ the question text is in the first <p> after the question heading.
        first_p = body.css_first("p")
        if first_p is not None:
            question_text = _clean(first_p.text())

        question_image_path: str | None = None
        # Image right after the question text (not inside answers list).
        for img in body.css("img"):
            src = img.attributes.get("src", "")
            # MCQ question image lives in /az/img/<id>, NOT /az/img/answer/<id>.
            if "/az/img/" in src and "/answer/" not in src:
                question_image_path = src
                break

        # First pass — gather raw class/checked flags per option. UNEC uses
        # different stylings depending on whether the user got the question
        # right; we resolve correctness/picked from the COLLECTIVE pattern of
        # checked options afterwards.
        raw_options: list[dict] = []
        for li in answers_ul.css("li"):
            text_node = li.css_first("span.text")
            if text_node is None:
                continue
            raw_html = li.html or ""
            label_part = (
                raw_html.split("</label>")[0] if "</label>" in raw_html else raw_html
            )
            text_only = re.sub(r"\s+", " ", (text_node.text() or "").strip())
            img = li.css_first(".answer img")
            raw_options.append(
                {
                    "checked": "checked" in label_part,
                    "success": "colored-success" in label_part,
                    "danger": "colored-danger" in label_part,
                    "text": text_only,
                    "image": img.attributes.get("src") if img is not None else None,
                }
            )

        checked_count = sum(1 for o in raw_options if o["checked"])

        options: list[ParsedAnswerOption] = []
        for o in raw_options:
            if checked_count <= 1:
                # User answered correctly (or no marker at all) — the lone
                # checked option is BOTH correct and the user's pick.
                is_correct = o["checked"]
                is_user_choice = o["checked"]
            else:
                # User got it wrong — UNEC marks two options as checked:
                #   correct    → has `colored-success` (possibly with danger)
                #   wrong-pick → `colored-danger` only, no success
                is_correct = o["checked"] and o["success"]
                is_user_choice = o["checked"] and not o["success"]

            options.append(
                ParsedAnswerOption(
                    text=o["text"],
                    image_path=o["image"],
                    is_correct=is_correct,
                    is_user_choice=is_user_choice,
                )
            )

        return ParsedQuestionDetail(
            question_text=question_text,
            question_image_path=question_image_path,
            options=options,
            kind="mcq",
        )

    # ── Written branch ────────────────────────────────────────────────────
    fields: dict[str, str] = {}
    for fg in body.css(".form-group"):
        label = fg.css_first("label")
        value = fg.css_first("div span")
        if label is None or value is None:
            continue
        key = (label.text() or "").strip().rstrip(":")
        val = (value.text() or "").strip()
        if key:
            fields[key] = val

    # Walk a single container and dedupe — UNEC nests #writtenAnswerText divs
    # inside .modalShowBox with duplicate IDs, so a comma-separated selector
    # would match each image twice.
    answer_images: list[str] = []
    seen: set[str] = set()
    container = body.css_first(".modalShowBox") or body
    for img in container.css("img"):
        src = img.attributes.get("src", "")
        if src and src not in seen:
            seen.add(src)
            answer_images.append(src)

    score: int | None = None
    if "Bal" in fields:
        try:
            score = int(fields["Bal"])
        except ValueError:
            score = None

    return ParsedQuestionDetail(
        question_text=fields.get("Sual", ""),
        difficulty=fields.get("Çətinlik dərəcəsi"),
        score=score,
        comment=fields.get("Qeyd"),
        answer_images=answer_images,
        kind="written",
    )


def parse_upcoming_exams(html: str) -> list[ParsedUpcomingExam]:
    tree = HTMLParser(html)
    grid = tree.css_first("#elist-grid table")
    if grid is None:
        return []

    out: list[ParsedUpcomingExam] = []
    for row in grid.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < 11:
            continue
        out.append(
            ParsedUpcomingExam(
                group_name=_clean(cells[1].text()),
                date=_parse_date(cells[2].text()),
                start_time=_parse_time(cells[3].text()),
                end_time=_parse_time(cells[4].text()),
                entry_score=_parse_int(cells[5].text()),
                username=_clean(cells[6].text()) or None,
                password=_clean(cells[7].text()) or None,
                exam_type_name=_clean(cells[8].text()),
                status=_clean(cells[9].text()) or None,
                blocked=_clean(cells[10].text()).lower()
                in {"bəli", "yes", "1", "true"},
            )
        )
    return out
