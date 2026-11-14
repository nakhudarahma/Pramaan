"""Authentication, registration and profile endpoints."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbSession, SettingsDep, get_current_user, get_request_id
from app.config import get_settings
from app.core.exceptions import ConflictError, UnauthorizedError
from app.core.permissions import require_student
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, hash_password, verify_password
from app.models.base import utcnow
from app.models.user import StudentProfile, User
from app.repositories import user_repository
from app.schemas.auth import (
    MeResponse,
    LoginRequest,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services import audit_service
from app.utils.validators import normalize_academic_year, normalize_semester

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: User, settings) -> TokenResponse:
    token = create_access_token(user.id, user.role)
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        user=UserOut.model_validate(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[
        Depends(rate_limit("register", lambda: get_settings().rate_limit_register_per_hour, 3600))
    ],
)
def register(
    payload: RegisterRequest,
    db: DbSession,
    settings: SettingsDep,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> TokenResponse:
    if user_repository.get_by_email(db, payload.email):
        raise ConflictError("An account with this email already exists")
    profile = payload.profile.model_dump(exclude_none=True) if payload.profile else {}
    if profile.get("semester") is not None:
        profile["semester"] = normalize_semester(profile["semester"])
    if profile.get("academic_year"):
        profile["academic_year"] = normalize_academic_year(profile["academic_year"])
    try:
        user = user_repository.create_student(
            db,
            email=payload.email,
            password_hash=hash_password(payload.password),
            full_name=payload.full_name,
            profile=profile,
        )
        audit_service.log(
            db,
            action="user.registered",
            actor=user,
            target_type="user",
            target_id=user.id,
            request_id=request_id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("An account with this email already exists") from exc
    db.refresh(user)
    return _token_response(user, settings)


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit("login", lambda: get_settings().rate_limit_login_per_minute))],
)
def login(
    payload: LoginRequest,
    db: DbSession,
    settings: SettingsDep,
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> TokenResponse:
    user = user_repository.get_by_email(db, payload.email)
    if user is None or not verify_password(payload.password, user.password_hash):
        # Deliberately identical error for unknown user and bad password.
        raise UnauthorizedError("Invalid email or password")
    if not user.is_active:
        raise UnauthorizedError("This account is inactive")
    user.last_login_at = utcnow()
    audit_service.log(
        db,
        action="user.login",
        actor=user,
        target_type="user",
        target_id=user.id,
        request_id=request_id,
    )
    db.commit()
    db.refresh(user)
    return _token_response(user, settings)


@router.get("/me", response_model=MeResponse)
def me(user: Annotated[User, Depends(get_current_user)]) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(user),
        student_profile=user.student_profile,
        admin_profile=user.admin_profile,
    )


@router.patch("/me/profile", response_model=MeResponse)
def update_profile(
    payload: ProfileUpdateRequest,
    db: DbSession,
    user: Annotated[User, Depends(get_current_user)],
    request_id: Annotated[str | None, Depends(get_request_id)],
) -> MeResponse:
    require_student(user)
    profile = user.student_profile
    if profile is None:
        profile = StudentProfile(user_id=user.id)
        db.add(profile)
        db.flush()
    updates = payload.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "semester" and value is not None:
            profile.semester = normalize_semester(value)
        elif key == "academic_year":
            profile.academic_year = normalize_academic_year(value)
        else:
            setattr(profile, key, value)
    audit_service.log(
        db,
        action="student_profile.updated",
        actor=user,
        target_type="student_profile",
        target_id=profile.id,
        details={"fields": sorted(updates.keys())},
        request_id=request_id,
    )
    db.commit()
    db.refresh(user)
    return MeResponse(
        user=UserOut.model_validate(user),
        student_profile=user.student_profile,
        admin_profile=user.admin_profile,
    )
