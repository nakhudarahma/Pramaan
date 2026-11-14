"""Import all ORM models so SQLAlchemy registers them on ``Base.metadata``."""
from app.models.audit import AuditLog
from app.models.base import Base, GUID, utcnow
from app.models.calendar import CalendarEvent
from app.models.change import ChangeEvent
from app.models.chunk import Chunk, Embedding, EmbeddingVector
from app.models.document import Document, DocumentProcessingJob
from app.models.fact import Fact, FactConflict, FactSource, FactVersion
from app.models.notice import Notice
from app.models.unanswered import UnansweredQuestion
from app.models.user import AdminProfile, StudentProfile, User

__all__ = [
    "Base",
    "GUID",
    "utcnow",
    "User",
    "StudentProfile",
    "AdminProfile",
    "Document",
    "DocumentProcessingJob",
    "Notice",
    "Fact",
    "FactVersion",
    "FactSource",
    "FactConflict",
    "ChangeEvent",
    "UnansweredQuestion",
    "AuditLog",
    "Chunk",
    "Embedding",
    "EmbeddingVector",
    "CalendarEvent",
]
