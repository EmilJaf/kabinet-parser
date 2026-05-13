"""Azerbaijan workday/holiday helpers.

Powered by the `holidays` package (knows AZ public holidays, including
movable Islamic dates and the move-to-next-workday rule when a holiday
falls on a weekend). Holiday name translations live in src/unec/locales/
under `calendar.holiday`; the AZ catalog also normalises the source
labels (typos, case, full official names).
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays

from ..i18n import get_map, t

_OBSERVED_SUFFIX = " (müşahidə olunur)"
_REST_DAY_PREFIX = "İstirahət günü"


def _translate_one(name: str, lang: str | None) -> str:
    """Translate a single holiday label to `lang`, handling the special
    "moved holiday" suffixes the `holidays` library tacks onto AZ labels."""
    name = name.strip()
    if name.startswith(_REST_DAY_PREFIX):
        return t("calendar.rest_day_replaced", lang)
    observed = name.endswith(_OBSERVED_SUFFIX)
    if observed:
        name = name[: -len(_OBSERVED_SUFFIX)].strip()
    catalog = get_map("calendar.holiday", lang)
    base = catalog.get(name, name)
    if observed:
        return base + t("calendar.moved_holiday_suffix", lang)
    return base


@lru_cache(maxsize=8)
def _calendar_for(year: int) -> holidays.HolidayBase:
    """Cached AZ holiday calendar for a given year. Cheap to recompute,
    but lru_cache keeps it instant during the same process lifetime."""
    return holidays.country_holidays("AZ", years=year, language="az")


def holiday_name_for(d: date, lang: str | None = None) -> str | None:
    """Localised name of the holiday on `d`, or None if it's not a holiday.

    `lang` defaults to AZ. Multiple holidays on the same day come back
    comma-separated and each is translated independently.
    """
    cal = _calendar_for(d.year)
    raw = cal.get(d)
    if raw is None:
        return None
    parts = [p.strip() for p in str(raw).split(",")]
    return ", ".join(_translate_one(p, lang) for p in parts)


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
