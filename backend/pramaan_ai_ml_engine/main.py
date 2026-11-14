"""
Pramaan FastAPI Backend + Live PDF Ingestion Runner (main.py)
=============================================================
Drop this file in the same folder as `pramaan_ai_engine.py` and your `sample_notices/` directory.

1. Test real PDF extraction on one of your sample notices right now:
       python main.py --ingest sample_notices/

2. Start the live API server for your frontend teammates:
       pip install fastapi uvicorn python-multipart
       uvicorn main:app --reload --port 8000

Open http://127.0.0.1:8000/docs in your browser to test every endpoint interactively!
"""

import argparse
import glob
import json
import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pramaan_ai_engine import (
    answer_volatile_query,
    classify_candidate_conflict,
    compute_specificity,
    extract_facts_from_pdf,
    format_fact_value,
    route_question,
    scopes_overlap,
)

DB_FILE = "ledger_db.json"
UPLOAD_DIR = "sample_notices"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =====================================================================
# 1. LIGHTWEIGHT JSON LEDGER STORE (Zero-setup local persistence)
# =====================================================================

def load_db() -> Dict[str, Any]:
    """Loads the local notice & fact ledger from ledger_db.json."""
    if not os.path.exists(DB_FILE):
        return {
            "notices": [],
            "facts": [],
            "change_events": [],
            "unanswered": [],
        }
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_db(db: Dict[str, Any]) -> None:
    """Persists the ledger to ledger_db.json."""
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def ingest_pdf_into_ledger(
    pdf_path: str,
    title: Optional[str] = None,
    issuer: str = "Examination & Academic Cell",
    issued_on: Optional[str] = None,
    auto_approve: bool = False,
) -> Dict[str, Any]:
    """
    Runs Step 1-4 of the Ingestion Pipeline (Section 8.4):
    1. Registers the notice in the database
    2. Calls Gemini + PyMuPDF (`extract_facts_from_pdf`) to get facts + bbox
    3. Runs `classify_candidate_conflict` against currently active facts
    4. Saves candidate facts (or auto-approves baseline notices if requested)
    """
    db = load_db()
    notice_id = len(db["notices"]) + 1
    filename = os.path.basename(pdf_path)
    issued_date = issued_on or datetime.now().strftime("%Y-%m-%d")

    notice_record = {
        "id": notice_id,
        "title": title or filename.replace(".pdf", "").replace("_", " "),
        "issuer": issuer,
        "issued_on": issued_date,
        "file_url": f"/files/{filename}",
        "local_path": pdf_path,
        "status": "published" if auto_approve else "review_pending",
    }
    db["notices"].append(notice_record)

    # Extract candidate facts with Gemini + PyMuPDF bbox
    extracted = extract_facts_from_pdf(pdf_path, notice_id=notice_id)
    active_facts = [f for f in db["facts"] if f.get("status") == "active"]

    created_facts = []
    for item in extracted:
        fact_id = len(db["facts"]) + 1
        conflict = classify_candidate_conflict(item, issued_date, active_facts)

        fact_row = {
            "id": fact_id,
            "notice_id": notice_id,
            "issued_on": issued_date,
            "fact_key": item["fact_key"],
            "type": item["type"],
            "value": item["value"],
            "unit": item.get("unit"),
            "scope": item["scope"],
            "valid_from": item.get("valid_from") or issued_date,
            "valid_to": item.get("valid_to"),
            "source": item["source"],
            "supersedes_ref": item.get("supersedes_ref"),
            "conflict_outcome": conflict["outcome"],
            "target_fact_id": conflict["target_fact_id"],
            "diff": conflict["diff"],
            "status": "active" if auto_approve else "candidate",
            "supersedes_id": None,
            "supersedes_summary": None,
        }
        db["facts"].append(fact_row)
        created_facts.append(fact_row)

    save_db(db)
    return {"notice": notice_record, "extracted_facts": created_facts}


# =====================================================================
# 2. FASTAPI APPLICATION & ENDPOINTS (Section 8.10)
# =====================================================================

