from fastapi import Depends, Header, HTTPException, status

from src.modules.core.auth.api_key_auth import ApiKeyService
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.core.config.settings import get_settings
from src.modules.core.database.prisma_client import get_client
from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.infrastructure.webhook.webhook_client import WebhookClient
from src.modules.matching.services.matching_service import MatchingService
from src.modules.matching.services.user_profile_reader import UserProfileReader


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
