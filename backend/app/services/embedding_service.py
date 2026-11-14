"""Text embeddings.

Uses Gemini's embedding model when configured.  Otherwise a deterministic
hashed bag-of-words/trigram vector is used.  The fallback is lexical, not a
neural semantic model; it keeps local development and tests functional without
paid API calls.  The provider is recorded on every stored embedding.
"""
from __future__ import annotations

import hashlib
import math
import re

from app.config import get_settings
from app.integrations.gemini_client import GeminiClient
from app.utils.text_utils import normalize_unicode, tokenize

_HASH_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _hash_vector(text: str, dim: int) -> list[float]:
    vector = [0.0] * dim
    tokens = tokenize(text)
    grams: list[str] = list(tokens)
    for token in tokens:
        if len(token) >= 4:
            grams.extend(token[i : i + 3] for i in range(len(token) - 2))
    if not grams:
        return vector
    for gram in grams:
        digest = hashlib.sha256(gram.encode("utf-8")).digest()
        index = int.from_bytes(digest[:8], "big") % dim
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm:
        vector = [v / norm for v in vector]
    return vector


def embed(text: str, *, gemini: GeminiClient | None = None) -> tuple[list[float], str]:
    settings = get_settings()
    client = gemini or GeminiClient(settings)
    if client.configured:
        values = client.embed_text(normalize_unicode(text))
        if values:
            return values, f"gemini:{settings.gemini_embedding_model}"
    return _hash_vector(normalize_unicode(text), settings.embedding_dim), "hash-ngram-v1"


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    val = dot / (na * nb)
    if val > 1.0:
        return 1.0
    if val < -1.0:
        return -1.0
    return val
