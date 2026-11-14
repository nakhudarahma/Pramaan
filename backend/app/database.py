"""Database engine, session factory and FastAPI dependency."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.base import Base

_settings = get_settings()

_connect_args: dict = {}
_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if _settings.is_sqlite:
    _connect_args = {"check_same_thread": False}
    _engine_kwargs["connect_args"] = _connect_args
else:
    # Disable prepared statements for PgBouncer transaction-mode pooler compatibility
    _connect_args = {"prepare_threshold": None}
    _engine_kwargs["connect_args"] = _connect_args

engine: Engine = create_engine(_settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


if _settings.is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db(engine_override: Engine | None = None) -> None:
    """Create all tables. Idempotent (``checkfirst``).

    Production deployments should run ``python -m scripts.migrate`` which also
    applies the PostgreSQL-only pgvector/RLS migrations.
    """
    import app.models  # noqa: F401  (register all mappers)

    Base.metadata.create_all(bind=engine_override or engine, checkfirst=True)


def session_factory(bind: Engine | None = None) -> sessionmaker:
    return sessionmaker(bind=bind or engine, autoflush=False, autocommit=False, expire_on_commit=False)
