"""Scope, fact and upload validation helpers."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from app.models.enums import FactStatus
from app.utils.date_utils import normalize_academic_year


class ValidationFailure(ValueError):
    pass


SEMESTER_MIN, SEMESTER_MAX = 1, 12
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    FactStatus.CANDIDATE.value: {FactStatus.ACTIVE.value, FactStatus.REJECTED.value, FactStatus.DISPUTED.value},
    FactStatus.DISPUTED.value: {FactStatus.ACTIVE.value, FactStatus.REJECTED.value},
    FactStatus.ACTIVE.value: {FactStatus.SUPERSEDED.value, FactStatus.EXPIRED.value, FactStatus.DISPUTED.value},
    FactStatus.SUPERSEDED.value: set(),
    FactStatus.EXPIRED.value: set(),
    FactStatus.REJECTED.value: set(),
}


def assert_transition(current: str, new: str) -> None:
    if new not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValidationFailure(f"Invalid fact status transition: {current} -> {new}")


def normalize_scope_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"all", "any", "none", "null", "*"}:
        return None
    return text[:200]


def normalize_semester(value: object) -> int | None:
    if value is None or value == "" or (isinstance(value, str) and value.lower() in {"all", "any"}):
        return None
    try:
        semester = int(str(value).strip().lower().replace("sem", "").replace("semester", "").strip())
    except ValueError as exc:
        raise ValidationFailure(f"Invalid semester: {value!r}") from exc
    if not SEMESTER_MIN <= semester <= SEMESTER_MAX:
        raise ValidationFailure(f"Semester must be between {SEMESTER_MIN} and {SEMESTER_MAX}")
    return semester


def normalize_scope(raw: dict) -> dict:
    course = normalize_scope_value(raw.get("course"))
    academic_year = normalize_academic_year(normalize_scope_value(raw.get("academic_year")))
    return {
        "college": normalize_scope_value(raw.get("college")),
        "course": course,
        "department": normalize_scope_value(raw.get("department")),
        "semester": normalize_semester(raw.get("semester")),
        "academic_year": academic_year,
        "batch": normalize_scope_value(raw.get("batch")),
        "student_group": normalize_scope_value(raw.get("student_group")),
    }


def scope_specificity(scope: dict) -> int:
    return sum(1 for value in scope.values() if value is not None)


def _scope_value(value: object, key: str) -> str | None:
    if value is None:
        return None
    if key == "academic_year":
        return normalize_academic_year(str(value))
    return str(value).strip().lower()


def scopes_overlap(a: dict, b: dict) -> bool:
    for key in ("college", "course", "department", "semester", "academic_year", "batch", "student_group"):
        left, right = _scope_value(a.get(key), key), _scope_value(b.get(key), key)
        if left is not None and right is not None and left != right:
            return False
    return True


def scopes_equal(a: dict, b: dict) -> bool:
    keys = ("college", "course", "department", "semester", "academic_year", "batch", "student_group")
    return all(_scope_value(a.get(k), k) == _scope_value(b.get(k), k) for k in keys)


def scope_matches(fact_scope: dict, student_scope: dict) -> bool:
    """A fact applies when every restricted dimension matches the student."""
    for key in ("college", "course", "department", "semester", "academic_year", "batch", "student_group"):
        fact_value = fact_scope.get(key)
        if fact_value is None:
            continue
        student_value = student_scope.get(key)
        if student_value is None:
            return False
        if _scope_value(fact_value, key) != _scope_value(student_value, key):
            return False
    return True


def compute_active_scope_key(fact_key: str, scope: dict) -> str:
    normalized = {
        "fact_key": fact_key.lower().strip(),
        **{k: _scope_value(v, k) for k, v in scope.items()},
    }
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_academic_year(value: str | None) -> str | None:
    normalized = normalize_academic_year(value)
    if normalized is None:
        return None
    if not re.match(r"^\d{4}-\d{2}$", normalized):
        raise ValidationFailure(f"Invalid academic year: {value!r} (expected e.g. 2026-27)")
    return normalized


def validate_date_range(start: date | None, end: date | None) -> None:
    if start and end and end < start:
        raise ValidationFailure("effective_to cannot be before effective_from")


def validate_pdf_signature(data: bytes) -> None:
    if not data:
        raise ValidationFailure("Uploaded file is empty")
    if len(data) < 8:
        raise ValidationFailure("Uploaded file is too small to be a PDF")
    if not data.startswith(b"%PDF-"):
        raise ValidationFailure("File content is not a valid PDF (missing %PDF- signature)")
    tail = data[-2048:]
    if b"%%EOF" not in tail:
        raise ValidationFailure("File appears to be a truncated or corrupt PDF (missing %%EOF)")


def validate_content_type(content_type: str | None) -> None:
    allowed = {"application/pdf", "application/x-pdf", "application/octet-stream"}
    if content_type and content_type.lower().split(";")[0].strip() not in allowed:
        raise ValidationFailure("Only PDF uploads are accepted (content-type must be application/pdf)")


def sanitize_filename(name: str, max_length: int = 200) -> str:
    base = (name or "document.pdf").replace("\\", "/").split("/")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base[:max_length]
