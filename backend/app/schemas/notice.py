"""Notice library schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, model_validator

from app.schemas.document import DocumentOut, DocumentJobOut
from app.schemas.fact import FactOut
from app.schemas.common import ORMModel


class NoticeOut(ORMModel):
    id: str
    document_id: str
    title: str
    issuer: str | None
    issued_on: dt.date | None
    category: str
    summary: str | None
    language: str
    status: str
    published_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime
    page_count: int | None = None
    fact_count: int | None = None

    # Frontend compatibility fields:
    date: str | None = None
    page: int = 1
    noticeNumber: str | None = None
    replaces: str | None = None
    body: str | None = None
    highlightedSentence: str | None = None

    @model_validator(mode="after")
    def sync_notice_fields(self) -> "NoticeOut":
        if not self.date and self.issued_on:
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            self.date = f"{self.issued_on.day} {months[self.issued_on.month - 1]} {self.issued_on.year}"
        if not self.noticeNumber:
            clean_id = self.id.replace("-", "")[:3].upper()
            self.noticeNumber = f"PRM/2026/{clean_id}"
        if not self.body:
            self.body = self.summary or self.title
        if not self.highlightedSentence:
            self.highlightedSentence = self.summary or self.title
        return self


class NoticeDetail(NoticeOut):
    document: DocumentOut | None = None
    facts: list[FactOut] = []


class NoticeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=500)
    issuer: str | None = Field(default=None, max_length=200)
    issued_on: dt.date | None = None
    category: str | None = Field(default=None, max_length=60)
    summary: str | None = Field(default=None, max_length=5000)
    language: str | None = Field(default=None, max_length=20)


class UploadResult(BaseModel):
    document: DocumentOut
    notice: NoticeOut
    job: DocumentJobOut | None = None
    extracted_fact_count: int = 0
    requires_manual_review: bool = False
    message: str
