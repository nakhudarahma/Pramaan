"""Shared schema helpers."""
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    pages: int = Field(ge=0)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None
    request_id: str | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class MessageResponse(BaseModel):
    message: str
    request_id: str | None = None


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    database: str
    gemini_configured: bool
    storage_backend: str
    timestamp: str
