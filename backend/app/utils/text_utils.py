"""Text normalisation, chunking and lightweight lexical helpers."""
from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9]+")
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_DATE_LIKE_RE = re.compile(
    r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "what", "when", "where", "which", "who", "whom", "how", "why",
    "is", "it", "its", "for", "of", "to", "in", "on", "at", "by", "with",
    "and", "or", "do", "does", "did", "can", "could", "should", "would",
    "i", "me", "my", "we", "our", "you", "your", "this", "that", "these",
    "please", "tell", "about", "any", "there", "will", "from", "as", "if",
    "mera", "meri", "kya", "kab", "hai", "hain", "kitni", "kitna", "ka",
    "ki", "ke", "me", "mein", "ko", "par", "se", "batao", "bata",
}


def normalize_whitespace(value: str | None) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", value).strip()


def normalize_unicode(value: str | None) -> str:
    if not value:
        return ""
    return unicodedata.normalize("NFKC", value)


def normalize_question(value: str) -> str:
    text = normalize_unicode(value).lower()
    text = re.sub(r"[^\w\s?]", " ", text)
    tokens = [tok for tok in text.split() if tok not in STOPWORDS]
    return " ".join(tokens)[:500]


def normalize_key(value: str) -> str:
    text = normalize_unicode(value).lower().strip()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    return text.strip("_")[:160]


def tokenize(value: str) -> list[str]:
    return [tok for tok in _WORD_RE.findall(normalize_unicode(value).lower()) if tok not in STOPWORDS]


def extract_numbers(value: str) -> list[float]:
    found: list[float] = []
    for match in _NUMBER_RE.findall(value or ""):
        try:
            found.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return found


def extract_date_like(value: str) -> list[str]:
    return _DATE_LIKE_RE.findall(value or "")


def contains_any(value: str, keywords: set[str] | list[str] | tuple[str, ...]) -> bool:
    lowered = (value or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def truncate(value: str | None, limit: int = 500) -> str:
    if not value:
        return ""
    text = normalize_whitespace(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def chunk_text(text: str, max_chars: int = 1100, overlap_chars: int = 150) -> list[str]:
    """Paragraph-aware chunking with a little overlap.

    Tables are preserved as best as plain text allows; facts (not chunks) remain
    the source of truth for volatile values.
    """
    text = normalize_unicode(text).replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            words = paragraph.split()
            piece = ""
            for word in words:
                if len(piece) + len(word) + 1 > max_chars:
                    chunks.append(piece.strip())
                    piece = " ".join(piece.split()[-20:]) + " " if overlap_chars else ""
                piece = f"{piece} {word}".strip()
            if piece:
                chunks.append(piece.strip())
            continue
        if len(current) + len(paragraph) + 2 <= max_chars:
            current = f"{current}\n\n{paragraph}".strip()
        else:
            if current:
                chunks.append(current.strip())
            tail = current[-overlap_chars:] if overlap_chars and current else ""
            current = f"{tail}\n\n{paragraph}".strip() if tail else paragraph
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c.strip()]
