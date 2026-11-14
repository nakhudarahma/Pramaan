"""Liveness and readiness probes."""
from __future__ import annotations

from fastapi import APIRouter, Response
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession, SettingsDep
from app.models.base import utcnow
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


def _health(db, settings, *, mark_failure: bool = False) -> tuple[HealthResponse, bool]:
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - probe must report, not crash
        database = "error"
    healthy = database == "ok"
    response = HealthResponse(
        status="ok" if healthy else ("unavailable" if mark_failure else "degraded"),
        version=__version__,
        environment=settings.environment,
        database=database,
        gemini_configured=settings.gemini_configured,
        storage_backend=settings.storage_backend,
        timestamp=utcnow().isoformat() + "Z",
    )
    return response, healthy


@router.get("/health", response_model=HealthResponse)
def health(db: DbSession, settings: SettingsDep) -> HealthResponse:
    response, _ = _health(db, settings)
    return response


@router.get("/health/ready", response_model=HealthResponse)
def ready(response: Response, db: DbSession, settings: SettingsDep) -> HealthResponse:
    payload, healthy = _health(db, settings, mark_failure=True)
    if not healthy:
        response.status_code = 503
    return payload
