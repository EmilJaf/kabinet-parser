from datetime import date
from pathlib import Path

from unec.scraper.parsers.evaluation import (
    parse_filter_options,
    parse_grades_popup,
    parse_selected_filters,
    parse_semester_options,
    parse_subject_list,
)

FIX = Path(__file__).parent / "fixtures"


def test_parse_subject_list_returns_six():
    subjects = parse_subject_list((FIX / "grades_subjects_2025-26-II.html").read_text())
    assert len(subjects) == 6
    first = subjects[0]
    assert first.unec_subject_id == 1175887
    assert first.name == "Differensial tənliklər"
    assert first.credits == 3
    assert first.group_name == "10_24_02_574-R_00230_Diferensial tənliklər"
    assert first.edu_form_id == 450


def test_parse_subject_list_empty_state():
    subjects = parse_subject_list((FIX / "grades_subjects_empty.html").read_text())
    assert subjects == []


def test_parse_selected_filters():
    filters = parse_selected_filters((FIX / "grades_subjects_2025-26-II.html").read_text())
    assert filters == {
        "edu_year_id": 1000048,
        "edu_semester_id": 1000111,
        "lesson_type_id": 4100,
    }


def test_parse_filter_options():
    options = parse_filter_options((FIX / "grades_subjects_2025-26-II.html").read_text())
    assert {opt.id for opt in options["edu_years"]} == {1000048, 1000044}
    assert {opt.id for opt in options["edu_semesters"]} == {1000109, 1000111, 1000112}
    assert {opt.id for opt in options["lesson_types"]} == {4100, 4101, 4102, 4103, 4104}
    selected_year = next(opt for opt in options["edu_years"] if opt.selected)
    assert selected_year.id == 1000048
    selected_lesson = next(opt for opt in options["lesson_types"] if opt.selected)
    assert selected_lesson.id == 4100


def test_parse_semester_options_xhr():
    options = parse_semester_options((FIX / "grades_semester_options.html").read_text())
    assert {opt.id: opt.label for opt in options} == {
        1000109: "I semestr",
        1000111: "II semestr",
        1000112: "Yay semestri",
    }


def test_parse_grades_popup_marks():
    popup = parse_grades_popup((FIX / "grades_popup_vbs.html").read_text())
    assert len(popup.marks) == 12

    most_recent = popup.marks[0]
    assert most_recent.date == date(2026, 5, 6)
    assert most_recent.mark_code == "q/b"
    assert "DCL" in most_recent.topic

    # Row 7 had a blank Qiymət cell — should normalise to None.
    blank_mark = popup.marks[6]
    assert blank_mark.date == date(2026, 3, 25)
    assert blank_mark.mark_code is None


def test_parse_grades_popup_final_eval_flattens_multilevel_header():
    popup = parse_grades_popup((FIX / "grades_popup_vbs.html").read_text())
    assert popup.final_eval is not None
    fe = popup.final_eval
    assert fe["Davamiyyət"] == "0"
    assert fe["Kollokvium 1"] == "15"
    assert fe["Kollokvium 2"] == ""
    assert fe["Kollokvium orta balı"] == "15"
    assert fe["Seminarın orta balı"] == "15"
    assert fe["Cari qiymətləndirmə"] == "30"
    assert fe["Mühazirə balı"] == ""
    assert fe["Qaib faizi"] == "13.33"


def test_parse_grades_popup_forma():
    popup = parse_grades_popup((FIX / "grades_popup_vbs.html").read_text())
    assert popup.scheme is not None
    assert popup.scheme["Seminar"] == "20"
    assert popup.scheme["Ara imtahanına verilən maksimal bal"] == "30"
    assert popup.scheme["İmtahan maksimum bal"] == "50"


def test_parse_grades_popup_empty_tabs_are_none():
    popup = parse_grades_popup((FIX / "grades_popup_vbs.html").read_text())
    assert popup.course_work is None
    assert popup.independent_work is None
    # writing has a row of empty cells — should be parsed (the row exists).
    assert popup.writing is not None
