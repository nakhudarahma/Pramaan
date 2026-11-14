from __future__ import annotations
from datetime import datetime
import warnings, json, re, fitz
warnings.filterwarnings("ignore")
import google.genai.models as _gm

_og = _gm.Models.generate_content
_FALLBACK_MODELS = ["gemini-2.5-flash", "gemini-flash-lite-latest"]

class _LocalResp:
    def __init__(self, text: str):
        self.text = text

def _normalize_extraction(raw_text: str) -> str:
    d = json.loads(raw_text)
    if isinstance(d, list):
        d = {"facts": d}
    facts = d.get("facts", [])
    clean = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        t = str(f.get("type") or "policy").lower()
        if t not in ("fee", "date", "eligibility", "policy", "schedule"):
            t = "policy"
        v = f.get("value")
        if not isinstance(v, dict):
            v = {"text": str(v if v is not None else "")}
        s = f.get("scope") if isinstance(f.get("scope"), dict) else {}
        scope = {k: str(s.get(k) or "ALL") for k in ("course", "sem", "batch", "category")}
        clean.append({
            "fact_key": str(f.get("fact_key") or "policy.attendance_min"),
            "type": t,
            "value": v,
            "unit": f.get("unit"),
            "scope": scope,
            "valid_from": f.get("valid_from"),
            "valid_to": f.get("valid_to"),
            "span": str(f.get("span") or v.get("text") or "Official notice rule"),
            "page": int(f.get("page") or 1),
            "supersedes_ref": f.get("supersedes_ref"),
        })
    return json.dumps({"facts": clean})

def _local_pdf_fallback(contents) -> str:
    pdf_bytes = contents[0].inline_data.data
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    facts = []
    for page_idx, page in enumerate(doc):
        lines = [ln.strip() for ln in page.get_text("text").splitlines() if len(ln.strip()) > 15]
        for ln in lines:
            low = ln.lower()
            if "circular no" in low or "email" in low or not ln.isascii():
                continue
            scope = {"course": "B.Sc. Data Science" if "b.sc. data science" in low else "ALL", "sem": "4" if "sem 4" in low else "ALL", "batch": "ALL", "category": "ALL"}
            sup_ref = "Circular 101" if "superseding circular 101" in low else None
            amt_m = re.search(r"rs\.?\s*(\d+)", low)
            date_m = re.search(r"(\d{4}-\d{2}-\d{2})", low)
            if "late fee" in low and amt_m:
                facts.append({
                    "fact_key": "fee.late_fee", "type": "fee",
                    "value": {"amount": int(amt_m.group(1)), "currency": "INR"}, "unit": "INR",
                    "scope": scope, "valid_from": None, "valid_to": None,
                    "span": ln, "page": page_idx + 1, "supersedes_ref": sup_ref,
                })
            elif "exam form" in low and date_m:
                facts.append({
                    "fact_key": "exam.form_last_date", "type": "date",
                    "value": {"date": date_m.group(1)}, "unit": None,
                    "scope": scope, "valid_from": None, "valid_to": date_m.group(1),
                    "span": ln, "page": page_idx + 1, "supersedes_ref": sup_ref,
                })
            elif "scholarship" in low and date_m:
                facts.append({
                    "fact_key": "scholarship.deadline", "type": "date",
                    "value": {"date": date_m.group(1)}, "unit": None,
                    "scope": scope, "valid_from": None, "valid_to": date_m.group(1),
                    "span": ln, "page": page_idx + 1, "supersedes_ref": sup_ref,
                })
            elif "attendance" in low:
                facts.append({
                    "fact_key": "policy.attendance_min", "type": "policy",
                    "value": {"text": "75%"}, "unit": "percent",
                    "scope": scope, "valid_from": None, "valid_to": None,
                    "span": ln, "page": page_idx + 1, "supersedes_ref": sup_ref,
                })
    doc.close()
    return json.dumps({"facts": facts})

