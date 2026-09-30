from typing import Any

from src.modules.core.config.settings import Settings, get_settings

from .anthropic_client import AnthropicStructuredClient, create_anthropic_client
from .base import StructuredGenerator
from .langchain_client import LangChainStructuredClient

GOOGLE_PREFIXES = ("gemini", "google")

_structured_client: StructuredGenerator | None = None
_chat_model: Any = None


def resolve_provider(model: str) -> str:
    name = model.lower().strip()
    if name.startswith(GOOGLE_PREFIXES):
        return "google"
    return "anthropic"


def create_chat_model(settings: Settings) -> Any:
    provider = resolve_provider(settings.ai_model)

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI  # noqa: PLC0415

        params: dict[str, Any] = {
            "model": settings.ai_model,
            "max_tokens": settings.ai_chat_max_tokens,
            "timeout": settings.ai_timeout_seconds,
            "max_retries": settings.ai_max_retries,
        }
        if settings.google_api_key:
            params["api_key"] = settings.google_api_key
        return ChatGoogleGenerativeAI(**params)

    from langchain_anthropic import ChatAnthropic  # noqa: PLC0415

    params = {
        "model": settings.ai_model,
        "max_tokens": settings.ai_chat_max_tokens,
        "timeout": settings.ai_timeout_seconds,
        "max_retries": settings.ai_max_retries,
    }
    if settings.anthropic_api_key:
        params["api_key"] = settings.anthropic_api_key
    return ChatAnthropic(**params)


def create_structured_client(settings: Settings) -> StructuredGenerator:
    if resolve_provider(settings.ai_model) == "google":
        return LangChainStructuredClient(create_chat_model(settings), settings.ai_model)

    return AnthropicStructuredClient(
        create_anthropic_client(
            settings.anthropic_api_key,
            settings.ai_timeout_seconds,
            settings.ai_max_retries,
        ),
        model=settings.ai_model,
        max_tokens=settings.ai_review_max_tokens,
        refusal_fallbacks=settings.ai_refusal_fallbacks,
    )


def get_structured_client() -> StructuredGenerator:
    global _structured_client
    if _structured_client is None:
        _structured_client = create_structured_client(get_settings())
    return _structured_client


def get_chat_model() -> Any:
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
