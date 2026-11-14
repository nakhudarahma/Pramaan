"""Admin APIs: uploads, notices, fact review, conflicts, unanswered, audit."""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import (
    DbSession,
    SettingsDep,
    get_current_admin,
    get_document_service,
    get_request_id,
)
from app.services.document_service import DocumentService
from app.api.pagination import make_page, page_params
from app.config import get_settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    UploadValidationError,
    ValidationAppError,
)
from app.core.rate_limit import rate_limit
from app.models.base import utcnow
from app.models.document import Document
from app.models.enums import (
    FACT_STATUSES,
    ConflictKind,
    ConflictStatus,
    DocumentStatus,
    FactStatus,
    NoticeStatus,
    UnansweredStatus,
)
from app.models.fact import Fact, FactConflict
from app.models.notice import Notice
from app.models.unanswered import UnansweredQuestion
from app.models.user import User
from app.schemas.admin import (
    AdminDashboardResponse,
    AuditLogOut,
    PublishResponse,
    ResolveResponse,
    UnansweredOut,
    UnansweredResolveRequest,
)
from app.schemas.common import Page
from app.schemas.document import DocumentDetail, DocumentJobOut, DocumentOut
from app.schemas.fact import (
    ApproveFactRequest,
    ConflictOut,
    ConflictResolveRequest,
    FactDetail,
    FactEditRequest,
    FactOut,
    RejectFactRequest,
)
from app.schemas.notice import NoticeDetail, NoticeOut, NoticeUpdate, UploadResult
from app.services import (
    audit_service,
    conflict_service,
    fact_service,
    notice_service,
    notification_service,
)
from app.utils.validators import sanitize_filename

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(get_current_admin)],
)

AdminUser = Annotated[User, Depends(get_current_admin)]


def _scope_dict(fact: Fact) -> dict:
    return {
        "college": fact.college,
        "course": fact.course,
        "department": fact.department,
        "semester": fact.semester,
        "academic_year": fact.academic_year,
        "batch": fact.batch,
        "student_group": fact.student_group,
    }


# --------------------------------------------------------------------- dashboard
@router.get("/dashboard", response_model=AdminDashboardResponse)
def admin_dashboard(db: DbSession) -> AdminDashboardResponse:
    def count(model, *conditions) -> int:
        query = select(func.count()).select_from(model)
        if conditions:
            query = query.where(*conditions)
        return db.scalar(query) or 0

    return AdminDashboardResponse(
        documents_total=count(Document),
        documents_failed=count(Document, Document.status == DocumentStatus.FAILED.value),
        documents_needs_review=count(
            Document, Document.status == DocumentStatus.NEEDS_REVIEW.value
        ),
        facts_candidate=count(Fact, Fact.status == FactStatus.CANDIDATE.value),
        facts_active=count(Fact, Fact.status == FactStatus.ACTIVE.value),
        facts_disputed=count(Fact, Fact.status == FactStatus.DISPUTED.value),
        facts_rejected=count(Fact, Fact.status == FactStatus.REJECTED.value),
        facts_superseded=count(Fact, Fact.status == FactStatus.SUPERSEDED.value),
        conflicts_pending=count(
            FactConflict, FactConflict.status == ConflictStatus.PENDING.value
        ),
        unanswered_open=count(
            UnansweredQuestion, UnansweredQuestion.status == UnansweredStatus.OPEN.value
        ),
        notices_published=count(Notice, Notice.status == NoticeStatus.PUBLISHED.value),
        generated_at=utcnow(),
    )


@router.get("/alerts")
def admin_alerts(db: DbSession) -> dict:
    return notification_service.admin_alerts(db)


