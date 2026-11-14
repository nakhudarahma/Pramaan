"""Document ingestion: validate, store, extract, index, queue for review."""
from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, UploadValidationError
from app.core.logging import get_logger
from app.integrations.gemini_client import GeminiClient
from app.integrations.storage_client import StorageClient
from app.models.base import new_uuid, utcnow
from app.models.chunk import Chunk, Embedding
from app.models.document import Document, DocumentProcessingJob
from app.models.enums import DocumentStatus, JobStatus, NoticeStatus
from app.models.notice import Notice
from app.models.user import User
from app.services import audit_service, embedding_service, extraction_service
from app.services.extraction_service import ExtractionService
from app.services.pdf_service import PDFExtraction, PDFProcessingError, extract_pdf
from app.utils.text_utils import chunk_text, tokenize
from app.utils.validators import sanitize_filename, validate_content_type, validate_pdf_signature

logger = get_logger("pramaan.ingestion")


class DocumentService:
    def __init__(
        self,
        settings: Settings | None = None,
        storage: StorageClient | None = None,
        gemini: GeminiClient | None = None,
    ):
        self.settings = settings or get_settings()
        self.storage = storage or StorageClient(self.settings)
        self.gemini = gemini or GeminiClient(self.settings)

    # ------------------------------------------------------------------ upload
    def create_upload(
        self,
        db: Session,
        *,
        data: bytes,
        filename: str,
        content_type: str | None,
        title: str | None,
        issuer: str | None,
        issued_on: date | None,
        category: str,
        summary: str | None,
        language: str,
        actor: User,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        max_bytes = self.settings.max_upload_mb * 1024 * 1024
        if len(data) > max_bytes:
            raise UploadValidationError(
                f"File is too large. Maximum size is {self.settings.max_upload_mb} MB.",
                details={"max_mb": self.settings.max_upload_mb},
            )
        try:
            validate_content_type(content_type)
            validate_pdf_signature(data)
        except ValueError as exc:
            raise UploadValidationError(str(exc)) from exc

        # Validate that the PDF can actually be parsed before storing it.
        try:
            preliminary = extract_pdf(data)
        except PDFProcessingError as exc:
            raise UploadValidationError(str(exc)) from exc

        document_id = new_uuid()
        safe_name = sanitize_filename(filename)
        storage_key = f"documents/{document_id}.pdf"
        self.storage.save(storage_key, data)

        document = Document(
            id=document_id,
            original_filename=safe_name,
            content_type="application/pdf",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            storage_backend=self.storage.backend,
            storage_key=storage_key,
            page_count=preliminary.page_count,
            status=DocumentStatus.PROCESSING.value,
            requires_ocr=preliminary.requires_ocr,
            uploaded_by=actor.id,
        )
        notice = Notice(
            document_id=document_id,
            title=(title or safe_name.rsplit(".", 1)[0])[:500],
            issuer=issuer,
            issued_on=issued_on,
            category=(category or "general")[:60],
            summary=summary,
            language=language or "en",
            status=NoticeStatus.DRAFT.value,
            uploaded_by=actor.id,
        )
        db.add(document)
        db.add(notice)
        db.flush()

        result = self.process_document(
            db,
            document=document,
            notice=notice,
            actor=actor,
            request_id=request_id,
            extraction=preliminary,
        )
        result["message"] = self._status_message(document)
        return result

    # --------------------------------------------------------------- processing
    def process_document(
        self,
        db: Session,
        *,
        document: Document,
        notice: Notice,
        actor: User | None,
        request_id: str | None = None,
        extraction: PDFExtraction | None = None,
    ) -> dict[str, Any]:
        job = DocumentProcessingJob(
            document_id=document.id,
            status=JobStatus.RUNNING.value,
            stage="extracting",
            attempt=1,
            started_at=utcnow(),
        )
        db.add(job)
        document.status = DocumentStatus.PROCESSING.value
        db.flush()

        summary: dict[str, Any] = {
            "document": document,
            "notice": notice,
            "job": job,
            "extracted_fact_count": 0,
            "requires_manual_review": False,
        }
        try:
            if extraction is None:
                data = self.storage.read(document.storage_key)
                extraction = extract_pdf(data)
            document.page_count = extraction.page_count
            document.requires_ocr = extraction.requires_ocr

            if extraction.empty:
                self._mark_needs_review(
                    db, document, notice, job, "PDF contains no pages", request_id=request_id, actor=actor
                )
                summary["requires_manual_review"] = True
                return summary

            # Index narrative text even if fact extraction needs review.
            self._index_chunks(db, extraction, notice, document)

            if extraction.requires_ocr:
                self._mark_needs_review(
                    db,
                    document,
                    notice,
                    job,
                    "Scanned PDF: no extractable text. Configure OCR or enter facts manually.",
                    request_id=request_id,
                    actor=actor,
                )
                summary["requires_manual_review"] = True
                return summary

            extraction_service_instance = ExtractionService(self.gemini, self.settings)
            extracted = extraction_service_instance.extract(extraction, notice)
            summary["extraction"] = extracted
            if extracted.facts:
                from app.services import fact_service

                created = fact_service.create_candidates(
                    db, extraction=extracted, notice=notice, actor=actor, request_id=request_id
                )
                summary["extracted_fact_count"] = len(created["facts"])
                summary["duplicate_count"] = len(created["duplicates"])
                summary["disputed_count"] = len(created["disputed"])

            if extracted.requires_manual_review or extracted.error:
                self._mark_needs_review(
                    db,
                    document,
                    notice,
                    job,
                    extracted.error or "Extraction needs manual review",
                    request_id=request_id,
                    actor=actor,
                    status=JobStatus.NEEDS_REVIEW.value,
                )
                summary["requires_manual_review"] = True
            else:
                document.status = DocumentStatus.PROCESSED.value
                document.extraction_error = None
                document.requires_ocr = extraction.requires_ocr
                job.status = JobStatus.SUCCEEDED.value
                job.stage = "completed"
                job.error_message = None
                job.details = {"facts": summary["extracted_fact_count"], "method": extracted.method}
                summary["requires_manual_review"] = False
        except (PDFProcessingError, UploadValidationError) as exc:
            self._mark_needs_review(
                db, document, notice, job, str(exc), request_id=request_id, actor=actor
            )
            summary["requires_manual_review"] = True
        except Exception as exc:  # noqa: BLE001 - preserve document, never crash upload
            logger.exception("document processing failed document_id=%s", document.id)
            self._mark_needs_review(
                db,
                document,
                notice,
                job,
                f"Processing failed ({type(exc).__name__}). Manual review required.",
                request_id=request_id,
                actor=actor,
            )
            summary["requires_manual_review"] = True
        finally:
            job.finished_at = utcnow()
            document.processed_at = utcnow()
            db.flush()
        return summary

    def _mark_needs_review(
        self,
        db: Session,
        document: Document,
        notice: Notice,
        job: DocumentProcessingJob,
        message: str,
        *,
        request_id: str | None,
        actor: User | None,
        status: str = JobStatus.FAILED.value,
    ) -> None:
        document.status = DocumentStatus.NEEDS_REVIEW.value
        document.extraction_error = message[:2000]
        job.status = status
        job.stage = "needs_review"
        job.error_message = message[:2000]
        db.flush()
        audit_service.log(
            db,
            action="document.needs_review",
            actor=actor,
            target_type="document",
            target_id=document.id,
            details={"reason": message[:500]},
            request_id=request_id,
        )

    def _index_chunks(
        self,
        db: Session,
        extraction: PDFExtraction,
        notice: Notice,
        document: Document,
    ) -> None:
        # Idempotent re-processing: replace old chunks for this notice.
        existing = list(db.scalars(select(Chunk.id).where(Chunk.notice_id == notice.id)))
        if existing:
            db.execute(delete(Embedding).where(Embedding.chunk_id.in_(existing)))
            db.execute(delete(Chunk).where(Chunk.notice_id == notice.id))
            db.flush()
        index = 0
        for page in extraction.pages:
            if not page.text.strip():
                continue
            for piece in chunk_text(page.text):
                chunk = Chunk(
                    notice_id=notice.id,
                    document_id=document.id,
                    page_number=page.number,
                    chunk_index=index,
                    text=piece,
                    scope_json={},
                    source_bbox=None,
                    token_count=len(tokenize(piece)),
                )
                db.add(chunk)
                db.flush()
                vector, model = embedding_service.embed(piece, gemini=self.gemini)
                db.add(
                    Embedding(
                        chunk_id=chunk.id,
                        model=model,
                        dim=len(vector),
                        vector=vector,
                    )
                )
                index += 1
        db.flush()

    # ------------------------------------------------------------------ queries
    def list_documents(
        self,
        db: Session,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[Document], int]:
        conditions = []
        if status:
            conditions.append(Document.status == status)
        if search:
            conditions.append(Document.original_filename.ilike(f"%{search.strip()}%"))
        base = select(Document)
        if conditions:
            base = base.where(*conditions)
        total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = list(
            db.scalars(
                base.order_by(Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        return rows, total

    def get_document(self, db: Session, document_id: str) -> Document:
        document = db.get(Document, document_id)
        if document is None:
            raise NotFoundError("Document not found")
        return document

    @staticmethod
    def _status_message(document: Document) -> str:
        if document.status == DocumentStatus.NEEDS_REVIEW.value:
            return (
                "Document stored. Extraction requires manual review; no facts were published."
            )
        if document.status == DocumentStatus.FAILED.value:
            return "Document stored but processing failed. Manual review required."
        return "Document processed. Extracted facts are candidates awaiting admin approval."
