"""PDF validation, text extraction and source-location.

Primary engine: PyMuPDF when the native module is available.  Fallback:
pdfplumber (pure Python) which also yields word-level bounding boxes.  If a page
has no extractable text it is flagged as requiring OCR; Pramaan does not pretend
to OCR scanned documents without a configured OCR backend.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.core.logging import get_logger
from app.utils.text_utils import normalize_whitespace

logger = get_logger("pramaan.pdf")

try:  # pragma: no cover - environment dependent
    import fitz  # type: ignore

    _FITZ_AVAILABLE = True
except Exception:  # noqa: BLE001 - blocked DLLs / optional dependency
    fitz = None  # type: ignore
    _FITZ_AVAILABLE = False

try:
    import pdfplumber
except Exception:  # pragma: no cover
    pdfplumber = None  # type: ignore


class PDFProcessingError(Exception):
    pass


class OCRBackend(Protocol):
    """Integration point for a real OCR provider (Tesseract, cloud OCR, ...)."""

    def ocr_page(self, pdf_bytes: bytes, page_number: int) -> str:  # pragma: no cover - interface
        ...


class NoOCRBackend:
    """Explicit no-op OCR backend. Never fabricates text for scanned pages."""

    def ocr_page(self, pdf_bytes: bytes, page_number: int) -> str:
        raise PDFProcessingError(
            "This page has no extractable text and OCR is not configured. "
            "Manual review is required."
        )


@dataclass
class PDFLine:
    text: str
    bbox: list[float]


@dataclass
class PDFPage:
    number: int
    text: str
    lines: list[PDFLine] = field(default_factory=list)
    has_text: bool = False

    @property
    def words(self) -> list[tuple[str, list[float]]]:
        result: list[tuple[str, list[float]]] = []
        for line in self.lines:
            for word in line.text.split():
                result.append((word, line.bbox))
        return result


@dataclass
class PDFExtraction:
    pages: list[PDFPage]
    page_count: int
    requires_ocr: bool
    empty: bool
    engine: str
    error: str | None = None

    def page(self, number: int) -> PDFPage | None:
        for page in self.pages:
            if page.number == number:
                return page
        return None

    def text_with_markers(self, max_chars: int = 60_000) -> str:
        parts = []
        used = 0
        for page in self.pages:
            header = f"\n\n=== PAGE {page.number} ===\n"
            body = page.text or "[NO EXTRACTABLE TEXT ON THIS PAGE]"
            block = header + body
            if used + len(block) > max_chars:
                parts.append(header + body[: max(0, max_chars - used)])
                break
            parts.append(block)
            used += len(block)
        return "".join(parts).strip()


def _lines_from_words(words: list[dict], tolerance: float = 3.0) -> list[PDFLine]:
    if not words:
        return []
    grouped: dict[int, list[dict]] = {}
    for word in words:
        key = round(float(word.get("top", 0.0)) / tolerance)
        grouped.setdefault(key, []).append(word)
    lines: list[PDFLine] = []
    for key in sorted(grouped):
        row = sorted(grouped[key], key=lambda w: float(w.get("x0", 0.0)))
        text = " ".join(str(w.get("text", "")) for w in row).strip()
        if not text:
            continue
        bbox = [
            round(min(float(w["x0"]) for w in row), 2),
            round(min(float(w["top"]) for w in row), 2),
            round(max(float(w["x1"]) for w in row), 2),
            round(max(float(w["bottom"]) for w in row), 2),
        ]
        lines.append(PDFLine(text=text, bbox=bbox))
    return lines


def _extract_with_fitz(data: bytes) -> PDFExtraction:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        if doc.needs_pass:
            raise PDFProcessingError("PDF is password protected")
        pages: list[PDFPage] = []
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            blocks = page.get_text("blocks") or []
            lines = [
                PDFLine(
                    text=normalize_whitespace(block[4]),
                    bbox=[round(float(block[0]), 2), round(float(block[1]), 2),
                          round(float(block[2]), 2), round(float(block[3]), 2)],
                )
                for block in blocks
                if len(block) >= 5 and normalize_whitespace(str(block[4]))
            ]
            pages.append(
                PDFPage(number=index, text=text, lines=lines, has_text=len(text.strip()) >= 20)
            )
        page_count = doc.page_count
    finally:
        doc.close()
    empty = page_count == 0
    requires_ocr = (not empty) and all(not p.has_text for p in pages)
    return PDFExtraction(
        pages=pages,
        page_count=page_count,
        requires_ocr=requires_ocr,
        empty=empty,
        engine="pymupdf",
    )


def _extract_with_pdfplumber(data: bytes) -> PDFExtraction:
    if pdfplumber is None:  # pragma: no cover
        raise PDFProcessingError("No PDF extraction engine is available")
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        page_count = len(pdf.pages)
        if page_count == 0:
            return PDFExtraction([], 0, False, True, "pdfplumber")
        pages: list[PDFPage] = []
        for index, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text(x_tolerance=2, y_tolerance=3) or ""
                words = page.extract_words(x_tolerance=2, y_tolerance=3) or []
            except Exception as exc:  # noqa: BLE001 - malformed page
                logger.warning("pdf page extraction failed page=%s error=%s", index, type(exc).__name__)
                text, words = "", []
            lines = _lines_from_words(words)
            pages.append(
                PDFPage(number=index, text=text, lines=lines, has_text=len(text.strip()) >= 20)
            )
    requires_ocr = all(not p.has_text for p in pages)
    return PDFExtraction(
        pages=pages,
        page_count=page_count,
        requires_ocr=requires_ocr,
        empty=False,
        engine="pdfplumber",
    )


def extract_pdf(data: bytes) -> PDFExtraction:
    if not data:
        raise PDFProcessingError("PDF is empty")
    errors: list[str] = []
    if _FITZ_AVAILABLE:
        try:
            return _extract_with_fitz(data)
        except PDFProcessingError:
            raise
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pymupdf:{type(exc).__name__}")
            logger.warning("pymupdf extraction failed, falling back to pdfplumber")
    if pdfplumber is not None:
        try:
            extraction = _extract_with_pdfplumber(data)
            if errors:
                extraction.error = "; ".join(errors)
            return extraction
        except Exception as exc:  # noqa: BLE001
            errors.append(f"pdfplumber:{type(exc).__name__}")
    raise PDFProcessingError(
        "Could not read the PDF. It may be corrupt, encrypted or unsupported."
        + (f" ({'; '.join(errors)})" if errors else "")
    )


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def locate_span(
    extraction: PDFExtraction, page_number: int | None, span: str | None
) -> tuple[list[float] | None, str]:
    """Return (bbox, precision).  Never invents coordinates."""
    if page_number is None or not span:
        return None, "page"
    page = extraction.page(page_number)
    if page is None:
        return None, "page"
    target = _normalize_for_match(span)
    if not target:
        return None, "page"
    target_tokens = target.split()
    page_tokens: list[tuple[str, list[float]]] = []
    for line in page.lines:
        line_tokens = _normalize_for_match(line.text).split()
        for token in line_tokens:
            page_tokens.append((token, line.bbox))
    if not page_tokens:
        return None, "page"
    window = len(target_tokens)
    for start in range(0, len(page_tokens) - window + 1):
        candidate = " ".join(token for token, _ in page_tokens[start : start + window])
        if candidate == target:
            boxes = [bbox for _, bbox in page_tokens[start : start + window]]
            bbox = [
                round(min(b[0] for b in boxes), 2),
                round(min(b[1] for b in boxes), 2),
                round(max(b[2] for b in boxes), 2),
                round(max(b[3] for b in boxes), 2),
            ]
            return bbox, "exact"
    if target in _normalize_for_match(page.text):
        return None, "page"
    return None, "page"
