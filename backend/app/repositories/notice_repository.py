"""Notice library queries."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.enums import NoticeStatus
from app.models.fact import Fact
from app.models.notice import Notice


def get(db: Session, notice_id: str) -> Notice | None:
    return db.get(Notice, notice_id)


def get_published(db: Session, notice_id: str) -> Notice | None:
    return db.scalar(
        select(Notice).where(
            Notice.id == notice_id, Notice.status == NoticeStatus.PUBLISHED.value
        )
    )


def list_notices(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    search: str | None = None,
    category: str | None = None,
    published_only: bool = True,
    status: str | None = None,
    issued_from=None,
    issued_to=None,
) -> tuple[list[Notice], int]:
    conditions = []
    if published_only:
        conditions.append(Notice.status == NoticeStatus.PUBLISHED.value)
    if status:
        conditions.append(Notice.status == status)
    if category:
        conditions.append(Notice.category == category)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Notice.title.ilike(pattern), Notice.summary.ilike(pattern)))
    if issued_from:
        conditions.append(Notice.issued_on >= issued_from)
    if issued_to:
        conditions.append(Notice.issued_on <= issued_to)

    base = select(Notice)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(Notice.issued_on.desc().nullslast(), Notice.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return rows, total


def fact_count(db: Session, notice_id: str) -> int:
    return (
        db.scalar(select(func.count(Fact.id)).where(Fact.notice_id == notice_id)) or 0
    )


def document_for(db: Session, notice: Notice) -> Document | None:
    return db.get(Document, notice.document_id)
