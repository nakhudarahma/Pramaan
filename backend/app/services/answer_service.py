"""Student question answering orchestration.

Rules:
* Volatile values come only from approved, active, in-scope facts.
* Static answers come only from published, in-scope source chunks.
* The LLM may phrase volatile answers, but values are injected from the ledger
  and independently verified.  On any doubt Pramaan abstains.
* Unanswered questions are logged for admins without storing user identity.
"""
from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.integrations.gemini_client import GeminiClient
from app.models.enums import FactStatus
from app.models.fact import Fact
from app.models.notice import Notice
from app.models.user import User
from app.repositories import fact_repository, unanswered_repository
from app.schemas.answer import (
    AnswerResponse,
    AskRequest,
    SupersessionInfo,
    ValidityInfo,
)
from app.services import (
    citation_service,
    fact_service,
    intent_router,
    rag_service,
    retrieval_service,
    verification_service,
)
from app.utils.date_utils import format_human_date, normalize_academic_year
from app.utils.validators import normalize_scope_value

logger = get_logger("pramaan.answer")

_OFFICE_BY_TOPIC = {
    "fee": "the Accounts Office",
    "date": "the Examination Cell or Academic Office",
    "schedule": "the Examination Cell",
    "attendance": "the Academic Office",
    "scholarship": "the Scholarship Cell",
    "admission": "the Admissions Office",
    "document": "the Admissions or Examination Office",
    "hostel": "the Hostel Office",
    "eligibility": "the Admissions Office",
    "policy": "the Academic Office",
}


def _office(topic: str | None) -> str:
    return _OFFICE_BY_TOPIC.get(topic or "", "the Academic Office")


def build_student_scope(payload: AskRequest, user: User | None = None) -> dict[str, Any]:
    profile = user.student_profile if user is not None else None

    def pick(field: str):
        value = getattr(payload, field, None)
        if value not in (None, ""):
            return value
        return getattr(profile, field, None) if profile is not None else None

    semester = pick("semester")
    try:
        semester = int(semester) if semester not in (None, "") else None
    except (TypeError, ValueError):
        semester = None
    scope = {
        "college": normalize_scope_value(pick("college")),
        "course": normalize_scope_value(pick("course")),
        "department": normalize_scope_value(pick("department")),
        "semester": semester,
        "academic_year": normalize_academic_year(normalize_scope_value(pick("academic_year"))),
        "batch": normalize_scope_value(pick("batch")),
        "student_group": normalize_scope_value(pick("student_group")),
    }
    return {key: value for key, value in scope.items() if value is not None}


def _scope_phrase(fact: Fact) -> str:
    parts: list[str] = []
    if fact.course:
        parts.append(fact.course)
    if fact.semester:
        parts.append(f"Semester {fact.semester}")
    if fact.academic_year:
        parts.append(f"AY {fact.academic_year}")
    if fact.batch:
        parts.append(f"Batch {fact.batch}")
    if fact.student_group:
        parts.append(fact.student_group)
    return f"For {', '.join(parts)}: " if parts else ""


def _validity(facts: list[Fact]) -> ValidityInfo | None:
    if not facts:
        return None
    current = all(fact.status == FactStatus.ACTIVE.value for fact in facts)
    end_dates = {fact.effective_to for fact in facts}
    start_dates = {fact.effective_from for fact in facts}
    if len(end_dates) == 1 and len(start_dates) == 1:
        first = facts[0]
        if first.effective_to:
            label = f"Valid until {format_human_date(first.effective_to)}"
        elif first.effective_from:
            label = f"Effective from {format_human_date(first.effective_from)}"
        else:
            label = "No end date specified in the approved record"
        return ValidityInfo(
            effective_from=first.effective_from,
            effective_to=first.effective_to,
            is_current=current,
            label=label,
        )
    return ValidityInfo(
        is_current=current,
        label="See each cited record for its validity period",
    )


def _supersession(db: Session, facts: list[Fact]) -> SupersessionInfo | None:
    for fact in facts:
        if not fact.previous_fact_id:
            continue
        old = db.get(Fact, fact.previous_fact_id)
        if old is None:
            continue
        old_notice = db.get(Notice, old.notice_id)
        return SupersessionInfo(
            replaces_fact_id=old.id,
            replaces_value_text=old.value_text,
            replaces_notice_title=old_notice.title if old_notice else None,
            replaces_issued_on=old_notice.issued_on if old_notice else None,
        )
    return None


