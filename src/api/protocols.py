# [OMA-W005-T041] FastAPI dependency injection protocols and container providers for scraping services
"""FastAPI protocols and dependency injection container providers for scraping services."""

from typing import Annotated, Any, Protocol, runtime_checkable

from fastapi import Depends

from src.api.dependencies import get_webhook_client
from src.modules.core.config.settings import Settings, get_settings
from src.modules.infrastructure.webhook.webhook_client import WebhookClient
from src.modules.scraping.services.crawler_service import CrawlerService
from src.modules.scraping.services.discovery_service import DiscoveryService
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
)
from src.modules.scraping.services.language_classifier_service import (
    LanguageClassifierService,
)
from src.modules.scraping.services.pagination_service import PaginationService
from src.modules.scraping.services.prioritization_service import (
    PrioritizationService,
)
from src.modules.scraping.services.scraper_service import ScraperService
from src.modules.scraping.services.template_engine_service import (
    TemplateEngineService,
)


# [OMA-W004-FIX-CYCLE-2] Protocol interface for ScraperService orchestrator
@runtime_checkable
class ScraperServiceProtocol(Protocol):
    """Protocol interface defining operations of ScraperService."""

    def is_operation_cancelled(self, operation_id: str) -> bool: ...

    def is_source_cancelled(self, source_id: str) -> bool: ...

    async def prepare_scrape_operation(
        self,
        source_ids: list[str] | None = None,
        idempotency_key: str | None = None,
        triggered_by: str = "manual",
    ) -> tuple[Any, bool, int, int]: ...

    async def run_scrape_operation(
        self,
        operation_id: str,
        prioritized_source_ids: list[str],
    ) -> Any: ...

    async def abort_operation(self, operation_id: str) -> dict[str, Any]: ...

    async def abort_source(self, source_id: str) -> dict[str, Any]: ...

    async def get_operations_log(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        offset: int | None = None,
    ) -> tuple[list[Any], int]: ...

    async def get_latest_operation(self) -> Any | None: ...

    async def get_operation_by_id(self, operation_id: str) -> Any | None: ...

    async def get_dead_letter_records(
        self,
        entity_type: str = "listings",
        skip: int = 0,
        limit: int = 50,
        offset: int | None = None,
    ) -> tuple[list[Any], int]: ...


# [OMA-W004-FIX-CYCLE-2] Protocol interface for DiscoveryService
@runtime_checkable
class DiscoveryServiceProtocol(Protocol):
    """Protocol interface defining operations of DiscoveryService."""

    async def onboard_source(
        self,
        url: str,
        name: str | None = None,
        created_by: str | None = None,
    ) -> Any: ...

    async def check_relevance(self, html_content: str, url: str) -> bool: ...


# [OMA-W005-T041] Protocol interface for CrawlerService
@runtime_checkable
class CrawlerServiceProtocol(Protocol):
    """Protocol interface defining operations of CrawlerService."""

    async def fetch_page(self, url: str, **kwargs: Any) -> Any: ...

    async def close(self) -> None: ...


# [OMA-W005-T041] Protocol interface for TemplateEngineService
@runtime_checkable
class TemplateEngineServiceProtocol(Protocol):
    """Protocol interface defining operations of TemplateEngineService."""

    async def match_template(
        self, source_id: str, url: str, html: str, page_type: str = "detail"
    ) -> Any: ...


# [OMA-W005-T041] Protocol interface for PaginationService
@runtime_checkable
class PaginationServiceProtocol(Protocol):
    """Protocol interface defining operations of PaginationService."""

    def step(self, state: Any, html: str, current_url: str) -> Any: ...


