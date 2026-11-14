"""Declarative base, portable UUID type and timestamp helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC timestamp.

    Stored consistently as UTC.  SQLite has no timezone support, so using naive
    UTC everywhere avoids ambiguous comparisons between stored and new values.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class GUID(TypeDecorator):
    """Store UUIDs as 36-character strings on every supported database.

    PostgreSQL could use a native UUID type, but a portable representation keeps
    SQLite tests and Supabase deployments byte-for-byte compatible.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return str(value)
        try:
            return str(uuid.UUID(str(value)))
        except ValueError as exc:  # pragma: no cover - defensive
            raise ValueError(f"Invalid UUID: {value!r}") from exc

    def process_result_value(self, value: Any, dialect):
        return str(value) if value is not None else None


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
