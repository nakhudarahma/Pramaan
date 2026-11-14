"""Fact ledger lifecycle: extraction -> review -> approval -> supersession.

All state changes are written in the caller's database transaction.  Approval is
atomic: an old fact is superseded in the same transaction as the new fact is
activated, and a unique ``active_scope_key`` prevents two active facts for the
same key+scope even under concurrent requests.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationAppError
from app.models.base import utcnow
from app.models.change import ChangeEvent
from app.models.document import Document
from app.models.enums import ConflictKind, ConflictStatus, FactStatus
from app.models.fact import Fact, FactConflict, FactSource, FactVersion
from app.models.notice import Notice
from app.models.user import User
from app.repositories import fact_repository
from app.schemas.fact import FactDetail, FactEditRequest, FactOut, FactSourceOut, FactVersionOut
from app.services import audit_service, calendar_service, citation_service, conflict_service
from app.services.extraction_service import ExtractedFact, ExtractionResult
from app.utils.date_utils import days_until, is_expired, today_utc
from app.utils.validators import (
    ValidationFailure,
    assert_transition,
    compute_active_scope_key,
    normalize_academic_year,
    normalize_semester,
    scope_matches,
    validate_date_range,
)


def _scope(fact: Fact) -> dict:
    return {
        "college": fact.college,
        "course": fact.course,
        "department": fact.department,
        "semester": fact.semester,
        "academic_year": fact.academic_year,
        "batch": fact.batch,
        "student_group": fact.student_group,
    }


def _snapshot(fact: Fact, change_type: str, *, actor: User | None = None, note: str | None = None) -> FactVersion:
    fact.version += 1
    version = FactVersion(
        fact_id=fact.id,
        version_number=fact.version,
        change_type=change_type,
        snapshot=_serialize(fact),
        changed_by=actor.id if actor else None,
        note=note,
    )
    return version


def _initial_version(fact: Fact, *, actor: User | None = None) -> FactVersion:
    return FactVersion(
        fact_id=fact.id,
        version_number=1,
        change_type="extracted",
        snapshot=_serialize(fact),
        changed_by=actor.id if actor else None,
    )


def _serialize(fact: Fact) -> dict:
    return {
        "id": fact.id,
        "fact_key": fact.fact_key,
        "category": fact.category,
        "title": fact.title,
        "value_json": fact.value_json,
        "value_text": fact.value_text,
        "value_number": float(fact.value_number) if fact.value_number is not None else None,
        "value_date": fact.value_date.isoformat() if fact.value_date else None,
        "currency": fact.currency,
        "unit": fact.unit,
        "scope": _scope(fact),
        "effective_from": fact.effective_from.isoformat() if fact.effective_from else None,
        "effective_to": fact.effective_to.isoformat() if fact.effective_to else None,
        "page_number": fact.page_number,
        "source_text": fact.source_text,
        "source_bbox": fact.source_bbox,
        "status": fact.status,
        "version": fact.version,
        "notice_id": fact.notice_id,
        "document_id": fact.document_id,
        "approved_by": fact.approved_by,
        "approved_at": fact.approved_at.isoformat() if fact.approved_at else None,
    }


# ---------------------------------------------------------------------------
# Candidate creation
# ---------------------------------------------------------------------------
def create_candidates(
    db: Session,
    *,
    extraction: ExtractionResult,
    notice: Notice,
    actor: User | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    created: list[Fact] = []
    duplicates: list[str] = []
    disputed: list[str] = []
    conflicts: list[str] = []

    for extracted in extraction.facts:
        fact = Fact(
            fact_key=extracted.fact_key,
            category=extracted.category,
            title=extracted.title,
            value_json=extracted.value_json,
            value_text=extracted.value_text,
            value_number=extracted.value_number,
            value_date=extracted.value_date,
            currency=extracted.currency,
            unit=extracted.unit,
            college=extracted.scope.get("college"),
            course=extracted.scope.get("course"),
            department=extracted.scope.get("department"),
            semester=extracted.scope.get("semester"),
            academic_year=extracted.scope.get("academic_year"),
            batch=extracted.scope.get("batch"),
            student_group=extracted.scope.get("student_group"),
            effective_from=extracted.effective_from,
            effective_to=extracted.effective_to,
            notice_id=notice.id,
            document_id=notice.document_id,
            page_number=extracted.page_number,
            source_text=extracted.source_text,
            source_bbox=extracted.source_bbox,
            source_precision=extracted.source_precision,
            extraction_confidence=extracted.confidence,
            extraction_method=extraction.method,
            description=extracted.description,
            status=FactStatus.CANDIDATE.value,
            version=1,
        )
        db.add(fact)
        db.flush()
        db.add(_initial_version(fact, actor=actor))
        db.flush()

        decision = conflict_service.detect(
            db,
            fact_key=fact.fact_key,
            scope=_scope(fact),
            value_text=fact.value_text,
            value_number=float(fact.value_number) if fact.value_number is not None else None,
            effective_from=fact.effective_from,
            notice_issued_on=notice.issued_on,
            supersedes_ref=extracted.supersedes_ref,
            exclude_fact_id=fact.id,
        )

        if decision.kind == ConflictKind.NEW.value:
            pass
        elif decision.kind == ConflictKind.DUPLICATE.value and decision.existing is not None:
            _attach_source(db, decision.existing, fact)
            fact.status = FactStatus.REJECTED.value
            fact.rejection_reason = f"Duplicate of existing fact {decision.existing.id}"
            db.add(
                _snapshot(
                    fact,
                    "rejected",
                    actor=actor,
                    note=f"Duplicate of existing fact {decision.existing.id}; source attached",
                )
            )
            db.add(
                FactConflict(
                    kind=ConflictKind.DUPLICATE.value,
                    status=ConflictStatus.RESOLVED.value,
                    candidate_fact_id=fact.id,
                    existing_fact_id=decision.existing.id,
                    reason=decision.reason,
                    resolution="duplicate_attached",
                    resolution_note="Same value; extra source attached to the existing fact",
                    resolved_at=utcnow(),
                )
            )
            duplicates.append(fact.id)
            db.flush()
        else:
            conflict = conflict_service.record(db, decision=decision, candidate_fact=fact)
            if conflict:
                conflicts.append(conflict.id)
            if decision.kind == ConflictKind.SUPERSEDES.value and decision.existing is not None:
                fact.previous_fact_id = decision.existing.id
            if decision.kind == ConflictKind.DISPUTED.value:
                fact.status = FactStatus.DISPUTED.value
                disputed.append(fact.id)
                db.add(_snapshot(fact, "marked_disputed", note=decision.reason))
            db.flush()
        created.append(fact)

    audit_service.log(
        db,
        action="extraction.completed",
        actor=actor,
        target_type="notice",
        target_id=notice.id,
        details={
            "method": extraction.method,
            "facts_created": len(created),
            "duplicates": len(duplicates),
            "disputed": len(disputed),
            "conflicts": len(conflicts),
            "errors": extraction.errors[:10],
        },
        request_id=request_id,
    )
    return {
        "facts": created,
        "duplicates": duplicates,
        "disputed": disputed,
        "conflict_ids": conflicts,
    }


def _attach_source(db: Session, existing: Fact, candidate: Fact) -> None:
    duplicate = db.scalar(
        select(FactSource).where(
            FactSource.fact_id == existing.id,
            FactSource.notice_id == candidate.notice_id,
            FactSource.page_number == candidate.page_number,
        )
    )
    if duplicate:
        return
    db.add(
        FactSource(
            fact_id=existing.id,
            notice_id=candidate.notice_id,
            document_id=candidate.document_id,
            page_number=candidate.page_number,
            source_text=candidate.source_text,
            source_bbox=candidate.source_bbox,
        )
    )
    db.flush()


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------
def edit_fact(
    db: Session,
    fact_id: str,
    payload: FactEditRequest,
    *,
    actor: User,
    request_id: str | None = None,
) -> Fact:
    fact = db.get(Fact, fact_id)
    if fact is None:
        raise NotFoundError("Fact not found")
    if fact.status not in {FactStatus.CANDIDATE.value, FactStatus.DISPUTED.value}:
        raise ConflictError("Only candidate or disputed facts can be edited")
    updates = payload.model_dump(exclude_unset=True)
    note = updates.pop("note", None)
    if not updates:
        return fact

    scope_keys = {"college", "course", "department", "semester", "academic_year", "batch", "student_group"}
    scope_changed = any(key in updates for key in scope_keys)
    try:
        for key, value in updates.items():
            if key == "value_date" and value is not None:
                setattr(fact, key, value)
            elif key == "semester" and value is not None:
                setattr(fact, key, normalize_semester(value))
            elif key == "academic_year":
                setattr(fact, key, normalize_academic_year(value))
            elif key == "category" and value:
                setattr(fact, key, str(value).lower())
            else:
                setattr(fact, key, value)
        validate_date_range(fact.effective_from, fact.effective_to)
        if not fact.value_text:
            raise ValidationFailure("value_text is required")
        if fact.semester is not None and not 1 <= int(fact.semester) <= 12:
            raise ValidationFailure("semester must be between 1 and 12")
    except (ValidationFailure, ValueError) as exc:
        raise ValidationAppError(str(exc)) from exc

    if scope_changed:
        fact.active_scope_key = None
    db.flush()

    # Recompute conflicts against the edited values.
    pending = list(
        db.scalars(
            select(FactConflict).where(
                FactConflict.candidate_fact_id == fact.id,
                FactConflict.status == ConflictStatus.PENDING.value,
            )
        )
    )
    for conflict in pending:
        conflict.status = ConflictStatus.DISMISSED.value
        conflict.resolution = "superseded_by_edit"
        conflict.resolution_note = "Candidate was edited; conflict recomputed"
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
    db.flush()

    decision = conflict_service.detect(
        db,
        fact_key=fact.fact_key,
        scope=_scope(fact),
        value_text=fact.value_text,
        value_number=float(fact.value_number) if fact.value_number is not None else None,
        effective_from=fact.effective_from,
        notice_issued_on=(db.get(Notice, fact.notice_id).issued_on if fact.notice_id else None),
        exclude_fact_id=fact.id,
    )
    if decision.kind == ConflictKind.NEW.value:
        if fact.status == FactStatus.DISPUTED.value:
            fact.status = FactStatus.CANDIDATE.value
        fact.previous_fact_id = None
    else:
        conflict_service.record(db, decision=decision, candidate_fact=fact)
        if decision.kind == ConflictKind.SUPERSEDES.value and decision.existing is not None:
            fact.previous_fact_id = decision.existing.id
            if fact.status == FactStatus.DISPUTED.value:
                fact.status = FactStatus.CANDIDATE.value
        elif decision.kind == ConflictKind.DISPUTED.value:
            fact.previous_fact_id = None
            fact.status = FactStatus.DISPUTED.value
        else:
            fact.previous_fact_id = None
            if fact.status == FactStatus.DISPUTED.value:
                fact.status = FactStatus.CANDIDATE.value
    db.add(_snapshot(fact, "edited", actor=actor, note=note))
    db.flush()
    audit_service.log(
        db,
        action="fact.edited",
        actor=actor,
        target_type="fact",
        target_id=fact.id,
        details={"fields": sorted(updates.keys()), "note": note},
        request_id=request_id,
    )
    return fact


# ---------------------------------------------------------------------------
# Approval / rejection
# ---------------------------------------------------------------------------
def approve_fact(
    db: Session,
    fact_id: str,
    *,
    actor: User,
    note: str | None = None,
    publish_notice: bool = False,
    request_id: str | None = None,
) -> Fact:
    fact = db.scalar(select(Fact).where(Fact.id == fact_id).with_for_update())
    if fact is None:
        raise NotFoundError("Fact not found")
    if fact.status not in {FactStatus.CANDIDATE.value, FactStatus.DISPUTED.value}:
        raise ConflictError(f"Fact in status '{fact.status}' cannot be approved")

    pending = fact_repository.pending_conflicts_for_fact(db, fact.id)
    if pending:
        raise ConflictError(
            "This fact has unresolved conflicts. Resolve them before approval.",
            details={"conflict_ids": [c.id for c in pending]},
        )
    try:
        validate_date_range(fact.effective_from, fact.effective_to)
        if fact.semester is not None and not 1 <= int(fact.semester) <= 12:
            raise ValidationFailure("semester must be between 1 and 12")
        if not fact.fact_key or not fact.value_text:
            raise ValidationFailure("fact_key and value are required")
        if is_expired(fact.effective_to):
            raise ValidationFailure("Fact is expired; update effective_to or reject it")
    except ValidationFailure as exc:
        raise ValidationAppError(str(exc)) from exc

    scope = _scope(fact)
    active_scope_key = compute_active_scope_key(fact.fact_key, scope)

    exact_active = [
        other
        for other in fact_repository.active_by_key(db, fact.fact_key)
        if other.id != fact.id and compute_active_scope_key(other.fact_key, _scope(other)) == active_scope_key
    ]
    for other in exact_active:
        if _same_value(other, fact):
            raise ConflictError(
                "An active fact with the same key, scope and value already exists",
                details={"existing_fact_id": other.id},
            )

    superseded: list[Fact] = []
    for old in exact_active:
        old_status = old.status
        assert_transition(old_status, FactStatus.SUPERSEDED.value)
        old.status = FactStatus.SUPERSEDED.value
        old.active_scope_key = None
        old.superseded_by_id = fact.id
        db.add(_snapshot(old, "superseded", actor=actor, note=f"Superseded by {fact.id}"))
        calendar_service.cancel_for_fact(db, old)
        if fact.previous_fact_id is None:
            fact.previous_fact_id = old.id
        superseded.append(old)
    db.flush()

    assert_transition(fact.status, FactStatus.ACTIVE.value)
    fact.status = FactStatus.ACTIVE.value
    fact.active_scope_key = active_scope_key
    fact.approved_by = actor.id
    fact.approved_at = utcnow()
    fact.published_at = utcnow()
    db.add(_snapshot(fact, "approved", actor=actor, note=note))
    db.flush()

    for conflict in fact_repository.pending_conflicts_for_fact(db, fact.id):
        conflict.status = ConflictStatus.RESOLVED.value
        conflict.resolution = "approved"
        conflict.resolution_note = note
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
    db.flush()

    for old in superseded:
        db.add(
            ChangeEvent(
                old_fact_id=old.id,
                new_fact_id=fact.id,
                notice_id=fact.notice_id,
                fact_key=fact.fact_key,
                diff_json={
                    "old_value": old.value_text,
                    "new_value": fact.value_text,
                    "old_scope": _scope(old),
                    "new_scope": scope,
                },
                scope_json=scope,
                effective_date=fact.effective_from or today_utc(),
            )
        )
    db.flush()

    calendar_service.sync_event_for_fact(db, fact)

    if publish_notice:
        publish_notice_facts(db, fact.notice_id, actor=actor, request_id=request_id)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "Another administrator approved a conflicting fact at the same time. "
            "Reload the review screen and try again."
        ) from exc

    audit_service.log(
        db,
        action="fact.approved",
        actor=actor,
        target_type="fact",
        target_id=fact.id,
        details={
            "fact_key": fact.fact_key,
            "value": fact.value_text,
            "superseded": [old.id for old in superseded],
            "note": note,
        },
        request_id=request_id,
    )
    return fact


def reject_fact(
    db: Session,
    fact_id: str,
    *,
    actor: User,
    reason: str,
    request_id: str | None = None,
) -> Fact:
    fact = db.scalar(select(Fact).where(Fact.id == fact_id).with_for_update())
    if fact is None:
        raise NotFoundError("Fact not found")
    if fact.status not in {FactStatus.CANDIDATE.value, FactStatus.DISPUTED.value}:
        raise ConflictError(f"Fact in status '{fact.status}' cannot be rejected")
    assert_transition(fact.status, FactStatus.REJECTED.value)
    fact.status = FactStatus.REJECTED.value
    fact.active_scope_key = None
    fact.rejection_reason = reason
    db.add(_snapshot(fact, "rejected", actor=actor, note=reason))
    for conflict in fact_repository.pending_conflicts_for_fact(db, fact.id):
        conflict.status = ConflictStatus.RESOLVED.value
        conflict.resolution = "candidate_rejected"
        conflict.resolution_note = reason
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
    db.flush()
    audit_service.log(
        db,
        action="fact.rejected",
        actor=actor,
        target_type="fact",
        target_id=fact.id,
        details={"reason": reason, "fact_key": fact.fact_key},
        request_id=request_id,
    )
    return fact


# ---------------------------------------------------------------------------
# Publication / expiry
# ---------------------------------------------------------------------------
def publish_notice_facts(
    db: Session,
    notice_id: str,
    *,
    actor: User,
    request_id: str | None = None,
) -> tuple[Notice, int]:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise NotFoundError("Notice not found")
    now = utcnow()
    notice.status = "published"
    notice.published_at = now
    facts = list(
        db.scalars(
            select(Fact).where(
                Fact.notice_id == notice_id,
                Fact.status == FactStatus.ACTIVE.value,
            )
        )
    )
    for fact in facts:
        fact.published_at = now
    db.flush()
    audit_service.log(
        db,
        action="notice.published",
        actor=actor,
        target_type="notice",
        target_id=notice.id,
        details={"facts_published": len(facts)},
        request_id=request_id,
    )
    return notice, len(facts)


def expire_fact(
    db: Session,
    fact_id: str,
    *,
    actor: User,
    note: str | None = None,
    request_id: str | None = None,
) -> Fact:
    fact = db.scalar(select(Fact).where(Fact.id == fact_id).with_for_update())
    if fact is None:
        raise NotFoundError("Fact not found")
    if fact.status != FactStatus.ACTIVE.value:
        raise ConflictError("Only active facts can be expired")
    today = today_utc()
    if fact.effective_to is None or fact.effective_to > today:
        fact.effective_to = today
    fact.status = FactStatus.EXPIRED.value
    fact.active_scope_key = None
    db.add(_snapshot(fact, "expired", actor=actor, note=note or "Expired by administrator"))
    calendar_service.cancel_for_fact(db, fact)
    db.flush()
    audit_service.log(
        db,
        action="fact.expired",
        actor=actor,
        target_type="fact",
        target_id=fact.id,
        details={"note": note},
        request_id=request_id,
    )
    return fact


def expire_active_facts(db: Session, *, on_date: date | None = None) -> int:
    current = on_date or today_utc()
    expired = list(
        db.scalars(
            select(Fact).where(
                Fact.status == FactStatus.ACTIVE.value,
                Fact.effective_to.is_not(None),
                Fact.effective_to < current,
            )
        )
    )
    for fact in expired:
        fact.status = FactStatus.EXPIRED.value
        fact.active_scope_key = None
        calendar_service.cancel_for_fact(db, fact)
        db.add(_snapshot(fact, "expired", note="Validity period ended"))
    db.flush()
    return len(expired)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def _specificity(fact: Fact) -> int:
    return sum(1 for value in _scope(fact).values() if value is not None)


def best_active_facts(
    db: Session,
    fact_keys: list[str],
    student_scope: dict,
    *,
    prefixes: list[str] | None = None,
) -> list[Fact]:
    matched = fact_repository.matching_active_facts(
        db, fact_keys, student_scope, prefixes=prefixes
    )
    best: dict[str, Fact] = {}
    for fact in matched:
        current = best.get(fact.fact_key)
        if current is None:
            best[fact.fact_key] = fact
            continue
        if _specificity(fact) > _specificity(current):
            best[fact.fact_key] = fact
        elif _specificity(fact) == _specificity(current):
            if (fact.approved_at or fact.updated_at) > (current.approved_at or current.updated_at):
                best[fact.fact_key] = fact
    return list(best.values())


def outdated_facts(
    db: Session,
    fact_keys: list[str],
    student_scope: dict,
    *,
    prefixes: list[str] | None = None,
) -> list[Fact]:
    condition = fact_repository.key_condition(fact_keys, prefixes)
    if condition is None:
        return []
    current = today_utc()
    rows = list(
        db.scalars(
            select(Fact).where(
                condition,
                Fact.status.in_({FactStatus.ACTIVE.value, FactStatus.EXPIRED.value}),
                Fact.effective_to.is_not(None),
                Fact.effective_to < current,
            )
        )
    )
    matches = [fact for fact in rows if scope_matches(_scope(fact), student_scope)]
    matches.sort(key=lambda f: (f.approved_at or f.updated_at), reverse=True)
    return matches


def any_fact_exists_for_keys(
    db: Session,
    fact_keys: list[str],
    *,
    prefixes: list[str] | None = None,
) -> bool:
    condition = fact_repository.key_condition(fact_keys, prefixes)
    if condition is None:
        return False
    return (db.scalar(select(func.count(Fact.id)).where(condition)) or 0) > 0


def get_fact(db: Session, fact_id: str) -> Fact:
    fact = db.get(Fact, fact_id)
    if fact is None:
        raise NotFoundError("Fact not found")
    return fact


def get_fact_detail(db: Session, fact_id: str) -> FactDetail:
    fact = get_fact(db, fact_id)
    notice = db.get(Notice, fact.notice_id)
    document = db.get(Document, fact.document_id)
    conflicts = list(
        db.scalars(
            select(FactConflict).where(
                or_(
                    FactConflict.candidate_fact_id == fact.id,
                    FactConflict.existing_fact_id == fact.id,
                )
            )
        )
    )
    sources = [
        {
            "document_id": document.id if document else fact.document_id,
            "document_name": document.original_filename if document else None,
            "notice_id": notice.id if notice else fact.notice_id,
            "notice_title": notice.title if notice else None,
            "page_number": fact.page_number,
            "source_text": fact.source_text,
            "source_bbox": fact.source_bbox,
            "source_precision": fact.source_precision,
            "file_url": f"/api/notices/{fact.notice_id}/file",
        }
    ]
    for source in fact.sources:
        src_doc = db.get(Document, source.document_id)
        src_notice = db.get(Notice, source.notice_id)
        sources.append(
            {
                "document_id": source.document_id,
                "document_name": src_doc.original_filename if src_doc else None,
                "notice_id": source.notice_id,
                "notice_title": src_notice.title if src_notice else None,
                "page_number": source.page_number,
                "source_text": source.source_text,
                "source_bbox": source.source_bbox,
                "source_precision": "exact" if source.source_bbox else "page",
                "file_url": f"/api/notices/{source.notice_id}/file",
            }
        )
    return FactDetail(
        **FactOut.model_validate(fact).model_dump(),
        versions=[FactVersionOut.model_validate(v) for v in fact.versions],
        sources=[FactSourceOut(**source) for source in sources],
        notice_title=notice.title if notice else None,
        document_name=document.original_filename if document else None,
        conflict_ids=[c.id for c in conflicts],
    )


def list_admin_facts(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    fact_key: str | None = None,
    category: str | None = None,
    notice_id: str | None = None,
    course: str | None = None,
    semester: int | None = None,
    academic_year: str | None = None,
    search: str | None = None,
) -> tuple[list[Fact], int]:
    conditions = []
    if status:
        conditions.append(Fact.status == status)
    if fact_key:
        conditions.append(Fact.fact_key.ilike(f"%{fact_key}%"))
    if category:
        conditions.append(Fact.category == category)
    if notice_id:
        conditions.append(Fact.notice_id == notice_id)
    if course:
        conditions.append(Fact.course == course)
    if semester is not None:
        conditions.append(Fact.semester == semester)
    if academic_year:
        conditions.append(Fact.academic_year == academic_year)
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Fact.fact_key.ilike(pattern), Fact.value_text.ilike(pattern), Fact.title.ilike(pattern)))
    base = select(Fact)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(Fact.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    )
    return rows, total


def deadlines_for_scope(
    db: Session, student_scope: dict, *, limit: int = 20, days_ahead: int | None = None
) -> list[dict]:
    today = today_utc()
    rows = list(
        db.scalars(
            select(Fact).where(
                Fact.status == FactStatus.ACTIVE.value,
                Fact.value_date.is_not(None),
                Fact.value_date >= today,
            )
        )
    )
    selected: dict[str, Fact] = {}
    for fact in rows:
        if not scope_matches(_scope(fact), student_scope):
            continue
        if is_expired(fact.effective_to):
            continue
        if days_ahead is not None and (fact.value_date - today).days > days_ahead:
            continue
        current = selected.get(fact.fact_key)
        specificity = sum(1 for value in _scope(fact).values() if value is not None)
        current_specificity = (
            sum(1 for value in _scope(current).values() if value is not None) if current else -1
        )
        if current is None or specificity > current_specificity:
            selected[fact.fact_key] = fact
        elif specificity == current_specificity and fact.value_date < current.value_date:
            selected[fact.fact_key] = fact
    ordered = sorted(selected.values(), key=lambda f: f.value_date)
    result = []
    for fact in ordered[:limit]:
        result.append(
            {
                "fact_id": fact.id,
                "fact_key": fact.fact_key,
                "title": fact.title,
                "value_text": fact.value_text,
                "date": fact.value_date,
                "days_remaining": days_until(fact.value_date),
                "scope": _scope(fact),
                "category": fact.category,
                "citation": citation_service.for_fact(db, fact),
            }
        )
    return result


def changes_for_scope(db: Session, student_scope: dict, *, limit: int = 10) -> list[dict]:
    events = list(
        db.scalars(select(ChangeEvent).order_by(ChangeEvent.created_at.desc()).limit(200))
    )
    result = []
    for event in events:
        new_fact = db.get(Fact, event.new_fact_id)
        if new_fact is None or new_fact.status not in {
            FactStatus.ACTIVE.value,
            FactStatus.SUPERSEDED.value,
            FactStatus.EXPIRED.value,
        }:
            continue
        new_scope = _scope(new_fact)
        old_fact = db.get(Fact, event.old_fact_id) if event.old_fact_id else None
        old_scope = _scope(old_fact) if old_fact else None
        if not (scope_matches(new_scope, student_scope) or (old_scope and scope_matches(old_scope, student_scope))):
            continue
        notice = db.get(Notice, new_fact.notice_id)
        result.append(
            {
                "id": event.id,
                "fact_key": event.fact_key,
                "title": new_fact.title,
                "old_value": old_fact.value_text if old_fact else None,
                "new_value": new_fact.value_text,
                "effective_date": event.effective_date,
                "changed_at": event.created_at,
                "notice_id": new_fact.notice_id,
                "notice_title": notice.title if notice else None,
                "page_number": new_fact.page_number,
                "source_text": new_fact.source_text,
                "citation": citation_service.for_fact(db, new_fact),
            }
        )
        if len(result) >= limit:
            break
    return result


def _same_value(left: Fact, right: Fact) -> bool:
    if left.value_number is not None and right.value_number is not None:
        return abs(float(left.value_number) - float(right.value_number)) < 0.001
    return (left.value_text or "").strip().lower() == (right.value_text or "").strip().lower()
