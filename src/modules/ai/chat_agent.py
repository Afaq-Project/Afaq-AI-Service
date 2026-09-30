from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from wardhook.core import AgentGraph


class ChatAgent(Protocol):
    async def ainvoke(
        self,
        user_input: Any,
        *,
        principal: Any = None,
        run_id: str | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class ChatAgentFactory(Protocol):
    def build(self, system_prompt: str) -> ChatAgent: ...


class WardhookChatAgentFactory:

    def __init__(self, model: Any, guardrails: Sequence[Any] = ()) -> None:
        self._model = model
        self._guardrails = list(guardrails)

    def build(self, system_prompt: str) -> ChatAgent:
        return AgentGraph(
            model=self._model,
            system_prompt=system_prompt,
            guardrails=self._guardrails,
            name="levora-chat",
        )


def to_chat_messages(records: Iterable[Any]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for record in records:
        if not record.content:
            continue
        if record.role == "user":
            messages.append(HumanMessage(content=record.content))
        elif record.role == "assistant":
            messages.append(AIMessage(content=record.content))
    return messages


def redacted_user_text(result: Mapping[str, Any]) -> str | None:
    for message in reversed(result.get("messages") or []):
        if isinstance(message, HumanMessage) and isinstance(message.content, str):
            return message.content
    return None


def token_usage(result: Mapping[str, Any]) -> tuple[int | None, int | None]:
    for message in reversed(result.get("messages") or []):
        if isinstance(message, AIMessage) and message.usage_metadata:
            usage = message.usage_metadata
            return usage.get("input_tokens"), usage.get("output_tokens")
    return None, None
