"""Shared pytest fixtures.

The environment is configured before importing the application so that every
test runs against an isolated SQLite database and local storage directory.
Gemini is deliberately left unconfigured: tests must never make paid API calls.
"""
from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

import pytest

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="pramaan-tests-"))
_DB_PATH = (_TEST_ROOT / "pramaan-test.db").as_posix()
_STORAGE_PATH = (_TEST_ROOT / "storage").as_posix()

os.environ.update(
    {
        "ENVIRONMENT": "testing",
        "DATABASE_URL": f"sqlite:///{_DB_PATH}",
        "STORAGE_BACKEND": "local",
        "STORAGE_DIR": _STORAGE_PATH,
        "PUBLIC_FILE_ACCESS": "true",
        "AUTO_CREATE_TABLES": "true",
        "RATE_LIMIT_ENABLED": "false",
        "GEMINI_API_KEY": "",
        "JWT_SECRET": "test-secret-that-is-long-enough-for-hs256-signing-1234567890",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "60",
    }
)


@pytest.fixture(autouse=True)
def clean_database():
    import app.models  # noqa: F401
    from app.database import engine
    from app.models.base import Base

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db():
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pdf_factory():
    from fpdf import FPDF

    def make(lines: list[str]) -> bytes:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        for line in lines:
            pdf.cell(0, 10, line, new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    return make


@pytest.fixture
def create_admin(db):
    from app.core.security import hash_password
    from app.models.user import AdminProfile, User

    def create(
        email: str = "admin@example.com",
        password: str = "Password123",
        full_name: str = "Test Admin",
    ) -> User:
        user = User(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role="admin",
        )
        db.add(user)
        db.flush()
        db.add(AdminProfile(user_id=user.id, is_superadmin=True))
        db.commit()
        db.refresh(user)
        return user

    return create


@pytest.fixture
def admin_headers(client, create_admin):
    def create(email: str = "admin@example.com", password: str = "Password123") -> dict[str, str]:
        create_admin(email=email, password=password)
        response = client.post("/api/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return create


@pytest.fixture
def register_student(client):
    def register(
        email: str = "student@example.com",
        password: str = "Password123",
        profile: dict | None = None,
    ) -> dict[str, str]:
        response = client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": password,
                "full_name": "Test Student",
                "profile": profile
                if profile is not None
                else {
                    "course": "B.Tech",
                    "semester": 4,
                    "academic_year": "2026-27",
                },
            },
        )
        assert response.status_code == 201, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return register


@pytest.fixture
def approve_candidates(client):
    def approve(headers: dict[str, str], *, notice_id: str | None = None) -> list[dict]:
        params = {"status": "candidate", "page_size": 100}
        if notice_id:
            params["notice_id"] = notice_id
        response = client.get("/api/admin/facts", headers=headers, params=params)
        assert response.status_code == 200, response.text
        facts = response.json()["items"]
        for fact in facts:
            approved = client.post(
                f"/api/admin/facts/{fact['id']}/approve",
                headers=headers,
                json={"note": "test approval"},
            )
            assert approved.status_code == 200, approved.text
        return facts

    return approve


@pytest.fixture
def seed_ledger(db):
    """Create a minimal notice/document pair and an active fact."""
    from app.models.document import Document
    from app.models.enums import FactStatus, NoticeStatus
    from app.models.fact import Fact
    from app.models.notice import Notice
    from app.models.user import User

    def seed(
        *,
        fact_key: str = "fee.late_fee",
        value_text: str = "INR 500",
        value_number: float | None = 500.0,
        value_date: date | None = None,
        category: str = "fee",
        status: str = FactStatus.ACTIVE.value,
        effective_from: date | None = None,
        effective_to: date | None = None,
        scope: dict | None = None,
        issued_on: date = date(2026, 11, 10),
    ) -> Fact:
        scope = scope or {}
        admin = db.query(User).filter(User.role == "admin").first()
        if admin is None:
            from app.core.security import hash_password

            admin = User(
                email="seed-admin@example.com",
                password_hash=hash_password("Password123"),
                role="admin",
            )
            db.add(admin)
            db.flush()

        document = Document(
            original_filename="seed.pdf",
            content_type="application/pdf",
            size_bytes=10,
            sha256="0" * 64,
            storage_backend="local",
            storage_key="documents/seed.pdf",
            status="processed",
            uploaded_by=admin.id,
        )
        db.add(document)
        db.flush()
        notice = Notice(
            document_id=document.id,
            title="Seeded Notice",
            issued_on=issued_on,
            category=category,
            status=NoticeStatus.PUBLISHED.value,
            uploaded_by=admin.id,
        )
        db.add(notice)
        db.flush()
        fact = Fact(
            fact_key=fact_key,
            category=category,
            title=fact_key.split(".")[-1].replace("_", " ").title(),
            value_json={"text": value_text},
            value_text=value_text,
            value_number=value_number,
            value_date=value_date,
            status=status,
            version=1,
            notice_id=notice.id,
            document_id=document.id,
            page_number=1,
            source_text=value_text,
            source_precision="page",
            extraction_method="test",
            approved_at=None,
            effective_from=effective_from,
            effective_to=effective_to,
            college=scope.get("college"),
            course=scope.get("course"),
            department=scope.get("department"),
            semester=scope.get("semester"),
            academic_year=scope.get("academic_year"),
            batch=scope.get("batch"),
            student_group=scope.get("student_group"),
        )
        db.add(fact)
        db.commit()
        db.refresh(fact)
        return fact

    return seed
