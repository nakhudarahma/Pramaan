"""Student question-answering schemas."""
from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.fact import Citation


class AskContext(BaseModel):
    college: str | None = Field(default=None, max_length=200)
    course: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    semester: int | None = Field(default=None, ge=1, le=12)
    section: str | None = Field(default=None, max_length=40)
    academic_year: str | None = Field(default=None, max_length=20)
    batch: str | None = Field(default=None, max_length=40)
    student_group: str | None = Field(default=None, max_length=80)
    language: str = Field(default="en", max_length=20)


class AskRequest(AskContext):
    question: str = Field(min_length=3, max_length=1000)


AnswerState = Literal[
    "verified",
    "static_grounded",
    "disputed",
    "outdated",
    "unavailable",
    "clarification",
    "error",
]


class ValidityInfo(BaseModel):
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None
    is_current: bool = True
    label: str | None = None


class SupersessionInfo(BaseModel):
    replaces_fact_id: str | None = None
    replaces_value_text: str | None = None
    replaces_notice_title: str | None = None
    replaces_issued_on: dt.date | None = None


class AnswerResponse(BaseModel):
    answer: str
    state: AnswerState
    verified: bool
    intent: str
    topic: str | None = None
    fact_ids: list[str] = []
    citations: list[Citation] = []
    validity: ValidityInfo | None = None
    supersession: SupersessionInfo | None = None
    clarification: str | None = None
    office_contact: str | None = None
    unanswered_logged: bool = False
    generated_by: str = "code"
    latency_ms: float | None = None

    # Frontend compatibility fields:
    text: str | None = None
    appliesTo: str | None = None
    validUntil: str | None = None
    replaces: str | None = None
    sources: list[dict] = []
    contact: str | None = None
    note: str | None = None
    issuedBy: str | None = None
    noticeNumber: str | None = None
    noticeDate: str | None = None
    category: str | None = None

    @model_validator(mode="after")
    def sync_frontend_fields(self) -> "AnswerResponse":
        if self.text is None:
            self.text = self.answer
        if self.contact is None:
            self.contact = self.office_contact
        if not self.sources and self.citations:
            self.sources = [
                {
                    "factId": c.fact_id or "f0",
                    "notice": c.notice_title or "Notice",
                    "page": c.page_number or 1,
                }
                for c in self.citations
            ]
        if self.validUntil is None:
            if self.validity and self.validity.label:
                self.validUntil = self.validity.label
            elif self.validity and self.validity.effective_to:
                months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                d = self.validity.effective_to
                self.validUntil = f"{d.day} {months[d.month - 1]} {d.year}"
            else:
                self.validUntil = "—"
        if self.replaces is None and self.supersession:
            self.replaces = self.supersession.replaces_value_text
        return self
