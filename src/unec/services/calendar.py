"""Azerbaijan workday/holiday helpers.

Powered by the `holidays` package (knows AZ public holidays, including
movable Islamic dates and the move-to-next-workday rule when a holiday
falls on a weekend). Names are translated to Russian for the SPA.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays

# Translate known Azerbaijani holiday names to Russian. Anything not in
# the map falls back to the source label. Suffixes like " (müşahidə olunur)"
# (a moved-day marker) are stripped before lookup, then appended back as
# "(перенос)" so the displayed text stays informative.
_RU_NAMES: dict[str, str] = {
    "Yeni il bayramı": "Новый год",
    "Ümumxalq hüzn günü": "Всенародный день скорби",
    "Bələdiyyə seçkiləri": "Муниципальные выборы",
    "Qadınlar günü": "8 марта",
    "Novruz bayramı": "Новруз байрамы",
    "Ramazan bayrami": "Праздник Рамазан",
    "Qurban bayrami": "Праздник Курбан",
    "Faşizm üzərində qələbə günü": "День Победы над фашизмом",
    "Müstəqillik Günü": "День независимости",
    "Müstəqillik günü": "День независимости",
    "Respublika günü": "День Республики",
    "Azərbaycan xalqının milli qurtuluş günü": "День национального спасения",
    "Azərbaycan Respublikasının Silahlı Qüvvələri günü": "День Вооружённых сил",
    "Zəfər Günü": "День Победы (Карабах)",
    "Azərbaycan Respublikasının Dövlət bayrağı günü": "День государственного флага",
    "Konstitusiya günü": "День Конституции",
    "Milli dirçəliş günü": "День национального возрождения",
    "Dünya azərbaycanlıların həmrəyliyi günü": "День солидарности азербайджанцев",
    "Azərbaycanlıların soyqırımı günü": "День геноцида азербайджанцев",
}

_OBSERVED_SUFFIX = " (müşahidə olunur)"
_REST_DAY_PREFIX = "İstirahət günü"


def _translate_one(name: str) -> str:
    name = name.strip()
    # "Day off (replaced by ...)" — synthetic moved holiday.
    if name.startswith(_REST_DAY_PREFIX):
        return "Выходной (перенос)"
    observed = name.endswith(_OBSERVED_SUFFIX)
    if observed:
        name = name[: -len(_OBSERVED_SUFFIX)].strip()
    ru = _RU_NAMES.get(name, name)
    return f"{ru} (перенос)" if observed else ru


@lru_cache(maxsize=8)
def _calendar_for(year: int) -> holidays.HolidayBase:
    """Cached AZ holiday calendar for a given year. Cheap to recompute,
    but lru_cache keeps it instant during the same process lifetime."""
    return holidays.country_holidays("AZ", years=year, language="az")


def holiday_name_for(d: date) -> str | None:
    """Russian name of the holiday on `d`, or None if it's not a holiday."""
    cal = _calendar_for(d.year)
    raw = cal.get(d)
    if raw is None:
        return None
    # Multiple holidays on the same day come back comma-separated.
    parts = [p.strip() for p in str(raw).split(",")]
    return ", ".join(_translate_one(p) for p in parts)


def is_holiday(d: date) -> bool:
    return d in _calendar_for(d.year)


def is_weekend(d: date) -> bool:
    # Mon=0..Sun=6 — AZ standard work week is Mon-Fri.
    return d.weekday() >= 5


def is_workday(d: date) -> bool:
    return not is_weekend(d) and not is_holiday(d)


def next_workday(d: date) -> date:
    """First workday strictly after `d`."""
    cur = d + timedelta(days=1)
    while not is_workday(cur):
        cur += timedelta(days=1)
    return cur
