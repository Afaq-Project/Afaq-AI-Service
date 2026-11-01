from fastapi import Depends, Header, HTTPException, status

from src.modules.core.auth.api_key_auth import ApiKeyService
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.core.config.settings import get_settings
from src.modules.core.database.prisma_client import get_client
from src.modules.infrastructure.webhook.webhook_client import WebhookClient


def get_api_key_service() -> ApiKeyService:
    return ApiKeyService(db=get_client())


async def require_api_key(
    x_api_key: str = Header(default="", alias="X-API-Key"),
    service: ApiKeyService = Depends(get_api_key_service),
) -> ApiKeyInfo:
    """Dependency protecting endpoints: rejects request if API key is invalid."""
    key_info = await service.validate(x_api_key)

    if key_info is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return key_info


def get_webhook_client() -> WebhookClient:
    settings = get_settings()
    url = settings.main_service_webhook_url
    secret = settings.main_service_webhook_secret
    return WebhookClient(
        webhook_url=url, secret=secret, timeout=settings.webhook_timeout
    )
