"""Document upload and processing schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import ORMModel


class DocumentJobOut(ORMModel):
    id: str
    document_id: str
    status: str
    stage: str
    attempt: int
    error_message: str | None
    details: dict | None = None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class DocumentOut(ORMModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int
    sha256: str
    storage_backend: str
    page_count: int
    status: str
    requires_ocr: bool
    extraction_error: str | None
    uploaded_by: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentOut):
    jobs: list[DocumentJobOut] = []


class DocumentListResponse(BaseModel):
    items: list[DocumentOut]
    page: int
    page_size: int
    total: int
    pages: int
