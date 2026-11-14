"""Aggregate the versioned API routes under /api."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import admin, auth, frontend_bridge, students

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(frontend_bridge.router)
api_router.include_router(students.router)
api_router.include_router(admin.router)
