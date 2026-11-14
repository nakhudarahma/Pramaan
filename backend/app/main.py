"""Pramaan FastAPI application."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.api.router import api_router
from app.api.routes import health
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.database import init_db

logger = get_logger("pramaan.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()
    Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
    if settings.auto_create_tables:
        init_db()
        logger.info("database tables ensured", extra={"event": "db.init"})
    logger.info(
        "application started",
        extra={
            "event": "app.start",
            "environment": settings.environment,
            "storage_backend": settings.storage_backend,
            "gemini_configured": settings.gemini_configured,
        },
    )
    yield
    logger.info("application stopped", extra={"event": "app.stop"})


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details=None,
    headers: dict | None = None,
) -> JSONResponse:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details) if details is not None else None,
            "request_id": _request_id(request),
        }
    }
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        description=(
            "Version-aware, evidence-based college information assistant. "
            "Approved facts (not the LLM) are the source of truth."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    allow_all = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=not allow_all,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)
    if settings.allowed_hosts and "*" not in settings.allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        headers = None
        if exc.status_code == 429:
            retry = (exc.details or {}).get("retry_after_seconds") if isinstance(exc.details, dict) else None
            if retry:
                headers = {"Retry-After": str(retry)}
        logger.warning(
            "application error code=%s status=%s", exc.code, exc.status_code,
            extra={"request_id": _request_id(request), "path": request.url.path},
        )
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed",
            details=exc.errors(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return _error_response(
            request,
            status_code=exc.status_code,
            code="http_error",
            message=message,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.exception(
            "unhandled application error",
            extra={"request_id": _request_id(request), "path": request.url.path},
        )
        return _error_response(
            request,
            status_code=500,
            code="internal_error",
            message="An internal error occurred. Please try again later.",
        )

    app.include_router(health.router)
    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