def _template_answer(facts: list[Fact]) -> str:
    if len(facts) == 1:
        fact = facts[0]
        label = fact.title or verification_service.humanize_key(fact.fact_key)
        return f"{_scope_phrase(fact)}{label} is {fact.value_text}."
    lines: list[str] = []
    for fact in facts:
        label = fact.title or verification_service.humanize_key(fact.fact_key)
        lines.append(f"{_scope_phrase(fact)}{label}: {fact.value_text}.")
    return " ".join(lines)


def _log_unanswered(
    db: Session,
    *,
    question: str,
    scope: dict,
    intent: str | None,
    topic: str | None,
) -> bool:
    try:
        unanswered_repository.record(
            db,
            question=question,
            course=scope.get("course"),
            semester=scope.get("semester"),
            academic_year=scope.get("academic_year"),
            intent=intent,
            topic=topic,
        )
        return True
    except Exception:  # noqa: BLE001 - logging must never break answering
        logger.exception("failed to record unanswered question")
        return False


def _unavailable(
    *,
    topic: str | None,
    clarification: str,
    intent: str,
    logged: bool,
    latency_ms: float,
) -> AnswerResponse:
    return AnswerResponse(
        answer=(
            "I couldn't find a current, approved official record that answers this. "
            f"Please contact {_office(topic)} or try rephrasing with your course, "
            "semester and academic year."
        ),
        state="unavailable",
        verified=False,
        intent=intent,
        topic=topic,
        clarification=clarification,
        office_contact=_office(topic),
        unanswered_logged=logged,
        generated_by="abstain",
        latency_ms=latency_ms,
    )


def _clarification(
    *,
    topic: str | None,
    clarification: str,
    logged: bool,
    latency_ms: float,
) -> AnswerResponse:
    return AnswerResponse(
        answer=clarification,
        state="clarification",
        verified=False,
        intent="clarification",
        topic=topic,
        clarification=clarification,
        office_contact=_office(topic),
        unanswered_logged=logged,
        generated_by="abstain",
        latency_ms=latency_ms,
    )


def _volatile_answer(
    db: Session,
    *,
    question: str,
    scope: dict,
    intent: intent_router.IntentResult,
    gemini: GeminiClient,
    settings: Settings,
    request_id: str | None,
    latency_ms: float,
) -> AnswerResponse:
    disputed = fact_repository.matching_disputed_facts(
        db, intent.fact_keys, scope, prefixes=intent.fact_prefixes
    )
    if disputed:
        citations = [c for c in (citation_service.for_fact(db, f) for f in disputed) if c]
        values: list[str] = []
        for fact in disputed[:3]:
            label = fact.title or verification_service.humanize_key(fact.fact_key)
            values.append(f"{label}: {fact.value_text}")
        answer = (
            "Official records currently disagree on this information, so Pramaan will not "
            "guess a value. " + "; ".join(values) + f" Please confirm with {_office(intent.topic)}."
        )
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="volatile", topic=intent.topic
        )
        return AnswerResponse(
            answer=answer,
            state="disputed",
            verified=False,
            intent="volatile",
            topic=intent.topic,
            fact_ids=[f.id for f in disputed],
            citations=citations,
            office_contact=_office(intent.topic),
            unanswered_logged=logged,
            generated_by="code_disputed",
            latency_ms=latency_ms,
        )

    facts = fact_service.best_active_facts(
        db, intent.fact_keys, scope, prefixes=intent.fact_prefixes
    )
    if not facts:
        outdated = fact_service.outdated_facts(
            db, intent.fact_keys, scope, prefixes=intent.fact_prefixes
        )
        if outdated:
            fact = outdated[0]
            citations = [c for c in (citation_service.for_fact(db, f) for f in outdated[:3]) if c]
            label = fact.title or verification_service.humanize_key(fact.fact_key)
            answer = (
                f"The last approved record for {label.lower()} expired on "
                f"{format_human_date(fact.effective_to)} and said: {fact.value_text}. "
                f"It may no longer be current. Please confirm with {_office(intent.topic)}."
            )
            logged = _log_unanswered(
                db, question=question, scope=scope, intent="volatile", topic=intent.topic
            )
            return AnswerResponse(
                answer=answer,
                state="outdated",
                verified=False,
                intent="volatile",
                topic=intent.topic,
                fact_ids=[f.id for f in outdated[:3]],
                citations=citations,
                validity=_validity(outdated[:1]),
                office_contact=_office(intent.topic),
                unanswered_logged=logged,
                generated_by="code_outdated",
                latency_ms=latency_ms,
            )

        if fact_service.any_fact_exists_for_keys(
            db, intent.fact_keys, prefixes=intent.fact_prefixes
        ):
            clarification = (
                "This information exists for a different course, semester or academic year. "
                "I cannot confirm that it applies to your profile without more detail."
            )
            logged = _log_unanswered(
                db, question=question, scope=scope, intent="volatile", topic=intent.topic
            )
            return _clarification(
                topic=intent.topic,
                clarification=clarification,
                logged=logged,
                latency_ms=latency_ms,
            )

        logged = _log_unanswered(
            db, question=question, scope=scope, intent="volatile", topic=intent.topic
        )
        return _unavailable(
            topic=intent.topic,
            clarification="No approved fact matches this question and scope.",
            intent="volatile",
            logged=logged,
            latency_ms=latency_ms,
        )

    citations = [c for c in (citation_service.for_fact(db, f) for f in facts) if c]
    if len(citations) != len(facts):
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="volatile", topic=intent.topic
        )
        return _unavailable(
            topic=intent.topic,
            clarification="A source citation could not be constructed.",
            intent="volatile",
            logged=logged,
            latency_ms=latency_ms,
        )

    context = {
        "semester": scope.get("semester"),
        "academic_year": scope.get("academic_year"),
        "course": scope.get("course"),
    }
    text, generated_by = _phrase_volatile(
        question, facts, context=context, gemini=gemini, settings=settings
    )
    errors = verification_service.verify_answer(text, facts=facts, context=context)
    errors.extend(verification_service.verify_scope(facts, scope))
    if errors:
        logger.warning("answer verification failed errors=%s", errors[:8])
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="volatile", topic=intent.topic
        )
        citation_ids = ",".join(fact.id for fact in facts)
        return _unavailable(
            topic=intent.topic,
            clarification=f"Generated answer failed verification (facts: {citation_ids}).",
            intent="volatile",
            logged=logged,
            latency_ms=latency_ms,
        )

    return AnswerResponse(
        answer=verification_service.sanitize_answer(text),
        state="verified",
        verified=True,
        intent="volatile",
        topic=intent.topic,
        fact_ids=[fact.id for fact in facts],
        citations=citations,
        validity=_validity(facts),
        supersession=_supersession(db, facts),
        office_contact=_office(intent.topic),
        generated_by=generated_by,
        latency_ms=latency_ms,
    )


