"""Notice library queries and admin metadata updates."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.base import utcnow
from app.models.document import Document
from app.models.enums import FactStatus, NoticeStatus
from app.models.fact import Fact
from app.models.notice import Notice
from app.models.user import User
from app.schemas.document import DocumentOut
from app.schemas.fact import FactOut
from app.schemas.notice import NoticeDetail, NoticeOut, NoticeUpdate
from app.services import audit_service


def _fact_counts(db: Session, notice_ids: list[str], statuses: set[str]) -> dict[str, int]:
    if not notice_ids:
        return {}
    rows = db.execute(
        select(Fact.notice_id, func.count(Fact.id))
        .where(Fact.notice_id.in_(notice_ids), Fact.status.in_(statuses))
        .group_by(Fact.notice_id)
    ).all()
    return {notice_id: count for notice_id, count in rows}


def notice_out(db: Session, notice: Notice, *, fact_count: int | None = None) -> NoticeOut:
    document = db.get(Document, notice.document_id)
    out = NoticeOut.model_validate(notice)
    out.page_count = document.page_count if document else None
    if fact_count is None:
        fact_count = (
            db.scalar(
                select(func.count(Fact.id)).where(
                    Fact.notice_id == notice.id,
                    Fact.status.in_({FactStatus.ACTIVE.value, FactStatus.SUPERSEDED.value}),
                )
            )
            or 0
        )
    out.fact_count = fact_count
    return out


def list_notices(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    published_only: bool = True,
    status: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> tuple[list[NoticeOut], int]:
    conditions = []
    if published_only:
        conditions.append(Notice.status == NoticeStatus.PUBLISHED.value)
    elif status:
        conditions.append(Notice.status == status)
    if category:
        conditions.append(Notice.category == category)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Notice.title.ilike(pattern),
                Notice.summary.ilike(pattern),
                Notice.issuer.ilike(pattern),
            )
        )
    base = select(Notice)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    notices = list(
        db.scalars(
            base.order_by(
                Notice.issued_on.desc().nullslast(), Notice.created_at.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    counts = _fact_counts(
        db,
        [notice.id for notice in notices],
        {FactStatus.ACTIVE.value, FactStatus.SUPERSEDED.value},
    )
    return [notice_out(db, notice, fact_count=counts.get(notice.id, 0)) for notice in notices], total


def get_notice(db: Session, notice_id: str, *, published_only: bool = True) -> Notice:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise NotFoundError("Notice not found")
    if published_only and notice.status != NoticeStatus.PUBLISHED.value:
        raise NotFoundError("Notice not found")
    return notice


def notice_detail(
    db: Session,
    notice_id: str,
    *,
    published_only: bool = True,
    fact_statuses: set[str] | None = None,
) -> NoticeDetail:
    notice = get_notice(db, notice_id, published_only=published_only)
    allowed = fact_statuses or {FactStatus.ACTIVE.value}
    facts = list(
        db.scalars(
            select(Fact)
            .where(Fact.notice_id == notice.id, Fact.status.in_(allowed))
            .order_by(Fact.created_at)
        )
    )
    detail = NoticeDetail.model_validate(notice)
    document = db.get(Document, notice.document_id)
    detail.document = DocumentOut.model_validate(document) if document else None
    detail.facts = [FactOut.model_validate(fact) for fact in facts]
    detail.page_count = document.page_count if document else None
    detail.fact_count = len(facts)
    return detail


def update_notice(
    db: Session,
    notice_id: str,
    payload: NoticeUpdate,
    *,
    actor: User,
    request_id: str | None = None,
) -> Notice:
    notice = get_notice(db, notice_id, published_only=False)
    if notice.status == NoticeStatus.ARCHIVED.value:
        raise ConflictError("Archived notices cannot be edited")
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(notice, key, value)
    if updates.get("language"):
        notice.language = str(updates["language"])[:20]
    db.flush()
    audit_service.log(
        db,
        action="notice.updated",
        actor=actor,
        target_type="notice",
        target_id=notice.id,
        details={"fields": sorted(updates.keys())},
        request_id=request_id,
    )
    return notice


def archive_notice(
    db: Session,
    notice_id: str,
    *,
    actor: User,
    request_id: str | None = None,
) -> Notice:
    notice = get_notice(db, notice_id, published_only=False)
    notice.status = NoticeStatus.ARCHIVED.value
    notice.archived_at = utcnow()
    db.flush()
    audit_service.log(
        db,
        action="notice.archived",
        actor=actor,
        target_type="notice",
        target_id=notice.id,
        request_id=request_id,
    )
    return notice


def published_notices_for_dashboard(db: Session, *, limit: int = 5) -> list[NoticeOut]:
    notices = list(
        db.scalars(
            select(Notice)
            .where(Notice.status == NoticeStatus.PUBLISHED.value)
            .order_by(Notice.published_at.desc().nullslast(), Notice.created_at.desc())
            .limit(limit)
        )
    )
    counts = _fact_counts(
        db, [notice.id for notice in notices], {FactStatus.ACTIVE.value}
    )
    return [notice_out(db, notice, fact_count=counts.get(notice.id, 0)) for notice in notices]


def document_detail(db: Session, document_id: str):
    document = db.get(Document, document_id)
    if document is None:
        raise NotFoundError("Document not found")
    from app.schemas.document import DocumentDetail, DocumentJobOut

    detail = DocumentDetail.model_validate(document)
    detail.jobs = [DocumentJobOut.model_validate(job) for job in document.jobs]
    return detail