# --------------------------------------------------------------------- documents
@router.post(
    "/notices",
    response_model=UploadResult,
    status_code=201,
    dependencies=[
        Depends(rate_limit("upload", lambda: get_settings().rate_limit_upload_per_minute))
    ],
)
async def upload_notice(
    db: DbSession,
    settings: SettingsDep,
    admin: AdminUser,
    document_service: Annotated[DocumentService, Depends(get_document_service)],
    request_id: Annotated[str | None, Depends(get_request_id)],
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    issuer: str | None = Form(default=None),
    issued_on: date | None = Form(default=None),
    category: str = Form(default="general"),
    summary: str | None = Form(default=None),
    language: str = Form(default="en"),
) -> UploadResult:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadValidationError(
            f"File is too large. Maximum size is {settings.max_upload_mb} MB."
        )
    result = document_service.create_upload(
        db,
        data=data,
        filename=file.filename or "document.pdf",
        content_type=file.content_type,
        title=title,
        issuer=issuer,
        issued_on=issued_on,
        category=category,
        summary=summary,
        language=language,
        actor=admin,
        request_id=request_id,
    )
    document = result["document"]
    notice = result["notice"]
    job = result.get("job")
    audit_service.log(
        db,
        action="document.uploaded",
        actor=admin,
        target_type="document",
        target_id=document.id,
        details={
            "filename": sanitize_filename(document.original_filename),
            "size_bytes": document.size_bytes,
            "notice_id": notice.id,
            "requires_manual_review": result["requires_manual_review"],
        },
        request_id=request_id,
    )
    db.commit()
    db.refresh(document)
    db.refresh(notice)
    if job is not None:
        db.refresh(job)
    return UploadResult(
        document=DocumentOut.model_validate(document),
        notice=notice_service.notice_out(db, notice),
        job=DocumentJobOut.model_validate(job) if job else None,
        extracted_fact_count=result["extracted_fact_count"],
        requires_manual_review=result["requires_manual_review"],
        message=result["message"],
    )


@router.get("/documents", response_model=Page[DocumentOut])
def list_documents(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    document_service: Annotated[DocumentService, Depends(get_document_service)],
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
) -> Page[DocumentOut]:
    if status and status not in {item.value for item in DocumentStatus}:
        raise ValidationAppError("Unknown document status")
    page, page_size = pagination
    rows, total = document_service.list_documents(
        db, page=page, page_size=page_size, status=status, search=search
    )
    return make_page([DocumentOut.model_validate(row) for row in rows], page, page_size, total)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
def get_document(document_id: str, db: DbSession) -> DocumentDetail:
    return notice_service.document_detail(db, document_id)


# ----------------------------------------------------------------------- notices
@router.get("/notices", response_model=Page[NoticeOut])
def list_notices(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    status: str | None = Query(default=None),
    category: str | None = Query(default=None, max_length=60),
    search: str | None = Query(default=None, max_length=200),
) -> Page[NoticeOut]:
    if status and status not in {item.value for item in NoticeStatus}:
        raise ValidationAppError("Unknown notice status")
    page, page_size = pagination
    items, total = notice_service.list_notices(
        db,
        page=page,
        page_size=page_size,
        published_only=False,
        status=status,
        category=category,
        search=search,
    )
    return make_page(items, page, page_size, total)


@router.get("/notices/{notice_id}", response_model=NoticeDetail)
def admin_notice_detail(notice_id: str, db: DbSession) -> NoticeDetail:
    return notice_service.notice_detail(
        db,
        notice_id,
        published_only=False,
        fact_statuses={status for status in FACT_STATUSES},
    )


