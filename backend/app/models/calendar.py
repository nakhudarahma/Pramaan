"""Materialised calendar events derived from approved date facts."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GUID, TimestampMixin, new_uuid


class CalendarEvent(Base, TimestampMixin):
    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint("status IN ('confirmed','cancelled')", name="ck_calendar_status"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    fact_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    notice_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("notices.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(400), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    end_date: Mapped[date | None] = mapped_column(Date)
    all_day: Mapped[bool] = mapped_column(default=True, nullable=False)
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed", index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime)
