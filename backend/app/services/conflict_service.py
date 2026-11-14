"""Conflict detection and admin-controlled resolution.

Decision order (blueprint 8.5):
NEW -> DUPLICATE -> SCOPE_OVERLAP -> SUPERSEDES -> DISPUTED.
No conflict is ever resolved silently; the ledger proposes, an admin confirms.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.base import utcnow
from app.models.enums import ConflictKind, ConflictStatus, FactStatus
from app.models.fact import Fact, FactConflict
from app.models.notice import Notice
from app.models.user import User
from app.repositories import fact_repository
from app.services import audit_service
from app.utils.validators import scopes_equal, scopes_overlap


@dataclass
class ConflictDecision:
    kind: str
    existing: Fact | None = None
    reason: str = ""
    matches: list[Fact] | None = None


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


def _value_matches(existing: Fact, value_text: str, value_number: float | None) -> bool:
    if value_number is not None and existing.value_number is not None:
        return abs(float(existing.value_number) - float(value_number)) < 0.001
    return (existing.value_text or "").strip().lower() == (value_text or "").strip().lower()


def _issue_date(db: Session, fact: Fact) -> date | None:
    notice = db.get(Notice, fact.notice_id)
    return notice.issued_on if notice else None


def detect(
    db: Session,
    *,
    fact_key: str,
    scope: dict,
    value_text: str,
    value_number: float | None,
    effective_from: date | None,
    notice_issued_on: date | None,
    supersedes_ref: str | None = None,
    exclude_fact_id: str | None = None,
) -> ConflictDecision:
    existing = [
        fact
        for fact in fact_repository.overlapping_facts(db, fact_key, scope)
        if fact.id != exclude_fact_id
    ]
    if not existing:
        return ConflictDecision(ConflictKind.NEW.value, reason="No overlapping fact", matches=[])

    disputed = [fact for fact in existing if fact.status == FactStatus.DISPUTED.value]
    if disputed:
        return ConflictDecision(
            ConflictKind.DISPUTED.value,
            existing=sorted(disputed, key=lambda f: f.source_precision, reverse=True)[0],
            reason="An existing fact for this topic is already disputed",
            matches=existing,
        )

    exact = [fact for fact in existing if scopes_equal(_scope(fact), scope)]
    if exact:
        exact.sort(key=lambda f: (f.approved_at or f.updated_at), reverse=True)
        best = exact[0]
        if len(exact) > 1:
            return ConflictDecision(
                ConflictKind.DISPUTED.value,
                existing=best,
                reason="Multiple active records already exist for this exact scope",
                matches=exact,
            )
        if _value_matches(best, value_text, value_number):
            return ConflictDecision(
                ConflictKind.DUPLICATE.value,
                existing=best,
                reason="Same key, scope and value already exist",
                matches=exact,
            )
        if supersedes_ref:
            return ConflictDecision(
                ConflictKind.SUPERSEDES.value,
                existing=best,
                reason=f"Notice explicitly references an earlier notice ({supersedes_ref})",
                matches=exact,
            )
        existing_issue = _issue_date(db, best)
        if notice_issued_on and existing_issue:
            if notice_issued_on > existing_issue:
                return ConflictDecision(
                    ConflictKind.SUPERSEDES.value,
                    existing=best,
                    reason=f"Newer notice ({notice_issued_on}) replaces older notice ({existing_issue})",
                    matches=exact,
                )
            if notice_issued_on == existing_issue:
                return ConflictDecision(
                    ConflictKind.DISPUTED.value,
                    existing=best,
                    reason="Conflicting values from notices with the same issue date",
                    matches=exact,
                )
            return ConflictDecision(
                ConflictKind.DISPUTED.value,
                existing=best,
                reason="Candidate notice is older than the active record; order is unclear",
                matches=exact,
            )
        if effective_from and best.effective_from:
            if effective_from > best.effective_from:
                return ConflictDecision(
                    ConflictKind.SUPERSEDES.value,
                    existing=best,
                    reason="Candidate has a later effective date",
                    matches=exact,
                )
            if effective_from == best.effective_from:
                return ConflictDecision(
                    ConflictKind.DISPUTED.value,
                    existing=best,
                    reason="Conflicting values with the same effective date",
                    matches=exact,
                )
        return ConflictDecision(
            ConflictKind.DISPUTED.value,
            existing=best,
            reason="Same scope but different value and no reliable ordering evidence",
            matches=exact,
        )

    # Overlapping but not identical scopes.
    overlap = [fact for fact in existing if scopes_overlap(_scope(fact), scope)]
    if not overlap:
        return ConflictDecision(ConflictKind.NEW.value, reason="No overlapping fact", matches=[])
    overlap.sort(
        key=lambda f: (
            sum(1 for v in _scope(f).values() if v is not None),
            f.approved_at or f.updated_at,
        ),
        reverse=True,
    )
    return ConflictDecision(
        ConflictKind.SCOPE_OVERLAP.value,
        existing=overlap[0],
        reason="Scopes overlap; the more specific approved fact wins for matching students",
        matches=overlap,
    )


def record(
    db: Session,
    *,
    decision: ConflictDecision,
    candidate_fact: Fact,
) -> FactConflict | None:
    if decision.kind == ConflictKind.NEW.value or decision.existing is None:
        return None
    conflict = FactConflict(
        kind=decision.kind,
        status=ConflictStatus.PENDING.value,
        candidate_fact_id=candidate_fact.id,
        existing_fact_id=decision.existing.id,
        reason=decision.reason,
    )
    db.add(conflict)
    db.flush()
    return conflict


def _log_resolution(
    db: Session,
    conflict: FactConflict,
    candidate: Fact,
    *,
    resolution: str,
    note: str | None,
    actor: User,
    request_id: str | None,
) -> None:
    audit_service.log(
        db,
        action="conflict.resolved",
        actor=actor,
        target_type="conflict",
        target_id=conflict.id,
        details={
            "kind": conflict.kind,
            "resolution": resolution,
            "candidate_fact_id": candidate.id,
            "existing_fact_id": conflict.existing_fact_id,
            "note": note,
        },
        request_id=request_id,
    )


def resolve(
    db: Session,
    conflict_id: str,
    *,
    resolution: str,
    note: str | None,
    actor: User,
    request_id: str | None = None,
) -> dict[str, Any]:
    conflict = db.get(FactConflict, conflict_id)
    if conflict is None:
        raise NotFoundError("Conflict not found")
    if conflict.status != ConflictStatus.PENDING.value:
        raise ConflictError("Conflict has already been resolved")

    candidate = db.get(Fact, conflict.candidate_fact_id)
    existing = db.get(Fact, conflict.existing_fact_id) if conflict.existing_fact_id else None
    if candidate is None:
        raise NotFoundError("Candidate fact not found")

    if resolution == "approve_new":
        conflict.status = ConflictStatus.RESOLVED.value
        conflict.resolution = resolution
        conflict.resolution_note = note
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
        db.flush()
        from app.services import fact_service

        fact = fact_service.approve_fact(
            db,
            candidate.id,
            actor=actor,
            note=note or "Conflict resolved: approve new fact",
            request_id=request_id,
        )
        _log_resolution(
            db,
            conflict,
            candidate,
            resolution=resolution,
            note=note,
            actor=actor,
            request_id=request_id,
        )
        return {"message": "New fact approved; older record superseded if applicable", "fact_id": fact.id, "status": fact.status}

    if resolution == "keep_existing":
        conflict.status = ConflictStatus.RESOLVED.value
        conflict.resolution = resolution
        conflict.resolution_note = note
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
        db.flush()
        if candidate.status in {FactStatus.CANDIDATE.value, FactStatus.DISPUTED.value}:
            from app.services import fact_service

            fact_service.reject_fact(
                db,
                candidate.id,
                actor=actor,
                reason=note or "Admin chose the existing record over this candidate",
                request_id=request_id,
            )
        _log_resolution(
            db,
            conflict,
            candidate,
            resolution=resolution,
            note=note,
            actor=actor,
            request_id=request_id,
        )
        return {"message": "Existing fact retained; candidate rejected", "fact_id": candidate.id, "status": FactStatus.REJECTED.value}

    if resolution == "scope_difference":
        if conflict.kind != ConflictKind.SCOPE_OVERLAP.value:
            raise ConflictError("Scope difference is only valid for scope_overlap conflicts")
        conflict.status = ConflictStatus.RESOLVED.value
        conflict.resolution = resolution
        conflict.resolution_note = note
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
        db.flush()
        _log_resolution(
            db,
            conflict,
            candidate,
            resolution=resolution,
            note=note,
            actor=actor,
            request_id=request_id,
        )
        return {
            "message": "Scopes marked as different; the candidate can now be approved",
            "fact_id": candidate.id,
            "status": candidate.status,
        }

    if resolution == "dismiss":
        conflict.status = ConflictStatus.DISMISSED.value
        conflict.resolution = resolution
        conflict.resolution_note = note
        conflict.resolved_by = actor.id
        conflict.resolved_at = utcnow()
        db.flush()
        if candidate.status == FactStatus.DISPUTED.value:
            from app.services import fact_service

            fact_service.reject_fact(
                db,
                candidate.id,
                actor=actor,
                reason=note or "Conflict dismissed by administrator",
                request_id=request_id,
            )
        db.flush()
        _log_resolution(
            db,
            conflict,
            candidate,
            resolution=resolution,
            note=note,
            actor=actor,
            request_id=request_id,
        )
        return {"message": "Conflict dismissed", "fact_id": candidate.id, "status": candidate.status}

    raise ConflictError(
        "Unknown resolution. Use approve_new, keep_existing, scope_difference or dismiss."
    )
