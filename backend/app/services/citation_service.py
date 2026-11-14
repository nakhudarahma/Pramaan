"""Build citations that are guaranteed to point at real stored records."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.enums import SourcePrecision
from app.models.fact import Fact
from app.models.notice import Notice
from app.schemas.fact import Citation


def _file_url(notice_id: str) -> str:
    settings = get_settings()
    return f"{settings.api_prefix}/notices/{notice_id}/file"


def for_fact(db: Session, fact: Fact) -> Citation | None:
    notice = db.get(Notice, fact.notice_id)
    document = db.get(Document, fact.document_id)
    if notice is None or document is None:
        return None
    return Citation(
        fact_id=fact.id,
        version=fact.version,
        status=fact.status,
        document_id=document.id,
        document_name=document.original_filename,
        notice_id=notice.id,
        notice_title=notice.title,
        page_number=fact.page_number,
        source_text=fact.source_text,
        source_bbox=fact.source_bbox,
        source_precision=fact.source_precision,
        effective_from=fact.effective_from,
        effective_to=fact.effective_to,
        approved_at=fact.approved_at,
    )


def for_chunk(db: Session, chunk: Chunk) -> Citation | None:
    notice = db.get(Notice, chunk.notice_id)
    document = db.get(Document, chunk.document_id)
    if notice is None or document is None:
        return None
    return Citation(
        document_id=document.id,
        document_name=document.original_filename,
        notice_id=notice.id,
        notice_title=notice.title,
        page_number=chunk.page_number,
        source_text=chunk.text[:800],
        source_bbox=chunk.source_bbox,
        source_precision=SourcePrecision.EXACT.value if chunk.source_bbox else SourcePrecision.PAGE.value,
    )


def source_payload(db: Session, fact: Fact) -> dict:
    notice = db.get(Notice, fact.notice_id)
    document = db.get(Document, fact.document_id)
    return {
        "fact_id": fact.id,
        "version": fact.version,
        "status": fact.status,
        "notice": {
            "id": notice.id if notice else None,
            "title": notice.title if notice else None,
            "issuer": notice.issuer if notice else None,
            "issued_on": notice.issued_on if notice else None,
        },
        "document": {
            "id": document.id if document else None,
            "name": document.original_filename if document else None,
            "file_url": _file_url(fact.notice_id),
        },
        "page_number": fact.page_number,
        "source_text": fact.source_text,
        "source_bbox": fact.source_bbox,
        "source_precision": fact.source_precision,
        "effective_from": fact.effective_from,
        "effective_to": fact.effective_to,
        "approved_at": fact.approved_at,
    }