_SYSTEM = (
    "You phrase answers using ONLY the supplied approved facts. "
    "Every number, date, amount and month must be a placeholder; never type one yourself. "
    "Placeholders: {fact:FACT_ID.value} (default value), {fact:FACT_ID.date}, "
    "{fact:FACT_ID.amount}, {fact:FACT_ID.title}, {fact:FACT_ID.semester}, "
    "{fact:FACT_ID.academic_year}. "
    "Write 1-3 short sentences. Do not add facts, guesses, contact details or citation markers. "
    "Return JSON only: {\"answerable\": true|false, \"draft\": \"...\"}."
)


def _facts_payload(facts: list[Fact]) -> str:
    rows = []
    for fact in facts:
        rows.append(
            {
                "id": fact.id,
                "fact_key": fact.fact_key,
                "title": fact.title,
                "value_type": "date" if fact.value_date else (
                    "amount" if fact.value_number is not None else "text"
                ),
                "scope": {
                    "course": fact.course,
                    "semester": fact.semester,
                    "academic_year": fact.academic_year,
                    "batch": fact.batch,
                },
                "effective_from": fact.effective_from.isoformat() if fact.effective_from else None,
                "effective_to": fact.effective_to.isoformat() if fact.effective_to else None,
            }
        )
    return str(rows)


def _phrase_volatile(
    question: str,
    facts: list[Fact],
    *,
    context: dict,
    gemini: GeminiClient,
    settings: Settings,
) -> tuple[str, str]:
    fallback = _template_answer(facts)
    if not gemini.configured:
        return fallback, "code_template"

    facts_by_id = {fact.id: fact for fact in facts}
    prompt = (
        f"Question: {question}\n"
        f"Approved facts: {_facts_payload(facts)}\n"
        "Use only placeholders for values. If the facts do not answer the question, "
        "set answerable to false."
    )
    attempts: list[str] = []
    for attempt in range(2):
        current_prompt = prompt
        if attempt:
            current_prompt += (
                "\n\nPrevious draft failed verification: "
                + "; ".join(attempts[-6:])
                + "\nUse placeholders only; do not type any digit or month."
            )
        try:
            payload = gemini.generate_json(
                current_prompt, system_instruction=_SYSTEM, max_output_tokens=400
            )
        except ExternalServiceError as exc:
            logger.warning("volatile phrasing unavailable: %s", exc)
            return fallback, "code_template_after_gemini_error"
        if not isinstance(payload, dict):
            attempts.append("response was not a JSON object")
            continue
        if payload.get("answerable") is False:
            return fallback, "code_template_model_declined"
        draft = str(payload.get("draft") or "")
        errors = verification_service.validate_template(draft, facts_by_id)
        if errors:
            attempts.extend(errors)
            continue
        rendered = verification_service.render_template(draft, facts_by_id)
        if verification_service.verify_answer(rendered, facts=facts, context=context):
            attempts.append("rendered answer contained unsupported numbers")
            continue
        return rendered, "gemini"

    return fallback, "code_template_after_verification_failure"


