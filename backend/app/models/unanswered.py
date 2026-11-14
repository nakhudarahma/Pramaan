"""Student questions that could not be answered from verified records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GUID, TimestampMixin, new_uuid, utcnow


class UnansweredQuestion(Base, TimestampMixin):
    __tablename__ = "unanswered_questions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open','resolved','dismissed')", name="ck_unanswered_status"
        ),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_question: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    course: Mapped[str | None] = mapped_column(String(120))
    semester: Mapped[int | None] = mapped_column(Integer)
    academic_year: Mapped[str | None] = mapped_column(String(20))
    intent_guess: Mapped[str | None] = mapped_column(String(60))
    topic_guess: Mapped[str | None] = mapped_column(String(160))
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_asked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
