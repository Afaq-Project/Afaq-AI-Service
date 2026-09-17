from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.dependencies import (
    get_api_key_service,
    get_chat_service,
    get_essay_review_service,
    require_api_key,
)
from src.api.errors import register_ai_error_handlers
from src.api.routes.v1 import ai
from src.modules.ai.constants import DISCLAIMERS, ERROR_MESSAGES
from src.modules.ai.exceptions import OpportunityNotFoundError
from src.modules.ai.models import ChatReply, ConversationHistory, EssayReview
from src.modules.core.auth.api_key_auth import ApiKeyService
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.infrastructure.llm.exceptions import (
    LLMRateLimitError,
    LLMRefusalError,
    LLMTimeoutError,
    LLMUnavailableError,
)

USER_ID = "3f1c2b4e-8d5a-4c7e-9b1f-2a6d8e0c4b7a"
OPPORTUNITY_ID = "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
CREATED_AT = datetime(2026, 9, 15, 10, 0, tzinfo=UTC)

ESSAY = "I want to study public policy to improve digital services at home. " * 3


class FakeChatService:

    def __init__(self, reply=None, error=None, history=None):
        self.reply = reply or ChatReply(
            conversation_id="conv-1",
            message_id="msg-2",
            answer="آخر موعد هو 5 نوفمبر.",
            status="ok",
            official_source_url="https://www.chevening.org/apply",
            created_at=CREATED_AT,
        )
        self.error = error
        self.history = history
        self.calls: list[dict] = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.reply

    async def get_history(self, **kwargs):
        self.calls.append(kwargs)
        return self.history


