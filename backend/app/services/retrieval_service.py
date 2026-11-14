"""Hybrid retrieval over published notice chunks.

Lexical scoring works with no external services.  When Gemini embeddings are
configured (or the deterministic fallback vectors have been stored) cosine
similarity is blended in.  Only chunks from *published* notices and matching the
student's scope are ever considered.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.gemini_client import GeminiClient
from app.models.chunk import Chunk
from app.models.notice import Notice
from app.repositories import chunk_repository
from app.services import embedding_service
from app.utils.text_utils import tokenize


@dataclass(slots=True)
class RetrievedChunk:
    chunk: Chunk
    notice: Notice
    score: float
    lexical_score: float
    semantic_score: float


def _lexical_scores(question_tokens: list[str], row_tokens: list[str]) -> float:
    query = set(question_tokens)
    if not query or not row_tokens:
        return 0.0
    document = set(row_tokens)
    overlap = query & document
    if not overlap:
        return 0.0

    # Coverage rewards matching all query terms; density rewards a concentrated
    # match inside a short chunk.
    coverage = len(overlap) / len(query)
    density = len(overlap) / math.sqrt(len(document))
    phrase_bonus = 0.08 if " ".join(question_tokens) in " ".join(row_tokens) else 0.0
    return min(1.0, 0.75 * coverage + 0.25 * min(1.0, density * 2.0) + phrase_bonus)


def retrieve(
    db: Session,
    question: str,
    student_scope: dict,
    *,
    limit: int = 5,
    candidate_limit: int = 400,
    gemini: GeminiClient | None = None,
    settings: Settings | None = None,
    min_score: float = 0.18,
) -> list[RetrievedChunk]:
    settings = settings or get_settings()
    candidates = chunk_repository.candidate_chunks(db, student_scope, limit=candidate_limit)
    if not candidates:
        return []

    question_tokens = tokenize(question)
    if not question_tokens:
        return []
    query_vector, _ = embedding_service.embed(question, gemini=gemini)

    scored: list[RetrievedChunk] = []
    notice_cache: dict[str, Notice | None] = {}
    for chunk, embedding in candidates:
        lexical = _lexical_scores(question_tokens, tokenize(chunk.text))
        semantic = embedding_service.cosine(query_vector, embedding.vector if embedding else None)
        score = 0.6 * lexical + 0.4 * semantic
        if lexical < 0.05 and semantic < 0.35:
            continue
        if score < min_score:
            continue
        notice = notice_cache.get(chunk.notice_id)
        if chunk.notice_id not in notice_cache:
            notice = db.get(Notice, chunk.notice_id)
            notice_cache[chunk.notice_id] = notice
        if notice is None:
            continue
        scored.append(
            RetrievedChunk(
                chunk=chunk,
                notice=notice,
                score=round(score, 6),
                lexical_score=round(lexical, 6),
                semantic_score=round(semantic, 6),
            )
        )

    scored.sort(key=lambda item: (item.score, item.lexical_score), reverse=True)

    results: list[RetrievedChunk] = []
    seen: set[tuple[str, int | None]] = set()
    for item in scored:
        key = (item.chunk.notice_id, item.chunk.page_number)
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
        if len(results) >= limit:
            break
    return results
