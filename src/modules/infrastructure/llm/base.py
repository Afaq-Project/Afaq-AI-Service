from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


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

    async def close(self) -> None: ...
