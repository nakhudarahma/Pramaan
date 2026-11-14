"""Chunk + embedding persistence and candidate retrieval."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.chunk import Chunk, Embedding
from app.models.enums import NoticeStatus
from app.models.notice import Notice
from app.utils.validators import scope_matches


def add_chunk(
    db: Session,
    *,
    notice_id: str,
    document_id: str,
    page_number: int | None,
    chunk_index: int,
    text: str,
    scope: dict,
    bbox: list | None,
    token_count: int,
) -> Chunk:
    chunk = Chunk(
        notice_id=notice_id,
        document_id=document_id,
        page_number=page_number,
        chunk_index=chunk_index,
        text=text,
        scope_json=scope,
        source_bbox=bbox,
        token_count=token_count,
    )
    db.add(chunk)
    db.flush()
    return chunk


def add_embedding(db: Session, chunk_id: str, model: str, vector: list[float]) -> Embedding:
    embedding = Embedding(chunk_id=chunk_id, model=model, dim=len(vector), vector=vector)
    db.add(embedding)
    db.flush()
    return embedding


def candidate_chunks(
    db: Session,
    student_scope: dict,
    *,
    limit: int = 400,
) -> list[tuple[Chunk, Embedding | None]]:
    if limit <= 0:
        return []
    rows = db.execute(
        select(Chunk, Embedding)
        .join(Notice, Notice.id == Chunk.notice_id)
        .outerjoin(Embedding, Embedding.chunk_id == Chunk.id)
        .where(Notice.status == NoticeStatus.PUBLISHED.value)
        .order_by(Chunk.created_at.desc())
    ).all()
    result: list[tuple[Chunk, Embedding | None]] = []
    for chunk, embedding in rows:
        if scope_matches(chunk.scope_json or {}, student_scope):
            result.append((chunk, embedding))
            if len(result) >= limit:
                break
    return result
