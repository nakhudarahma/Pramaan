"""FastAPI dependencies: DB, authentication, services and student scope."""
from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import UnauthorizedError
from app.core.permissions import require_admin
from app.core.security import decode_access_token
from app.database import get_db
from app.integrations.gemini_client import GeminiClient
from app.integrations.storage_client import StorageClient
from app.models.user import User
from app.schemas.student import StudentContext
from app.services.document_service import DocumentService
from app.utils.date_utils import normalize_academic_year
from app.utils.validators import normalize_scope_value

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _user_from_token(db: Session, token: str) -> User:
    payload = decode_access_token(token)
    user = db.get(User, payload.get("sub"))
    if user is None or not user.is_active:
        raise UnauthorizedError("User account is inactive or no longer exists")
    return user


def get_optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User | None:
    if credentials is None:
        return None
    return _user_from_token(db, credentials.credentials)


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required")
    return _user_from_token(db, credentials.credentials)


def get_current_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    return require_admin(user)


def get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


@lru_cache(maxsize=1)
def get_gemini_client() -> GeminiClient:
    return GeminiClient(get_settings())


@lru_cache(maxsize=1)
def get_storage_client() -> StorageClient:
    return StorageClient(get_settings())


def get_document_service(
    settings: SettingsDep,
    storage: Annotated[StorageClient, Depends(get_storage_client)],
    gemini: Annotated[GeminiClient, Depends(get_gemini_client)],
) -> DocumentService:
    return DocumentService(settings=settings, storage=storage, gemini=gemini)


def merge_context(context: StudentContext, user: User | None) -> dict:
    """Query context wins where supplied; the authenticated profile fills gaps."""
    profile = user.student_profile if user is not None else None

    def pick(field: str):
        value = getattr(context, field, None)
        if value not in (None, ""):
            return value
        return getattr(profile, field, None) if profile is not None else None

    semester = pick("semester")
    try:
        semester = int(semester) if semester not in (None, "") else None
    except (TypeError, ValueError):
        semester = None
    scope = {
        "college": normalize_scope_value(pick("college")),
        "course": normalize_scope_value(pick("course")),
        "department": normalize_scope_value(pick("department")),
        "semester": semester,
        "academic_year": normalize_academic_year(pick("academic_year")),
        "batch": normalize_scope_value(pick("batch")),
        "student_group": normalize_scope_value(pick("student_group")),
    }
    return {key: value for key, value in scope.items() if value is not None}


def student_context_out(context: StudentContext, user: User | None) -> dict:
    scope = merge_context(context, user)
    return {
        "college": scope.get("college"),
        "course": scope.get("course"),
        "department": scope.get("department"),
        "semester": scope.get("semester"),
        "section": context.section or (
            user.student_profile.section if user is not None and user.student_profile else None
        ),
        "academic_year": scope.get("academic_year"),
        "batch": scope.get("batch"),
        "student_group": scope.get("student_group"),
        "language": context.language,
    }
