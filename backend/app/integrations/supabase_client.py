"""Minimal Supabase Storage REST client (no heavy SDK dependency)."""
from __future__ import annotations

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger("pramaan.supabase")


class SupabaseStorageClient:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=30.0)

    @property
    def configured(self) -> bool:
        return bool(self.settings.supabase_url and self.settings.supabase_service_role_key)

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.settings.supabase_service_role_key}",
            "apikey": self.settings.supabase_service_role_key or "",
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def upload(self, key: str, data: bytes, content_type: str = "application/pdf") -> None:
        if not self.configured:
            raise ExternalServiceError("Supabase Storage is not configured")
        url = (
            f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{self.settings.supabase_bucket}/{key.lstrip('/')}"
        )
        response = self._client.post(
            url,
            content=data,
            headers={**self._headers(content_type), "x-upsert": "true"},
        )
        if response.status_code >= 400:
            logger.warning("supabase upload failed status=%s", response.status_code)
            raise ExternalServiceError("Failed to store document in Supabase Storage")

    def download(self, key: str) -> bytes:
        if not self.configured:
            raise ExternalServiceError("Supabase Storage is not configured")
        url = (
            f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{self.settings.supabase_bucket}/{key.lstrip('/')}"
        )
        response = self._client.get(url, headers=self._headers())
        if response.status_code >= 400:
            logger.warning("supabase download failed status=%s", response.status_code)
            raise ExternalServiceError("Failed to read document from Supabase Storage")
        return response.content

    def create_signed_url(self, key: str) -> str | None:
        if not self.configured:
            return None
        url = (
            f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/sign/"
            f"{self.settings.supabase_bucket}/{key.lstrip('/')}"
        )
        response = self._client.post(
            url,
            json={"expiresIn": self.settings.supabase_signed_url_ttl_seconds},
            headers=self._headers("application/json"),
        )
        if response.status_code >= 400:
            logger.warning("supabase sign failed status=%s", response.status_code)
            return None
        signed = response.json().get("signedURL")
        if not signed:
            return None
        if signed.startswith("http"):
            return signed
        return f"{self.settings.supabase_url.rstrip('/')}/storage/v1{signed}"

    def delete(self, key: str) -> None:
        if not self.configured:
            return
        url = (
            f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/"
            f"{self.settings.supabase_bucket}/{key.lstrip('/')}"
        )
        response = self._client.delete(url, headers=self._headers())
        if response.status_code >= 400:
            logger.warning("supabase delete failed status=%s", response.status_code)
