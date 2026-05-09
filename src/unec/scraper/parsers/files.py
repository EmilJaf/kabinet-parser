"""Parser for UNEC's /az/files page (Tədris materialları — teaching materials).

The page has cascading dropdowns: year → semester → subject → teacher → themes.
Each <option> set is populated only when its parent is selected, so we re-parse
the same HTML for whichever level happens to be present.

Theme rows have green-dot indicators for which file types are available
(Mühazirə = lecture, Təqdimat = presentation, Test, Seminar, Digər = other).
"""
from __future__ import annotations

from dataclasses import dataclass

from selectolax.parser import HTMLParser

# Order of file-type columns in the themes table, mapped to the
# UNEC API selectedFileType strings.
FILE_TYPE_ORDER = ("lection", "presentation", "test", "seminar", "other")


@dataclass(slots=True)
class FilesOption:
    value: str
    label: str
    selected: bool = False


@dataclass(slots=True)
class FilesSubject:
    value: str          # filter param (e.g. "1175924")
    subj_id: str        # data-subject — needed for further requests (e.g. "1021478")
    label: str
    selected: bool = False


@dataclass(slots=True)
class FilesTeacher:
    value: str          # SHA-256 hash UNEC uses as identifier
    name: str
    sylabus_path: str | None = None  # /ASEU/...docx, downloadable directly
    selected: bool = False


@dataclass(slots=True)
class FilesTheme:
    theme_id: str
    subj_id: str
    topic: str
    has_lecture: bool
    has_presentation: bool
    has_test: bool
    has_seminar: bool
    has_other: bool


@dataclass(slots=True)
class ParsedFilesPage:
    years: list[FilesOption]
    semesters: list[FilesOption]
    subjects: list[FilesSubject]
    teachers: list[FilesTeacher]
    themes: list[FilesTheme]


def _parse_options(tree: HTMLParser, select_id: str) -> list[FilesOption]:
    sel = tree.css_first(f"select#{select_id}")
    if sel is None:
        return []
    out: list[FilesOption] = []
    for opt in sel.css("option"):
        value = (opt.attributes.get("value") or "").strip()
        if not value:
            continue  # skip the placeholder "--Select--"
        out.append(
            FilesOption(
                value=value,
                label=(opt.text() or "").strip(),
                selected="selected" in (opt.attributes.get("selected") or ""),
            )
        )
    return out


def _parse_subjects(tree: HTMLParser) -> list[FilesSubject]:
    sel = tree.css_first("select#subject")
    if sel is None:
        return []
    out: list[FilesSubject] = []
    for opt in sel.css("option"):
        value = (opt.attributes.get("value") or "").strip()
        if not value:
            continue
        subj_id = (opt.attributes.get("data-subject") or "").strip()
        out.append(
            FilesSubject(
                value=value,
                subj_id=subj_id,
                label=(opt.text() or "").strip(),
                selected="selected" in (opt.attributes.get("selected") or ""),
            )
        )
    return out


def _parse_teachers(tree: HTMLParser) -> list[FilesTeacher]:
    sel = tree.css_first("select#teacherList")
    if sel is None:
        return []
    out: list[FilesTeacher] = []
    for opt in sel.css("option"):
        value = (opt.attributes.get("value") or "").strip()
        if not value:
            continue
        sylabus = (opt.attributes.get("data-sylabus") or "").strip() or None
        out.append(
            FilesTeacher(
                value=value,
                name=(opt.text() or "").strip(),
                sylabus_path=sylabus,
                selected="selected" in (opt.attributes.get("selected") or ""),
            )
        )
    return out


def _parse_themes(tree: HTMLParser) -> list[FilesTheme]:
    grid = tree.css_first("#files-grid")
    if grid is None:
        return []
    out: list[FilesTheme] = []
    for row in grid.css("tbody tr"):
        cells = row.css("td")
        if len(cells) < 4:
            continue  # placeholder "Nəticə yoxdur" row
        # Layout per request_url 3:
        # td0=№, td1(hidden)=themeId, td2(hidden)=subjId, td3=topic,
        # td4..td8 = 5 file-type indicators (Mühazirə, Təqdimat, Test,
        # Seminar, Digər) — green dot if present, empty otherwise.
        try:
            theme_id = (cells[1].text() or "").strip()
            subj_id = (cells[2].text() or "").strip()
            topic = (cells[3].text() or "").strip()
        except IndexError:
            continue
        if not theme_id:
            continue

        flags: list[bool] = []
        for i in range(4, 9):
            if i >= len(cells):
                flags.append(False)
                continue
            flags.append(bool(cells[i].css_first("span.green")))

        out.append(
            FilesTheme(
                theme_id=theme_id,
                subj_id=subj_id,
                topic=topic,
                has_lecture=flags[0],
                has_presentation=flags[1],
                has_test=flags[2],
                has_seminar=flags[3],
                has_other=flags[4],
            )
        )
    return out


def parse_files_page(html: str) -> ParsedFilesPage:
    tree = HTMLParser(html)
    return ParsedFilesPage(
        years=_parse_options(tree, "eduYearFiles"),
        semesters=_parse_options(tree, "eduSemesterFiles"),
        subjects=_parse_subjects(tree),
        teachers=_parse_teachers(tree),
        themes=_parse_themes(tree),
    )