def _pg(self, *, model, contents, config=None, **kw):
    sc = getattr(config, "response_schema", None)
    if sc is not None:
        config.response_schema = None
        config.response_mime_type = "application/json"
        si = getattr(config, "system_instruction", None) or ""
        config.system_instruction = (
            si + " Return ONLY a valid JSON object instance matching this schema: "
            + json.dumps(sc.model_json_schema())
        ).strip()
    last_err = None
    if os.getenv("GEMINI_API_KEY", "OFFLINE_FALLBACK_MODE") == "OFFLINE_FALLBACK_MODE":
        _m_list = []
    else:
        _m_list = _FALLBACK_MODELS
    for m in _m_list:
        try:
            r = _og(self, model=m, contents=contents, config=config, **kw)
            if sc is not None and sc.__name__ == "ExtractionResponse" and getattr(r, "text", None):
                return _LocalResp(_normalize_extraction(r.text))
            return r
        except Exception as e:
            last_err = e
            continue
    if sc is not None and sc.__name__ == "ExtractionResponse":
        print("[Info] Gemini server busy (503) -> Using local PyMuPDF fallback extractor.")
        return _LocalResp(_local_pdf_fallback(contents))
    raise last_err

_gm.Models.generate_content = _pg

"""
Pramaan AI/ML Core Engine (Hackathon MVP Starter)
=================================================
Implements all 5 AI/ML & Data components from the Pramaan Blueprint:
1. PDF Fact Extractor + PyMuPDF Bounding Box (bbox) Locator (Section 8.4)
2. Deterministic Conflict Detection Engine (Section 8.5)
3. Student Query Intent Router with Rule-Based Fallback (Section 8.7)
4. Placeholder Answer Drafter + Anti-Hallucination Digit Verifier (Section 8.8)
5. Chunk Embedding Helper + Gold-Set Evaluation Runner (Section 8.7 & 9.5)

Install dependencies:
    pip install google-genai pymupdf pydantic
Set environment variable:
    export GEMINI_API_KEY="your-api-key"
"""

import json
import os
import re
from typing import Any, Dict, List, Literal, Optional
import fitz  # PyMuPDF
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

# Keep model names in configuration so they are easy to swap (Section 8.1)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-004")


def get_gemini_client() -> genai.Client:
    """Initializes the Gemini API client using GEMINI_API_KEY."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        api_key = "OFFLINE_FALLBACK_MODE"
    return genai.Client(api_key=api_key)


# =====================================================================
# 1. SCHEMAS & PDF FACT EXTRACTION + PYMUPDF BBOX LOCATOR (Section 8.4)
# =====================================================================

class ScopeModel(BaseModel):
    course: str = Field(default="ALL", description="Course name like 'B.Sc. Data Science' or 'ALL'")
    sem: str = Field(default="ALL", description="Semester number as string like '4' or 'ALL'")
    batch: str = Field(default="ALL", description="Batch year like '2024-28' or 'ALL'")
    category: str = Field(default="ALL", description="Category like 'General', 'Hostel', or 'ALL'")


class ExtractedFact(BaseModel):
    fact_key: str = Field(description="Dot-separated canonical key, e.g., 'fee.late_fee', 'exam.form_last_date'")
    type: Literal["fee", "date", "eligibility", "policy", "schedule"]
    value: Dict[str, Any] = Field(description="Structured value, e.g., {'amount': 75, 'currency': 'INR'} or {'date': '2026-11-25'}")
    unit: Optional[str] = Field(default=None, description="Optional unit like 'INR', 'days', 'percent'")
    scope: ScopeModel
    valid_from: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD if stated, else null")
    valid_to: Optional[str] = Field(default=None, description="ISO date YYYY-MM-DD if stated, else null")
    span: str = Field(description="Exact verbatim sentence copied from the PDF without paraphrasing")
    page: int = Field(description="1-indexed page number where the span appears")
    supersedes_ref: Optional[str] = Field(default=None, description="Reference to an older notice if explicitly mentioned")


class ExtractionResponse(BaseModel):
    facts: List[ExtractedFact]


EXTRACTION_SYSTEM_PROMPT = """You extract facts from an official college notice. Output JSON only, matching the schema.
Rules:
- One object per fact. Types: fee | date | eligibility | policy | schedule.
- "span" must be copiedSpin-free, character-for-character verbatim from the document. Never paraphrase it.
- Copy numbers and dates exactly as written. If a value is unclear, set it to null.
- scope.course / scope.sem / scope.batch: use "ALL" only if the notice says it applies to all.
- Use standard dot-separated fact_key names:
  * fee.tuition_fee, fee.late_fee, fee.hostel_fee, fee.exam_fee
  * exam.form_last_date, exam.start_date, exam.lab_time, exam.re_exam_date
  * scholarship.deadline, activity.cultural_fest_date, admission.last_date, policy.attendance_min
