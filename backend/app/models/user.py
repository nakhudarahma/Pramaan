"""Users, student profiles and admin profiles."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, GUID, TimestampMixin, new_uuid, utcnow


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('student','admin')", name="ck_users_role"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="student", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    student_profile: Mapped["StudentProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    admin_profile: Mapped["AdminProfile | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="AdminProfile.user_id",
    )


class StudentProfile(Base, TimestampMixin):
    __tablename__ = "student_profiles"
    __table_args__ = (
        CheckConstraint("semester IS NULL OR (semester >= 1 AND semester <= 12)", name="ck_student_sem"),
    )

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    college: Mapped[str | None] = mapped_column(String(200), index=True)
    course: Mapped[str | None] = mapped_column(String(120), index=True)
    department: Mapped[str | None] = mapped_column(String(120))
    semester: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(40))
    academic_year: Mapped[str | None] = mapped_column(String(20), index=True)
    batch: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(60))
    language: Mapped[str] = mapped_column(String(20), nullable=False, default="en")

    user: Mapped[User] = relationship(back_populates="student_profile")


class AdminProfile(Base, TimestampMixin):
    __tablename__ = "admin_profiles"

    id: Mapped[str] = mapped_column(GUID, primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(
        GUID, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    college: Mapped[str | None] = mapped_column(String(200))
    department: Mapped[str | None] = mapped_column(String(120))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str | None] = mapped_column(GUID, ForeignKey("users.id", ondelete="SET NULL"))

    user: Mapped[User] = relationship(
        back_populates="admin_profile", foreign_keys=[user_id]
    )
