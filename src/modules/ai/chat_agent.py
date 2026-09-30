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
    def build(self, system_prompt: str, tools: Sequence[Any] = ()) -> ChatAgent: ...


class WardhookChatAgentFactory:

    def __init__(
        self,
        model: Any,
        guardrails: Sequence[Any] = (),
        max_tool_iterations: int = 3,
    ) -> None:
        self._model = model
        self._guardrails = list(guardrails)
        self._max_tool_iterations = max_tool_iterations

    def build(self, system_prompt: str, tools: Sequence[Any] = ()) -> ChatAgent:
        return AgentGraph(
            model=self._model,
            system_prompt=system_prompt,
            guardrails=self._guardrails,
            tools=list(tools),
            max_tool_iterations=self._max_tool_iterations,
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
    totals: list[int] = [0, 0]
    seen = False
    for message in result.get("messages") or []:
        if isinstance(message, AIMessage) and message.usage_metadata:
            usage = message.usage_metadata
            totals[0] += usage.get("input_tokens") or 0
            totals[1] += usage.get("output_tokens") or 0
            seen = True
    if not seen:
        return None, None
    return totals[0], totals[1]


def called_tools(result: Mapping[str, Any]) -> list[str]:
    return [str(name) for name in result.get("tool_calls") or []]
