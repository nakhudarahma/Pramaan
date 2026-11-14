"""Uploaded documents and processing jobs."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, new_uuid, utcnow
from app.models.enums import DocumentStatus, JobStatus


class Document(Base, TimestampMixin):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','processing','processed','needs_review','failed')",
            name="ck_documents_status",
        ),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    original_filename: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="application/pdf")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(600), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=DocumentStatus.UPLOADED.value, index=True
    )
    requires_ocr: Mapped[bool] = mapped_column(default=False, nullable=False)
    extraction_error: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[str | None] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    notice: Mapped["Notice | None"] = relationship(back_populates="document", uselist=False)
    jobs: Mapped[list["DocumentProcessingJob"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentProcessingJob.created_at"
    )


class DocumentProcessingJob(Base):
    __tablename__ = "document_processing_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','needs_review')",
            name="ck_jobs_status",
        ),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    document_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=JobStatus.QUEUED.value, index=True
    )
    stage: Mapped[str] = mapped_column(String(60), nullable=False, default="queued")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    document: Mapped[Document] = relationship(back_populates="jobs")