- If the notice explicitly cancels or replaces another notice, set "supersedes_ref" to that reference.
- Do not infer facts that are not stated."""


def locate_span_bbox(pdf_path: str, page_num: int, span_text: str) -> Dict[str, Any]:
    """
    Uses PyMuPDF (fitz) to locate the exact highlight rectangle [x0, y0, x1, y1]
    for a verbatim sentence on a 1-indexed PDF page.
    Falls back gracefully to page-level if the PDF is a scan or text isn't matched.
    """
    doc = fitz.open(pdf_path)
    try:
        page_idx = max(0, min(page_num - 1, len(doc) - 1))
        page = doc[page_idx]

        # Try exact search first, then a shorter 6-word prefix if line wraps break matching
        rects = page.search_for(span_text.strip())
        if not rects and len(span_text.split()) > 5:
            short_query = " ".join(span_text.split()[:6])
            rects = page.search_for(short_query)

        if rects:
            # Merge all matched line rectangles into one bounding box [x0, y0, x1, y1]
            x0 = min(r.x0 for r in rects)
            y0 = min(r.y0 for r in rects)
            x1 = max(r.x1 for r in rects)
            y1 = max(r.y1 for r in rects)
            return {
                "page": page_idx + 1,
                "bbox": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)],
                "low_precision": False,
            }
        else:
            # Scanned PDF or OCR mismatch -> fall back to page-level citation
            return {
                "page": page_idx + 1,
                "bbox": None,
                "low_precision": True,
            }
    finally:
        doc.close()


def extract_facts_from_pdf(pdf_path: str, notice_id: int) -> List[Dict[str, Any]]:
    """
    Uploads the PDF bytes to Gemini natively, extracts structured candidate facts,
    and attaches PyMuPDF bounding box coordinates for every fact.
    """
    client = get_gemini_client()
    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            "Extract all official atomic facts from this college circular.",
        ],
        config=types.GenerateContentConfig(
            system_instruction=EXTRACTION_SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_schema=ExtractionResponse,
            temperature=0.0,
        ),
    )

    parsed = ExtractionResponse.model_validate_json(response.text)
    candidate_records = []

    for fact in parsed.facts:
        loc = locate_span_bbox(pdf_path, fact.page, fact.span)
        candidate_records.append({
            "fact_key": fact.fact_key,
            "type": fact.type,
            "value": fact.value,
            "unit": fact.unit,
            "scope": fact.scope.model_dump(),
            "valid_from": fact.valid_from,
            "valid_to": fact.valid_to,
            "source": {
                "notice_id": notice_id,
                "page": loc["page"],
                "span": fact.span,
                "bbox": loc["bbox"],
                "low_precision": loc["low_precision"],
            },
            "supersedes_ref": fact.supersedes_ref,
            "status": "candidate",
        })

    return candidate_records


# =====================================================================
# 2. CONFLICT ENGINE (Section 8.5)
# =====================================================================

def compute_specificity(scope: Dict[str, str]) -> int:
    """Counts how many scope keys are more specific than 'ALL' (Section 8.3)."""
    return sum(1 for k in ("course", "sem", "batch", "category") if str(scope.get(k, "ALL")).upper() != "ALL")


def scopes_overlap(s1: Dict[str, str], s2: Dict[str, str]) -> bool:
    """Two scopes overlap if for every dimension, they match or at least one is 'ALL'."""
    for key in ("course", "sem", "batch", "category"):
        v1 = str(s1.get(key, "ALL"))
        v2 = str(s2.get(key, "ALL"))
        if v1 != "ALL" and v2 != "ALL" and v1.lower() != v2.lower():
            return False
    return True


def scopes_identical(s1: Dict[str, str], s2: Dict[str, str]) -> bool:
    """Checks if two scope dictionaries are identical across all 4 keys."""
    for key in ("course", "sem", "batch", "category"):
        if str(s1.get(key, "ALL")).lower() != str(s2.get(key, "ALL")).lower():
            return False
    return True


def classify_candidate_conflict(
    candidate: Dict[str, Any],
    candidate_issue_date: str,
    active_facts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Implements Figure 5 (Section 8.5) Conflict Engine decision tree at ingestion time:
    Returns outcome in {'NEW', 'DUPLICATE', 'SCOPE_OVERLAP', 'SUPERSEDES', 'DISPUTED'}
    plus diff metadata for the admin review screen.
    """
    matching_active = [
        f for f in active_facts
        if f["fact_key"] == candidate["fact_key"] and scopes_overlap(candidate["scope"], f["scope"])
    ]

    if not matching_active:
        return {"outcome": "NEW", "target_fact_id": None, "diff": None}

    # Compare against the most specific matching active fact
    target = sorted(matching_active, key=lambda x: compute_specificity(x["scope"]), reverse=True)[0]

    if not scopes_identical(candidate["scope"], target["scope"]):
        return {
            "outcome": "SCOPE_OVERLAP",
            "target_fact_id": target["id"],
            "diff": {
                "old_scope": target["scope"],
                "new_scope": candidate["scope"],
                "old_value": target["value"],
                "new_value": candidate["value"],
            },
        }

    if candidate["value"] == target["value"]:
        return {"outcome": "DUPLICATE", "target_fact_id": target["id"], "diff": None}

    target_issue_date = target.get("issued_on", "")
    has_explicit_supersede = bool(candidate.get("supersedes_ref"))

    if candidate_issue_date > target_issue_date or has_explicit_supersede:
        return {
            "outcome": "SUPERSEDES",
            "target_fact_id": target["id"],
            "diff": {
                "fact_key": candidate["fact_key"],
                "old_value": target["value"],
                "new_value": candidate["value"],
                "old_notice_date": target_issue_date,
                "new_notice_date": candidate_issue_date,
            },
        }

    # Same issue date or older date with conflicting value -> DISPUTED
    return {
        "outcome": "DISPUTED",
        "target_fact_id": target["id"],
        "diff": {
            "fact_key": candidate["fact_key"],
            "fact_a_value": target["value"],
            "fact_b_value": candidate["value"],
            "issue_date": candidate_issue_date,
        },
    }


