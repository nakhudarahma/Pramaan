"""Google Gemini integration.

The API key is read from the environment and is never logged or returned.  When
the key is missing (or Gemini is unavailable) callers must degrade gracefully;
they must never fabricate a model response.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger("pramaan.gemini")

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _parse_json_payload(text: str) -> Any:
    cleaned = _CODE_FENCE_RE.sub("", (text or "").strip()).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opening, closing in (("{", "}"), ("[", "]")):
        start = cleaned.find(opening)
        end = cleaned.rfind(closing)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ExternalServiceError("Gemini returned a response that was not valid JSON")


class GeminiClient:
    def __init__(self, settings: Settings | None = None, client: httpx.Client | None = None):
        self.settings = settings or get_settings()
        self._client = client or httpx.Client(timeout=self.settings.gemini_timeout_seconds)

    @property
    def configured(self) -> bool:
        return self.settings.gemini_configured

    def _generate(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> str:
        if not self.configured:
            raise ExternalServiceError("Gemini is not configured")
        url = (
            f"{self.settings.gemini_base_url.rstrip('/')}/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        try:
            response = self._client.post(
                url,
                params={"key": self.settings.gemini_api_key},
                json=body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.TimeoutException as exc:
            logger.warning("gemini timeout")
            raise ExternalServiceError("Gemini request timed out") from exc
        except httpx.HTTPError as exc:
            logger.warning("gemini network error: %s", type(exc).__name__)
            raise ExternalServiceError("Gemini is currently unreachable") from exc

        if response.status_code >= 400:
            # Never include request URL/query (contains the API key).
            logger.warning("gemini http error status=%s", response.status_code)
            raise ExternalServiceError(f"Gemini returned HTTP {response.status_code}")

        try:
            payload = response.json()
            candidates = payload.get("candidates") or []
            parts = candidates[0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExternalServiceError("Gemini returned an unexpected response shape") from exc
        if not text.strip():
            raise ExternalServiceError("Gemini returned an empty response")
        return text

    def generate_json(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> Any:
        return _parse_json_payload(
            self._generate(
                prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
        )

    def embed_text(self, text: str) -> list[float] | None:
        if not self.configured:
            return None
        url = (
            f"{self.settings.gemini_base_url.rstrip('/')}/models/"
            f"{self.settings.gemini_embedding_model}:embedContent"
        )
        body = {
            "model": f"models/{self.settings.gemini_embedding_model}",
            "content": {"parts": [{"text": text[:8000]}]},
            "output_dimensionality": self.settings.embedding_dim,
        }
        try:
            response = self._client.post(
                url, params={"key": self.settings.gemini_api_key}, json=body
            )
            if response.status_code >= 400:
                logger.warning("gemini embedding error status=%s", response.status_code)
                return None
            payload = response.json()
            values = payload.get("embedding", {}).get("values")
            if isinstance(values, list) and values:
                return [float(v) for v in values]
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("gemini embedding failed: %s", type(exc).__name__)
        return None
