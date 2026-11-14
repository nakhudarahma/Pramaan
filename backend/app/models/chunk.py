"""Narrative document chunks and their embeddings (fallback RAG path)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, GUID, new_uuid, utcnow

try:  # Optional: only needed on PostgreSQL with the pgvector extension.
    from pgvector.sqlalchemy import Vector as _PgVector
except Exception:  # pragma: no cover - pgvector is optional
    _PgVector = None  # type: ignore[assignment]


class EmbeddingVector(TypeDecorator):
    """Portable embedding column.

    * PostgreSQL + pgvector: native ``vector(dim)`` column.
    * SQLite / other, or PGVECTOR_ENABLED=false: JSON text, so cosine similarity
      can be computed in Python.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 768):
        super().__init__()
        self.dim = dim

    @staticmethod
    def _pgvector_enabled(dialect) -> bool:
        if dialect.name != "postgresql" or _PgVector is None:
            return False
        from app.config import get_settings

        return get_settings().pgvector_enabled

    def load_dialect_impl(self, dialect):
        if self._pgvector_enabled(dialect):
            return dialect.type_descriptor(_PgVector(self.dim))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect):
        if value is None:
            return None
        if self._pgvector_enabled(dialect):
            return value
        return json.dumps(list(value))

    def process_result_value(self, value: Any, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return list(value)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    notice_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("notices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int | None] = mapped_column(Integer, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    scope_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_bbox: Mapped[list | None] = mapped_column(JSON)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    chunk_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("chunks.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list | None] = mapped_column(EmbeddingVector(768))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