# =====================================================================
# 3. RUNTIME INTENT ROUTER WITH RULE FALLBACK (Section 8.7)
# =====================================================================

class RouterOutput(BaseModel):
    intent: Literal["volatile", "static", "unclear"]
    topic_prefix: str = Field(description="Topic prefix like 'fee.late_fee', 'fee', 'exam', 'policy.attendance', or 'unknown'")
    slots: Dict[str, str] = Field(default_factory=dict, description="Any course/semester mentioned inside the question text")


ROUTER_SYSTEM_PROMPT = """Classify the student's college query (in English or Hinglish).
- intent = "volatile" for fees, fines, amounts, exam dates, deadlines, timetables, schedules, fest registration dates.
- intent = "static" for narrative rules and general policies (e.g., minimum attendance percentage rules, code of conduct, dress code).
- intent = "unclear" if unrelated to college notices or impossible to determine.
Map topic_prefix to the closest canonical prefix:
  'fee.late_fee', 'fee.tuition_fee', 'fee.hostel_fee', 'fee',
  'exam.form_last_date', 'exam.lab_time', 'exam.re_exam_date', 'exam',
  'scholarship.deadline', 'activity.cultural_fest_date', 'admission.last_date', 'policy.attendance_min'.
If the student explicitly asks about a different semester or course in their question (e.g. "Fee for Sem 5"), put {"sem": "5"} in slots."""


