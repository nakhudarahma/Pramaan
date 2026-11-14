"""Official notices / circulars."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, new_uuid, utcnow
from app.models.enums import NoticeStatus


class Notice(Base, TimestampMixin):
    __tablename__ = "notices"
    __table_args__ = (
        CheckConstraint("status IN ('draft','published','archived')", name="ck_notices_status"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    issuer: Mapped[str | None] = mapped_column(String(200))
    issued_on: Mapped[date | None] = mapped_column(Date, index=True)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="general", index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="en")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=NoticeStatus.DRAFT.value, index=True
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    document: Mapped["Document"] = relationship(back_populates="notice")
    facts: Mapped[list["Fact"]] = relationship(back_populates="notice")
