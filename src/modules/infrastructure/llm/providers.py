from langchain_anthropic import ChatAnthropic

from src.modules.core.config.settings import get_settings

from .anthropic_client import (
    StructuredLLMClient,
    create_chat_model,
    create_structured_client,
)

_structured_client: StructuredLLMClient | None = None
_chat_model: ChatAnthropic | None = None


def get_structured_client() -> StructuredLLMClient:
    global _structured_client
    if _structured_client is None:
        _structured_client = create_structured_client(get_settings())
    return _structured_client


def get_chat_model() -> ChatAnthropic:
    global _chat_model
    if _chat_model is None:
        _chat_model = create_chat_model(get_settings())
    return _chat_model


async def close_llm_clients() -> None:
    global _structured_client, _chat_model
    if _structured_client is not None:
        await _structured_client.close()
    _structured_client = None
    _chat_model = None
