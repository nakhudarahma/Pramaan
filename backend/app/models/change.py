"""Change events used by the "What changed for you" feed."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GUID, new_uuid, utcnow


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    old_fact_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    new_fact_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notice_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("notices.id", ondelete="SET NULL"), nullable=True
    )
    fact_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    diff_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effective_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
