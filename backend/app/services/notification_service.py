"""Derived admin alerts.

No notification table is required for the MVP: alerts are computed from the
ledger's real state so they can never drift out of sync.  Outbound email/push is
intentionally not implemented.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.enums import ConflictStatus, DocumentStatus, UnansweredStatus
from app.models.fact import FactConflict
from app.models.unanswered import UnansweredQuestion


def admin_alerts(db: Session) -> dict:
    pending_conflicts = (
        db.scalar(
            select(func.count(FactConflict.id)).where(
                FactConflict.status == ConflictStatus.PENDING.value
            )
        )
        or 0
    )
    open_unanswered = (
        db.scalar(
            select(func.count(UnansweredQuestion.id)).where(
                UnansweredQuestion.status == UnansweredStatus.OPEN.value
            )
        )
        or 0
    )
    needs_review = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.status.in_(
                    {DocumentStatus.NEEDS_REVIEW.value, DocumentStatus.FAILED.value}
                )
            )
        )
        or 0
    )
    return {
        "pending_conflicts": pending_conflicts,
        "open_unanswered": open_unanswered,
        "documents_needing_review": needs_review,
        "total": pending_conflicts + open_unanswered + needs_review,
    }