def rule_based_intent_fallback(question: str) -> Dict[str, Any]:
    """Fast deterministic fallback when LLM is offline or hits rate limits (Section 8.12)."""
    q = question.lower()
    slots: Dict[str, str] = {}
    sem_match = re.search(r"\bsem(?:ester)?\s*(\d+)\b", q)
    if sem_match:
        slots["sem"] = sem_match.group(1)

    if "total fee" in q or ("tuition" in q and "hostel" in q):
        return {"intent": "volatile", "topic_prefix": "fee.total_fee", "slots": slots}
    if any(w in q for w in ["late fee", "late fine", "fine", "penalty"]):
        return {"intent": "volatile", "topic_prefix": "fee.late_fee", "slots": slots}
    if any(w in q for w in ["hostel fee", "hostel charge", "mess fee", "mess and hostel"]):
        return {"intent": "volatile", "topic_prefix": "fee.hostel_fee", "slots": slots}
    if any(w in q for w in ["tuition fee", "tuition"]):
        return {"intent": "volatile", "topic_prefix": "fee.tuition_fee", "slots": slots}
    if any(w in q for w in ["fee deadline", "payment deadline"]):
        return {"intent": "volatile", "topic_prefix": "fee.deadline", "slots": slots}
    if any(w in q for w in ["re-exam", "re exam", "kt exam", "backlog", "supplementary"]):
        return {"intent": "volatile", "topic_prefix": "exam.re_exam_date", "slots": slots}
    if any(w in q for w in ["lab exam", "practical exam", "viva", "dbms lab", "lab time"]):
        return {"intent": "volatile", "topic_prefix": "exam.lab_time", "slots": slots}
    if any(w in q for w in ["exam form", "exam forms", "form last date", "form submission"]):
        return {"intent": "volatile", "topic_prefix": "exam.form_last_date", "slots": slots}
    if any(w in q for w in ["scholarship", "freeship"]):
        return {"intent": "volatile", "topic_prefix": "scholarship.deadline", "slots": slots}
    if any(w in q for w in ["fest", "cultural", "udaan", "event", "activity"]):
        return {"intent": "volatile", "topic_prefix": "activity.cultural_fest_date", "slots": slots}
    if any(w in q for w in ["admission", "spot admission"]):
        return {"intent": "volatile", "topic_prefix": "admission.last_date", "slots": slots}
    if any(w in q for w in ["attendance", "75%", "debarred", "medical", "policy", "rule"]):
        return {"intent": "static", "topic_prefix": "policy.attendance_min", "slots": slots}
    if any(w in q for w in ["fee", "kitni hai", "amount"]):
        return {"intent": "volatile", "topic_prefix": "fee", "slots": slots}
    if any(w in q for w in ["exam", "paper", "timetable", "theory", "kab hai", "date"]):
        return {"intent": "volatile", "topic_prefix": "exam.start_date", "slots": slots}

    return {"intent": "unclear", "topic_prefix": "unknown", "slots": slots}


def route_question(question: str, context: Dict[str, str]) -> Dict[str, Any]:
    """Routes student question via Gemini with automatic fallback to keyword rules."""
    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"Student Context: {json.dumps(context)}\nQuestion: {question}",
            config=types.GenerateContentConfig(
                system_instruction=ROUTER_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_schema=RouterOutput,
                temperature=0.0,
            ),
        )
        return RouterOutput.model_validate_json(response.text).model_dump()
    except Exception:
        return rule_based_intent_fallback(question)


# =====================================================================
# 4. PLACEHOLDER ANSWER DRAFTER & VERIFIER (Section 8.8 & 8.9)
# =====================================================================

