from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from src.modules.core.config.settings import Settings
from src.modules.infrastructure.llm.anthropic_client import (
    FALLBACK_BETA,
    StructuredLLMClient,
    create_chat_model,
    translate_error,
)
from src.modules.infrastructure.llm.exceptions import (
    LLMError,
    LLMIncompleteResponseError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMTimeoutError,
    LLMUnavailableError,
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
        client = StructuredLLMClient(FakeAnthropic(messages), "claude-opus-5", 2048)

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
        client = StructuredLLMClient(
            FakeAnthropic(messages), "claude-sonnet-5", 1024, refusal_fallbacks=False
        )

        await client.generate(system="s", prompt="p", output_type=Answer)

        assert "betas" not in messages.kwargs
        assert "fallbacks" not in messages.kwargs

    async def test_refusal(self):
        messages = FakeMessages(parsed_response(None, stop_reason="refusal"))
        client = StructuredLLMClient(FakeAnthropic(messages), "claude-opus-5", 1024)

        with pytest.raises(LLMRefusalError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_missing_output(self):
        messages = FakeMessages(parsed_response(None, stop_reason="max_tokens"))
        client = StructuredLLMClient(FakeAnthropic(messages), "claude-opus-5", 1024)

        with pytest.raises(LLMIncompleteResponseError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_translates_sdk_errors(self):
        messages = FakeMessages(error=anthropic.APITimeoutError(request=REQUEST))
        client = StructuredLLMClient(FakeAnthropic(messages), "claude-opus-5", 1024)

        with pytest.raises(LLMTimeoutError):
            await client.generate(system="s", prompt="p", output_type=Answer)

    async def test_close(self):
        fake = FakeAnthropic(FakeMessages())
        await StructuredLLMClient(fake, "claude-opus-5", 1024).close()
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
