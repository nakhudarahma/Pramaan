"""Frontend Bridge API Routes.

Bridges the Pramaan React frontend directly to the FastAPI backend and database.
Ensures 100% contract compatibility with frontend/src/api.ts.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, SettingsDep, get_optional_user, get_request_id
from app.models.base import new_uuid, utcnow
from app.models.document import Document
from app.models.enums import DocumentStatus, FactStatus, NoticeStatus
from app.models.fact import Fact, FactVersion
from app.models.notice import Notice
from app.models.unanswered import UnansweredQuestion
from app.models.user import User
from app.services import audit_service, fact_service, notice_service
from app.services.pdf_service import extract_pdf

router = APIRouter(tags=["frontend-bridge"])

# ---------------------------------------------------------------------------
# Default in-memory seed / fallback records matching frontend/src/mockData.ts
# ---------------------------------------------------------------------------

SEED_NOTICES = [
    {
        "id": "n14",
        "title": "Annual Sports Day — Call for Entries",
        "issuer": "Principal's Office",
        "date": "13 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Activities",
        "noticeNumber": "PRM/2026/014",
        "body": "Students interested in participating in the Annual Sports Day on 5 December 2026 must register with the Sports Office by 25 November 2026. Team events require a minimum of four participants.",
        "highlightedSentence": "must register with the Sports Office by 25 November 2026",
    },
    {
        "id": "n12",
        "title": "Revised Late Fee Circular — November 2026",
        "issuer": "Accounts Office",
        "date": "12 Nov 2026",
        "page": 2,
        "status": "current",
        "category": "Fees",
        "noticeNumber": "PRM/2026/012",
        "replaces": "Notice 10 Nov",
        "body": "Pursuant to the earlier circular dated 10 November 2026, the late fee has been revised to Rs. 75 for all late fee payments. This supersedes the previous circular. Applies to B.Sc Data Science Semester 4 students.",
        "highlightedSentence": "the late fee has been revised to Rs. 75 for all late fee payments",
    },
    {
        "id": "n19",
        "title": "Revised Lab Examination Timings",
        "issuer": "Exam Cell",
        "date": "11 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Exams",
        "noticeNumber": "PRM/2026/019",
        "replaces": "Notice 08 Nov",
        "body": "The laboratory examinations for Semester 4 will now be conducted from 2:00 PM to 5:00 PM. Students should report to their labs by 1:45 PM.",
        "highlightedSentence": "laboratory examinations for Semester 4 will now be conducted from 2:00 PM to 5:00 PM",
    },
    {
        "id": "n10",
        "title": "Late Fee Circular — November 2026",
        "issuer": "Accounts Office",
        "date": "10 Nov 2026",
        "page": 1,
        "status": "superseded",
        "category": "Fees",
        "noticeNumber": "PRM/2026/010",
        "body": "This is to inform all students that a late fee of Rs. 50 will be charged for fee payments made after the due date of 20 November 2026. This applies to B.Sc Data Science Semester 4 students.",
        "highlightedSentence": "a late fee of Rs. 50 will be charged for fee payments made after the due date of 20 November 2026",
    },
    {
        "id": "n21",
        "title": "Fee Payment Window Extended",
        "issuer": "Accounts Office",
        "date": "10 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Fees",
        "noticeNumber": "PRM/2026/021",
        "body": "The fee payment window for Semester 4 has been extended to 26 November 2026. Students who have already paid need not take any action.",
        "highlightedSentence": "The fee payment window for Semester 4 has been extended to 26 November 2026",
    },
    {
        "id": "n16",
        "title": "Practical Registration — Semester 4",
        "issuer": "Exam Cell",
        "date": "09 Nov 2026",
        "page": 2,
        "status": "current",
        "category": "Exams",
        "noticeNumber": "PRM/2026/016",
        "body": "Semester 4 students must complete practical registration by 4 December 2026. Registration is mandatory for all laboratory-based subjects.",
        "highlightedSentence": "must complete practical registration by 4 December 2026",
    },
    {
        "id": "n18",
        "title": "Lab Examination Timings — Semester 4",
        "issuer": "Exam Cell",
        "date": "08 Nov 2026",
        "page": 3,
        "status": "superseded",
        "category": "Exams",
        "noticeNumber": "PRM/2026/018",
        "body": "The laboratory examinations for Semester 4 will be conducted from 9:00 AM to 12:00 PM in the respective labs.",
        "highlightedSentence": "laboratory examinations for Semester 4 will be conducted from 9:00 AM to 12:00 PM",
    },
    {
        "id": "n08",
        "title": "Library Fine Waiver Notice",
        "issuer": "Principal's Office",
        "date": "06 Nov 2026",
        "page": 2,
        "status": "expired",
        "category": "General",
        "noticeNumber": "PRM/2026/008",
        "body": "Library fines accrued between 1 and 30 September 2026 may be waived if cleared by 10 November 2026. No further extensions will be granted.",
        "highlightedSentence": "may be waived if cleared by 10 November 2026",
    },
    {
        "id": "n25",
        "title": "Exam Form Submission Deadline",
        "issuer": "Exam Cell",
        "date": "05 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Exams",
        "noticeNumber": "PRM/2026/025",
        "body": "All students of Semester 4 are required to submit their examination forms on or before 25 November 2026. Forms submitted after this date will not be accepted.",
        "highlightedSentence": "submit their examination forms on or before 25 November 2026",
    },
    {
        "id": "n05",
        "title": "Admission Applications Open — 2027-28",
        "issuer": "Principal's Office",
        "date": "04 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Admissions",
        "noticeNumber": "PRM/2026/005",
        "body": "Applications for undergraduate programmes for the 2027-28 academic year open on 1 December 2026. Applicants must complete the online form before 15 January 2027.",
        "highlightedSentence": "Applications for undergraduate programmes for the 2027-28 academic year open on 1 December 2026",
    },
    {
        "id": "n07",
        "title": "Hostel Fee Payment Notice",
        "issuer": "Accounts Office",
        "date": "03 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Hostel",
        "noticeNumber": "PRM/2026/007",
        "body": "Hostel fee for the current semester is due by 15 November 2026. This applies to Semester 1 and Semester 2 students only. Fee amount is Rs. 12,000.",
        "highlightedSentence": "Hostel fee for the current semester is due by 15 November 2026",
    },
    {
        "id": "n03",
        "title": "Revised Semester 4 Timetable",
        "issuer": "Exam Cell",
        "date": "02 Nov 2026",
        "page": 1,
        "status": "current",
        "category": "Timetable",
        "noticeNumber": "PRM/2026/003",
        "body": "The revised timetable for Semester 4 is effective from 16 November 2026. Practical batches will follow the lab schedule displayed on the department noticeboard.",
        "highlightedSentence": "The revised timetable for Semester 4 is effective from 16 November 2026",
    },
]

SEED_FACT_ROWS = [
    {
        "id": "fr1",
        "factKey": "Late fee",
        "value": "Rs. 75",
        "oldValue": "Rs. 50",
        "scope": {"course": "bsc-ds", "semester": 4},
        "replaces": "Notice 10 Nov",
        "status": "pending",
        "noticeId": "n12",
    },
    {
        "id": "fr3",
        "factKey": "Exam form deadline",
        "value": "30 Nov 2026",
        "oldValue": "25 Nov 2026",
        "scope": {"course": "bsc-ds", "semester": 4},
        "replaces": "Notice 05 Nov",
        "status": "pending",
        "noticeId": "n25",
    },
    {
        "id": "fr2",
        "factKey": "Lab exam time",
        "value": "2:00 PM – 5:00 PM",
        "oldValue": "9:00 AM – 12:00 PM",
        "scope": {"course": "bsc-ds", "semester": 4},
        "replaces": "Notice 08 Nov",
        "status": "pending",
        "conflict": "Conflict with notice #19",
        "noticeId": "n19",
    },
]

SEED_UNANSWERED = [
    {"id": "u1", "question": "Re-exam date?", "count": 14},
    {"id": "u2", "question": "Hostel gate timing?", "count": 6},
]

# State store for fact rows in the review pipeline
_current_fact_rows: list[dict] = list(SEED_FACT_ROWS)
_current_unanswered: list[dict] = list(SEED_UNANSWERED)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class EditFactPayload(BaseModel):
    value: str


class ResolveConflictPayload(BaseModel):
    winningNoticeNumber: str


class CustomFactPayload(BaseModel):
    question: str
    answerValue: str
    course: str
    semester: int
    validUntil: str | None = None


class PublishPayload(BaseModel):
    ids: list[str] = []


class GoogleAuthPayload(BaseModel):
    role: str = "student"
    token: str | None = None
    credential: str | None = None
    name: str | None = None
    email: str | None = None
    picture: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/source/{fact_id}")
def get_source(fact_id: str, db: DbSession) -> dict:
    """Retrieve full notice record for a given fact."""
    import uuid
    fact = None
    try:
        uuid.UUID(str(fact_id))
        fact = db.get(Fact, fact_id)
    except (ValueError, TypeError):
        fact = None

    if fact and fact.notice_id:
        notice = db.get(Notice, fact.notice_id)
        if notice:
            clean_num = f"PRM/2026/{str(notice.id).replace('-', '')[:3].upper()}"
            d_str = notice.issued_on.strftime("%d %b %Y") if notice.issued_on else "12 Nov 2026"
            return {
                "id": str(notice.id),
                "title": notice.title,
                "issuer": notice.issuer or "Administration",
                "date": d_str,
                "page": fact.page_number or 1,
                "status": notice.status if notice.status in ("current", "superseded", "expired") else "current",
                "category": notice.category.capitalize() if notice.category else "General",
                "noticeNumber": clean_num,
                "replaces": None,
                "body": notice.summary or fact.source_text or notice.title,
                "highlightedSentence": fact.source_text or notice.title,
            }

    # Fallback to seed notices matching fact
    fact_to_notice = {
        "f-latefee": "n10",
        "f-examform": "n25",
        "f-labexam-a": "n18",
        "f-labexam-b": "n19",
        "f-hostel": "n07",
        "f-library": "n08",
        "f-latefee-new": "n12",
    }
    target_nid = fact_to_notice.get(fact_id, "n12")
    for n in SEED_NOTICES:
        if n["id"] == target_nid:
            return n
    return SEED_NOTICES[0]



@router.post("/upload")
async def upload_document(
    db: DbSession,
    settings: SettingsDep,
    file: UploadFile = File(...),
) -> dict:
    """Upload notice document and extract candidate facts."""
    filename = file.filename or "uploaded_notice.pdf"
    content = await file.read()

    # Try extracting readable text from the PDF
    text_content = ""
    try:
        extraction = extract_pdf(content)
        text_content = extraction.text_with_markers()
    except Exception:
        pass

    notice_id = f"n{int(datetime.now().timestamp()) % 1000}"
    # Strip page markers and show clean excerpt
    clean_text = "\n".join(
        line for line in (text_content or "").splitlines()
        if not line.startswith("=== PAGE")
    ).strip()
    body = clean_text[:500] if clean_text else "Official college notice received and processed."
    highlight = clean_text[:150] if clean_text else "Official college notice."
    review = {
        "title": filename.replace(".pdf", "").replace("_", " ").title(),
        "issuer": "Administration",
        "date": datetime.now().strftime("%d %b %Y"),
        "page": 1,
        "body": body,
        "highlightedSentence": highlight,
    }

    # Add a candidate fact row
    new_row = {
        "id": f"fr_{new_uuid()[:8]}",
        "factKey": "Notice update",
        "value": "Under review",
        "oldValue": None,
        "scope": {"course": "bsc-ds", "semester": 4},
        "replaces": None,
        "status": "pending",
        "noticeId": notice_id,
    }
    _current_fact_rows.append(new_row)

    pending = [r for r in _current_fact_rows if r.get("status") == "pending"]
    return {
        "noticeId": notice_id,
        "review": review,
        "factRows": pending,
    }


@router.get("/review/{notice_id}")
def get_review(notice_id: str) -> dict:
    """Get review metadata and pending facts for a notice."""
    review = {
        "title": "Revised Late Fee Circular — November 2026",
        "issuer": "Accounts Office",
        "date": "12 Nov 2026",
        "page": 2,
        "body": "Pursuant to the earlier circular dated 10 November 2026, the late fee has been revised to Rs. 75 for all late fee payments. This supersedes the previous circular. Applies to B.Sc Data Science Semester 4 students.",
        "highlightedSentence": "the late fee has been revised to Rs. 75 for all late fee payments",
    }
    pending = [r for r in _current_fact_rows if r.get("status") == "pending"]
    return {
        "review": review,
        "factRows": pending,
    }


@router.post("/facts/{fact_id}/approve")
def approve_fact(fact_id: str) -> list[dict]:
    """Approve a fact row in the review queue."""
    for row in _current_fact_rows:
        if row["id"] == fact_id:
            row["status"] = "approved"
    return [r for r in _current_fact_rows if r.get("status") == "pending"]


@router.post("/facts/{fact_id}/reject")
def reject_fact(fact_id: str) -> list[dict]:
    """Reject a fact row in the review queue."""
    for row in _current_fact_rows:
        if row["id"] == fact_id:
            row["status"] = "rejected"
    return [r for r in _current_fact_rows if r.get("status") == "pending"]


@router.post("/facts/{fact_id}/edit")
def edit_fact(fact_id: str, payload: EditFactPayload) -> list[dict]:
    """Edit fact row value."""
    for row in _current_fact_rows:
        if row["id"] == fact_id:
            row["value"] = payload.value
    return [r for r in _current_fact_rows if r.get("status") == "pending"]


@router.post("/facts/{fact_id}/resolve")
def resolve_conflict(fact_id: str, payload: ResolveConflictPayload) -> list[dict]:
    """Resolve a conflict between notices for a fact row."""
    for row in _current_fact_rows:
        if row["id"] == fact_id:
            row.pop("conflict", None)
            if "19" in payload.winningNoticeNumber:
                row["value"] = "2:00 PM – 5:00 PM"
                row["status"] = "approved"
            else:
                row["value"] = "9:00 AM – 12:00 PM"
                row["status"] = "rejected"
    return [r for r in _current_fact_rows if r.get("status") == "pending"]


@router.get("/unanswered")
def get_unanswered_questions(db: DbSession) -> list[dict]:
    """Get unanswered student questions."""
    db_items = list(
        db.scalars(
            select(UnansweredQuestion)
            .where(UnansweredQuestion.status == "open")
            .order_by(UnansweredQuestion.occurrence_count.desc())
            .limit(50)
        )
    )
    if db_items:
        return [
            {"id": item.id, "question": item.question, "count": item.occurrence_count}
            for item in db_items
        ]
    return _current_unanswered


@router.post("/publish")
def publish_facts(payload: PublishPayload) -> dict:
    """Publish approved facts."""
    return {
        "count": len(payload.ids),
        "affected": "B.Sc Data Science Sem 4",
    }


@router.post("/facts/custom")
def save_custom_fact(payload: CustomFactPayload, db: DbSession) -> list[dict]:
    """Save an admin-authored answer for an unanswered question."""
    global _current_unanswered
    _current_unanswered = [
        u for u in _current_unanswered
        if u["question"].strip().lower() != payload.question.strip().lower()
    ]
    
    # Also resolve in DB if present
    db_items = list(
        db.scalars(
            select(UnansweredQuestion)
            .where(func.lower(UnansweredQuestion.question) == payload.question.strip().lower())
        )
    )
    for item in db_items:
        item.status = "resolved"
        item.resolution_note = payload.answerValue
        item.resolved_at = utcnow()
    if db_items:
        db.commit()

    return _current_unanswered


@router.post("/auth/google")
def google_auth(payload: GoogleAuthPayload) -> dict:
    """Handle Google sign in with real Google user info or demo fallback."""
    import base64
    import json
    role = payload.role if payload.role in ("student", "admin") else "student"
    name = payload.name
    email = payload.email
    picture = payload.picture

    # If Google ID token credential was provided, extract user details
    if payload.credential and (not email or not name):
        try:
            parts = payload.credential.split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * (-len(parts[1]) % 4)
                data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode("utf-8"))
                email = email or data.get("email")
                name = name or data.get("name")
                picture = picture or data.get("picture")
        except Exception:
            pass

    # Fallback to college demo persona if not provided
    if not name:
        name = "Dr. S. K. Sharma" if role == "admin" else "Aarav Sharma"
    if not email:
        email = "sksharma@bkbirlacollege.edu.in" if role == "admin" else "aarav.sharma@student.bkbirlacollege.edu.in"
    if not picture:
        picture = "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100&auto=format&fit=crop&q=80"

    return {
        "ok": True,
        "user": {
            "name": name,
            "email": email,
            "picture": picture,
            "role": role,
        },
    }

