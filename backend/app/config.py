"""Application configuration.

All configuration comes from environment variables (optionally loaded from a
local ``.env`` file).  Secrets are never hard-coded and never included in API
responses or logs.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Pramaan API"
    environment: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_prefix: str = "/api"
    timezone: str = "Asia/Kolkata"

    # ------------------------------------------------------------- security
    jwt_secret: str = "insecure-development-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"]
    )
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"])

    # ------------------------------------------------------------- database
    database_url: str = "sqlite:///./pramaan.db"
    pgvector_enabled: bool = False
    auto_create_tables: bool = True

    # ---------------------------------------------------------- bootstrap
    admin_email: str | None = None
    admin_password: str | None = None
    admin_name: str = "Pramaan Admin"
    seed_demo_data: bool = False

    # -------------------------------------------------------------- storage
    storage_backend: Literal["local", "supabase"] = "local"
    storage_dir: str = "./storage"
    max_upload_mb: int = 20
    public_file_access: bool = True
    supabase_url: str | None = None
    supabase_service_role_key: str | None = None
    supabase_bucket: str = "pramaan-documents"
    supabase_signed_url_ttl_seconds: int = 900

    # --------------------------------------------------------------- gemini
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-flash-lite-latest"
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_seconds: float = 30.0

    # ------------------------------------------------------------ retrieval
    embedding_dim: int = 768
    static_similarity_threshold: float = 0.15
    max_static_context_chunks: int = 6
    min_extraction_confidence: float = 0.45

    # --------------------------------------------------------- rate limits
    rate_limit_enabled: bool = True
    rate_limit_ask_per_minute: int = 30
    rate_limit_login_per_minute: int = 10
    rate_limit_register_per_hour: int = 20
    rate_limit_upload_per_minute: int = 10

    # ------------------------------------------------------------- helpers
    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if isinstance(value, str):
            val = value.strip().strip('"').strip("'")
            if val.startswith("postgresql://"):
                val = val.replace("postgresql://", "postgresql+psycopg://", 1)
            # Remove pgbouncer query parameter if present since SQLAlchemy/psycopg handles pooling
            if "pgbouncer=true" in val:
                val = val.replace("?pgbouncer=true", "").replace("&pgbouncer=true", "")
                if "?" not in val and "sslmode" not in val:
                    val += "?sslmode=require"
            return val
        return value

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> "Settings":
        if self.environment == "production":
            if self.jwt_secret == "insecure-development-secret-change-me" or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be a strong random value in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("PostgreSQL DATABASE_URL is required in production")
        return self

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Used by tests after changing environment variables."""
    get_settings.cache_clear()


def load_dotenv_if_present(path: str = ".env") -> None:
    """Minimal .env loader for contexts where pydantic's loader is not enough.

    pydantic-settings already loads .env; this helper is intentionally small and
    does not override existing environment variables.  It exists so scripts can
    be run from any working directory in a predictable way.
    """
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)
