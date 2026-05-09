from datetime import date, time
from enum import Enum

from pydantic import BaseModel


class WeekParity(str, Enum):
    NORMAL = "normal"
    UPPER = "upper"
    LOWER = "lower"


WEEK_PARITY_AZ = {
    "Normal Həftə": WeekParity.NORMAL,
    "Üst həftə": WeekParity.UPPER,
    "Alt həftə": WeekParity.LOWER,
}


class DayOfWeek(int, Enum):
    MON = 1
    TUE = 2
    WED = 3
    THU = 4
    FRI = 5
    SAT = 6
    SUN = 7


class Lesson(BaseModel):
    day: DayOfWeek
    start: time
    end: time
    subject: str
    subject_code: str | None = None
    lesson_type: str | None = None
    room: str | None = None
    building: str | None = None
    teacher: str | None = None
    week_parity: WeekParity = WeekParity.NORMAL
    period_start: date | None = None
    period_end: date | None = None


class Profile(BaseModel):
    full_name: str
    specialty: str | None = None
    group: str | None = None
    admission_year: int | None = None
    education_status: str | None = None
