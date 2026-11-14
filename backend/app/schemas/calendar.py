"""Calendar schemas."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from app.schemas.fact import Citation


class CalendarEventOut(BaseModel):
    id: str
    fact_id: str
    title: str
    description: str | None = None
    start_date: date
    end_date: date | None = None
    all_day: bool = True
    timezone: str
    status: str
    citation: Citation | None = None


class CalendarResponse(BaseModel):
    timezone: str
    generated_at: datetime
    events: list[CalendarEventOut] = []
