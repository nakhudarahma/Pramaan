"""Date parsing, academic-year normalisation and validity helpers."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B, %Y",
    "%d %b, %Y",
    "%Y/%m/%d",
)

_ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)\b", re.IGNORECASE)
_ACADEMIC_YEAR_RE = re.compile(r"^(\d{4})\s*[-/]\s*(\d{2,4})$")


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def parse_date(value: str | date | datetime | None) -> date | None:
    """Parse common Indian college circular date formats. Returns None if unknown."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _ORDINAL_RE.sub(r"\1", str(value).strip())
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    # Last-resort ISO datetime prefix.
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalize_academic_year(value: str | None) -> str | None:
    """Normalise 2026-2027 / 2026-27 / 2026/27 to 2026-27."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "all", "any", "none"}:
        return None
    match = _ACADEMIC_YEAR_RE.match(text)
    if not match:
        return text
    start, end = match.groups()
    if len(end) == 4:
        end = end[2:]
    return f"{start}-{end}"


def academic_year_for_date(value: date) -> str:
    """Indian academic years typically start in June/July."""
    start = value.year if value.month >= 6 else value.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def is_within_validity(
    effective_from: date | None,
    effective_to: date | None,
    *,
    on_date: date | None = None,
) -> bool:
    current = on_date or today_utc()
    if effective_from and effective_from > current:
        return False
    if effective_to and effective_to < current:
        return False
    return True


def is_expired(effective_to: date | None, *, on_date: date | None = None) -> bool:
    if effective_to is None:
        return False
    return effective_to < (on_date or today_utc())


def format_human_date(value: date | None) -> str:
    if value is None:
        return ""
    return value.strftime("%d %b %Y").lstrip("0")


def format_iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat() + "Z"
    return value.isoformat()


def days_until(value: date | None, *, on_date: date | None = None) -> int | None:
    if value is None:
        return None
    return (value - (on_date or today_utc())).days
