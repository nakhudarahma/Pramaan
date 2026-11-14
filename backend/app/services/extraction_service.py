"""Structured fact extraction from official PDFs.

Gemini is the primary extractor when configured.  A conservative rule-based
extractor is used only when Gemini is *not* configured, so local development and
tests are functional without paid API calls.  Its output is labelled
``extraction_method="heuristic"`` and always lands in the admin review queue.
Nothing is published automatically.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.integrations.gemini_client import GeminiClient
from app.models.enums import FACT_CATEGORIES, FactCategory
from app.models.notice import Notice
from app.services.pdf_service import PDFExtraction, locate_span
from app.utils.date_utils import format_human_date, parse_date
from app.utils.text_utils import normalize_key, normalize_whitespace
from app.utils.validators import (
    ValidationFailure,
    normalize_scope,
    validate_academic_year,
    validate_date_range,
)

logger = get_logger("pramaan.extraction")


class GeminiFact(BaseModel):
    fact_key: str | None = None
    category: str | None = None
    title: str | None = None
    value: Any = None
    value_text: str | None = None
    unit: str | None = None
    currency: str | None = None
    scope: dict = Field(default_factory=dict)
    effective_from: str | None = None
    effective_to: str | None = None
    page: int | None = None
    span: str | None = None
    confidence: float = 0.6
    supersedes_ref: str | None = None


class GeminiFactsEnvelope(BaseModel):
    facts: list[GeminiFact] = Field(default_factory=list)


@dataclass
class ExtractedFact:
    fact_key: str
    category: str
    title: str | None
    value_json: dict
    value_text: str
    value_number: float | None
    value_date: date | None
    currency: str | None
    unit: str | None
    scope: dict
    effective_from: date | None
    effective_to: date | None
    page_number: int | None
    source_text: str
    source_bbox: list[float] | None
    source_precision: str
    confidence: float
    supersedes_ref: str | None = None
    description: str | None = None


@dataclass
class ExtractionResult:
    facts: list[ExtractedFact] = field(default_factory=list)
    method: str = "none"
    errors: list[str] = field(default_factory=list)
    requires_manual_review: bool = False
    error: str | None = None


SYSTEM_PROMPT = """You extract atomic facts from an official college notice.
Return JSON only, matching: {"facts": [ ... ]}.
Each fact object:
{
  "fact_key": "fee.late_fee | date.exam_form_last_date | policy.attendance_requirement | ...",
  "category": "fee | date | eligibility | policy | schedule | document | attendance | scholarship | holiday | other",
  "title": "short human title",
  "value": {"amount": 75, "currency": "INR"} | {"date": "2026-11-25"} | {"text": "..."},
  "value_text": "exactly what the notice states",
  "unit": null | "%" | "INR",
  "currency": null | "INR",
  "scope": {"college": null, "course": null, "department": null, "semester": null,
             "academic_year": null, "batch": null, "student_group": null},
  "effective_from": "YYYY-MM-DD or null",
  "effective_to": "YYYY-MM-DD or null",
  "page": 1,
  "span": "exact sentence copied verbatim from the page",
  "confidence": 0.0,
  "supersedes_ref": "reference to an older notice if explicitly stated, else null"
}
Rules:
- One object per fact. Do not infer facts that are not explicitly stated.
- Copy numbers and dates exactly. If unclear, omit the fact.
- "span" must be copied exactly from the page text. Never paraphrase it.
- Use null for scope dimensions when the notice does not restrict them.
- Never output markdown or commentary.
"""


class ExtractionService:
    def __init__(self, gemini: GeminiClient | None = None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.gemini = gemini or GeminiClient(self.settings)

    def extract(self, extraction: PDFExtraction, notice: Notice) -> ExtractionResult:
        if extraction.empty:
            return ExtractionResult(
                method="none",
                error="PDF contains no pages",
                requires_manual_review=True,
                errors=["PDF contains no pages"],
            )
        if extraction.requires_ocr:
            return ExtractionResult(
                method="none",
                error="PDF appears to be scanned; OCR is not configured. Manual review required.",
                requires_manual_review=True,
                errors=["Scanned PDF: no extractable text. Configure OCR or enter facts manually."],
            )

        if self.gemini.configured:
            result = self._extract_with_gemini(extraction, notice)
            if result is not None:
                return result
            return ExtractionResult(
                method="gemini",
                error="Gemini extraction failed; document requires manual review.",
                requires_manual_review=True,
                errors=["Gemini extraction failed. The original PDF was preserved."],
            )

        logger.info("gemini not configured; using heuristic extraction document_id=%s", notice.document_id)
        return self._extract_heuristic(extraction, notice)

    # ---------------------------------------------------------------- gemini
    def _extract_with_gemini(self, extraction: PDFExtraction, notice: Notice) -> ExtractionResult | None:
        prompt = (
            f"Notice title: {notice.title}\n"
            f"Issuer: {notice.issuer or 'unknown'}\n"
            f"Issued on: {notice.issued_on or 'unknown'}\n"
            f"Category: {notice.category}\n\n"
            "Extract facts from the following pages. Page markers are authoritative; "
            "the 'page' field must be the page number where the span appears.\n\n"
            f"{extraction.text_with_markers()}"
        )
        try:
            payload = self.gemini.generate_json(
                prompt, system_instruction=SYSTEM_PROMPT, temperature=0.0, max_output_tokens=8192
            )
        except ExternalServiceError as exc:
            logger.warning("gemini extraction failed: %s", exc.message)
            return None

        raw_facts: list[Any]
        if isinstance(payload, dict):
            raw_facts = payload.get("facts") or []
        elif isinstance(payload, list):
            raw_facts = payload
        else:
            return None
        if not isinstance(raw_facts, list):
            return None

        result = ExtractionResult(method="gemini")
        for raw in raw_facts:
            try:
                validated = GeminiFact.model_validate(raw)
            except ValidationError as exc:
                result.errors.append(f"Invalid Gemini fact schema: {exc.errors()[:1]}")
                continue
            fact, error = self._normalize_gemini_fact(validated, extraction, notice)
            if fact is not None:
                result.facts.append(fact)
            elif error:
                result.errors.append(error)
        if not result.facts:
            result.requires_manual_review = True
            result.error = "No valid facts could be extracted"
        return result

    def _normalize_gemini_fact(
        self, raw: GeminiFact, extraction: PDFExtraction, notice: Notice
    ) -> tuple[ExtractedFact | None, str | None]:
        try:
            scope = normalize_scope(raw.scope or {})
            category = (raw.category or self._infer_category(raw.fact_key or "")).lower()
            if category not in FACT_CATEGORIES:
                category = FactCategory.OTHER.value
            fact_key = normalize_key(raw.fact_key or "")
            if not fact_key:
                return None, "Fact missing fact_key"
            value_json, value_text, value_number, value_date, currency, unit = self._normalize_value(
                raw.value, raw.value_text, raw.currency, raw.unit, category
            )
            effective_from = parse_date(raw.effective_from)
            effective_to = parse_date(raw.effective_to)
            validate_date_range(effective_from, effective_to)
            page_number = raw.page
            if page_number is not None and extraction.page(page_number) is None:
                return None, f"Fact references invalid page {page_number}"
            span = normalize_whitespace(raw.span) or value_text
            bbox, precision = locate_span(extraction, page_number, span)
            if category in {FactCategory.DATE.value, FactCategory.SCHEDULE.value, FactCategory.HOLIDAY.value} and value_date is None:
                return None, f"Fact {fact_key} has no parseable date"
            return (
                ExtractedFact(
                    fact_key=fact_key,
                    category=category,
                    title=raw.title or value_text[:200],
                    value_json=value_json,
                    value_text=value_text,
                    value_number=value_number,
                    value_date=value_date,
                    currency=currency,
                    unit=unit,
                    scope=scope,
                    effective_from=effective_from,
                    effective_to=effective_to,
                    page_number=page_number,
                    source_text=span,
                    source_bbox=bbox,
                    source_precision=precision,
                    confidence=max(0.0, min(1.0, float(raw.confidence))),
                    supersedes_ref=raw.supersedes_ref,
                ),
                None,
            )
        except (ValidationFailure, ValueError, TypeError) as exc:
            return None, f"Invalid fact: {exc}"

    # -------------------------------------------------------------- heuristic
    def _extract_heuristic(self, extraction: PDFExtraction, notice: Notice) -> ExtractionResult:
        result = ExtractionResult(method="heuristic")
        seen: set[tuple[str, str, int | None]] = set()
        for page in extraction.pages:
            for line in page.lines:
                text = normalize_whitespace(line.text)
                if len(text) < 5:
                    continue
                scope = self._detect_scope(text, notice)
                for fact in self._facts_from_line(
                    text, page.number, line.bbox, scope, notice
                ):
                    identity = (fact.fact_key, fact.value_text, fact.page_number)
                    if identity in seen:
                        continue
                    seen.add(identity)
                    result.facts.append(fact)
        if not result.facts:
            result.requires_manual_review = True
            result.error = "No facts matched the conservative extractor; manual review required."
            result.errors.append(result.error)
        elif extraction.requires_ocr:
            result.requires_manual_review = True
        return result

    def _facts_from_line(
        self, text: str, page: int, bbox: list[float], scope: dict, notice: Notice
    ) -> list[ExtractedFact]:
        facts: list[ExtractedFact] = []
        lowered = text.lower()
        amount = self._find_amount(text)
        percentage = self._find_percentage(text)
        found_date = self._find_date(text)
        effective_from = notice.issued_on

        if amount is not None and "fee" in lowered and "late fee" not in lowered:
            pass  # handled below (kept for readability)
        if amount is not None and "fee" in lowered:
            key = self._fee_key(lowered)
            facts.append(
                self._build_fact(
                    fact_key=key,
                    category=FactCategory.FEE.value,
                    title=f"{key.split('.')[-1].replace('_', ' ').title()}",
                    value_json={"amount": amount, "currency": "INR"},
                    value_text=f"INR {amount:g}",
                    value_number=amount,
                    currency="INR",
                    unit="INR",
                    scope=scope,
                    effective_from=effective_from,
                    page=page,
                    span=text,
                    bbox=bbox,
                    confidence=0.55,
                    notice=notice,
                )
            )

        if found_date is not None and self._looks_like_date_fact(lowered):
            key = self._date_key(lowered)
            facts.append(
                self._build_fact(
                    fact_key=key,
                    category=FactCategory.DATE.value,
                    title=self._title_from_key(key),
                    value_json={"date": found_date.isoformat()},
                    value_text=format_human_date(found_date),
                    value_date=found_date,
                    scope=scope,
                    effective_from=min(effective_from, found_date) if effective_from else effective_from,
                    page=page,
                    span=text,
                    bbox=bbox,
                    confidence=0.55,
                    notice=notice,
                )
            )

        if percentage is not None and "attendance" in lowered:
            facts.append(
                self._build_fact(
                    fact_key="policy.attendance_requirement",
                    category=FactCategory.ATTENDANCE.value,
                    title="Attendance requirement",
                    value_json={"percentage": percentage},
                    value_text=f"{percentage:g}%",
                    value_number=percentage,
                    unit="%",
                    scope=scope,
                    effective_from=effective_from,
                    page=page,
                    span=text,
                    bbox=bbox,
                    confidence=0.5,
                    notice=notice,
                )
            )

        if "document" in lowered and any(word in lowered for word in ("required", "submit", "carry")):
            facts.append(
                self._build_fact(
                    fact_key="document.required_documents",
                    category=FactCategory.DOCUMENT.value,
                    title="Required documents",
                    value_json={"text": text},
                    value_text=text,
                    scope=scope,
                    effective_from=effective_from,
                    page=page,
                    span=text,
                    bbox=bbox,
                    confidence=0.42,
                    notice=notice,
                )
            )

        if "eligib" in lowered and found_date is None and amount is None:
            facts.append(
                self._build_fact(
                    fact_key="eligibility.general",
                    category=FactCategory.ELIGIBILITY.value,
                    title="Eligibility",
                    value_json={"text": text},
                    value_text=text,
                    scope=scope,
                    effective_from=effective_from,
                    page=page,
                    span=text,
                    bbox=bbox,
                    confidence=0.4,
                    notice=notice,
                )
            )
        return facts

    def _build_fact(
        self,
        *,
        fact_key: str,
        category: str,
        title: str | None,
        value_json: dict,
        value_text: str,
        scope: dict,
        effective_from: date | None,
        page: int,
        span: str,
        bbox: list[float] | None,
        confidence: float,
        notice: Notice,
        value_number: float | None = None,
        value_date: date | None = None,
        currency: str | None = None,
        unit: str | None = None,
    ) -> ExtractedFact:
        return ExtractedFact(
            fact_key=normalize_key(fact_key),
            category=category,
            title=title,
            value_json=value_json,
            value_text=value_text,
            value_number=value_number,
            value_date=value_date,
            currency=currency,
            unit=unit,
            scope=scope,
            effective_from=effective_from,
            effective_to=None,
            page_number=page,
            source_text=span,
            source_bbox=bbox,
            source_precision="exact" if bbox else "page",
            confidence=confidence,
            description=None,
        )

    @staticmethod
    def _find_amount(text: str) -> float | None:
        patterns = [
            r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d{1,2})?)",
            r"([\d,]+(?:\.\d{1,2})?)\s*(?:rs\.?|rupees|inr|₹)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1).replace(",", ""))
                except ValueError:
                    return None
        return None

    @staticmethod
    def _find_percentage(text: str) -> float | None:
        match = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", text)
        if match:
            try:
                value = float(match.group(1))
            except ValueError:
                return None
            return value if 0 <= value <= 100 else None
        return None

    @staticmethod
    def _find_date(text: str) -> date | None:
        patterns = [
            r"\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b",
            r"\b\d{4}-\d{2}-\d{2}\b",
            r"\b\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)[a-z,]*\s+\d{4}\b",
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                parsed = parse_date(match.group(0))
                if parsed:
                    return parsed
        return None

    @staticmethod
    def _looks_like_date_fact(lowered: str) -> bool:
        keywords = (
            "last date", "deadline", "due date", "on or before", "exam date",
            "examination date", "will be held", "scheduled", "exam form",
            "admission", "registration", "scholarship", "result", "fee payment",
            "hostel", "commence", "starts on", "begin",
        )
        return any(keyword in lowered for keyword in keywords)

    @staticmethod
    def _fee_key(lowered: str) -> str:
        mapping = {
            "late fee": "fee.late_fee",
            "tuition": "fee.tuition_fee",
            "hostel": "fee.hostel_fee",
            "exam": "fee.examination_fee",
            "examination": "fee.examination_fee",
            "admission": "fee.admission_fee",
            "library": "fee.library_fee",
            "transport": "fee.transport_fee",
        }
        for needle, key in mapping.items():
            if needle in lowered:
                return key
        return "fee.general"

    @staticmethod
    def _date_key(lowered: str) -> str:
        if "exam form" in lowered or "examination form" in lowered:
            return "date.exam_form_last_date"
        if "scholarship" in lowered:
            return "date.scholarship_deadline"
        if "admission" in lowered:
            return "date.admission_deadline"
        if "registration" in lowered:
            return "date.registration_last_date"
        if "hostel" in lowered:
            return "date.hostel_last_date"
        if "fee payment" in lowered or "fee" in lowered:
            return "date.fee_last_date"
        if "revaluation" in lowered or "rechecking" in lowered:
            return "date.revaluation_last_date"
        if "result" in lowered:
            return "date.result_date"
        if "holiday" in lowered or "vacation" in lowered:
            return "date.holiday"
        if "commence" in lowered or "semester start" in lowered or "classes begin" in lowered:
            return "date.semester_start"
        if "exam" in lowered or "examination" in lowered:
            return "date.exam_date"
        return "date.deadline"

    @staticmethod
    def _detect_scope(text: str, notice: Notice) -> dict:
        scope = normalize_scope({})
        sem_match = re.search(r"\bsem(?:ester)?\s*[-:]?\s*(\d{1,2})\b", text, re.IGNORECASE)
        if sem_match:
            try:
                sem = int(sem_match.group(1))
                if 1 <= sem <= 12:
                    scope["semester"] = sem
            except ValueError:
                pass
        course_match = re.search(
            r"\b(B\.?\s?Tech(?:\s+(?:CS|CSE|IT|ECE|EEE|ME|Civil))?|B\.?\s?E\.?|"
            r"M\.?\s?Tech|B\.?\s?Com|BBA|BCA|MCA|MBA|B\.?\s?Sc|M\.?\s?Sc|BA|MA)\b",
            text,
            re.IGNORECASE,
        )
        if course_match:
            scope["course"] = normalize_whitespace(course_match.group(1))
        academic_year_match = re.search(r"\b(20\d{2})\s*[-/]\s*(\d{2,4})\b", text)
        if academic_year_match:
            try:
                scope["academic_year"] = validate_academic_year(academic_year_match.group(0))
            except ValidationFailure:
                pass
        batch_match = re.search(r"\b(20\d{2})\s+batch\b", text, re.IGNORECASE)
        if batch_match:
            scope["batch"] = batch_match.group(1)
        return scope

    @staticmethod
    def _infer_category(fact_key: str) -> str:
        prefix = (fact_key or "").split(".")[0].lower()
        mapping = {
            "fee": FactCategory.FEE.value,
            "date": FactCategory.DATE.value,
            "policy": FactCategory.POLICY.value,
            "schedule": FactCategory.SCHEDULE.value,
            "eligibility": FactCategory.ELIGIBILITY.value,
            "document": FactCategory.DOCUMENT.value,
            "attendance": FactCategory.ATTENDANCE.value,
            "scholarship": FactCategory.SCHOLARSHIP.value,
            "holiday": FactCategory.HOLIDAY.value,
        }
        return mapping.get(prefix, FactCategory.OTHER.value)

    @staticmethod
    def _title_from_key(key: str) -> str:
        return key.split(".")[-1].replace("_", " ").title()

    @staticmethod
    def _normalize_value(
        value: Any,
        value_text: str | None,
        currency: str | None,
        unit: str | None,
        category: str,
    ) -> tuple[dict, str, float | None, date | None, str | None, str | None]:
        value_number: float | None = None
        value_date: date | None = None
        if isinstance(value, dict):
            value_json = dict(value)
        elif isinstance(value, list):
            value_json = {"items": value}
        elif value is None:
            value_json = {}
        else:
            value_json = {"value": value}

        amount = value_json.get("amount", value_json.get("value"))
        if isinstance(amount, (int, float)) or (
            isinstance(amount, str) and re.fullmatch(r"[\d,]+(?:\.\d+)?", amount.strip())
        ):
            try:
                value_number = float(str(amount).replace(",", ""))
            except ValueError:
                value_number = None
            if not currency:
                detected = re.search(r"(?:rs\.?|inr|₹)", str(value_text or ""), re.IGNORECASE)
                currency = "INR" if detected else None
        raw_date = value_json.get("date")
        value_date = parse_date(raw_date) if raw_date else None
        if value_date is None:
            value_date = parse_date(value_text)
        if value_date is None and category in {"date", "schedule", "holiday"}:
            value_date = parse_date(value_json.get("value"))

        if not value_text:
            if value_date:
                value_text = format_human_date(value_date)
            elif value_number is not None:
                prefix = f"{currency} " if currency else ""
                suffix = f" {unit}" if unit and unit not in {"INR", currency} else ""
                value_text = f"{prefix}{value_number:g}{suffix}".strip()
            elif value_json:
                value_text = ", ".join(f"{k}: {v}" for k, v in value_json.items())
            else:
                value_text = ""
        if not value_text:
            raise ValidationFailure("Fact has no usable value")
        return value_json, value_text, value_number, value_date, currency, unit
