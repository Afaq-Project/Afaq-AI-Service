from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.modules.ai.models import EssayReview


class ChatMessageResponse(BaseModel):

    conversation_id: str
    message_id: str
    answer: str
    status: Literal["ok", "declined"]
    decline_reason: str | None = None
    official_source_url: str | None = None
    disclaimer: str
    created_at: datetime


class EssayReviewResponse(EssayReview):

    disclaimer: str


class ConversationMessageItem(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: str
    role: str
    content: str
    status: str
    created_at: datetime


class ConversationHistoryResponse(BaseModel):

    conversation_id: str | None
    messages: list[ConversationMessageItem]
    has_more: bool


class ErrorBody(BaseModel):

    code: str
    message: str


class ErrorResponse(BaseModel):

    error: ErrorBody
