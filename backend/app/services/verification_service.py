"""Independent, code-based answer verification.

Gemini may phrase an answer, but it is never allowed to invent critical numbers
or dates.  The model receives opaque placeholders such as ``{fact:<id>.date}``
and the application substitutes the approved ledger values itself.  After
rendering, every numeric/date-like claim is checked against the cited facts or
the supplied source text.

This reduces hallucination risk; it does not make hallucinations impossible.
Semantic claims in free-form prose remain the responsibility of the grounded
prompt + citations.
"""
from __future__ import annotations

import re

from app.models.fact import Fact
from app.utils.date_utils import format_human_date
from app.utils.text_utils import extract_numbers, normalize_whitespace
from app.utils.validators import scope_matches

PLACEHOLDER_RE = re.compile(
    r"\{fact:([A-Za-z0-9_-]{1,64})(?:\.([a-z_]+))?\}",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_MONTH_NAME = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_MONTH_DATE_RE = re.compile(
    rf"\b(?:\d{{1,2}}\s+{_MONTH_NAME}|{_MONTH_NAME}\s+\d{{1,2}}|\d{{1,2}}\s+{_MONTH_NAME}\s+\d{{4}})\b",
    re.IGNORECASE,
)
_FIELD_ALIASES = {
    "value": "value_text",
    "amount": "amount",
    "date": "date",
    "title": "title",
    "fact_key": "fact_key",
    "unit": "unit",
    "currency": "currency",
    "semester": "semester",
    "course": "course",
    "academic_year": "academic_year",
    "page": "page",
    "version": "version",
}


def humanize_key(fact_key: str) -> str:
    return fact_key.replace(".", " ").replace("_", " ").strip().capitalize()


def _scope(fact: Fact) -> dict:
    return {
        "college": fact.college,
        "course": fact.course,
        "department": fact.department,
        "semester": fact.semester,
        "academic_year": fact.academic_year,
        "batch": fact.batch,
        "student_group": fact.student_group,
    }


def _format_number(value: float | None) -> str:
    if value is None:
        return ""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def render_field(fact: Fact, field: str | None) -> str:
    field = _FIELD_ALIASES.get((field or "value").lower(), "value_text")
    if field == "value_text":
        return fact.value_text
    if field == "amount":
        number = _format_number(float(fact.value_number) if fact.value_number is not None else None)
        if number:
            return f"{fact.currency or '₹'} {number}".strip()
        return fact.value_text
    if field == "date":
        return format_human_date(fact.value_date) or fact.value_text
    if field == "title":
        return fact.title or humanize_key(fact.fact_key)
    if field == "page":
        return str(fact.page_number or "")
    if field == "version":
        return str(fact.version)
    return str(getattr(fact, field, "") or fact.value_text)


def render_template(draft: str, facts: dict[str, Fact]) -> str:
    def replace(match: re.Match[str]) -> str:
        fact = facts.get(match.group(1))
        if fact is None:
            return ""
        return render_field(fact, match.group(2))

    return normalize_whitespace(PLACEHOLDER_RE.sub(replace, draft))


def validate_template(draft: str, facts: dict[str, Fact]) -> list[str]:
    errors: list[str] = []
    placeholders = list(PLACEHOLDER_RE.finditer(draft))
    if not placeholders:
        errors.append("Draft contains no ledger placeholders")
    for match in placeholders:
        fact_id, field = match.group(1), match.group(2)
        if fact_id not in facts:
            errors.append(f"Unknown fact placeholder: {fact_id}")
            continue
        if field and field.lower() not in _FIELD_ALIASES:
            errors.append(f"Unknown placeholder field: {field}")
    remainder = PLACEHOLDER_RE.sub(" ", draft)
    if _NUMBER_RE.search(remainder):
        errors.append("Draft contains a hardcoded number; use a placeholder")
    if _MONTH_DATE_RE.search(remainder):
        errors.append("Draft contains a hardcoded date; use a placeholder")
    if len(PLACEHOLDER_RE.findall(draft)) > 8:
        errors.append("Too many placeholders")
    return errors


def _allowed_numeric_tokens(
    facts: list[Fact],
    context: dict | None = None,
) -> set[str]:
    allowed: set[str] = set()

    def add(value: object) -> None:
        if value is None:
            return
        text = str(value)
        for match in _NUMBER_RE.findall(text):
            cleaned = match.replace(",", "")
            allowed.add(cleaned)
            try:
                number = float(cleaned)
            except ValueError:
                continue
            if number.is_integer():
                allowed.add(str(int(number)))
            else:
                allowed.add(f"{number:.2f}".rstrip("0").rstrip("."))

    for fact in facts:
        add(fact.value_text)
        add(fact.value_number)
        add(fact.page_number)
        add(fact.semester)
        for scope_value in _scope(fact).values():
            add(scope_value)
        if fact.value_date:
            add(fact.value_date.day)
            add(fact.value_date.month)
            add(fact.value_date.year)
            add(fact.value_date.isoformat())
            add(format_human_date(fact.value_date))
        for effective in (fact.effective_from, fact.effective_to):
            if effective:
                add(effective.day)
                add(effective.month)
                add(effective.year)
                add(effective.isoformat())
    for value in (context or {}).values():
        add(value)
    return allowed


def verify_answer(
    answer: str,
    *,
    facts: list[Fact],
    context: dict | None = None,
) -> list[str]:
    errors: list[str] = []
    if PLACEHOLDER_RE.search(answer):
        errors.append("Unrendered placeholders remain in the answer")
    if not answer.strip():
        errors.append("Answer is empty")
    allowed = _allowed_numeric_tokens(facts, context)
    for match in _NUMBER_RE.findall(answer):
        token = match.replace(",", "")
        if token not in allowed:
            errors.append(f"Numeric claim not supported by cited facts: {token}")
    return errors


def verify_scope(facts: list[Fact], student_scope: dict) -> list[str]:
    return [
        f"Fact {fact.id} is outside the student's scope"
        for fact in facts
        if not scope_matches(_scope(fact), student_scope)
    ]


def verify_citations(citations: list[object], facts: list[Fact]) -> list[str]:
    errors: list[str] = []
    cited_fact_ids = {getattr(citation, "fact_id", None) for citation in citations}
    cited_fact_ids.discard(None)
    for fact in facts:
        if fact.id not in cited_fact_ids:
            errors.append(f"Missing citation for fact {fact.id}")
    for citation in citations:
        citation_fact_id = getattr(citation, "fact_id", None)
        if citation_fact_id and citation_fact_id not in {fact.id for fact in facts}:
            errors.append(f"Citation references uncited fact {citation_fact_id}")
    return errors


def verify_grounded_text(
    answer: str,
    *,
    source_texts: list[str],
    context: dict | None = None,
) -> list[str]:
    """For static/grounded prose: every number must appear in a source chunk."""
    errors: list[str] = []
    if not answer.strip():
        return ["Answer is empty"]
    allowed: set[str] = set()
    for text in source_texts:
        for value in extract_numbers(text):
            allowed.add(_format_number(value))
            allowed.add(str(value))
    for value in (context or {}).values():
        if value is None:
            continue
        for match in _NUMBER_RE.findall(str(value)):
            allowed.add(match.replace(",", ""))
    for match in _NUMBER_RE.findall(answer):
        token = match.replace(",", "")
        if token not in allowed:
            errors.append(f"Numeric claim not supported by source text: {token}")
    return errors


def sanitize_answer(answer: str, *, limit: int = 1200) -> str:
    text = normalize_whitespace(answer)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
