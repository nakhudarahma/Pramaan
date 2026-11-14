"""Unit tests for scope, lifecycle, extraction and security rules."""
from __future__ import annotations

from datetime import date

import pytest

from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models.enums import FactStatus
from app.utils.validators import (
    ValidationFailure,
    assert_transition,
    compute_active_scope_key,
    normalize_academic_year,
    normalize_semester,
    scope_matches,
    scopes_equal,
    scopes_overlap,
    validate_date_range,
    validate_pdf_signature,
)


def test_scope_matching_allows_broad_facts_but_not_wrong_scope():
    broad = {"course": None, "semester": None, "academic_year": None}
    btech4 = {"course": "B.Tech", "semester": 4, "academic_year": "2026-27"}
    assert scope_matches(broad, btech4)
    assert scope_matches(
        {"course": "B.Tech", "semester": None, "academic_year": None}, btech4
    )
    assert not scope_matches(
        {"course": "B.Tech", "semester": 6, "academic_year": None}, btech4
    )
    assert not scope_matches(
        {"course": "B.Tech", "semester": None, "academic_year": "2025-26"}, btech4
    )
    assert not scope_matches({"course": "B.Tech"}, {"semester": 4})


def test_scope_overlap_and_equality_and_active_key():
    a = {"course": "B.Tech", "semester": 4}
    b = {"course": "B.Tech", "semester": None}
    c = {"course": "B.Tech", "semester": 4}
    assert scopes_overlap(a, b)
    assert scopes_equal(a, c)
    assert not scopes_equal(a, b)
    assert not scopes_overlap(a, {"course": "B.Com", "semester": 4})
    assert compute_active_scope_key("fee.late_fee", a) == compute_active_scope_key(
        "fee.late_fee", c
    )
    assert compute_active_scope_key("fee.late_fee", a) != compute_active_scope_key(
        "fee.late_fee", b
    )
    legacy = {"academic_year": "2026-2027"}
    canonical = {"academic_year": "2026-27"}
    assert scopes_equal(legacy, canonical)
    assert scopes_overlap(legacy, canonical)
    assert scope_matches(canonical, legacy)
    assert compute_active_scope_key("date.exam_date", legacy) == compute_active_scope_key(
        "date.exam_date", canonical
    )


def test_normalization_helpers():
    assert normalize_semester("Sem 4") == 4
    assert normalize_semester("all") is None
    assert normalize_academic_year("2026-2027") == "2026-27"
    with pytest.raises(ValidationFailure):
        normalize_semester(13)
    with pytest.raises(ValidationFailure):
        validate_date_range(date(2026, 12, 1), date(2026, 11, 1))


def test_fact_transition_guard():
    assert_transition(FactStatus.CANDIDATE.value, FactStatus.ACTIVE.value)
    assert_transition(FactStatus.ACTIVE.value, FactStatus.SUPERSEDED.value)
    with pytest.raises(ValidationFailure):
        assert_transition(FactStatus.REJECTED.value, FactStatus.ACTIVE.value)
    with pytest.raises(ValidationFailure):
        assert_transition(FactStatus.SUPERSEDED.value, FactStatus.ACTIVE.value)


def test_pdf_signature_validation():
    validate_pdf_signature(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF")
    with pytest.raises(ValidationFailure):
        validate_pdf_signature(b"plain text")
    with pytest.raises(ValidationFailure):
        validate_pdf_signature(b"%PDF-1.4\nno eof marker")


def test_password_and_token_helpers():
    hashed = hash_password("Password123")
    assert verify_password("Password123", hashed)
    assert not verify_password("wrong", hashed)

    token = create_access_token("user-id", "student")
    payload = decode_access_token(token)
    assert payload["sub"] == "user-id"
    assert payload["role"] == "student"

    with pytest.raises(UnauthorizedError):
        decode_access_token("not-a-token")


def test_heuristic_extraction_uses_exact_line_bbox(pdf_factory):
    from app.services.extraction_service import ExtractionService
    from app.services.pdf_service import extract_pdf
    from app.models.notice import Notice

    data = pdf_factory(
        ["Late fee of INR 500 will apply after 20 November 2026."]
    )
    extraction = extract_pdf(data)
    notice = Notice(document_id="00000000-0000-0000-0000-000000000001", title="Test")
    result = ExtractionService().extract(extraction, notice)
    assert result.method == "heuristic"
    assert result.facts
    fee = next(fact for fact in result.facts if fact.fact_key == "fee.late_fee")
    assert fee.source_bbox is not None
    assert len(fee.source_bbox) == 4
    assert fee.source_precision == "exact"


def test_heuristic_uses_canonical_date_keys(pdf_factory):
    from app.models.notice import Notice
    from app.services.extraction_service import ExtractionService
    from app.services.pdf_service import extract_pdf

    data = pdf_factory(
        [
            "Last date for admission is 20 November 2026.",
            "Last date for fee payment is 21 November 2026.",
        ]
    )
    extraction = extract_pdf(data)
    notice = Notice(document_id="00000000-0000-0000-0000-000000000001", title="Test")
    result = ExtractionService().extract(extraction, notice)
    keys = {fact.fact_key for fact in result.facts}
    assert "date.admission_deadline" in keys
    assert "date.fee_last_date" in keys