app = FastAPI(
    title="Pramaan - Verified College Notice Ledger API",
    description="AI/ML Backend for PDF Fact Extraction, Conflict Detection, and Verified Student QA",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve PDF files so the frontend Source Drawer can open them
app.mount("/files", StaticFiles(directory=UPLOAD_DIR), name="files")


class AskRequest(BaseModel):
    question: str
    course: str = "B.Sc. Data Science"
    sem: str = "4"
    batch: str = "ALL"
    language: str = "en"


class FactActionRequest(BaseModel):
    action: str = "approve"  # "approve" | "reject" | "edit"
    edited_value: Optional[Dict[str, Any]] = None
    edited_scope: Optional[Dict[str, str]] = None


@app.get("/")
def health_check() -> Dict[str, Any]:
    db = load_db()
    return {
        "status": "ok",
        "service": "Pramaan AI/ML Backend",
        "notices_count": len(db["notices"]),
        "active_facts_count": sum(1 for f in db["facts"] if f["status"] == "active"),
        "candidate_facts_count": sum(1 for f in db["facts"] if f["status"] == "candidate"),
    }


@app.post("/admin/notices")
async def upload_and_extract_notice(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    issuer: str = Form("Examination Cell"),
    issued_on: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Admin drops a PDF -> stores file -> runs Gemini extraction + PyMuPDF bbox + Conflict Engine."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    dest_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    result = ingest_pdf_into_ledger(
        pdf_path=dest_path,
        title=title or file.filename,
        issuer=issuer,
        issued_on=issued_on,
        auto_approve=False,
    )
    return result


@app.get("/admin/review/{notice_id}")
def get_admin_review_screen(notice_id: int) -> Dict[str, Any]:
    """Returns candidate facts with conflict outcomes and before/after diffs for Admin Review."""
    db = load_db()
    notice = next((n for n in db["notices"] if n["id"] == notice_id), None)
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")

    candidates = [f for f in db["facts"] if f["notice_id"] == notice_id]
    return {"notice": notice, "facts": candidates}


@app.post("/admin/facts/{fact_id}/review")
def review_candidate_fact(fact_id: int, req: FactActionRequest) -> Dict[str, Any]:
    """
    Approves, edits, or rejects a candidate fact (Section 7.3 & 8.6):
    - When approved, if conflict_outcome == 'SUPERSEDES', marks the old fact as 'superseded'
      and creates a scoped 'What changed for you' alert in change_events!
    """
    db = load_db()
    fact = next((f for f in db["facts"] if f["id"] == fact_id), None)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")

    if req.action == "reject":
        fact["status"] = "rejected"
        save_db(db)
        return {"status": "rejected", "fact": fact}

    if req.edited_value is not None:
        fact["value"] = req.edited_value
    if req.edited_scope is not None:
        fact["scope"] = req.edited_scope

    # Handle supersession chain & change_events alert
    target_id = fact.get("target_fact_id")
    outcome = fact.get("conflict_outcome")

    if outcome == "SUPERSEDES" and target_id:
        old_fact = next((f for f in db["facts"] if f["id"] == target_id), None)
        if old_fact:
            old_fact["status"] = "superseded"
            fact["supersedes_id"] = old_fact["id"]
            old_val_str = format_fact_value(old_fact)
            fact["supersedes_summary"] = f"Replaces notice of {old_fact.get('issued_on')} ({old_val_str})"

            db["change_events"].append({
                "id": len(db["change_events"]) + 1,
                "fact_key": fact["fact_key"],
                "scope": fact["scope"],
                "old_fact_id": old_fact["id"],
                "new_fact_id": fact["id"],
                "old_value": old_val_str,
                "new_value": format_fact_value(fact),
                "notice_date": fact.get("issued_on"),
                "created_at": datetime.now().isoformat(),
            })
    elif outcome == "DISPUTED" and target_id:
        fact["status"] = "disputed"
        old_fact = next((f for f in db["facts"] if f["id"] == target_id), None)
        if old_fact:
            old_fact["status"] = "disputed"
        save_db(db)
        return {"status": "disputed", "fact": fact}

    fact["status"] = "active"
    save_db(db)
    return {"status": "active", "fact": fact}


@app.post("/api/ask")
def ask_pramaan(req: AskRequest) -> Dict[str, Any]:
    """
    Student Runtime Pipeline (Section 8.7):
    1. Routes question (volatile | static | unclear)
    2. Queries active, in-scope facts ordered by specificity DESC, issued_on DESC
    3. Composes answer with {fact:ID} placeholders and runs the Digit Verifier
    """
    db = load_db()
    ctx = {"course": req.course, "sem": str(req.sem), "batch": req.batch}
    route_info = route_question(req.question, ctx)
    topic_prefix = route_info.get("topic_prefix", "unknown")
    slots = route_info.get("slots", {})

    # Check if student asked about a different semester/course than their selected context bar
    if "sem" in slots and str(slots["sem"]) != str(req.sem):
        return {
            "state": "wrong_scope",
            "badge": "DIFFERENT SEMESTER SELECTED",
            "answer": (
                f"You asked about Semester {slots['sem']}, but your context bar is set to "
                f"{req.course} Sem {req.sem}. Would you like to switch your selection?"
            ),
            "route": route_info,
        }

    # Filter active or disputed facts matching topic_prefix and student scope
    candidate_matches = []
    for f in db["facts"]:
        if f["status"] not in ("active", "disputed"):
            continue
        if topic_prefix != "unknown" and not f["fact_key"].startswith(topic_prefix.split(".")[0]):
            continue
        if scopes_overlap(f["scope"], ctx):
            candidate_matches.append(f)

    # Prefer exact fact_key matches if available (unless computing total_fee across multiple fee facts)
    if topic_prefix == "fee.total_fee":
        matched = [f for f in candidate_matches if f["type"] == "fee" and f["status"] == "active"]
    else:
        exact_matches = [f for f in candidate_matches if f["fact_key"] == topic_prefix]
        matched = exact_matches if exact_matches else candidate_matches
    matched.sort(
        key=lambda f: (compute_specificity(f["scope"]), f.get("issued_on", "")),
        reverse=True,
    )

    if not matched:
        # Log in unanswered queue for admin
        db["unanswered"].append({
            "id": len(db["unanswered"]) + 1,
            "question": req.question,
            "scope": ctx,
            "intent_guess": topic_prefix,
            "created_at": datetime.now().isoformat(),
        })
        save_db(db)

    card = answer_volatile_query(req.question, matched[:3], ctx)
    card["route"] = route_info
    return card


@app.get("/api/changes")
def get_what_changed_feed(course: str = "B.Sc. Data Science", sem: str = "4") -> List[Dict[str, Any]]:
    """Returns scoped 'What changed for you' diff cards for the student's course & semester."""
    db = load_db()
    student_scope = {"course": course, "sem": str(sem), "batch": "ALL", "category": "ALL"}
    return [
        ev for ev in reversed(db["change_events"])
        if scopes_overlap(ev["scope"], student_scope)
    ]


@app.get("/api/deadlines")
def get_upcoming_deadlines(course: str = "B.Sc. Data Science", sem: str = "4") -> List[Dict[str, Any]]:
    """Returns active date/deadline facts scoped to the student."""
    db = load_db()
    student_scope = {"course": course, "sem": str(sem), "batch": "ALL", "category": "ALL"}
    deadlines = [
        f for f in db["facts"]
        if f["status"] == "active"
        and f["type"] in ("date", "schedule")
        and scopes_overlap(f["scope"], student_scope)
    ]
    return deadlines


@app.get("/api/facts/{fact_id}/source")
def get_fact_source_drawer(fact_id: int) -> Dict[str, Any]:
    """Returns notice metadata, page number, and highlight bbox for the PDF Citation Drawer."""
    db = load_db()
    fact = next((f for f in db["facts"] if f["id"] == fact_id), None)
    if not fact:
        raise HTTPException(status_code=404, detail="Fact not found")
    notice = next((n for n in db["notices"] if n["id"] == fact["notice_id"]), None)
    return {"fact": fact, "notice": notice, "source": fact["source"]}


@app.get("/admin/unanswered")
def get_unanswered_queue() -> List[Dict[str, Any]]:
    """Returns student questions that had no matching official record."""
    db = load_db()
    return db["unanswered"]




@app.get("/api/notices")
def get_notices_library() -> List[Dict[str, Any]]:
    """Section 8.10: Notice library with validity badges (current, expired, superseded)."""
    db = load_db()
    return db.get("notices", [])


@app.get("/api/calendar.ics")
def export_calendar_ics(course: str = "B.Sc. Data Science", sem: str = "4"):
    """Section 8.10: Exports active in-scope deadlines as an iCalendar (.ics) file."""
    from fastapi.responses import PlainTextResponse
    deadlines = get_upcoming_deadlines(course=course, sem=sem)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Pramaan//Verified Notice Ledger//EN"]
    for f in deadlines:
        dt = str(f.get("value", {}).get("date", "20261125")).replace("-", "")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:pramaan-fact-{f['id']}@bkbirlacollege.edu",
            f"DTSTART;VALUE=DATE:{dt}",
            f"SUMMARY:Pramaan Deadline: {f['fact_key']}",
            f"DESCRIPTION:{f.get('source', {}).get('span', '')}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    return PlainTextResponse("\r\n".join(lines), media_type="text/calendar")


class ConflictResolveRequest(BaseModel):
    winner_fact_id: int


@app.post("/admin/conflicts/{fact_id}/resolve")
def resolve_disputed_conflict(fact_id: int, req: ConflictResolveRequest) -> Dict[str, Any]:
    """Section 8.10: Admin resolves a DISPUTED conflict by choosing the winning fact."""
    db = load_db()
    target = next((f for f in db["facts"] if f["id"] == fact_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="Fact not found")
    for f in db["facts"]:
        if f["fact_key"] == target["fact_key"] and f["status"] == "disputed":
            f["status"] = "active" if f["id"] == req.winner_fact_id else "rejected"
    db.setdefault("audit_log", []).append({
        "id": len(db.get("audit_log", [])) + 1,
        "action": "resolve_conflict",
        "winner_fact_id": req.winner_fact_id,
        "at": datetime.now().isoformat(),
    })
    save_db(db)
    return {"status": "resolved", "winner_fact_id": req.winner_fact_id}


@app.get("/admin/audit")
def get_admin_audit_log() -> List[Dict[str, Any]]:
    """Section 8.10: Returns the admin audit trail."""
    db = load_db()
    return db.get("audit_log", [])


# =====================================================================
# 3. CLI BATCH INGESTION RUNNER FOR YOUR `sample_notices/` FOLDER
# =====================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest sample PDF circulars into Pramaan ledger")
    parser.add_argument(
        "--ingest",
        type=str,
        default="sample_notices",
        help="Path to a PDF file or folder of PDFs (default: sample_notices)",
    )
    parser.add_argument(
        "--approve-first",
        action="store_true",
        help="Auto-approve the first ingested PDF as the active baseline",
    )
    args = parser.parse_args()

    target = args.ingest
    pdf_files = (
        sorted(glob.glob(os.path.join(target, "*.pdf")))
        if os.path.isdir(target)
        else ([target] if os.path.exists(target) else [])
    )

    if not pdf_files:
        print(f"No PDF files found at '{target}'. Place your PDFs in '{UPLOAD_DIR}/' and re-run.")
        raise SystemExit(1)

    print(f"Found {len(pdf_files)} PDF circular(s). Starting Gemini + PyMuPDF extraction...\n")
    for idx, pdf_path in enumerate(pdf_files):
        auto_approve = (idx == 0) or args.approve_first
        print(f"[{idx + 1}/{len(pdf_files)}] Extracting: {pdf_path} (auto_approve={auto_approve}) ...")
        res = ingest_pdf_into_ledger(pdf_path, auto_approve=auto_approve)
        print(f"    -> Extracted {len(res['extracted_facts'])} fact(s):")
        for f in res["extracted_facts"]:
            print(
                f"       * {f['fact_key']} = {f['value']} | Scope: {f['scope']} "
                f"| Page {f['source']['page']} bbox={f['source']['bbox']} "
                f"| Conflict={f['conflict_outcome']}"
            )
    print(f"\nDone! Saved extracted ledger to '{DB_FILE}'.")
    print("Now start your API server with: uvicorn main:app --reload --port 8000")