from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.api.dependencies import (
    get_chat_service,
    get_essay_review_service,
    require_api_key,
)
from src.api.models.ai_requests import ChatMessageRequest, EssayReviewRequest
from src.api.models.ai_responses import (
    ChatMessageResponse,
    ConversationHistoryResponse,
    ConversationMessageItem,
    ErrorResponse,
    EssayReviewResponse,
)
from src.modules.ai.chat_service import ChatService
from src.modules.ai.constants import disclaimer_for
from src.modules.ai.essay_review_service import EssayReviewService
from src.modules.core.auth.models import ApiKeyInfo

router = APIRouter(
    prefix="/api/v1/ai",
    tags=["ai"],
    responses={
        401: {"description": "Invalid or missing API key"},
        404: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)


@router.post("/chat", response_model=ChatMessageResponse)
async def send_chat_message(
    request: ChatMessageRequest,
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: ChatService = Depends(get_chat_service),
) -> ChatMessageResponse:
    reply = await service.send_message(
        user_id=str(request.user_id),
        opportunity_id=str(request.opportunity_id),
        application_id=str(request.application_id) if request.application_id else None,
        message=request.message,
        locale=request.locale,
        profile=request.profile,
    )
    return ChatMessageResponse(
        conversation_id=reply.conversation_id,
        message_id=reply.message_id,
        answer=reply.answer,
        status=reply.status,
        decline_reason=reply.decline_reason,
        official_source_url=reply.official_source_url,
        disclaimer=disclaimer_for(request.locale),
        created_at=reply.created_at,
    )


@router.post(
    "/essay-review",
    response_model=EssayReviewResponse,
    responses={422: {"model": ErrorResponse}},
)
async def review_essay(
    request: EssayReviewRequest,
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: EssayReviewService = Depends(get_essay_review_service),
) -> EssayReviewResponse:
    review = await service.review(
        user_id=str(request.user_id),
        essay_text=request.essay_text,
        essay_type=request.essay_type,
        locale=request.locale,
        opportunity_id=str(request.opportunity_id) if request.opportunity_id else None,
    )
    return EssayReviewResponse(
        **review.model_dump(), disclaimer=disclaimer_for(request.locale)
    )


@router.get("/conversations", response_model=ConversationHistoryResponse)
async def get_conversation_history(
    user_id: UUID,
    opportunity_id: UUID,
    application_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = None,
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: ChatService = Depends(get_chat_service),
) -> ConversationHistoryResponse:
    history = await service.get_history(
        user_id=str(user_id),
        opportunity_id=str(opportunity_id),
        application_id=str(application_id) if application_id else None,
        limit=limit,
        before=before,
    )
    return ConversationHistoryResponse(
        conversation_id=history.conversation_id,
        messages=[
            ConversationMessageItem.model_validate(message)
            for message in history.messages
        ],
        has_more=history.has_more,
    )