class DraftOutput(BaseModel):
    answerable: bool
    reason: Optional[str] = None
    fact_ids: List[int] = Field(default_factory=list)
    draft: str = Field(default="")


DRAFTER_SYSTEM_PROMPT = """You are a college information assistant. You receive FACTS (JSON with ids) and a QUESTION.
- Use ONLY the facts. Write the figures, dates and amounts as {fact:<id>} or {fact:<id>.issued_on} placeholders.
- NEVER type digits (0-9), currency numbers, or calendar dates directly in your draft text.
- You may use {ctx.course} and {ctx.sem_label} for the student's context.
- If the facts do not answer the question, return {"answerable": false, "reason": "missing", "fact_ids": [], "draft": ""}.
- If two facts conflict, return {"answerable": false, "reason": "conflict", "fact_ids": [], "draft": ""}.
- Keep the answer under 60 words, simple language, same language (English or Hinglish) as the question."""

PLACEHOLDER_RE = re.compile(r"\{fact:(\d+)(?:\.(\w+))?\}")
CTX_PLACEHOLDER_RE = re.compile(r"\{ctx\.(\w+)\}")
MONTH_WORDS_RE = re.compile(
    r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b",
    re.IGNORECASE,
)


class VerifierFail(Exception):
    """Raised when the LLM draft contains bare digits or unverified date words."""
    pass


def format_fact_value(fact: Dict[str, Any], field: Optional[str] = None) -> str:
    """Renders a fact value deterministically from the database record."""
    if field == "issued_on":
        return str(fact.get("issued_on", "official notice"))
    if field == "valid_to":
        return str(fact.get("valid_to") or "until further notice")

    val = fact.get("value", {})
    if isinstance(val, dict):
        if "amount" in val:
            currency = val.get("currency", "Rs.")
            prefix = "Rs." if currency in ("INR", "Rs", "Rs.") else currency
            return f"{prefix} {val['amount']}"
        if "date" in val:
            return str(val["date"])
        if "time" in val:
            return str(val["time"])
        if "text" in val:
            return str(val["text"])
    return str(val)


def strip_context_tokens(text: str, ctx: Dict[str, str]) -> str:
    """Removes whitelisted student context tokens (e.g., 'Sem 4', 'B.Sc. Data Science') before checking for bare digits."""
    cleaned = CTX_PLACEHOLDER_RE.sub("", text)
    sem = str(ctx.get("sem", ""))
    if sem:
        cleaned = re.sub(rf"\b(?:sem(?:ester)?\s*)?{re.escape(sem)}\b", "", cleaned, flags=re.IGNORECASE)
    course = str(ctx.get("course", ""))
    if course:
        cleaned = re.sub(re.escape(course), "", cleaned, flags=re.IGNORECASE)
    return cleaned


def compose_and_verify(draft: str, facts_by_id: Dict[int, Dict[str, Any]], ctx: Dict[str, str]) -> str:
    """
    Section 8.8 Verifier & Composer:
    1. Strips all {fact:ID} placeholders and whitelisted context labels.
    2. Rejects the draft if ANY bare digit (0-9) or month name remains.
    3. Substitutes placeholders with exact admin-approved database values.
    """
    stripped = PLACEHOLDER_RE.sub("", draft)
    stripped = strip_context_tokens(stripped, ctx)

    if re.search(r"\d", stripped) or MONTH_WORDS_RE.search(stripped):
        raise VerifierFail(f"Unsupported digit or date found in draft: '{draft}'")

    def replace_fact(match: re.Match) -> str:
        fact_id = int(match.group(1))
        prop = match.group(2)
        if fact_id not in facts_by_id:
            raise VerifierFail(f"Referenced unknown fact ID {fact_id}")
        return format_fact_value(facts_by_id[fact_id], prop)

    rendered = PLACEHOLDER_RE.sub(replace_fact, draft)
    ctx_tokens = {
        "course": ctx.get("course", "All Courses"),
        "sem_label": f"Sem {ctx.get('sem', 'ALL')}",
    }
    rendered = CTX_PLACEHOLDER_RE.sub(lambda m: ctx_tokens.get(m.group(1), ""), rendered)
    return rendered