def _static_answer(
    db: Session,
    *,
    question: str,
    scope: dict,
    intent: intent_router.IntentResult,
    gemini: GeminiClient,
    settings: Settings,
    latency_ms: float,
) -> AnswerResponse:
    retrieved = retrieval_service.retrieve(
        db,
        question,
        scope,
        gemini=gemini,
        settings=settings,
        limit=settings.max_static_context_chunks,
        min_score=settings.static_similarity_threshold,
    )
    if not retrieved:
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="static", topic=intent.topic
        )
        return _unavailable(
            topic=intent.topic,
            clarification="No published notice passage matched this question.",
            intent="static",
            logged=logged,
            latency_ms=latency_ms,
        )

    generated = rag_service.compose_static_answer(
        db,
        question=question,
        context={"semester": scope.get("semester"), "academic_year": scope.get("academic_year")},
        retrieved=retrieved,
        gemini=gemini,
        settings=settings,
    )
    if generated is None:
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="static", topic=intent.topic
        )
        return _unavailable(
            topic=intent.topic,
            clarification="The retrieved notices did not support an answer.",
            intent="static",
            logged=logged,
            latency_ms=latency_ms,
        )

    citations = [c for c in (citation_service.for_chunk(db, item.chunk) for item in generated.used_chunks) if c]
    if not citations:
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="static", topic=intent.topic
        )
        return _unavailable(
            topic=intent.topic,
            clarification="A source citation could not be constructed.",
            intent="static",
            logged=logged,
            latency_ms=latency_ms,
        )
    if generated.verification_errors:
        logger.warning("static answer verification failed errors=%s", generated.verification_errors[:8])
        logged = _log_unanswered(
            db, question=question, scope=scope, intent="static", topic=intent.topic
        )
        return _unavailable(
            topic=intent.topic,
            clarification="Generated answer failed source verification.",
            intent="static",
            logged=logged,
            latency_ms=latency_ms,
        )

    return AnswerResponse(
        answer=verification_service.sanitize_answer(generated.text),
        state="static_grounded",
        verified=True,
        intent="static",
        topic=intent.topic,
        citations=citations,
        office_contact=_office(intent.topic),
        generated_by=generated.generated_by,
        latency_ms=latency_ms,
    )


def ask(
    db: Session,
    payload: AskRequest,
    *,
    user: User | None = None,
    gemini: GeminiClient | None = None,
    settings: Settings | None = None,
    request_id: str | None = None,
) -> AnswerResponse:
    started = time.perf_counter()
    settings = settings or get_settings()
    client = gemini or GeminiClient(settings)
    scope = build_student_scope(payload, user)

    fact_service.expire_active_facts(db)
    intent = intent_router.classify(payload.question, gemini=client, settings=settings)
    lookup_scope = dict(scope)
    for key, value in intent.slots.items():
        if key != "language" and value not in (None, ""):
            lookup_scope[key] = (
                normalize_academic_year(value) if key == "academic_year" else value
            )
    lookup_scope = {key: value for key, value in lookup_scope.items() if value is not None}

    if intent.is_volatile:
        return _volatile_answer(
            db,
            question=payload.question,
            scope=lookup_scope,
            intent=intent,
            gemini=client,
            settings=settings,
            request_id=request_id,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    if intent.is_static:
        return _static_answer(
            db,
            question=payload.question,
            scope=lookup_scope,
            intent=intent,
            gemini=client,
            settings=settings,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    clarification = (
        "I'm not sure which official information you need. Ask about fees, deadlines, "
        "attendance, scholarships, admission, documents or exam schedules."
    )
    logged = _log_unanswered(
        db, question=payload.question, scope=lookup_scope, intent="unclear", topic=None
    )
    return _clarification(
        topic=None,
        clarification=clarification,
        logged=logged,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )
