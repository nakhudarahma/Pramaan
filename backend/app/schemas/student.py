"""Student-facing dashboard, deadlines and change-feed schemas."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, model_validator

from app.schemas.fact import Citation, FactScope


class StudentContext(BaseModel):
    college: str | None = None
    course: str | None = None
    department: str | None = None
    semester: int | None = None
    section: str | None = None
    academic_year: str | None = None
    batch: str | None = None
    student_group: str | None = None
    language: str = "en"


class DeadlineOut(BaseModel):
    fact_id: str
    fact_key: str
    title: str | None
    value_text: str
    date: dt.date
    days_remaining: int | None = None
    scope: FactScope
    category: str
    citation: Citation | None = None

    # Frontend fields:
    id: str | None = None
    daysLeft: int | None = None
    course: str | None = None
    semester: int | None = None
    formatted_date: str | None = None

    @model_validator(mode="after")
    def sync_deadline_fields(self) -> "DeadlineOut":
        if not self.id:
            self.id = self.fact_id
        if self.daysLeft is None:
            self.daysLeft = self.days_remaining if self.days_remaining is not None else 0
        if self.course is None and self.scope:
            self.course = self.scope.course
        if self.semester is None and self.scope:
            self.semester = self.scope.semester
        if self.formatted_date is None and self.date:
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            self.formatted_date = f"{self.date.day} {months[self.date.month - 1]} {self.date.year}"
        return self


class FactSourceResponse(BaseModel):
    fact_id: str
    fact_key: str
    value_text: str
    status: str
    effective_from: dt.date | None = None
    effective_to: dt.date | None = None
    notice_id: str
    notice_title: str | None = None
    issuer: str | None = None
    issued_on: dt.date | None = None
    document_id: str
    document_name: str | None = None
    page_number: int | None = None
    source_text: str | None = None
    source_bbox: list[float] | None = None
    source_precision: str = "page"
    file_url: str | None = None


class ChangeOut(BaseModel):
    id: str
    fact_key: str
    title: str | None
    old_value: str | None
    new_value: str | None
    effective_date: dt.date | None
    changed_at: dt.datetime
    notice_id: str | None = None
    notice_title: str | None = None
    page_number: int | None = None
    source_text: str | None = None
    citation: Citation | None = None

    # Frontend fields:
    label: str | None = None
    oldValue: str | None = None
    newValue: str | None = None
    noticeDate: str | None = None
    factId: str | None = None
    noticeTitle: str | None = None
    page: int = 1
    course: str | None = None
    semester: int | None = None
    approved: bool = True

    @model_validator(mode="after")
    def sync_change_fields(self) -> "ChangeOut":
        if not self.label:
            self.label = self.title or self.fact_key
        if self.oldValue is None:
            self.oldValue = self.old_value or ""
        if self.newValue is None:
            self.newValue = self.new_value or ""
        if not self.factId:
            self.factId = self.id
        if not self.noticeTitle:
            self.noticeTitle = self.notice_title or "Notice"
        if not self.page:
            self.page = self.page_number or 1
        if not self.noticeDate:
            d = self.effective_date or (self.changed_at.date() if self.changed_at else None)
            if d:
                months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                self.noticeDate = f"{d.day} {months[d.month - 1]} {d.year}"
            else:
                self.noticeDate = "12 Nov 2026"
        return self


class DashboardResponse(BaseModel):
    context: StudentContext
    deadlines: list[DeadlineOut] = []
    changes: list[ChangeOut] = []
    notices: list[dict] = []
    unresolved_disputes: int = 0
    generated_at: dt.datetime