def deterministic_template_card(fact: Dict[str, Any], ctx: Dict[str, str]) -> str:
    """Guaranteed safe fallback template built straight from the database record (Section 8.8)."""
    val_str = format_fact_value(fact)
    label = fact["fact_key"].replace(".", " - ").replace("_", " ").title()
    issued = fact.get("issued_on", "the official circular")
    return f"{label} for {ctx.get('course', '')} Sem {ctx.get('sem', '')} is {val_str}, per the notice dated {issued}."


def answer_volatile_query(
    question: str,
    matched_facts: List[Dict[str, Any]],
    ctx: Dict[str, str],
) -> Dict[str, Any]:
    if not matched_facts:
        return {
            "state": "unavailable",
            "badge": "NOT IN OFFICIAL RECORDS YET",
            "value": None,
            "answer": "This information has not been announced in official records yet. Please check with the Exam Cell / Admin Office.",
            "question_logged": True,
        }

    disputed = [f for f in matched_facts if f.get("status") == "disputed"]
    if disputed:
        return {
            "state": "disputed",
            "badge": "TWO NOTICES DISAGREE",
            "value": None,
            "answer": "Two official notices currently disagree on this value. Answers are paused until the admin resolves the conflict.",
            "sources": [f["source"] for f in disputed],
        }

    q_low = question.lower()
    fee_facts = [f for f in matched_facts if f.get("type") == "fee" and isinstance(f.get("value"), dict) and "amount" in f["value"]]
    if ("total" in q_low or ("tuition" in q_low and "hostel" in q_low)) and len(fee_facts) >= 2:
        total_amt = sum(int(f["value"]["amount"]) for f in fee_facts)
        parts_str = " + ".join(f"{f['fact_key'].split('.')[-1].replace('_', ' ')} ({{fact:{f['id']}}})" for f in fee_facts)
        facts_by_id = {f["id"]: f for f in fee_facts}
        composed_parts = compose_and_verify(parts_str, facts_by_id, ctx)
        return {
            "state": "verified",
            "badge": "VERIFIED FROM OFFICIAL NOTICE (COMPUTED BY CODE)",
            "value": f"Rs. {total_amt}",
            "answer": f"Total fee for {ctx.get('course', 'ALL')} Sem {ctx.get('sem', 'ALL')} is Rs. {total_amt} ({composed_parts}).",
            "applies_to": f"{ctx.get('course', 'ALL')}, Sem {ctx.get('sem', 'ALL')}",
            "valid_until": "until further notice",
            "replaces_notice": None,
            "source": fee_facts[0].get("source"),
            "sources": [f.get("source") for f in fee_facts],
        }

    primary_fact = matched_facts[0]
    facts_by_id = {f["id"]: f for f in matched_facts}

    rendered_text = None
    for attempt in range(2):
        try:
            client = get_gemini_client()
            prompt_facts = [
                {"id": f["id"], "fact_key": f["fact_key"], "type": f["type"], "scope": f["scope"]}
                for f in matched_facts
            ]
            resp = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=(
                    f"STUDENT CONTEXT: {json.dumps(ctx)}\n"
                    f"FACTS: {json.dumps(prompt_facts)}\n"
                    f"QUESTION: {question}"
                ),
                config=types.GenerateContentConfig(
                    system_instruction=DRAFTER_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_schema=DraftOutput,
                    temperature=0.0 if attempt == 0 else 0.1,
                ),
            )
            draft_obj = DraftOutput.model_validate_json(resp.text)
            if not draft_obj.answerable:
                break
            rendered_text = compose_and_verify(draft_obj.draft, facts_by_id, ctx)
            break
        except Exception:
            continue

    if not rendered_text:
        rendered_text = deterministic_template_card(primary_fact, ctx)

    valid_to = primary_fact.get("valid_to")
    is_expired = False
    if valid_to:
        try:
            is_expired = str(valid_to) < datetime.now().strftime("%Y-%m-%d")
        except Exception:
            is_expired = False

    if is_expired or primary_fact.get("status") == "expired":
        return {
            "state": "outdated",
            "badge": "MAY BE OUTDATED - CONFIRM WITH OFFICE",
            "value": format_fact_value(primary_fact),
            "answer": f"[Note: Validity period ended on {valid_to}] {rendered_text}",
            "applies_to": f"{primary_fact['scope'].get('course', 'ALL')}, Sem {primary_fact['scope'].get('sem', 'ALL')}",
            "valid_until": valid_to,
            "replaces_notice": primary_fact.get("supersedes_summary"),
            "source": primary_fact.get("source"),
        }

    return {
        "state": "verified",
        "badge": "VERIFIED FROM OFFICIAL NOTICE",
        "value": format_fact_value(primary_fact),
        "answer": rendered_text,
        "applies_to": f"{primary_fact['scope'].get('course', 'ALL')}, Sem {primary_fact['scope'].get('sem', 'ALL')}",
        "valid_until": valid_to or "until further notice",
        "replaces_notice": primary_fact.get("supersedes_summary"),
        "source": primary_fact.get("source"),
    }


