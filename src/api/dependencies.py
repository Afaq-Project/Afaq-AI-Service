from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Depends, Header, HTTPException, status

from src.api.protocols import ScraperServiceProtocol
from src.modules.core.auth.api_key_auth import ApiKeyService
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.core.config.settings import get_settings
from src.modules.core.database.prisma_client import get_client
from src.modules.core.database.repositories.conversation_repository import (
    ConversationRepository,
)
from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.infrastructure.llm.providers import (
    get_chat_model,
    get_structured_client,
)
from src.modules.infrastructure.webhook.webhook_client import WebhookClient
from src.modules.matching.services.matching_service import MatchingService
from src.modules.matching.services.user_profile_reader import UserProfileReader

if TYPE_CHECKING:
    from src.modules.ai.chat_agent import WardhookChatAgentFactory
    from src.modules.ai.chat_service import ChatService
    from src.modules.ai.essay_review_service import EssayReviewService


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
def get_chat_agent_factory() -> "WardhookChatAgentFactory":
    from src.modules.ai.chat_agent import WardhookChatAgentFactory
    from src.modules.ai.guardrails import build_chat_guardrails

    return WardhookChatAgentFactory(get_chat_model(), build_chat_guardrails())


def get_chat_service() -> "ChatService":
    from src.modules.ai.chat_service import ChatService

    db = get_client()
    return ChatService(
        conversations=ConversationRepository(db),
        opportunities=OpportunityRepository(db),
        agents=get_chat_agent_factory(),
        history_limit=get_settings().ai_history_limit,
    )


def get_essay_review_service() -> "EssayReviewService":
    from src.modules.ai.essay_review_service import EssayReviewService

    return EssayReviewService(
        llm=get_structured_client(),
        opportunities=OpportunityRepository(get_client()),
    )


def get_user_profile_reader() -> UserProfileReader:
    """Returns UserProfileReader configured with PROFILE_API_DATABASE_URL."""
    return UserProfileReader()


def get_match_score_repository() -> MatchScoreRepository:
    return MatchScoreRepository(get_client())


def get_matching_webhook_client() -> WebhookClient:
    settings = get_settings()
    url = settings.matching_webhook_url or settings.main_service_webhook_url
    secret = settings.matching_webhook_secret or settings.main_service_webhook_secret
    return WebhookClient(
        webhook_url=url, secret=secret, timeout=settings.webhook_timeout
    )


def get_matching_service(
    webhook_client: WebhookClient = Depends(get_matching_webhook_client),
    profile_reader: UserProfileReader = Depends(get_user_profile_reader),
) -> MatchingService:
    db = get_client()
    actual_reader = (
        profile_reader
        if isinstance(profile_reader, UserProfileReader)
        else get_user_profile_reader()
    )
    actual_webhook = (
        webhook_client
        if isinstance(webhook_client, WebhookClient)
        else get_matching_webhook_client()
    )
    return MatchingService(
        profile_reader=actual_reader,
        opportunity_repo=OpportunityRepository(db),
        match_score_repo=MatchScoreRepository(db),
        webhook_client=actual_webhook,
    )
