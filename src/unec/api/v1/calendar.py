from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...db.models import User
from ...services import calendar as cal_service
from ..deps import get_current_user

router = APIRouter(prefix="/calendar", tags=["calendar"])


class CalendarTodayOut(BaseModel):
    date: date
    is_workday: bool
    is_weekend: bool
    is_holiday: bool
    holiday_name: str | None = None
    next_workday: date


@router.get("/today", response_model=CalendarTodayOut)
async def today(
    _user: User = Depends(get_current_user),
) -> CalendarTodayOut:
    # Local container TZ is Asia/Baku (set in compose), so datetime.now()
    # gives us the wall-clock date the user actually sees.
    today_local = datetime.now().date()
    return CalendarTodayOut(
        date=today_local,
        is_workday=cal_service.is_workday(today_local),
        is_weekend=cal_service.is_weekend(today_local),
        is_holiday=cal_service.is_holiday(today_local),
        holiday_name=cal_service.holiday_name_for(today_local),
        next_workday=cal_service.next_workday(today_local),
    )
