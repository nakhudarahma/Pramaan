"""Admin dashboard, unanswered queue and audit schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class UnansweredOut(ORMModel):
    id: str
    question: str
    normalized_question: str
    course: str | None
    semester: int | None
    academic_year: str | None
    intent_guess: str | None
    topic_guess: str | None
    occurrence_count: int
    status: str
    resolution_note: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    last_asked_at: datetime
    created_at: datetime
    updated_at: datetime


class UnansweredResolveRequest(BaseModel):
    status: str = Field(default="resolved", pattern="^(resolved|dismissed)$")
    note: str | None = Field(default=None, max_length=2000)


class AuditLogOut(ORMModel):
    id: str
    actor_id: str | None
    actor_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    details: dict | None
    request_id: str | None
    created_at: datetime


class AdminDashboardResponse(BaseModel):
    documents_total: int
    documents_failed: int
    documents_needs_review: int
    facts_candidate: int
    facts_active: int
    facts_disputed: int
    facts_rejected: int
    facts_superseded: int
    conflicts_pending: int
    unanswered_open: int
    notices_published: int
    generated_at: datetime


class ResolveResponse(BaseModel):
    message: str
    fact_id: str | None = None
    status: str | None = None
    conflict_id: str | None = None


class PublishResponse(BaseModel):
    message: str
    notice_id: str
    published_at: datetime
    facts_published: int