# [OMA-W005-T041] Protocol interface for PrioritizationService
@runtime_checkable
class PrioritizationServiceProtocol(Protocol):
    """Protocol interface defining operations of PrioritizationService."""

    def rank_sources(self, sources: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


# [OMA-W005-T041] Protocol interface for LanguageClassifierService
@runtime_checkable
class LanguageClassifierServiceProtocol(Protocol):
    """Protocol interface defining operations of LanguageClassifierService."""

    def classify_text(self, text: str) -> Any: ...


# [OMA-W005-T041] Protocol interface for DocumentIngestionService
@runtime_checkable
class DocumentIngestionServiceProtocol(Protocol):
    """Protocol interface defining operations of DocumentIngestionService."""

    async def download_and_ingest(
        self, document_url: str, source_id: str, grant_id: str | None = None
    ) -> Any: ...


# [OMA-W005-T041] Dependency provider for ScrapingRepository
# [OMA-W005-T041] Legacy dependency provider stub preserved for test harness compatibility
def get_scraping_repository() -> Any:
    """Dependency injecting ScrapingRepository stub to prevent API layer coupling."""
    return None


# [OMA-W005-T041] Singleton ScraperService instance container
_singleton_scraper_service: ScraperService | None = None


# [OMA-W005-T041] Getter for singleton ScraperService instance
def get_singleton_scraper_service() -> ScraperService | None:
    """Returns the current singleton ScraperService instance if initialized."""
    global _singleton_scraper_service
    return _singleton_scraper_service


# [OMA-W005-T041] Setter for singleton ScraperService instance
def set_singleton_scraper_service(service: ScraperService | None) -> None:
    """Sets or overrides the singleton ScraperService instance."""
    global _singleton_scraper_service
    _singleton_scraper_service = service


# [OMA-W005-T041] Reset singleton ScraperService instance
def reset_singleton_scraper_service() -> None:
    """Resets the singleton ScraperService instance to None."""
    global _singleton_scraper_service
    _singleton_scraper_service = None


# [OMA-W005-T041] Dependency provider for ScraperService coordinator
def get_scraper_service(
    webhook_client: Annotated[WebhookClient | None, Depends(get_webhook_client)] = None,
) -> ScraperService:
    """Dependency providing ScraperService instance sharing token registries."""
    global _singleton_scraper_service
    if _singleton_scraper_service is None:
        client = webhook_client
        if client is None:
            try:
                client = get_webhook_client()
            except Exception:
                client = WebhookClient(webhook_url="")
        _singleton_scraper_service = ScraperService(
            webhook_client=client,
        )
    elif not getattr(_singleton_scraper_service._repository._db, "is_connected", lambda: False)():
        try:
            from src.modules.core.database.prisma_client import get_client
            client_db = get_client()
            if client_db.is_connected():
                _singleton_scraper_service._repository._db = client_db
        except Exception:
            pass
    return _singleton_scraper_service


# [OMA-W005-T041] Dependency provider for DiscoveryService coordinator
def get_discovery_service() -> DiscoveryService:
    """Dependency providing DiscoveryService instance."""
    return DiscoveryService()


# [OMA-W005-T041] Dependency provider for CrawlerService
def get_crawler_service(
    settings: Annotated[Settings | None, Depends(get_settings)] = None,
) -> CrawlerService:
    """Dependency providing CrawlerService instance."""
    return CrawlerService(settings=settings)


# [OMA-W005-T041] Dependency provider for PaginationService
def get_pagination_service() -> PaginationService:
    """Dependency providing PaginationService instance."""
    return PaginationService()


# [OMA-W005-T041] Dependency provider for PrioritizationService
def get_prioritization_service() -> PrioritizationService:
    """Dependency providing PrioritizationService instance."""
    return PrioritizationService()


# [OMA-W005-T041] Dependency provider for LanguageClassifierService
def get_language_classifier_service() -> LanguageClassifierService:
    """Dependency providing LanguageClassifierService instance."""
    return LanguageClassifierService()


# [OMA-W005-T041] Dependency provider for DocumentIngestionService
def get_document_ingestion_service(
    settings: Annotated[Settings | None, Depends(get_settings)] = None,
) -> DocumentIngestionService:
    """Dependency providing DocumentIngestionService instance."""
    return DocumentIngestionService(settings=settings)


# [OMA-W005-T041] Dependency provider for TemplateEngineService
def get_template_engine_service(
    settings: Annotated[Settings | None, Depends(get_settings)] = None,
) -> TemplateEngineService:
    """Dependency providing TemplateEngineService instance."""
    return TemplateEngineService(settings=settings)


__all__ = [
    # Protocols
    "CrawlerServiceProtocol",
    "DiscoveryServiceProtocol",
    "DocumentIngestionServiceProtocol",
    "LanguageClassifierServiceProtocol",
    "PaginationServiceProtocol",
    "PrioritizationServiceProtocol",
    "ScraperServiceProtocol",
    "TemplateEngineServiceProtocol",
    # Dependency Providers & Factories
    "get_crawler_service",
    "get_discovery_service",
    "get_document_ingestion_service",
    "get_language_classifier_service",
    "get_pagination_service",
    "get_prioritization_service",
    "get_scraper_service",
    "get_scraping_repository",
    "get_singleton_scraper_service",
    "get_template_engine_service",
    "reset_singleton_scraper_service",
    "set_singleton_scraper_service",
]
