import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from .base import StructuredCompletion
from .errors import translate_error
from .exceptions import LLMIncompleteResponseError


class LangChainStructuredClient:

    def __init__(self, model: Any, model_name: str) -> None:
        self._model = model
        self._model_name = model_name

    async def generate[OutputT: BaseModel](
        self, *, system: str, prompt: str, output_type: type[OutputT]
    ) -> StructuredCompletion[OutputT]:
        structured = self._model.with_structured_output(output_type, include_raw=True)
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]

        started = time.perf_counter()
        try:
            result = await structured.ainvoke(messages)
        except Exception as exc:
            raise translate_error(exc) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        parsed = result.get("parsed")
        if parsed is None:
            raise LLMIncompleteResponseError(
                f"no structured output ({result.get('parsing_error')})"
            )

        raw = result.get("raw")
        usage = getattr(raw, "usage_metadata", None) or {}
        return StructuredCompletion(
            output=parsed,
            model=self._model_name,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            latency_ms=latency_ms,
        )

    async def close(self) -> None:
        return None
