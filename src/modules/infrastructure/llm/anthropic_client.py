import time
from dataclasses import dataclass
from typing import Any, Protocol

import anthropic
from anthropic import AsyncAnthropic
from langchain_anthropic import ChatAnthropic
from pydantic import BaseModel

from src.modules.core.config.settings import Settings

from .exceptions import (
    LLMError,
    LLMIncompleteResponseError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMTimeoutError,
    LLMUnavailableError,
)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True)
class StructuredCompletion[OutputT: BaseModel]:
    output: OutputT
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class StructuredGenerator(Protocol):
    async def generate[OutputT: BaseModel](
        self, *, system: str, prompt: str, output_type: type[OutputT]
    ) -> StructuredCompletion[OutputT]: ...


def translate_error(exc: BaseException) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, anthropic.APITimeoutError | TimeoutError):
        return LLMTimeoutError(str(exc) or "request timed out")
    if isinstance(exc, anthropic.RateLimitError):
        return LLMRateLimitError(str(exc))
    if isinstance(exc, anthropic.APIConnectionError):
        return LLMUnavailableError(str(exc))
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return LLMUnavailableError(str(exc))
    return LLMError(f"{type(exc).__name__}: {exc}")


class StructuredLLMClient:

    def __init__(
        self,
        client: Any,
        model: str,
        max_tokens: int,
        refusal_fallbacks: bool = True,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._refusal_fallbacks = refusal_fallbacks

    async def generate[OutputT: BaseModel](
        self, *, system: str, prompt: str, output_type: type[OutputT]
    ) -> StructuredCompletion[OutputT]:
        extra: dict[str, Any] = {}
        if self._refusal_fallbacks:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}

        started = time.perf_counter()
        try:
            response = await self._client.beta.messages.parse(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=output_type,
                **extra,
            )
        except Exception as exc:
            raise translate_error(exc) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.stop_reason == "refusal":
            raise LLMRefusalError("model declined the request")

        parsed = response.parsed_output
        if parsed is None:
            raise LLMIncompleteResponseError(
                f"no structured output (stop_reason={response.stop_reason})"
            )

        return StructuredCompletion(
            output=parsed,
            model=str(response.model),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            latency_ms=latency_ms,
        )

    async def close(self) -> None:
        await self._client.close()


def create_structured_client(settings: Settings) -> StructuredLLMClient:
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key or None,
        timeout=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
    )
    return StructuredLLMClient(
        client,
        model=settings.ai_model,
        max_tokens=settings.ai_review_max_tokens,
        refusal_fallbacks=settings.ai_refusal_fallbacks,
    )


def create_chat_model(settings: Settings) -> ChatAnthropic:
    params: dict[str, Any] = {
        "model": settings.ai_model,
        "max_tokens": settings.ai_chat_max_tokens,
        "timeout": settings.ai_timeout_seconds,
        "max_retries": settings.ai_max_retries,
    }
    if settings.anthropic_api_key:
        params["api_key"] = settings.anthropic_api_key
    return ChatAnthropic(**params)
