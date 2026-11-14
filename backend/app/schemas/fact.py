"""Fact ledger schemas shared by admin and student APIs."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class FactScope(BaseModel):
    college: str | None = None
    course: str | None = None
    department: str | None = None
    semester: int | None = None
    academic_year: str | None = None
    batch: str | None = None
    student_group: str | None = None


class FactSourceOut(BaseModel):
    document_id: str
    document_name: str | None = None
    notice_id: str
    notice_title: str | None = None
    page_number: int | None = None
    source_text: str | None = None
    source_bbox: list[float] | None = None
    source_precision: str = "page"
    file_url: str | None = None


class Citation(BaseModel):
    fact_id: str | None = None
    version: int | None = None
    status: str | None = None
    document_id: str | None = None
    document_name: str | None = None
    notice_id: str | None = None
    notice_title: str | None = None
    page_number: int | None = None
    source_text: str | None = None
    source_bbox: list[float] | None = None
    source_precision: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    approved_at: datetime | None = None


class FactOut(ORMModel):
    id: str
    fact_key: str
    category: str
    title: str | None
    value_json: dict
    value_text: str
    value_number: float | None
    value_date: date | None
    currency: str | None
    unit: str | None
    description: str | None
    college: str | None
    course: str | None
    department: str | None
    semester: int | None
    academic_year: str | None
    batch: str | None
    student_group: str | None
    effective_from: date | None
    effective_to: date | None
    notice_id: str
    document_id: str
    page_number: int | None
    source_text: str | None
    source_bbox: list | None = None
    source_precision: str
    extraction_confidence: float | None
    extraction_method: str
    status: str
    rejection_reason: str | None
    version: int
    previous_fact_id: str | None
    superseded_by_id: str | None
    approved_by: str | None
    approved_at: datetime | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FactVersionOut(ORMModel):
    id: str
    fact_id: str
    version_number: int
    change_type: str
    snapshot: dict
    changed_by: str | None
    note: str | None
    created_at: datetime


class FactDetail(FactOut):
    versions: list[FactVersionOut] = []
    sources: list[FactSourceOut] = []
    notice_title: str | None = None
    document_name: str | None = None
    conflict_ids: list[str] = []


class FactEditRequest(BaseModel):
    fact_key: str | None = Field(default=None, max_length=160)
    category: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=300)
    value_json: dict | None = None
    value_text: str | None = None
    value_number: float | None = None
    value_date: date | None = None
    currency: str | None = Field(default=None, max_length=8)
    unit: str | None = Field(default=None, max_length=40)
    description: str | None = None
    college: str | None = None
    course: str | None = None
    department: str | None = None
    semester: int | None = Field(default=None, ge=1, le=12)
    academic_year: str | None = None
    batch: str | None = None
    student_group: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class ApproveFactRequest(BaseModel):
    publish_notice: bool = False
    note: str | None = Field(default=None, max_length=2000)


class RejectFactRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)


class ConflictOut(ORMModel):
    id: str
    kind: str
    status: str
    candidate_fact_id: str
    existing_fact_id: str | None
    reason: str | None
    resolution: str | None
    resolution_note: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    candidate_value: str | None = None
    existing_value: str | None = None
    candidate_scope: dict | None = None
    existing_scope: dict | None = None
    candidate_notice_title: str | None = None
    existing_notice_title: str | None = None


class ConflictResolveRequest(BaseModel):
    resolution: str = Field(description="approve_new | keep_existing | scope_difference | dismiss")
    note: str | None = Field(default=None, max_length=2000)