class FakeEssayService:

    def __init__(self, error=None):
        self.error = error
        self.calls: list[dict] = []

    async def review(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return EssayReview(
            overall_assessment="Solid.",
            strengths=[],
            weaknesses=[],
            suggestions=[],
            language_issues=[],
            fit_with_opportunity=None,
        )


class EmptyKeyTable:
    async def find_unique(self, where):
        return None


def build_app(chat=None, essay=None, authenticated=True) -> FastAPI:
    application = FastAPI()
    register_ai_error_handlers(application)
    application.include_router(ai.router)
    application.dependency_overrides[get_chat_service] = (
        lambda: chat or FakeChatService()
    )
    application.dependency_overrides[get_essay_review_service] = (
        lambda: essay or FakeEssayService()
    )
    if authenticated:
        application.dependency_overrides[require_api_key] = lambda: ApiKeyInfo(
            id="key-1", name="main-service", is_active=True
        )
    else:
        application.dependency_overrides[get_api_key_service] = lambda: ApiKeyService(
            db=SimpleNamespace(apikey=EmptyKeyTable())
        )
    return application


def chat_body(**overrides) -> dict:
    body = {
        "user_id": USER_ID,
        "opportunity_id": OPPORTUNITY_ID,
        "message": "  متى الموعد النهائي؟  ",
    }
    body.update(overrides)
    return body


class TestChatEndpoint:
    def test_returns_answer_with_disclaimer(self):
        chat = FakeChatService()
        response = TestClient(build_app(chat=chat)).post(
            "/api/v1/ai/chat", json=chat_body()
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "آخر موعد هو 5 نوفمبر."
        assert data["status"] == "ok"
        assert data["disclaimer"] == DISCLAIMERS["ar"]
        assert chat.calls[0]["message"] == "متى الموعد النهائي؟"
        assert chat.calls[0]["user_id"] == USER_ID
        assert chat.calls[0]["application_id"] is None

    def test_declined_reply_also_has_disclaimer(self):
        chat = FakeChatService(
            reply=ChatReply(
                conversation_id="conv-1",
                message_id="msg-2",
                answer="We don't have reliable enough information.",
                status="declined",
                decline_reason="missing_eligibility_data",
                official_source_url="https://www.chevening.org/apply",
                created_at=CREATED_AT,
            )
        )
        response = TestClient(build_app(chat=chat)).post(
            "/api/v1/ai/chat", json=chat_body(locale="en")
        )

        data = response.json()
        assert data["status"] == "declined"
        assert data["decline_reason"] == "missing_eligibility_data"
        assert data["disclaimer"] == DISCLAIMERS["en"]

    def test_passes_profile(self):
        chat = FakeChatService()
        profile = {
            "nationality": "Syria",
            "gpa": 3.4,
            "languages": [{"name": "English", "level": "B2"}],
        }

        TestClient(build_app(chat=chat)).post(
            "/api/v1/ai/chat", json=chat_body(profile=profile)
        )

        assert chat.calls[0]["profile"].nationality == "Syria"

    @pytest.mark.parametrize(
        "overrides",
        [
            {"message": "   "},
            {"message": "x" * 4001},
            {"user_id": "not-a-uuid"},
            {"locale": "fr"},
            {"profile": {"gpa": -1}},
        ],
    )
    def test_validation(self, overrides):
        response = TestClient(build_app()).post(
            "/api/v1/ai/chat", json=chat_body(**overrides)
        )
        assert response.status_code == 422

    def test_requires_api_key(self):
        response = TestClient(build_app(authenticated=False)).post(
            "/api/v1/ai/chat", json=chat_body(), headers={"X-API-Key": "bogus"}
        )
        assert response.status_code == 401

    @pytest.mark.parametrize(
        ("error", "status_code", "code"),
        [
            (LLMTimeoutError("slow"), 504, "ai_timeout"),
            (LLMRateLimitError("busy"), 429, "ai_busy"),
            (LLMUnavailableError("down"), 503, "ai_unavailable"),
            (OpportunityNotFoundError(OPPORTUNITY_ID), 404, "opportunity_not_found"),
        ],
    )
    def test_errors_are_friendly(self, error, status_code, code):
        response = TestClient(build_app(chat=FakeChatService(error=error))).post(
            "/api/v1/ai/chat", json=chat_body()
        )

        assert response.status_code == status_code
        assert response.json() == {
            "error": {"code": code, "message": ERROR_MESSAGES[code]}
        }


class TestEssayReviewEndpoint:
    def test_returns_review_with_disclaimer(self):
        essay = FakeEssayService()
        response = TestClient(build_app(essay=essay)).post(
            "/api/v1/ai/essay-review",
            json={
                "user_id": USER_ID,
                "essay_type": "motivation_letter",
                "essay_text": ESSAY,
                "opportunity_id": OPPORTUNITY_ID,
                "locale": "en",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["overall_assessment"] == "Solid."
        assert data["disclaimer"] == DISCLAIMERS["en"]
        assert essay.calls[0]["opportunity_id"] == OPPORTUNITY_ID

    @pytest.mark.parametrize(
        "overrides",
        [{"essay_text": "too short"}, {"essay_type": "poem"}],
    )
    def test_validation(self, overrides):
        body = {"user_id": USER_ID, "essay_type": "cv", "essay_text": ESSAY}
        body.update(overrides)

        response = TestClient(build_app()).post("/api/v1/ai/essay-review", json=body)

        assert response.status_code == 422

    def test_refusal(self):
        response = TestClient(
            build_app(essay=FakeEssayService(error=LLMRefusalError("declined")))
        ).post(
            "/api/v1/ai/essay-review",
            json={"user_id": USER_ID, "essay_type": "cv", "essay_text": ESSAY},
        )

        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ai_refused"


class TestConversationHistoryEndpoint:
    def test_returns_messages(self):
        history = ConversationHistory(
            conversation_id="conv-1",
            messages=[
                SimpleNamespace(
                    id="msg-1",
                    role="user",
                    content="سؤال",
                    status="ok",
                    created_at=CREATED_AT,
                    conversation_id="conv-1",
                )
            ],
            has_more=False,
        )
        chat = FakeChatService(history=history)

        response = TestClient(build_app(chat=chat)).get(
            "/api/v1/ai/conversations",
            params={"user_id": USER_ID, "opportunity_id": OPPORTUNITY_ID, "limit": 10},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["conversation_id"] == "conv-1"
        assert data["messages"][0]["content"] == "سؤال"
        assert chat.calls[0]["limit"] == 10

    def test_rejects_large_limit(self):
        response = TestClient(build_app()).get(
            "/api/v1/ai/conversations",
            params={
                "user_id": USER_ID,
                "opportunity_id": OPPORTUNITY_ID,
                "limit": 1000,
            },
        )
        assert response.status_code == 422
