"""Cheap, deterministic intent routing.

Every question is *not* sent to Gemini.  Keyword/rule routing handles the
common cases; Gemini is consulted only for genuinely ambiguous questions.  The
router returns which fact keys/prefixes to look up, never answers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.integrations.gemini_client import GeminiClient
from app.utils.date_utils import normalize_academic_year
from app.utils.text_utils import contains_any, normalize_key

logger = get_logger("pramaan.intent")

INTENTS = ("volatile", "static", "unclear")

FEE_KEYS = [
    "fee.tuition_fee",
    "fee.late_fee",
    "fee.examination_fee",
    "fee.hostel_fee",
    "fee.admission_fee",
    "fee.library_fee",
    "fee.transport_fee",
    "fee.general",
]
DATE_KEYS = [
    "date.exam_date",
    "date.exam_form_last_date",
    "date.fee_last_date",
    "date.admission_deadline",
    "date.scholarship_deadline",
    "date.registration_last_date",
    "date.hostel_last_date",
    "date.result_date",
    "date.revaluation_last_date",
    "date.holiday",
    "date.semester_start",
    "date.deadline",
    "schedule.exam_date",
    "schedule.exam_timetable",
    "schedule.semester",
]

# Ordered specific patterns.  The first matching pattern contributes its keys.
_SPECIFIC_RULES: list[tuple[str, tuple[str, ...], list[str]]] = [
    ("fee", ("late fee", "fine"), ["fee.late_fee"]),
    ("fee", ("tuition", "course fee", "semester fee", "college fee"), ["fee.tuition_fee"]),
    ("fee", ("exam fee", "examination fee"), ["fee.examination_fee"]),
    ("fee", ("hostel fee", "hostel charge", "mess fee"), ["fee.hostel_fee"]),
    ("fee", ("library fee", "library fine"), ["fee.library_fee"]),
    ("fee", ("transport fee", "bus fee"), ["fee.transport_fee"]),
    ("fee", ("admission fee",), ["fee.admission_fee"]),
    ("date", ("scholarship last date", "scholarship deadline", "last date for scholarship"),
     ["date.scholarship_deadline"]),
    ("date", ("fee last date", "last date to pay", "fee deadline", "last date of fee",
              "fee due date", "fee payment last date", "fee payment deadline",
              "last date for fee payment"), ["date.fee_last_date"]),
    ("date", ("exam form",), ["date.exam_form_last_date"]),
    ("date", ("revaluation", "rechecking"), ["date.revaluation_last_date"]),
    ("date", ("admission last date", "admission deadline", "last date of admission"),
     ["date.admission_deadline"]),
    ("date", ("result date", "result declaration", "when is result", "when will result"),
     ["date.result_date"]),
    ("date", ("registration last date", "registration deadline", "last date of registration"),
     ["date.registration_last_date"]),
    ("date", ("hostel last date", "hostel deadline", "last date for hostel"),
     ["date.hostel_last_date"]),
    ("date", ("holiday", "vacation", "break"), ["date.holiday"]),
    ("schedule", ("semester start", "classes begin", "classes start", "semester begin"),
     ["date.semester_start"]),
    ("schedule", ("timetable", "time table", "exam schedule", "examination schedule",
                  "schedule of exam"), ["schedule.exam_timetable", "schedule.exam_date"]),
    ("date", ("exam date", "exam when", "when is exam", "when are exams", "exam kab"),
     ["date.exam_date"]),
    ("attendance", ("minimum attendance", "attendance required", "required attendance",
                    "attendance percentage", "how much attendance"),
     ["policy.attendance_requirement"]),
]

_FEE_WORDS = {"fee", "fees", "amount", "cost", "price", "rs", "rupee", "rupees", "payment",
              "pay", "challan", "charges", "kitni", "kitna"}
_DATE_WORDS = {"date", "deadline", "last date", "due date", "due", "when", "kab", "tak",
               "timeline", "extended", "extension", "schedule", "timetable", "exam",
               "examination", "result", "holiday", "vacation", "commencement", "start"}
_DATE_PATTERNS = ("when ", "what date", "which date", "last date", "due date", "deadline",
                  "kab ", "kab?", "kitni tarikh")

_STATIC_RULES: list[tuple[str, set[str], list[str]]] = [
    ("attendance", {"attendance", "absenc", "present", "detained", "shortage", "condonation"},
     ["policy.attendance", "policy.attendance_requirement"]),
    ("document", {"document", "certificate", "marksheet", "migration", "transfer certificate",
                  "tc ", "id card", "aadhaar"},
     ["document.admission", "document.scholarship", "policy.document"]),
    ("scholarship", {"scholarship", "waiver", "concession", "freeship", "financial aid"},
     ["policy.scholarship", "eligibility.scholarship", "document.scholarship"]),
    ("admission", {"admission", "apply", "application", "enroll", "enrolment", "enrollment",
                   "how to join"},
     ["policy.admission", "eligibility.admission", "document.admission"]),
    ("hostel", {"hostel", "warden", "mess", "room allotment"}, ["policy.hostel"]),
    ("library", {"library", "borrow", "book", "journal"}, ["policy.library"]),
    ("eligibility", {"eligibility", "eligible", "qualify", "criteria"}, ["eligibility."]),
    ("exam", {"unfair", "malpractice", "grace", "revaluation", "rechecking", "exam rule"},
     ["policy.exam", "policy.revaluation"]),
    ("grievance", {"grievance", "complaint", "ragging", "harassment", "anti ragging"},
     ["policy.grievance"]),
]

_COURSE_RE = re.compile(
    r"\b(b\.?\s?tech|m\.?\s?tech|bca|mca|b\.?\s?sc|m\.?\s?sc|bba|mba|b\.?\s?com|m\.?\s?com|"
    r"b\.?\s?a\b|m\.?\s?a\b|bpharm|pharm\.?\s?d|llb|b\.?\s?ed|diploma|polytechnic)\b",
    re.IGNORECASE,
)
_SEMESTER_RE = re.compile(
    r"\b(?:sem(?:ester)?\s*(?:no\.?\s*|number\s*)?(1[0-2]|[1-9])|(1[0-2]|[1-9])\s*(?:st|nd|rd|th)?\s*sem(?:ester)?)\b",
    re.IGNORECASE,
)
_ACADEMIC_YEAR_RE = re.compile(r"\b(20\d{2})\s*[-/]\s*(20\d{2})\b")
_HINGLISH_RE = re.compile(r"\b(kab|kya|kitni|kitna|hai|hain|batao|bata|mera|meri|ka|ki|ke)\b",
                          re.IGNORECASE)


@dataclass(slots=True)
class IntentResult:
    intent: str
    topic: str | None
    fact_keys: list[str] = field(default_factory=list)
    fact_prefixes: list[str] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    method: str = "rules"
    language: str = "en"

    @property
    def is_volatile(self) -> bool:
        return self.intent == "volatile"

    @property
    def is_static(self) -> bool:
        return self.intent == "static"


def _normalize_course(raw: str) -> str:
    value = re.sub(r"[\s.]+", "", raw).upper()
    mapping = {
        "BTECH": "B.Tech",
        "MTECH": "M.Tech",
        "BSC": "B.Sc",
        "MSC": "M.Sc",
        "BCOM": "B.Com",
        "MCOM": "M.Com",
        "BA": "B.A",
        "MA": "M.A",
        "BPHARM": "B.Pharm",
        "PHARMD": "Pharm.D",
        "BED": "B.Ed",
    }
    return mapping.get(value, value)


def extract_slots(question: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    course = _COURSE_RE.search(question)
    if course:
        slots["course"] = _normalize_course(course.group(1))
    semester = _SEMESTER_RE.search(question)
    if semester:
        slots["semester"] = int(semester.group(1) or semester.group(2))
    academic_year = _ACADEMIC_YEAR_RE.search(question)
    if academic_year:
        slots["academic_year"] = normalize_academic_year(
            f"{academic_year.group(1)}-{academic_year.group(2)}"
        )
    if _HINGLISH_RE.search(question):
        slots["language"] = "hinglish"
    return slots


def _match_specific(lowered: str) -> tuple[list[str], list[str], str | None]:
    keys: list[str] = []
    prefixes: list[str] = []
    topic: str | None = None
    for rule_topic, phrases, rule_keys in _SPECIFIC_RULES:
        if contains_any(lowered, phrases):
            for key in rule_keys:
                if key not in keys:
                    keys.append(key)
            topic = topic or rule_topic
    return keys, prefixes, topic


def _match_static(lowered: str) -> tuple[list[str], list[str], str | None]:
    keys: list[str] = []
    prefixes: list[str] = []
    topic: str | None = None
    for rule_topic, words, rule_keys in _STATIC_RULES:
        if contains_any(lowered, words):
            for key in rule_keys:
                if key.endswith("."):
                    if key.rstrip(".") not in prefixes:
                        prefixes.append(key.rstrip("."))
                elif key not in keys:
                    keys.append(key)
            topic = topic or rule_topic
    return keys, prefixes, topic


def classify_with_rules(question: str) -> IntentResult:
    lowered = question.lower()
    slots = extract_slots(question)
    specific_keys, specific_prefixes, specific_topic = _match_specific(lowered)

    fee_hit = contains_any(lowered, _FEE_WORDS)
    date_hit = contains_any(lowered, _DATE_WORDS) or contains_any(lowered, _DATE_PATTERNS)
    static_keys, static_prefixes, static_topic = _match_static(lowered)

    if specific_keys:
        return IntentResult(
            intent="volatile",
            topic=specific_topic,
            fact_keys=specific_keys,
            fact_prefixes=specific_prefixes,
            slots=slots,
            confidence=0.9,
        )

    if fee_hit:
        broad = contains_any(lowered, {"all fee", "fee structure", "list of fee", "total fee"})
        prefixes = ["fee."] if broad else []
        keys = [] if broad else list(FEE_KEYS)
        return IntentResult(
            intent="volatile",
            topic="fee",
            fact_keys=keys,
            fact_prefixes=prefixes,
            slots=slots,
            confidence=0.75 if broad else 0.7,
        )

    if date_hit:
        broad = contains_any(lowered, {"all date", "dates", "calendar", "schedule"})
        return IntentResult(
            intent="volatile",
            topic="date",
            fact_keys=[] if broad else list(DATE_KEYS),
            fact_prefixes=["date.", "schedule."] if broad else [],
            slots=slots,
            confidence=0.65,
        )

    if static_keys or static_prefixes:
        return IntentResult(
            intent="static",
            topic=static_topic,
            fact_keys=static_keys,
            fact_prefixes=static_prefixes,
            slots=slots,
            confidence=0.8,
        )

    return IntentResult(
        intent="unclear",
        topic=None,
        slots=slots,
        confidence=0.2,
    )


_GEMINI_SYSTEM = (
    "You classify student questions for a college information assistant. "
    "Return JSON only. intents: volatile (fees, dates, deadlines, schedules, results), "
    "static (policies, procedures, eligibility rules), unclear. "
    "Never answer the question. Use fact keys only when obvious."
)


def _sanitize_keys(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    keys: list[str] = []
    for item in raw[:12]:
        if not isinstance(item, str):
            continue
        key = normalize_key(item)
        if key and key not in keys:
            keys.append(key)
    return keys


def classify(
    question: str,
    *,
    gemini: GeminiClient | None = None,
    settings: Settings | None = None,
) -> IntentResult:
    settings = settings or get_settings()
    result = classify_with_rules(question)
    if result.intent != "unclear":
        return result

    client = gemini or GeminiClient(settings)
    if not client.configured:
        return result

    prompt = (
        "Classify the student question.\n"
        "Return JSON: {\"intent\":\"volatile|static|unclear\",\"topic\":\"fee|date|schedule|"
        "attendance|scholarship|admission|document|eligibility|policy|other\","
        "\"fact_keys\":[\"dot.separated.key\"],\"slots\":{\"course\":null,\"semester\":null,"
        "\"academic_year\":null}}\n"
        f"Question: {question[:1000]}"
    )
    try:
        payload = client.generate_json(prompt, system_instruction=_GEMINI_SYSTEM, max_output_tokens=512)
    except ExternalServiceError as exc:
        logger.warning("intent classification fell back to rules: %s", exc)
        return result
    if not isinstance(payload, dict):
        return result
    intent = str(payload.get("intent", "")).strip().lower()
    if intent not in INTENTS:
        return result
    topic = payload.get("topic")
    topic = str(topic).strip().lower()[:40] if topic else None
    slots = dict(result.slots)
    raw_slots = payload.get("slots")
    if isinstance(raw_slots, dict):
        if raw_slots.get("course"):
            slots["course"] = str(raw_slots["course"])[:120]
        if raw_slots.get("semester"):
            try:
                semester = int(raw_slots["semester"])
                if 1 <= semester <= 12:
                    slots["semester"] = semester
            except (TypeError, ValueError):
                pass
        if raw_slots.get("academic_year"):
            slots["academic_year"] = normalize_academic_year(
                str(raw_slots["academic_year"])[:20]
            )
    return IntentResult(
        intent=intent,
        topic=topic,
        fact_keys=_sanitize_keys(payload.get("fact_keys")),
        fact_prefixes=[],
        slots=slots,
        confidence=0.6,
        method="gemini",
    )
