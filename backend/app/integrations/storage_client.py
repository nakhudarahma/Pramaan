"""Document storage abstraction: local disk for development, Supabase for prod."""
from __future__ import annotations

import os
import re
from pathlib import Path

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError, ServiceUnavailableError, UploadValidationError
from app.core.logging import get_logger
from app.integrations.supabase_client import SupabaseStorageClient

logger = get_logger("pramaan.storage")

_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _safe_relative_key(key: str) -> str:
    normalized = key.replace("\\", "/").lstrip("/")
    if ".." in normalized.split("/") or not _SAFE_KEY_RE.match(normalized):
        raise UploadValidationError("Invalid storage key")
    return normalized


class StorageClient:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.backend = self.settings.storage_backend
        self.base_dir = Path(self.settings.storage_dir).resolve()
        self.supabase = SupabaseStorageClient(self.settings) if self.backend == "supabase" else None

    def _local_path(self, key: str) -> Path:
        relative = _safe_relative_key(key)
        path = (self.base_dir / relative).resolve()
        if self.base_dir not in path.parents and path != self.base_dir:
            raise UploadValidationError("Invalid storage path")
        return path

    def save(self, key: str, data: bytes, content_type: str = "application/pdf") -> str:
        if self.backend == "supabase":
            if not self.supabase or not self.supabase.configured:
                raise ServiceUnavailableError("Document storage is not configured")
            self.supabase.upload(key, data, content_type)
            return key
        path = self._local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
        return key

    def read(self, key: str) -> bytes:
        if self.backend == "supabase":
            if not self.supabase or not self.supabase.configured:
                raise ServiceUnavailableError("Document storage is not configured")
            return self.supabase.download(key)
        path = self._local_path(key)
        if not path.exists():
            raise NotFoundError("Document file is missing from storage")
        return path.read_bytes()

    def signed_url(self, key: str) -> str | None:
        if self.backend == "supabase" and self.supabase:
            return self.supabase.create_signed_url(key)
        return None

    def exists(self, key: str) -> bool:
        if self.backend == "supabase":
            return True
        return self._local_path(key).exists()
