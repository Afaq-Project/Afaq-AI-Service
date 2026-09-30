import time
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from .base import StructuredCompletion
from .errors import translate_error
from .exceptions import LLMIncompleteResponseError, LLMRefusalError

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicStructuredClient:

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


def create_anthropic_client(
    api_key: str, timeout: float, max_retries: int
) -> AsyncAnthropic:
    return AsyncAnthropic(
        api_key=api_key or None,
        timeout=timeout,
        max_retries=max_retries,
    )
