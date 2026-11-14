"""Authentication and profile schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.common import ORMModel
from app.utils.validators import normalize_semester


class StudentProfileIn(BaseModel):
    college: str | None = Field(default=None, max_length=200)
    course: str | None = Field(default=None, max_length=120)
    department: str | None = Field(default=None, max_length=120)
    semester: int | None = Field(default=None, ge=1, le=12)
    section: str | None = Field(default=None, max_length=40)
    academic_year: str | None = Field(default=None, max_length=20)
    batch: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=60)
    language: str = Field(default="en", max_length=20)


class StudentProfileOut(ORMModel):
    id: str
    college: str | None
    course: str | None
    department: str | None
    semester: int | None
    section: str | None
    academic_year: str | None
    batch: str | None
    category: str | None
    language: str


class AdminProfileOut(ORMModel):
    id: str
    college: str | None
    department: str | None
    is_superadmin: bool


class UserOut(ORMModel):
    id: str
    email: EmailStr
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class MeResponse(BaseModel):
    user: UserOut
    student_profile: StudentProfileOut | None = None
    admin_profile: AdminProfileOut | None = None


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=200)
    profile: StudentProfileIn | None = None

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class ProfileUpdateRequest(StudentProfileIn):
    pass


def coerce_semester(value):
    return normalize_semester(value)
