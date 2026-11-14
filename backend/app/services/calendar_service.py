"""Calendar materialisation and RFC-5545 .ics generation."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.calendar import CalendarEvent
from app.models.enums import CalendarEventStatus, FactStatus
from app.models.fact import Fact
from app.schemas.calendar import CalendarEventOut
from app.services import citation_service


def sync_event_for_fact(db: Session, fact: Fact) -> CalendarEvent | None:
    """Create/refresh a calendar event for an approved date fact."""
    if fact.value_date is None or fact.category not in {"date", "schedule", "fee", "scholarship"}:
        return None
    event = db.scalar(select(CalendarEvent).where(CalendarEvent.fact_id == fact.id))
    settings = get_settings()
    title = fact.title or fact.value_text or fact.fact_key
    if event is None:
        event = CalendarEvent(
            fact_id=fact.id,
            notice_id=fact.notice_id,
            title=title,
            description=fact.description,
            start_date=fact.value_date,
            end_date=fact.value_date,
            all_day=True,
            timezone=settings.timezone,
            status=CalendarEventStatus.CONFIRMED.value,
        )
        db.add(event)
    else:
        event.title = title
        event.notice_id = fact.notice_id
        event.description = fact.description
        event.start_date = fact.value_date
        event.end_date = fact.value_date
        event.timezone = settings.timezone
        event.status = CalendarEventStatus.CONFIRMED.value
        event.cancelled_at = None
    db.flush()
    return event


def cancel_for_fact(db: Session, fact: Fact) -> None:
    event = db.scalar(select(CalendarEvent).where(CalendarEvent.fact_id == fact.id))
    if event is not None:
        event.status = CalendarEventStatus.CANCELLED.value
        event.cancelled_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.flush()


def _event_to_out(db: Session, event: CalendarEvent) -> CalendarEventOut:
    fact = db.get(Fact, event.fact_id)
    return CalendarEventOut(
        id=event.id,
        fact_id=event.fact_id,
        title=event.title,
        description=event.description,
        start_date=event.start_date,
        end_date=event.end_date,
        all_day=event.all_day,
        timezone=event.timezone,
        status=event.status,
        citation=citation_service.for_fact(db, fact) if fact else None,
    )


def list_events(db: Session, fact_ids: list[str]) -> list[CalendarEventOut]:
    if not fact_ids:
        return []
    events = list(
        db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.fact_id.in_(fact_ids),
                CalendarEvent.status == CalendarEventStatus.CONFIRMED.value,
            )
            .order_by(CalendarEvent.start_date)
        )
    )
    return [_event_to_out(db, event) for event in events]


def _escape_ics(value: str) -> str:
    text = (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    text = re.sub(r"\r?\n", r"\\n", text)
    return text


def _fold_line(line: str, limit: int = 75) -> str:
    """Fold content lines at 75 octets as required by RFC 5545."""
    encoded = line.encode("utf-8")
    if len(encoded) <= limit:
        return line
    parts: list[str] = []
    current = b""
    for char in line:
        chunk = char.encode("utf-8")
        if len(current) + len(chunk) > limit:
            parts.append(current.decode("utf-8"))
            current = b" " + chunk
        else:
            current += chunk
    if current:
        parts.append(current.decode("utf-8"))
    return "\r\n".join(parts)


def generate_ics(events: list[CalendarEventOut], *, timezone_name: str | None = None) -> str:
    settings = get_settings()
    tz_name = timezone_name or settings.timezone
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Pramaan//Verified College Notice Ledger//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-TIMEZONE:{tz_name}",
    ]
    for event in events:
        dtstart = event.start_date.strftime("%Y%m%d")
        dtend = (event.end_date or event.start_date) + timedelta(days=1)
        description_bits = []
        if event.description:
            description_bits.append(event.description)
        if event.citation:
            source = event.citation.notice_title or event.citation.document_name or "official notice"
            if event.citation.page_number:
                description_bits.append(f"Source: {source}, page {event.citation.page_number}")
            else:
                description_bits.append(f"Source: {source}")
        description = " ".join(description_bits) or "Source: official college notice"
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{event.fact_id}@pramaan",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{dtstart}",
                f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}",
                f"SUMMARY:{_escape_ics(event.title)}",
                f"DESCRIPTION:{_escape_ics(description)}",
                f"STATUS:{'CANCELLED' if event.status == 'cancelled' else 'CONFIRMED'}",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_line(line) for line in lines) + "\r\n"


def validate_ics(text: str) -> None:
    if not text.startswith("BEGIN:VCALENDAR"):
        raise ValueError("ICS must start with BEGIN:VCALENDAR")
    if "END:VCALENDAR" not in text:
        raise ValueError("ICS must end with END:VCALENDAR")
    if text.count("BEGIN:VEVENT") != text.count("END:VEVENT"):
        raise ValueError("ICS contains unbalanced VEVENT blocks")
    for line in text.splitlines():
        if not line:
            continue
        if ":" not in line and not line.startswith(" "):
            raise ValueError(f"Malformed ICS line: {line!r}")
