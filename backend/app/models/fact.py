"""The verified fact ledger.

Facts are immutable in spirit: every edit creates a ``FactVersion`` snapshot and
old facts are never deleted.  ``previous_fact_id`` / ``superseded_by_id`` form the
version chain.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, new_uuid, utcnow
from app.models.enums import ConflictStatus, FactStatus, SourcePrecision


class Fact(Base, TimestampMixin):
    __tablename__ = "extracted_facts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('candidate','active','superseded','expired','disputed','rejected')",
            name="ck_facts_status",
        ),
        CheckConstraint(
            "semester IS NULL OR (semester >= 1 AND semester <= 12)", name="ck_facts_semester"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_facts_effective_window",
        ),
        Index("ix_facts_key_status", "fact_key", "status"),
        Index("ix_facts_scope", "course", "semester", "academic_year"),
        Index("ix_facts_value_date", "value_date"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    fact_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="other", index=True)
    title: Mapped[str | None] = mapped_column(String(300))

    value_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    value_text: Mapped[str] = mapped_column(Text, nullable=False)
    value_number: Mapped[float | None] = mapped_column(Numeric(16, 2))
    value_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(8))
    unit: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text)

    # Scope. NULL / "ALL" means unrestricted along that dimension.
    college: Mapped[str | None] = mapped_column(String(200), index=True)
    course: Mapped[str | None] = mapped_column(String(120), index=True)
    department: Mapped[str | None] = mapped_column(String(120))
    semester: Mapped[int | None] = mapped_column(Integer)
    academic_year: Mapped[str | None] = mapped_column(String(20), index=True)
    batch: Mapped[str | None] = mapped_column(String(40))
    student_group: Mapped[str | None] = mapped_column(String(80))

    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)

    # Provenance
    notice_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("notices.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_bbox: Mapped[list | None] = mapped_column(JSON)
    source_precision: Mapped[str] = mapped_column(
        String(20), nullable=False, default=SourcePrecision.PAGE.value
    )

    extraction_confidence: Mapped[float | None] = mapped_column(Float)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False, default="gemini")

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FactStatus.CANDIDATE.value, index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    previous_fact_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="SET NULL"), nullable=True
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="SET NULL"), nullable=True
    )
    # Set only while ACTIVE. A unique constraint makes it impossible to have two
    # active facts for exactly the same key+scope, even under concurrent requests.
    active_scope_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)

    approved_by: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)

    notice: Mapped["Notice"] = relationship(back_populates="facts")
    versions: Mapped[list["FactVersion"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan", order_by="FactVersion.version_number"
    )
    sources: Mapped[list["FactSource"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan", order_by="FactSource.created_at"
    )


class FactVersion(Base):
    __tablename__ = "fact_versions"
    __table_args__ = (
        UniqueConstraint("fact_id", "version_number", name="uq_fact_version"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    fact_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_type: Mapped[str] = mapped_column(String(40), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changed_by: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    fact: Mapped[Fact] = relationship(back_populates="versions")


class FactSource(Base):
    """Additional source documents supporting an existing fact (duplicates)."""

    __tablename__ = "fact_sources"
    __table_args__ = (
        UniqueConstraint("fact_id", "notice_id", "page_number", name="uq_fact_source"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    fact_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notice_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("notices.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    source_text: Mapped[str | None] = mapped_column(Text)
    source_bbox: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    fact: Mapped[Fact] = relationship(back_populates="sources")


class FactConflict(Base, TimestampMixin):
    __tablename__ = "fact_conflicts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('new','duplicate','scope_overlap','supersedes','disputed')",
            name="ck_conflicts_kind",
        ),
        CheckConstraint(
            "status IN ('pending','resolved','dismissed')", name="ck_conflicts_status"
        ),
        Index("ix_conflicts_status_kind", "status", "kind"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConflictStatus.PENDING.value, index=True
    )
    candidate_fact_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    existing_fact_id: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("extracted_facts.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(String(40))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
