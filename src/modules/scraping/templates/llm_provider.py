"""
LLM Provider Abstraction and Gemini Implementation for Afaq Extraction Template Generation.

Provides a decoupled interface for invoking LLM providers (e.g. Gemini) to generate
candidate extraction templates from HTML samples.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

from src.modules.core.config.settings import get_settings

logger = logging.getLogger(__name__)


class LLMGenerationError(Exception):
    """Raised when LLM provider returns an error or invalid response."""

    pass


class LLMTimeoutError(LLMGenerationError):
    """Raised when LLM API call times out."""

    pass


@runtime_checkable
class BaseLLMProvider(Protocol):
    """Abstract protocol for LLM text/json generation providers."""

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        """Generates response text from the LLM provider given a prompt."""
        ...


class GeminiLLMProvider:
    """
    Google Gemini LLM provider implementation using httpx REST calls
    or Google GenAI REST API endpoints.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.5-flash",
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.google_api_key
        self.model = model
        self.timeout = timeout or settings.ai_timeout_seconds
        self.endpoint_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        """Invokes Google Gemini API with system instructions and user prompt."""
        if not self.api_key or not self.api_key.strip():
            raise LLMGenerationError("Gemini API key is missing or not configured.")

        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.endpoint_url,
                    headers=headers,
                    params=params,
                    json=payload,
                )

            if response.status_code != 200:
                error_body = response.text
                logger.error(
                    "Gemini API returned status %d: %s",
                    response.status_code,
                    error_body,
                )
                raise LLMGenerationError(
                    f"Gemini API error (HTTP {response.status_code}): {error_body[:200]}"
                )

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise LLMGenerationError("Gemini API returned no candidates.")

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts or "text" not in parts[0]:
                raise LLMGenerationError("Gemini API returned empty text part.")

            return parts[0]["text"]

        except httpx.TimeoutException as exc:
            logger.error(
                "Gemini API request timed out after %.1f seconds: %s", self.timeout, exc
            )
            raise LLMTimeoutError(
                f"Gemini API call timed out after {self.timeout}s."
            ) from exc
        except httpx.RequestError as exc:
            logger.error("Gemini API network request error: %s", exc)
            raise LLMGenerationError(
                f"Gemini API network request error: {exc}"
            ) from exc
        except Exception as exc:
            if isinstance(exc, LLMGenerationError):
                raise
            logger.error("Unexpected error calling Gemini API: %s", exc)
            raise LLMGenerationError(f"Unexpected LLM generation error: {exc}") from exc


class MockLLMProvider:
    """
    Mock LLM provider for deterministic unit testing without external network calls.
    """

    def __init__(
        self,
        response_text: str | None = None,
        should_raise: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.response_text = response_text
        self.should_raise = should_raise
        self.delay_seconds = delay_seconds
        self.last_prompt: str | None = None
        self.last_system_instruction: str | None = None

    async def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> str:
        self.last_prompt = prompt
        self.last_system_instruction = system_instruction

        if self.should_raise:
            raise self.should_raise

        if self.response_text is not None:
            return self.response_text

        raise LLMGenerationError(
            "MockLLMProvider configured without response_text or should_raise."
        )
