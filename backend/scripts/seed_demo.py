"""Seed a small, realistic demo dataset for local development.

Usage (from the Backend directory):
    python -m scripts.seed_demo

Creates a student, a published notice, three active verified facts, calendar
data and narrative chunks. Safe to run repeatedly: the notice is only seeded
once. Production requires --force.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings, load_dotenv_if_present  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models.base import utcnow  # noqa: E402
from app.models.chunk import Chunk  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.enums import DocumentStatus, FactStatus, NoticeStatus  # noqa: E402
from app.models.fact import Fact, FactVersion  # noqa: E402
from app.models.notice import Notice  # noqa: E402
from app.models.user import User  # noqa: E402
from app.repositories import user_repository  # noqa: E402
from app.services import calendar_service  # noqa: E402
from app.utils.validators import compute_active_scope_key  # noqa: E402
from scripts.create_admin import ensure_admin  # noqa: E402

DEMO_TITLE = "Demo Fee and Policy Notice 2026"
DEMO_STUDENT_EMAIL = "student@example.edu"
DEMO_STUDENT_PASSWORD = "Student123!"


def _scope() -> dict:
    return {
        "college": None,
        "course": None,
        "department": None,
        "semester": None,
        "academic_year": None,
        "batch": None,
        "student_group": None,
    }


def _snapshot(fact: Fact) -> dict:
    return {
        "fact_key": fact.fact_key,
        "value_text": fact.value_text,
        "value_json": fact.value_json,
        "status": fact.status,
        "version": fact.version,
        "course": fact.course,
        "semester": fact.semester,
        "academic_year": fact.academic_year,
    }


def _add_fact(
    db,
    *,
    notice: Notice,
    admin: User | None,
    fact_key: str,
    category: str,
    title: str,
    value_text: str,
    value_json: dict,
    source_text: str,
    value_number: float | None = None,
    value_date: date | None = None,
    currency: str | None = None,
) -> Fact:
    fact = Fact(
        fact_key=fact_key,
        category=category,
        title=title,
        value_json=value_json,
        value_text=value_text,
        value_number=value_number,
        value_date=value_date,
        currency=currency,
        effective_from=date(2026, 11, 1),
        notice_id=notice.id,
        document_id=notice.document_id,
        page_number=1,
        source_text=source_text,
        source_bbox=[72.0, 100.0, 520.0, 122.0],
        source_precision="exact",
        extraction_confidence=1.0,
        extraction_method="demo_seed",
        status=FactStatus.ACTIVE.value,
        version=2,
        approved_by=admin.id if admin else None,
        approved_at=utcnow(),
        published_at=utcnow(),
        active_scope_key=compute_active_scope_key(fact_key, _scope()),
    )
    db.add(fact)
    db.flush()
    db.add(
        FactVersion(
            fact_id=fact.id,
            version_number=1,
            change_type="extracted",
            snapshot={**_snapshot(fact), "status": FactStatus.CANDIDATE.value, "version": 1},
            note="Demo seed",
        )
    )
    db.add(
        FactVersion(
            fact_id=fact.id,
            version_number=2,
            change_type="approved",
            snapshot=_snapshot(fact),
            changed_by=admin.id if admin else None,
            note="Demo seed approval",
        )
    )
    return fact


def main() -> int:
    load_dotenv_if_present(str(ROOT / ".env"))
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Seed a Pramaan demo dataset")
    parser.add_argument("--force", action="store_true", help="Allow seeding in production")
    args = parser.parse_args()

    if settings.environment == "production" and not args.force:
        print("error: refusing to seed demo data in production without --force", file=sys.stderr)
        return 1

    init_db()
    with SessionLocal() as db:
        admin = None
        if settings.admin_email and settings.admin_password:
            admin_id = ensure_admin(
                email=settings.admin_email,
                password=settings.admin_password,
                full_name=settings.admin_name,
            )
            admin = db.get(User, admin_id)

        student = user_repository.get_by_email(db, DEMO_STUDENT_EMAIL)
        if student is None:
            student = user_repository.create_student(
                db,
                email=DEMO_STUDENT_EMAIL,
                password_hash=hash_password(DEMO_STUDENT_PASSWORD),
                full_name="Demo Student",
                profile={
                    "college": "Demo Institute of Technology",
                    "course": "B.Tech",
                    "department": "Computer Science",
                    "semester": 4,
                    "section": "A",
                    "academic_year": "2026-27",
                },
            )
            db.flush()

        existing = db.scalar(select(Notice).where(Notice.title == DEMO_TITLE))
        if existing is not None:
            db.commit()
            print(f"demo already seeded: notice={existing.id}")
            print(f"student login: {DEMO_STUDENT_EMAIL} / {DEMO_STUDENT_PASSWORD}")
            return 0

        document = Document(
            original_filename="demo-notice.pdf",
            content_type="application/pdf",
            size_bytes=0,
            sha256=hashlib.sha256(b"pramaan-demo-notice").hexdigest(),
            storage_backend=settings.storage_backend,
            storage_key="demo/demo-notice.pdf",
            page_count=1,
            status=DocumentStatus.PROCESSED.value,
            processed_at=utcnow(),
            uploaded_by=admin.id if admin else None,
        )
        db.add(document)
        db.flush()

        notice = Notice(
            document_id=document.id,
            title=DEMO_TITLE,
            issuer="Demo Institute of Technology",
            issued_on=date(2026, 11, 1),
            category="general",
            summary="Demo notice used for local evaluation of fee, exam and attendance questions.",
            status=NoticeStatus.PUBLISHED.value,
            uploaded_by=admin.id if admin else None,
            published_at=utcnow(),
        )
        db.add(notice)
        db.flush()

        _add_fact(
            db,
            notice=notice,
            admin=admin,
            fact_key="fee.late_fee",
            category="fee",
            title="Late fee",
            value_text="INR 500",
            value_json={"amount": 500, "currency": "INR"},
            value_number=500,
            currency="INR",
            source_text="A late fee of INR 500 will apply to fee payments received after 20 November 2026.",
        )
        exam_fact = _add_fact(
            db,
            notice=notice,
            admin=admin,
            fact_key="date.exam_date",
            category="date",
            title="Mid-semester examination",
            value_text="20 November 2026",
            value_json={"date": "2026-11-20"},
            value_date=date(2026, 11, 20),
            source_text="The mid-semester examination will begin on 20 November 2026.",
        )
        _add_fact(
            db,
            notice=notice,
            admin=admin,
            fact_key="policy.attendance_requirement",
            category="policy",
            title="Attendance requirement",
            value_text="75% attendance is required to appear for the end-semester examination.",
            value_json={"minimum_percentage": 75},
            source_text="Students must maintain at least 75% attendance to appear for the end-semester examination.",
        )

        chunk_texts = [
            "A late fee of INR 500 will apply to fee payments received after 20 November 2026.",
            "The mid-semester examination will begin on 20 November 2026.",
            "Students must maintain at least 75% attendance to appear for the end-semester examination. Attendance below 75% may lead to detention.",
        ]
        for index, text in enumerate(chunk_texts):
            db.add(
                Chunk(
                    notice_id=notice.id,
                    document_id=document.id,
                    page_number=1,
                    chunk_index=index,
                    text=text,
                    scope_json=_scope(),
                    token_count=len(text.split()),
                )
            )

        db.flush()
        calendar_service.sync_event_for_fact(db, exam_fact)
        db.commit()

        print(f"demo seeded: notice={notice.id}")
        print(f"student login: {DEMO_STUDENT_EMAIL} / {DEMO_STUDENT_PASSWORD}")
        if admin:
            print(f"admin login: {admin.email}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
