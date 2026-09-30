from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from google.api_core import exceptions as google_exceptions
from pydantic import BaseModel

from src.modules.core.config.settings import Settings
from src.modules.infrastructure.llm.anthropic_client import (
    FALLBACK_BETA,
    AnthropicStructuredClient,
)
from src.modules.infrastructure.llm.errors import translate_error
from src.modules.infrastructure.llm.exceptions import (
    LLMError,
    LLMIncompleteResponseError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from src.modules.infrastructure.llm.langchain_client import LangChainStructuredClient
from src.modules.infrastructure.llm.providers import (
    create_chat_model,
    create_structured_client,
    resolve_provider,
)

REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def status_error(cls, code: int):
    return cls("error", response=httpx2.Response(code, request=REQUEST), body=None)


class Answer(BaseModel):
    text: str


class FakeMessages:

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    async def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class FakeAnthropic:

    def __init__(self, messages: FakeMessages):
        self.beta = SimpleNamespace(messages=messages)
        self.closed = False

    async def close(self):
        self.closed = True


def parsed_response(output=None, stop_reason="end_turn"):
    return SimpleNamespace(
        parsed_output=output,
        stop_reason=stop_reason,
        model="claude-opus-5",
        usage=SimpleNamespace(input_tokens=300, output_tokens=80),
    )


class TestTranslateError:
    def test_timeout(self):
        assert isinstance(
            translate_error(anthropic.APITimeoutError(request=REQUEST)), LLMTimeoutError
        )
        assert isinstance(translate_error(TimeoutError()), LLMTimeoutError)

    def test_rate_limit(self):
        error = translate_error(status_error(anthropic.RateLimitError, 429))
        assert isinstance(error, LLMRateLimitError)
        assert error.status_code == 429

    def test_connection_and_server_errors(self):
        assert isinstance(
            translate_error(anthropic.APIConnectionError(request=REQUEST)),
            LLMUnavailableError,
        )
        assert isinstance(
            translate_error(status_error(anthropic.InternalServerError, 500)),
            LLMUnavailableError,
        )

    def test_client_errors_are_generic(self):
        error = translate_error(status_error(anthropic.BadRequestError, 400))
        assert type(error) is LLMError
        assert error.status_code == 500

    def test_keeps_existing_llm_errors(self):
        original = LLMRefusalError("no")
        assert translate_error(original) is original


class TestStructuredClient:
    async def test_returns_parsed_output_with_usage(self):
        messages = FakeMessages(parsed_response(Answer(text="hi")))
        client = AnthropicStructuredClient(
            FakeAnthropic(messages), "claude-opus-5", 2048
        )

        completion = await client.generate(system="sys", prompt="p", output_type=Answer)

        assert completion.output == Answer(text="hi")
        assert completion.input_tokens == 300
        assert completion.output_tokens == 80
        assert messages.kwargs["output_format"] is Answer
        assert messages.kwargs["max_tokens"] == 2048
        assert messages.kwargs["messages"] == [{"role": "user", "content": "p"}]
        assert messages.kwargs["betas"] == [FALLBACK_BETA]
        assert messages.kwargs["fallbacks"] == "default"

    async def test_fallbacks_can_be_disabled(self):
        messages = FakeMessages(parsed_response(Answer(text="hi")))
        client = AnthropicStructuredClient(
            FakeAnthropic(messages), "claude-sonnet-5", 1024, refusal_fallbacks=False
        )

        await client.generate(system="s", prompt="p", output_type=Answer)

        assert "betas" not in messages.kwargs
        assert "fallbacks" not in messages.kwargs

    async def test_refusal(self):
        messages = FakeMessages(parsed_response(None, stop_reason="refusal"))
        client = AnthropicStructuredClient(
            FakeAnthropic(messages), "claude-opus-5", 1024
        )

        with pytest.raises(LLMRefusalError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_missing_output(self):
        messages = FakeMessages(parsed_response(None, stop_reason="max_tokens"))
        client = AnthropicStructuredClient(
            FakeAnthropic(messages), "claude-opus-5", 1024
        )

        with pytest.raises(LLMIncompleteResponseError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_translates_sdk_errors(self):
        messages = FakeMessages(error=anthropic.APITimeoutError(request=REQUEST))
        client = AnthropicStructuredClient(
            FakeAnthropic(messages), "claude-opus-5", 1024
        )

        with pytest.raises(LLMTimeoutError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_close(self):
        fake = FakeAnthropic(FakeMessages())
        await AnthropicStructuredClient(fake, "claude-opus-5", 1024).close()
        assert fake.closed


class TestChatModel:
    def test_uses_settings(self):
        settings = Settings(
            anthropic_api_key="sk-test",
            ai_model="claude-opus-5",
            ai_chat_max_tokens=1234,
            ai_timeout_seconds=30,
            ai_max_retries=0,
        )

        model = create_chat_model(settings)

        assert model.model == "claude-opus-5"
        assert model.max_tokens == 1234
        assert model.default_request_timeout == 30
        assert model.max_retries == 0

    def test_builds_gemini_model(self):
        settings = Settings(
            google_api_key="AIza-test",
            ai_model="gemini-2.5-flash",
            ai_chat_max_tokens=2048,
            ai_timeout_seconds=45,
            ai_max_retries=2,
        )

        model = create_chat_model(settings)

        assert type(model).__name__ == "ChatGoogleGenerativeAI"
        assert model.model.endswith("gemini-2.5-flash")
        assert model.max_output_tokens == 2048
        assert model.timeout == 45


class TestProviderSelection:
    @pytest.mark.parametrize(
        ("model", "provider"),
        [
            ("claude-opus-5", "anthropic"),
            ("claude-sonnet-5", "anthropic"),
            ("gemini-2.5-flash", "google"),
            ("Gemini-2.5-Pro", "google"),
        ],
    )
    def test_resolves_provider(self, model, provider):
        assert resolve_provider(model) == provider

    def test_structured_client_matches_provider(self):
        gemini = create_structured_client(
            Settings(google_api_key="AIza-test", ai_model="gemini-2.5-flash")
        )
        claude = create_structured_client(
            Settings(anthropic_api_key="sk-test", ai_model="claude-opus-5")
        )

        assert type(gemini).__name__ == "LangChainStructuredClient"
        assert type(claude).__name__ == "AnthropicStructuredClient"


class FakeStructuredRunnable:

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error is not None:
            raise self.error
        return self.result


class FakeChatModel:

    def __init__(self, runnable):
        self.runnable = runnable
        self.schema = None
        self.include_raw = None

    def with_structured_output(self, schema, include_raw=False):
        self.schema = schema
        self.include_raw = include_raw
        return self.runnable


class TestLangChainStructuredClient:
    async def test_returns_parsed_output_with_usage(self):
        raw = SimpleNamespace(
            usage_metadata={"input_tokens": 420, "output_tokens": 65},
        )
        runnable = FakeStructuredRunnable(
            {"parsed": Answer(text="مرحبا"), "raw": raw, "parsing_error": None}
        )
        model = FakeChatModel(runnable)
        client = LangChainStructuredClient(model, "gemini-2.5-flash")

        completion = await client.generate(system="sys", prompt="p", output_type=Answer)

        assert completion.output == Answer(text="مرحبا")
        assert completion.model == "gemini-2.5-flash"
        assert completion.input_tokens == 420
        assert completion.output_tokens == 65
        assert model.schema is Answer
        assert model.include_raw is True
        assert [type(m).__name__ for m in runnable.messages] == [
            "SystemMessage",
            "HumanMessage",
        ]

    async def test_missing_output(self):
        runnable = FakeStructuredRunnable(
            {"parsed": None, "raw": None, "parsing_error": "bad json"}
        )
        client = LangChainStructuredClient(FakeChatModel(runnable), "gemini-2.5-flash")

        with pytest.raises(LLMIncompleteResponseError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_translates_provider_errors(self):
        runnable = FakeStructuredRunnable(
            error=google_exceptions.ResourceExhausted("quota")
        )
        client = LangChainStructuredClient(FakeChatModel(runnable), "gemini-2.5-flash")

        with pytest.raises(LLMRateLimitError):
            await client.generate(system="s", prompt="p", output_type=Answer)


class TestGoogleErrorTranslation:
    def test_quota(self):
        error = translate_error(google_exceptions.ResourceExhausted("quota"))
        assert isinstance(error, LLMRateLimitError)

    def test_deadline(self):
        assert isinstance(
            translate_error(google_exceptions.DeadlineExceeded("slow")), LLMTimeoutError
        )

    def test_unavailable(self):
        assert isinstance(
            translate_error(google_exceptions.ServiceUnavailable("down")),
            LLMUnavailableError,
        )