@router.patch("/notices/{notice_id}", response_model=NoticeOut)
def update_notice(
    notice_id: str,
    payload: NoticeUpdate,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> NoticeOut:
    notice = notice_service.update_notice(
        db, notice_id, payload, actor=admin, request_id=request_id
    )
    db.commit()
    db.refresh(notice)
    return notice_service.notice_out(db, notice)


@router.post("/notices/{notice_id}/publish", response_model=PublishResponse)
def publish_notice(
    notice_id: str,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> PublishResponse:
    notice, count = fact_service.publish_notice_facts(
        db, notice_id, actor=admin, request_id=request_id
    )
    db.commit()
    db.refresh(notice)
    return PublishResponse(
        message="Notice published" if count else "Notice published with no approved facts",
        notice_id=notice.id,
        published_at=notice.published_at or utcnow(),
        facts_published=count,
    )


@router.post("/notices/{notice_id}/archive", response_model=NoticeOut)
def archive_notice(
    notice_id: str,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> NoticeOut:
    notice = notice_service.archive_notice(
        db, notice_id, actor=admin, request_id=request_id
    )
    db.commit()
    db.refresh(notice)
    return notice_service.notice_out(db, notice)


# ------------------------------------------------------------------------- facts
@router.get("/facts", response_model=Page[FactOut])
def list_facts(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    status: str | None = Query(default=None),
    fact_key: str | None = Query(default=None, max_length=160),
    category: str | None = Query(default=None, max_length=40),
    notice_id: str | None = Query(default=None),
    course: str | None = Query(default=None),
    semester: int | None = Query(default=None, ge=1, le=12),
    academic_year: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
) -> Page[FactOut]:
    if status and status not in FACT_STATUSES:
        raise ValidationAppError("Unknown fact status")
    page, page_size = pagination
    rows, total = fact_service.list_admin_facts(
        db,
        page=page,
        page_size=page_size,
        status=status,
        fact_key=fact_key,
        category=category,
        notice_id=notice_id,
        course=course,
        semester=semester,
        academic_year=academic_year,
        search=search,
    )
    return make_page([FactOut.model_validate(row) for row in rows], page, page_size, total)


@router.get("/facts/{fact_id}", response_model=FactDetail)
def get_fact(fact_id: str, db: DbSession) -> FactDetail:
    return fact_service.get_fact_detail(db, fact_id)


@router.patch("/facts/{fact_id}", response_model=FactDetail)
def edit_fact(
    fact_id: str,
    payload: FactEditRequest,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> FactDetail:
    fact_service.edit_fact(
        db, fact_id, payload, actor=admin, request_id=request_id
    )
    db.commit()
    return fact_service.get_fact_detail(db, fact_id)


@router.post("/facts/{fact_id}/approve", response_model=ResolveResponse)
def approve_fact(
    fact_id: str,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
    payload: ApproveFactRequest | None = None,
) -> ResolveResponse:
    options = payload or ApproveFactRequest()
    fact = fact_service.approve_fact(
        db,
        fact_id,
        actor=admin,
        note=options.note,
        publish_notice=options.publish_notice,
        request_id=request_id,
    )
    db.commit()
    return ResolveResponse(message="Fact approved", fact_id=fact.id, status=fact.status)


@router.post("/facts/{fact_id}/reject", response_model=ResolveResponse)
def reject_fact(
    fact_id: str,
    payload: RejectFactRequest,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> ResolveResponse:
    fact = fact_service.reject_fact(
        db, fact_id, actor=admin, reason=payload.reason, request_id=request_id
    )
    db.commit()
    return ResolveResponse(message="Fact rejected", fact_id=fact.id, status=fact.status)


@router.post("/facts/{fact_id}/expire", response_model=ResolveResponse)
def expire_fact(
    fact_id: str,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> ResolveResponse:
    fact = fact_service.expire_fact(
        db, fact_id, actor=admin, request_id=request_id
    )
    db.commit()
    return ResolveResponse(message="Fact expired", fact_id=fact.id, status=fact.status)


# --------------------------------------------------------------------- conflicts
@router.get("/conflicts", response_model=Page[ConflictOut])
def list_conflicts(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    status: str = Query(default=ConflictStatus.PENDING.value),
    kind: str | None = Query(default=None),
) -> Page[ConflictOut]:
    if status not in {item.value for item in ConflictStatus}:
        raise ValidationAppError("Unknown conflict status")
    if kind and kind not in {item.value for item in ConflictKind}:
        raise ValidationAppError("Unknown conflict kind")
    page, page_size = pagination
    conditions = [FactConflict.status == status]
    if kind:
        conditions.append(FactConflict.kind == kind)
    base = select(FactConflict).where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    conflicts = list(
        db.scalars(
            base.order_by(FactConflict.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    items = []
    for conflict in conflicts:
        out = ConflictOut.model_validate(conflict)
        candidate = db.get(Fact, conflict.candidate_fact_id)
        existing = db.get(Fact, conflict.existing_fact_id) if conflict.existing_fact_id else None
        if candidate:
            out.candidate_value = candidate.value_text
            out.candidate_scope = _scope_dict(candidate)
            out.candidate_notice_title = (
                db.get(Notice, candidate.notice_id).title if candidate.notice_id else None
            )
        if existing:
            out.existing_value = existing.value_text
            out.existing_scope = _scope_dict(existing)
            out.existing_notice_title = (
                db.get(Notice, existing.notice_id).title if existing.notice_id else None
            )
        items.append(out)
    return make_page(items, page, page_size, total)


@router.post("/conflicts/{conflict_id}/resolve", response_model=ResolveResponse)
def resolve_conflict(
    conflict_id: str,
    payload: ConflictResolveRequest,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> ResolveResponse:
    result = conflict_service.resolve(
        db,
        conflict_id,
        resolution=payload.resolution,
        note=payload.note,
        actor=admin,
        request_id=request_id,
    )
    db.commit()
    return ResolveResponse(
        message=result["message"],
        fact_id=result.get("fact_id"),
        status=result.get("status"),
        conflict_id=conflict_id,
    )


# -------------------------------------------------------------------- unanswered
@router.get("/unanswered", response_model=Page[UnansweredOut])
def list_unanswered(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    status: str = Query(default=UnansweredStatus.OPEN.value),
) -> Page[UnansweredOut]:
    if status not in {item.value for item in UnansweredStatus}:
        raise ValidationAppError("Unknown unanswered status")
    page, page_size = pagination
    base = select(UnansweredQuestion).where(UnansweredQuestion.status == status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(UnansweredQuestion.last_asked_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return make_page([UnansweredOut.model_validate(row) for row in rows], page, page_size, total)


@router.post("/unanswered/{question_id}/resolve", response_model=ResolveResponse)
def resolve_unanswered(
    question_id: str,
    payload: UnansweredResolveRequest,
    db: DbSession,
    admin: AdminUser,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> ResolveResponse:
    row = db.get(UnansweredQuestion, question_id)
    if row is None:
        raise NotFoundError("Unanswered question not found")
    row.status = payload.status
    row.resolution_note = payload.note
    row.resolved_by = admin.id
    row.resolved_at = utcnow()
    audit_service.log(
        db,
        action="unanswered.resolved",
        actor=admin,
        target_type="unanswered_question",
        target_id=row.id,
        details={"status": payload.status, "note": payload.note},
        request_id=request_id,
    )
    db.commit()
    return ResolveResponse(
        message=f"Question marked {payload.status}", status=payload.status
    )


# --------------------------------------------------------------------- audit log
@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    action: str | None = Query(default=None, max_length=80),
    target_type: str | None = Query(default=None, max_length=60),
    actor_id: str | None = Query(default=None),
) -> Page[AuditLogOut]:
    from app.models.audit import AuditLog

    page, page_size = pagination
    conditions = []
    if action:
        conditions.append(AuditLog.action == action)
    if target_type:
        conditions.append(AuditLog.target_type == target_type)
    if actor_id:
        conditions.append(AuditLog.actor_id == actor_id)
    base = select(AuditLog)
    if conditions:
        base = base.where(*conditions)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return make_page([AuditLogOut.model_validate(row) for row in rows], page, page_size, total)
