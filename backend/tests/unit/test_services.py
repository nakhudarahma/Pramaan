"""Unit tests for deterministic routing, embeddings and verification."""
from __future__ import annotations

from datetime import date, timedelta

from app.config import Settings
from app.integrations.gemini_client import GeminiClient
from app.models.fact import Fact
from app.schemas.student import StudentContext
from app.services import answer_service, embedding_service, intent_router, retrieval_service, verification_service
from app.utils.text_utils import (
    chunk_text,
    extract_date_like,
    extract_numbers,
    normalize_key,
    tokenize,
)


def _fact() -> Fact:
    return Fact(
        id="fact-1",
        fact_key="fee.late_fee",
        category="fee",
        title="Late fee",
        value_json={"amount": 500, "currency": "INR"},
        value_text="INR 500",
        value_number=500,
        currency="INR",
        value_date=date(2026, 11, 20),
        effective_from=date(2026, 11, 1),
        page_number=1,
        version=2,
        status="active",
        source_precision="exact",
        extraction_method="test",
        notice_id="notice-1",
        document_id="doc-1",
        created_at=None,
        updated_at=None,
    )


def test_intent_rules_detect_volatile_and_static_questions():
    fee = intent_router.classify_with_rules("What is the late fee?")
    assert fee.intent == "volatile"
    assert fee.fact_keys == ["fee.late_fee"]

    attendance = intent_router.classify_with_rules("What is the attendance requirement?")
    assert attendance.intent == "static"
    assert "policy.attendance_requirement" in attendance.fact_keys

    ambiguous = intent_router.classify_with_rules("Tell me about the department")
    assert ambiguous.intent == "unclear"


def test_intent_extracts_course_semester_and_hinglish():
    result = intent_router.classify_with_rules("Mera B.Tech Sem 4 exam kab hai 2026-2027?")
    assert result.intent == "volatile"
    assert result.slots["course"] == "B.Tech"
    assert result.slots["semester"] == 4
    assert result.slots["academic_year"] == "2026-27"
    assert result.slots["language"] == "hinglish"


def test_merge_context_normalizes_academic_year():
    from app.api.deps import merge_context

    scope = merge_context(StudentContext(academic_year="2026-2027"), None)
    assert scope["academic_year"] == "2026-27"


def test_candidate_chunk_limit_applies_after_scope_filter(db):
    from app.models.base import utcnow
    from app.models.chunk import Chunk
    from app.models.document import Document
    from app.models.notice import Notice
    from app.repositories import chunk_repository

    document = Document(
        original_filename="scope.pdf",
        size_bytes=1,
        sha256="a" * 64,
        storage_key="documents/scope.pdf",
        status="processed",
    )
    db.add(document)
    db.flush()
    notice = Notice(
        document_id=document.id,
        title="Scope Notice",
        category="general",
        status="published",
    )
    db.add(notice)
    db.flush()

    now = utcnow()
    for index in range(3):
        db.add(
            Chunk(
                notice_id=notice.id,
                document_id=document.id,
                page_number=index + 1,
                chunk_index=index,
                text=f"Other course chunk {index}",
                scope_json={"course": "B.Com"},
                token_count=4,
                created_at=now + timedelta(seconds=index + 1),
            )
        )
    in_scope = Chunk(
        notice_id=notice.id,
        document_id=document.id,
        page_number=4,
        chunk_index=4,
        text="Relevant B.Tech chunk",
        scope_json={"course": "B.Tech"},
        token_count=4,
        created_at=now - timedelta(days=1),
    )
    db.add(in_scope)
    db.commit()

    matching = chunk_repository.candidate_chunks(db, {"course": "B.Tech"}, limit=2)
    assert [chunk.id for chunk, _ in matching] == [in_scope.id]


def test_static_retrieval_uses_configured_limits(db, monkeypatch):
    captured: dict = {}

    def fake_retrieve(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(retrieval_service, "retrieve", fake_retrieve)
    settings = Settings(static_similarity_threshold=0.42, max_static_context_chunks=3)
    result = answer_service._static_answer(
        db,
        question="What is the attendance policy?",
        scope={},
        intent=intent_router.IntentResult(intent="static", topic="attendance"),
        gemini=GeminiClient(settings),
        settings=settings,
        latency_ms=1.0,
    )
    assert captured["limit"] == 3
    assert captured["min_score"] == 0.42
    assert result.state == "unavailable"


def test_hash_embeddings_are_deterministic_and_comparable():
    first, provider = embedding_service.embed("late fee payment")
    second, _ = embedding_service.embed("late fee payment")
    assert provider == "hash-ngram-v1"
    assert len(first) == len(second) == 768
    assert first == second
    assert embedding_service.cosine(first, second) == 1.0
    assert embedding_service.cosine(first, [1.0, 2.0]) == 0.0


def test_placeholder_rendering_and_template_guards():
    fact = _fact()
    facts = {fact.id: fact}
    rendered = verification_service.render_template(
        "The late fee is {fact:fact-1.amount}.", facts
    )
    assert rendered == "The late fee is INR 500."
    assert verification_service.validate_template(
        "The late fee is {fact:fact-1.amount}.", facts
    ) == []
    assert verification_service.validate_template("The late fee is INR 500.", facts)
    assert verification_service.validate_template(
        "Payment on 20 November 2026 is {fact:fact-1.value}.", facts
    )


def test_verify_answer_rejects_unsupported_numbers():
    fact = _fact()
    assert verification_service.verify_answer("The late fee is INR 500.", facts=[fact]) == []
    assert verification_service.verify_answer("The late fee is INR 700.", facts=[fact])
    assert verification_service.verify_answer(
        "The late fee is {fact:fact-1.amount}.", facts=[fact]
    )
    assert verification_service.verify_scope([fact], {"course": "B.Tech"}) == []


def test_grounded_text_verification_uses_source_numbers_only():
    source = ["Students must maintain at least 75% attendance."]
    assert (
        verification_service.verify_grounded_text(
            "Students need 75% attendance.", source_texts=source
        )
        == []
    )
    assert verification_service.verify_grounded_text(
        "Students need 80% attendance.", source_texts=source
    )


def test_text_helpers_normalize_extract_and_chunk():
    assert normalize_key("Late Fee / Semester 4") == "late_fee_semester_4"
    assert extract_numbers("INR 1,500 and 75%") == [1500.0, 75.0]
    assert extract_date_like("on 20 November 2026 and 2026-11-20") == [
        "20 November 2026",
        "2026-11-20",
    ]
    assert "the" not in tokenize("What is the late fee?")
    chunks = chunk_text("First paragraph.\n\nSecond paragraph.", max_chars=30)
    assert len(chunks) == 2