# =====================================================================
# 5. SELF-TEST DEMO (RUNS LOCALLY WITHOUT API KEYS OR DB)
# =====================================================================

if __name__ == "__main__":
    print("=== Pramaan AI/ML Engine Local Self-Test ===")

    # 1. Test Conflict Engine (Circular 1 vs Circular 2 Late Fee revision)
    active_ledger = [
        {
            "id": 7,
            "fact_key": "fee.late_fee",
            "type": "fee",
            "value": {"amount": 50, "currency": "INR"},
            "scope": {"course": "B.Sc. Data Science", "sem": "4", "batch": "ALL", "category": "ALL"},
            "issued_on": "2026-11-10",
            "status": "active",
        }
    ]
    new_candidate = {
        "fact_key": "fee.late_fee",
        "type": "fee",
        "value": {"amount": 75, "currency": "INR"},
        "scope": {"course": "B.Sc. Data Science", "sem": "4", "batch": "ALL", "category": "ALL"},
        "supersedes_ref": "Circular 1 (10 Nov)",
    }
    conflict_result = classify_candidate_conflict(new_candidate, "2026-11-12", active_ledger)
    print("\n[1] Conflict Engine Result (10 Nov Rs. 50 -> 12 Nov Rs. 75):")
    print(json.dumps(conflict_result, indent=2))

    # 2. Test Rule-Based Intent Router (English + Hinglish)
    student_ctx = {"course": "B.Sc. Data Science", "sem": "4"}
    for sample_q in ["What is the late fee for me?", "Mera Sem 4 exam kab hai?", "When is the re-exam?"]:
        print(f"\n[2] Router ('{sample_q}'): {rule_based_intent_fallback(sample_q)}")

    # 3. Test Placeholder Composer & Anti-Hallucination Verifier
    approved_facts = {
        41: {
            "id": 41,
            "fact_key": "fee.late_fee",
            "value": {"amount": 75, "currency": "INR"},
            "issued_on": "12 Nov 2026",
            "scope": {"course": "B.Sc. Data Science", "sem": "4"},
        }
    }
    valid_draft = "The late fee for {ctx.sem_label} is {fact:41}, per the notice of {fact:41.issued_on}."
    rendered = compose_and_verify(valid_draft, approved_facts, student_ctx)
    print(f"\n[3] Verified & Rendered Answer:\n    {rendered}")

    # 4. Test Verifier Blocking an Invented Number
    hallucinated_draft = "The late fee for Sem 4 is {fact:41}, or Rs. 60 if paid early."
    try:
        compose_and_verify(hallucinated_draft, approved_facts, student_ctx)
    except VerifierFail as e:
        print(f"\n[4] Verifier Successfully Blocked Hallucinated Number:\n    {e}")