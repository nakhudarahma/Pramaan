"""Grounded generation for static/policy questions."""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.integrations.gemini_client import GeminiClient
from app.services import verification_service
from app.services.retrieval_service import RetrievedChunk
from app.utils.text_utils import normalize_whitespace, truncate

logger = get_logger("pramaan.rag")

_SYSTEM = (
    "You answer college policy questions using ONLY the supplied notice excerpts. "
    "If the excerpts do not contain the answer, set answerable to false. "
    "Never invent fees, dates, percentages, eligibility rules, or contacts. "
    "Copy every number/date exactly as written in the excerpts. "
    "Do not add citation markers; the application attaches citations. "
    "Return JSON only: {\"answerable\": true|false, \"answer\": \"...\", "
    "\"used_sources\": [1]}. used_sources must list the Source numbers you used. "
    "Keep the answer concise (max 4 sentences)."
)


@dataclass(slots=True)
class StaticAnswer:
    text: str
    generated_by: str
    used_chunks: list[RetrievedChunk] = field(default_factory=list)
    verification_errors: list[str] = field(default_factory=list)
    answerable: bool = True


def _context(retrieved: list[RetrievedChunk]) -> str:
    lines: list[str] = []
    for index, item in enumerate(retrieved, start=1):
        lines.append(
            f"[Source {index}] notice=\"{item.notice.title}\" page={item.chunk.page_number}\n"
            f"{truncate(item.chunk.text, 1600)}"
        )
    return "\n\n".join(lines)


def _verify(text: str, retrieved: list[RetrievedChunk], context: dict) -> list[str]:
    source_texts = [item.chunk.text for item in retrieved]
    numbers_context = dict(context)
    numbers_context["pages"] = ",".join(str(item.chunk.page_number or "") for item in retrieved)
    numbers_context["titles"] = " | ".join(item.notice.title for item in retrieved)
    return verification_service.verify_grounded_text(
        text, source_texts=source_texts, context=numbers_context
    )


def _fallback_excerpt(retrieved: list[RetrievedChunk], context: dict) -> StaticAnswer:
    top = retrieved[0]
    excerpt = truncate(top.chunk.text, 700)
    if excerpt and not excerpt.endswith((".", "!", "?", "”", '"')):
        cut = max(excerpt.rfind(". "), excerpt.rfind(".\n"))
        if cut > 200:
            excerpt = excerpt[: cut + 1]
    page = f", page {top.chunk.page_number}" if top.chunk.page_number else ""
    text = f'According to the notice "{top.notice.title}"{page}: “{excerpt}”'
    errors = _verify(text, [top], context)
    return StaticAnswer(
        text=text,
        generated_by="source_excerpt",
        used_chunks=[top],
        verification_errors=errors,
        answerable=True,
    )


def compose_static_answer(
    db: Session,
    *,
    question: str,
    context: dict,
    retrieved: list[RetrievedChunk],
    gemini: GeminiClient | None = None,
    settings: Settings | None = None,
    language: str = "en",
) -> StaticAnswer | None:
    settings = settings or get_settings()
    if not retrieved:
        return None

    client = gemini or GeminiClient(settings)
    if not client.configured:
        return _fallback_excerpt(retrieved, context)

    base_prompt = (
        f"Student question: {question}\n"
        f"Preferred language: {language}\n\n"
        f"Notice excerpts:\n{_context(retrieved)}"
    )
    attempts: list[str] = []
    for attempt in range(2):
        prompt = base_prompt
        if attempt:
            prompt += (
                "\n\nYour previous draft failed verification: "
                + "; ".join(attempts[-6:])
                + "\nUse only exact numbers/dates from the excerpts. Return JSON only."
            )
        try:
            payload = client.generate_json(prompt, system_instruction=_SYSTEM, max_output_tokens=800)
        except ExternalServiceError as exc:
            logger.warning("static generation unavailable: %s", exc)
            return _fallback_excerpt(retrieved, context)

        if not isinstance(payload, dict):
            attempts.append("response was not a JSON object")
            continue
        if payload.get("answerable") is False:
            return None
        text = normalize_whitespace(str(payload.get("answer") or ""))
        if not text:
            attempts.append("response was empty")
            continue
        errors = _verify(text, retrieved, context)
        if not errors:
            used: list[RetrievedChunk] = []
            raw_used = payload.get("used_sources")
            if isinstance(raw_used, list):
                for value in raw_used[:5]:
                    try:
                        index = int(value) - 1
                    except (TypeError, ValueError):
                        continue
                    if 0 <= index < len(retrieved) and retrieved[index] not in used:
                        used.append(retrieved[index])
            if not used:
                used = retrieved[:1]
            return StaticAnswer(
                text=text,
                generated_by="gemini",
                used_chunks=used,
            )
        attempts.extend(errors)

    # Gemini failed verification twice: deterministic source excerpt.
    fallback = _fallback_excerpt(retrieved, context)
    fallback.generated_by = "source_excerpt_after_verification_failure"
    return fallback
