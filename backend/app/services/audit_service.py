"""Append-only audit logging."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.models.audit import AuditLog
from app.models.user import User


def log(
    db: Session,
    *,
    action: str,
    actor: User | None = None,
    actor_id: str | None = None,
    actor_email: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else actor_id,
        actor_email=(actor.email if actor else actor_email),
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        details=redact(details) if details else None,
        request_id=request_id,
    )
    db.add(entry)
    db.flush()
    return entry
