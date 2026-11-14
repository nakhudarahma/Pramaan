"""Fact ledger queries.

Scope matching is evaluated in Python after a narrow SQL pre-filter.  At the
scale of a college notice ledger (thousands of facts) this is fast, portable
across SQLite/PostgreSQL, and avoids subtle JSON-operator differences.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models.enums import FactStatus
from app.models.fact import Fact, FactConflict
from app.utils.date_utils import is_within_validity, today_utc
from app.utils.validators import scope_matches


def get(db: Session, fact_id: str) -> Fact | None:
    return db.get(Fact, fact_id)


def get_many(db: Session, fact_ids: list[str]) -> list[Fact]:
    if not fact_ids:
        return []
    return list(db.scalars(select(Fact).where(Fact.id.in_(fact_ids))))


def active_by_key(db: Session, fact_key: str) -> list[Fact]:
    return list(
        db.scalars(
            select(Fact).where(
                Fact.fact_key == fact_key,
                Fact.status == FactStatus.ACTIVE.value,
            )
        )
    )


def key_condition(fact_keys: list[str], prefixes: list[str] | None):
    clauses = []
    if fact_keys:
        clauses.append(Fact.fact_key.in_(fact_keys))
    for prefix in prefixes or []:
        clauses.append(Fact.fact_key.like(f"{prefix}%"))
    return or_(*clauses) if clauses else None


def active_by_keys(
    db: Session, fact_keys: list[str], prefixes: list[str] | None = None
) -> list[Fact]:
    condition = key_condition(fact_keys, prefixes)
    if condition is None:
        return []
    return list(
        db.scalars(
            select(Fact).where(
                condition,
                Fact.status == FactStatus.ACTIVE.value,
            )
        )
    )


def matching_active_facts(
    db: Session,
    fact_keys: list[str],
    student_scope: dict,
    *,
    on_date: date | None = None,
    prefixes: list[str] | None = None,
) -> list[Fact]:
    current = on_date or today_utc()
    candidates = active_by_keys(db, fact_keys, prefixes)
    matched = [
        fact
        for fact in candidates
        if is_within_validity(fact.effective_from, fact.effective_to, on_date=current)
        and scope_matches(_fact_scope(fact), student_scope)
    ]
    return sorted(
        matched,
        key=lambda f: (
            _specificity(f),
            f.approved_at or f.updated_at,
            f.page_number or 0,
        ),
        reverse=True,
    )


def matching_disputed_facts(
    db: Session,
    fact_keys: list[str],
    student_scope: dict,
    *,
    prefixes: list[str] | None = None,
) -> list[Fact]:
    condition = key_condition(fact_keys, prefixes)
    if condition is None:
        return []
    candidates = list(
        db.scalars(
            select(Fact).where(
                condition,
                Fact.status == FactStatus.DISPUTED.value,
            )
        )
    )
    return [fact for fact in candidates if scope_matches(_fact_scope(fact), student_scope)]


def overlapping_facts(
    db: Session,
    fact_key: str,
    scope: dict,
    *,
    include_candidate: bool = True,
) -> list[Fact]:
    """Existing facts with the same key and overlapping scope, excluding rejected."""
    statuses = {FactStatus.ACTIVE.value, FactStatus.DISPUTED.value}
    if include_candidate:
        statuses.add(FactStatus.CANDIDATE.value)
    candidates = list(
        db.scalars(
            select(Fact).where(
                Fact.fact_key == fact_key,
                Fact.status.in_(statuses),
            )
        )
    )
    return [fact for fact in candidates if _scopes_overlap(_fact_scope(fact), scope)]


def disputed_for_scope(db: Session, student_scope: dict) -> list[Fact]:
    rows = list(
        db.scalars(select(Fact).where(Fact.status == FactStatus.DISPUTED.value))
    )
    return [fact for fact in rows if scope_matches(_fact_scope(fact), student_scope)]


def pending_conflicts_for_fact(db: Session, fact_id: str) -> list[FactConflict]:
    return list(
        db.scalars(
            select(FactConflict).where(
                FactConflict.candidate_fact_id == fact_id,
                FactConflict.status == "pending",
            )
        )
    )


def expire_past_due(db: Session, *, on_date: date | None = None) -> int:
    current = on_date or today_utc()
    facts = list(
        db.scalars(
            select(Fact).where(
                Fact.status == FactStatus.ACTIVE.value,
                Fact.effective_to.is_not(None),
                Fact.effective_to < current,
            )
        )
    )
    for fact in facts:
        fact.status = FactStatus.EXPIRED.value
        fact.active_scope_key = None
    if facts:
        db.flush()
    return len(facts)


def deactivate_other_active(db: Session, active_scope_key: str, keep_fact_id: str) -> None:
    """Safety net for overlapping duplicate active rows (should never happen)."""
    db.execute(
        update(Fact)
        .where(
            Fact.active_scope_key == active_scope_key,
            Fact.id != keep_fact_id,
            Fact.status == FactStatus.ACTIVE.value,
        )
        .values(status=FactStatus.SUPERSEDED.value, active_scope_key=None)
    )


def _fact_scope(fact: Fact) -> dict:
    return {
        "college": fact.college,
        "course": fact.course,
        "department": fact.department,
        "semester": fact.semester,
        "academic_year": fact.academic_year,
        "batch": fact.batch,
        "student_group": fact.student_group,
    }


def _specificity(fact: Fact) -> int:
    return sum(1 for value in _fact_scope(fact).values() if value is not None)


def _scopes_overlap(a: dict, b: dict) -> bool:
    for key in ("college", "course", "department", "semester", "academic_year", "batch", "student_group"):
        left, right = a.get(key), b.get(key)
        if left is not None and right is not None and str(left).lower() != str(right).lower():
            return False
    return True
