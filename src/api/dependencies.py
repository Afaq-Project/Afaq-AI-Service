from functools import lru_cache

from fastapi import Depends, Header, HTTPException, status

from src.api.protocols import ScraperServiceProtocol
from src.modules.ai.chat_agent import WardhookChatAgentFactory
from src.modules.ai.chat_service import ChatService
from src.modules.ai.essay_review_service import EssayReviewService
from src.modules.ai.guardrails import build_chat_guardrails
from src.modules.core.auth.api_key_auth import ApiKeyService
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.core.config.settings import get_settings
from src.modules.core.database.prisma_client import get_client
from src.modules.core.database.repositories.conversation_repository import (
    ConversationRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.infrastructure.llm.providers import (
    get_chat_model,
    get_structured_client,
)


def get_api_key_service() -> ApiKeyService:
    return ApiKeyService(db=get_client())


async def require_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyInfo:
    """تبعية تحمي نقاط النهاية: ترفض الطلب إذا كان المفتاح غير صالح."""
    key_info = await service.validate(x_api_key)

    if key_info is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return key_info


def get_scraper_service() -> ScraperServiceProtocol:
    """يرجع خدمة الجلب. تُنفَّذ في B-10 من قبل العضو الثاني."""
    try:
        from src.modules.scraping.services.scraper_service import (  # noqa: PLC0415
            ScraperService,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scraper service is not available yet",
        ) from exc

    return ScraperService(db=get_client())


@lru_cache
def get_chat_agent_factory() -> WardhookChatAgentFactory:
    return WardhookChatAgentFactory(get_chat_model(), build_chat_guardrails())


def get_chat_service() -> ChatService:
    db = get_client()
    return ChatService(
        conversations=ConversationRepository(db),
        opportunities=OpportunityRepository(db),
        agents=get_chat_agent_factory(),
        history_limit=get_settings().ai_history_limit,
    )


def get_essay_review_service() -> EssayReviewService:
    return EssayReviewService(
        llm=get_structured_client(),
        opportunities=OpportunityRepository(get_client()),
    )
