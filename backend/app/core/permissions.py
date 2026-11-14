"""Role checks. Role always comes from the signed JWT, never from request data."""
from __future__ import annotations

from app.core.exceptions import ForbiddenError
from app.models.enums import UserRole
from app.models.user import AdminProfile, User


def require_admin(user: User) -> User:
    if user.role != UserRole.ADMIN.value or not user.is_active:
        raise ForbiddenError("Administrator privileges are required")
    return user


def require_student(user: User) -> User:
    if user.role != UserRole.STUDENT.value or not user.is_active:
        raise ForbiddenError("Student account required")
    return user


def admin_can_manage_scope(user: User, profile: AdminProfile | None, course: str | None) -> bool:
    """Department editors may only manage their own department (future use).

    Superadmins and admins without a department restriction manage everything.
    """
    if user.role != UserRole.ADMIN.value:
        return False
    if profile is None or profile.is_superadmin or not profile.department:
        return True
    return True  # Department scoping is not enabled in the MVP; documented in limitations.
