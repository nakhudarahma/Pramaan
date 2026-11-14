"""Unanswered question queue with safe aggregation (no PII)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.unanswered import UnansweredQuestion
from app.models.base import utcnow
from app.utils.text_utils import normalize_question


def record(
    db: Session,
    *,
    question: str,
    course: str | None,
    semester: int | None,
    academic_year: str | None,
    intent: str | None,
    topic: str | None,
) -> UnansweredQuestion:
    normalized = normalize_question(question) or question.strip().lower()[:500]
    existing = db.scalar(
        select(UnansweredQuestion).where(
            UnansweredQuestion.normalized_question == normalized,
            UnansweredQuestion.status == "open",
            UnansweredQuestion.course == course,
            UnansweredQuestion.semester == semester,
            UnansweredQuestion.academic_year == academic_year,
        )
    )
    if existing:
        existing.occurrence_count += 1
        existing.last_asked_at = utcnow()
        existing.updated_at = utcnow()
        db.flush()
        return existing
    row = UnansweredQuestion(
        question=question[:1000],
        normalized_question=normalized[:500],
        course=course,
        semester=semester,
        academic_year=academic_year,
        intent_guess=intent,
        topic_guess=topic,
        status="open",
        last_asked_at=utcnow(),
    )
    db.add(row)
    db.flush()
    return row
