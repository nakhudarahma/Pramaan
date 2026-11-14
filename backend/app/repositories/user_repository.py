"""User persistence helpers."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.user import AdminProfile, StudentProfile, User


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower().strip()))


def get_by_id(db: Session, user_id: str) -> User | None:
    return db.get(User, user_id)


def create_user(
    db: Session,
    *,
    email: str,
    password_hash: str,
    full_name: str | None,
    role: str = UserRole.STUDENT.value,
) -> User:
    user = User(
        email=email.lower().strip(),
        password_hash=password_hash,
        full_name=full_name,
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def create_student(
    db: Session,
    *,
    email: str,
    password_hash: str,
    full_name: str | None,
    profile: dict | None = None,
) -> User:
    user = create_user(
        db, email=email, password_hash=password_hash, full_name=full_name, role=UserRole.STUDENT.value
    )
    student_profile = StudentProfile(user_id=user.id, **(profile or {}))
    db.add(student_profile)
    db.flush()
    return user


def create_admin(
    db: Session,
    *,
    email: str,
    password_hash: str,
    full_name: str | None,
    department: str | None = None,
    is_superadmin: bool = True,
) -> User:
    user = create_user(
        db, email=email, password_hash=password_hash, full_name=full_name, role=UserRole.ADMIN.value
    )
    db.add(
        AdminProfile(user_id=user.id, department=department, is_superadmin=is_superadmin)
    )
    db.flush()
    return user
