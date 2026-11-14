"""Student-facing APIs: ask, dashboard, deadlines, changes, notices, calendar."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    DbSession,
    SettingsDep,
    get_gemini_client,
    get_optional_user,
    get_request_id,
    get_storage_client,
    merge_context,
    student_context_out,
)
from app.api.pagination import make_page, page_params
from app.config import get_settings
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.core.rate_limit import rate_limit
from app.integrations.gemini_client import GeminiClient
from app.integrations.storage_client import StorageClient
from app.models.base import utcnow
from app.models.enums import FactStatus
from app.models.user import User
from app.repositories import fact_repository
from app.schemas.answer import AnswerResponse, AskRequest
from app.schemas.calendar import CalendarResponse
from app.schemas.common import Page
from app.schemas.notice import NoticeDetail, NoticeOut
from app.schemas.student import (
    ChangeOut,
    DashboardResponse,
    DeadlineOut,
    FactSourceResponse,
    StudentContext,
)
from app.services import answer_service, calendar_service, fact_service, notice_service
from app.utils.validators import sanitize_filename

router = APIRouter(tags=["students"])

OptionalUser = Annotated[User | None, Depends(get_optional_user)]


@router.post(
    "/ask",
    response_model=AnswerResponse,
    dependencies=[Depends(rate_limit("ask", lambda: get_settings().rate_limit_ask_per_minute))],
)
def ask(
    payload: AskRequest,
    db: DbSession,
    settings: SettingsDep,
    gemini: Annotated[GeminiClient, Depends(get_gemini_client)],
    user: OptionalUser = None,
    request_id: Annotated[str | None, Depends(get_request_id)] = None,
) -> AnswerResponse:
    response = answer_service.ask(
        db,
        payload,
        user=user,
        gemini=gemini,
        settings=settings,
        request_id=request_id,
    )
    db.commit()
    return response


@router.get(
    "/ask",
    response_model=AnswerResponse,
    dependencies=[Depends(rate_limit("ask", lambda: get_settings().rate_limit_ask_per_minute))],
)
def ask_get(
    db: DbSession,
    settings: SettingsDep,
    gemini: Annotated[GeminiClient, Depends(get_gemini_client)],
    q: str = Query(..., min_length=1, max_length=1000),
    course: str | None = Query(default=None),
    sem: int | None = Query(default=None),
    semester: int | None = Query(default=None),
    user: OptionalUser = None,
    request_id: Annotated[str | None, Depends(get_request_id)] = None,
) -> AnswerResponse:
    effective_sem = sem if sem is not None else semester
    payload = AskRequest(question=q, course=course, semester=effective_sem)
    response = answer_service.ask(
        db,
        payload,
        user=user,
        gemini=gemini,
        settings=settings,
        request_id=request_id,
    )
    db.commit()
    return response


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    context: Annotated[StudentContext, Depends()],
    db: DbSession,
    user: OptionalUser = None,
) -> DashboardResponse:
    scope = merge_context(context, user)
    fact_service.expire_active_facts(db)
    deadlines = [
        DeadlineOut(**item)
        for item in fact_service.deadlines_for_scope(db, scope, limit=5)
    ]
    changes = [ChangeOut(**item) for item in fact_service.changes_for_scope(db, scope, limit=5)]
    notices = [item.model_dump() for item in notice_service.published_notices_for_dashboard(db, limit=5)]
    disputes = len(fact_repository.disputed_for_scope(db, scope))
    db.commit()
    return DashboardResponse(
        context=StudentContext(**student_context_out(context, user)),
        deadlines=deadlines,
        changes=changes,
        notices=notices,
        unresolved_disputes=disputes,
        generated_at=utcnow(),
    )


@router.get("/deadlines", response_model=list[DeadlineOut])
def deadlines(
    context: Annotated[StudentContext, Depends()],
    db: DbSession,
    user: OptionalUser = None,
    sem: int | None = Query(default=None),
    days_ahead: int | None = Query(default=None, ge=0, le=3650),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[DeadlineOut]:
    if sem is not None and context.semester is None:
        context.semester = sem
    scope = merge_context(context, user)
    fact_service.expire_active_facts(db)
    items = fact_service.deadlines_for_scope(
        db, scope, limit=limit, days_ahead=days_ahead
    )
    db.commit()
    return [DeadlineOut(**item) for item in items]


@router.get("/changes", response_model=list[ChangeOut])
def changes(
    context: Annotated[StudentContext, Depends()],
    db: DbSession,
    user: OptionalUser = None,
    sem: int | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[ChangeOut]:
    if sem is not None and context.semester is None:
        context.semester = sem
    scope = merge_context(context, user)
    items = fact_service.changes_for_scope(db, scope, limit=limit)
    return [ChangeOut(**item) for item in items]


@router.get("/facts/{fact_id}/source", response_model=FactSourceResponse)
def fact_source(fact_id: str, db: DbSession) -> FactSourceResponse:
    fact = fact_service.get_fact(db, fact_id)
    visible = {
        FactStatus.ACTIVE.value,
        FactStatus.SUPERSEDED.value,
        FactStatus.EXPIRED.value,
    }
    if fact.status not in visible:
        raise NotFoundError("Fact not found")
    notice = notice_service.get_notice(db, fact.notice_id, published_only=True)
    from app.models.document import Document

    document = db.get(Document, fact.document_id)
    return FactSourceResponse(
        fact_id=fact.id,
        fact_key=fact.fact_key,
        value_text=fact.value_text,
        status=fact.status,
        effective_from=fact.effective_from,
        effective_to=fact.effective_to,
        notice_id=notice.id,
        notice_title=notice.title,
        issuer=notice.issuer,
        issued_on=notice.issued_on,
        document_id=fact.document_id,
        document_name=document.original_filename if document is not None else None,
        page_number=fact.page_number,
        source_text=fact.source_text,
        source_bbox=fact.source_bbox,
        source_precision=fact.source_precision,
        file_url=f"/api/notices/{notice.id}/file",
    )


@router.get("/notices", response_model=Page[NoticeOut])
def notices(
    db: DbSession,
    pagination: Annotated[tuple[int, int], Depends(page_params)],
    category: str | None = Query(default=None, max_length=60),
    search: str | None = Query(default=None, max_length=200),
) -> Page[NoticeOut]:
    page, page_size = pagination
    items, total = notice_service.list_notices(
        db,
        page=page,
        page_size=page_size,
        published_only=True,
        category=category,
        search=search,
    )
    return make_page(items, page, page_size, total)


@router.get("/notices/{notice_id}", response_model=NoticeDetail)
def notice_detail(notice_id: str, db: DbSession) -> NoticeDetail:
    return notice_service.notice_detail(db, notice_id, published_only=True)


@router.get("/notices/{notice_id}/file")
def notice_file(
    notice_id: str,
    db: DbSession,
    settings: SettingsDep,
    storage: Annotated[StorageClient, Depends(get_storage_client)],
    user: OptionalUser = None,
) -> Response:
    notice = notice_service.get_notice(db, notice_id, published_only=True)
    if not settings.public_file_access and user is None:
        raise UnauthorizedError("Authentication required to download this document")
    from app.models.document import Document

    document = db.get(Document, notice.document_id)
    if document is None:
        raise NotFoundError("Document not found")
    data = storage.read(document.storage_key)
    filename = sanitize_filename(document.original_filename)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=60",
        },
    )


def _calendar_events(db: Session, scope: dict):
    fact_service.expire_active_facts(db)
    deadlines = fact_service.deadlines_for_scope(db, scope, limit=500)
    return calendar_service.list_events(db, [item["fact_id"] for item in deadlines])


@router.get("/calendar", response_model=CalendarResponse)
def calendar(
    context: Annotated[StudentContext, Depends()],
    db: DbSession,
    settings: SettingsDep,
    user: OptionalUser = None,
) -> CalendarResponse:
    scope = merge_context(context, user)
    events = _calendar_events(db, scope)
    db.commit()
    return CalendarResponse(
        timezone=settings.timezone,
        generated_at=utcnow(),
        events=events,
    )


@router.get("/calendar/ics", operation_id="calendar_ics")
@router.get("/calendar.ics", operation_id="calendar_ics_legacy")
def calendar_ics(
    context: Annotated[StudentContext, Depends()],
    db: DbSession,
    settings: SettingsDep,
    user: OptionalUser = None,
) -> Response:
    scope = merge_context(context, user)
    events = _calendar_events(db, scope)
    ics = calendar_service.generate_ics(events, timezone_name=settings.timezone)
    db.commit()
    return Response(
        content=ics,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="pramaan-calendar.ics"',
            "Cache-Control": "private, max-age=300",
        },
    )
