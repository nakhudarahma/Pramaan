"""String enums used across the ledger.

Plain string columns plus check constraints are used (rather than a native DB
enum) so that the same models run on SQLite in tests and PostgreSQL in
production.
"""
from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    STUDENT = "student"
    ADMIN = "admin"


class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class NoticeStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class FactStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    DISPUTED = "disputed"
    REJECTED = "rejected"


class FactCategory(StrEnum):
    FEE = "fee"
    DATE = "date"
    ELIGIBILITY = "eligibility"
    POLICY = "policy"
    SCHEDULE = "schedule"
    DOCUMENT = "document"
    ATTENDANCE = "attendance"
    SCHOLARSHIP = "scholarship"
    HOLIDAY = "holiday"
    OTHER = "other"


class ConflictKind(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    SCOPE_OVERLAP = "scope_overlap"
    SUPERSEDES = "supersedes"
    DISPUTED = "disputed"


class ConflictStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class SourcePrecision(StrEnum):
    EXACT = "exact"
    PAGE = "page"


class UnansweredStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class CalendarEventStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


FACT_STATUSES = tuple(s.value for s in FactStatus)
FACT_CATEGORIES = tuple(c.value for c in FactCategory)
CONFLICT_KINDS = tuple(k.value for k in ConflictKind)
