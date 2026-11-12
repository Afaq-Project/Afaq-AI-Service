# [OMA-W006-T009] Public facade for ScraperService package

import asyncio
import logging
from typing import Any

from src.modules.core.config.settings import Settings, get_settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.webhook.webhook_client import WebhookClient
from src.modules.scraping.models import OperationAbortData, SourceAbortData
from src.modules.scraping.services.crawler_service import CrawlerService
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
)
from src.modules.scraping.services.language_classifier_service import (
    LanguageClassifierService,
)
from src.modules.scraping.services.pagination_service import PaginationService
from src.modules.scraping.services.prioritization_service import PrioritizationService

from .catalog_phase import crawl_catalog_phase, extract_cards_from_html
from .coordinator import DEFAULT_MAX_OPERATION_TIMEOUT_SEC, ScraperCoordinator
from .details_phase import (
    crawl_details_phase,
    extract_details_from_html,
    is_downloadable_document,
    resolve_opportunity_group_id,
)
from .lock_manager import STALE_LOCK_THRESHOLD_MINUTES
from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class ScraperService:
    """Master orchestrator for autonomous multi-source scraping pipeline."""

    _operation_cancellation_tokens = TokenManager._operation_tokens
    _source_cancellation_tokens = TokenManager._source_tokens

    # Backward compatible class/static methods
    _is_downloadable_document = staticmethod(is_downloadable_document)
    _extract_cards_from_html = staticmethod(extract_cards_from_html)
    _extract_details_from_html = staticmethod(extract_details_from_html)

    def __init__(
        self,
        repository: ScrapingRepository | None = None,
        crawler_service: CrawlerService | None = None,
        pagination_service: PaginationService | None = None,
        prioritization_service: PrioritizationService | None = None,
        webhook_client: WebhookClient | None = None,
        language_classifier: LanguageClassifierService | None = None,
        document_ingestion: DocumentIngestionService | None = None,
        settings: Settings | None = None,
    ) -> None:
        if repository is None:
            try:
                from src.modules.core.database.prisma_client import get_client

                db = get_client()
            except Exception:
                from prisma import Prisma

                db = Prisma()
            repository = ScrapingRepository(db=db)
        self._repository = repository
        self._settings = settings or get_settings()
        self._crawler_service = crawler_service or CrawlerService(self._settings)
        self._pagination_service = pagination_service or PaginationService()
        self._prioritization_service = prioritization_service or PrioritizationService()
        self._webhook_client = webhook_client
        self._language_classifier = language_classifier or LanguageClassifierService()
        self._document_ingestion = document_ingestion

        self._coordinator = ScraperCoordinator(
            repository=self._repository,
            crawler_service=self._crawler_service,
            pagination_service=self._pagination_service,
            prioritization_service=self._prioritization_service,
            webhook_client=self._webhook_client,
            language_classifier=self._language_classifier,
            document_ingestion=self._document_ingestion,
            settings=self._settings,
        )

    def is_operation_cancelled(self, operation_id: str) -> bool:
        return TokenManager.is_operation_cancelled(operation_id)

    def is_source_cancelled(self, source_id: str) -> bool:
        return TokenManager.is_source_cancelled(source_id)

    async def prepare_scrape_operation(
        self,
        source_ids: list[str] | None = None,
        idempotency_key: str | None = None,
        triggered_by: str = "admin_api",
    ) -> tuple[Any, bool, int, int]:
        return await self._coordinator.prepare_scrape_operation(
            source_ids=source_ids,
            idempotency_key=idempotency_key,
            triggered_by=triggered_by,
        )

    async def run_scrape_operation(
        self,
        operation_id: str,
        prioritized_source_ids: list[str],
    ) -> Any:
        return await self._coordinator.run_scrape_operation(
            operation_id=operation_id,
            prioritized_source_ids=prioritized_source_ids,
        )

    async def _execute_batch(
        self,
        operation_id: str,
        source_ids: list[str],
    ) -> Any:
        return await self._coordinator._execute_batch(
            operation_id=operation_id,
            source_ids=source_ids,
        )

    async def _crawl_catalog_phase(
        self,
        operation_id: str,
        source: Any,
        config: Any,
        operation_token: asyncio.Event | None,
        source_token: asyncio.Event | None,
    ) -> int:
        return await crawl_catalog_phase(
            crawler_service=self._crawler_service,
            pagination_service=self._pagination_service,
            repository=self._repository,
            operation_id=operation_id,
            source=source,
            config=config,
            operation_token=operation_token,
            source_token=source_token,
        )

    async def _crawl_details_phase(
        self,
        operation_id: str,
        source: Any,
        config: Any,
        operation_token: asyncio.Event | None,
        source_token: asyncio.Event | None,
    ) -> int:
        return await crawl_details_phase(
            crawler_service=self._crawler_service,
            language_classifier=self._language_classifier,
            document_ingestion=self._document_ingestion,
            repository=self._repository,
            operation_id=operation_id,
            source=source,
            config=config,
            operation_token=operation_token,
            source_token=source_token,
        )

    async def _resolve_opportunity_group_id(
        self,
        source_id: str,
        source_url: str,
        title: str,
        detected_language: str,
        alternate_links: list[str] | None = None,
    ) -> str:
        return await resolve_opportunity_group_id(
            repository=self._repository,
            source_id=source_id,
            source_url=source_url,
            title=title,
            detected_language=detected_language,
            alternate_links=alternate_links,
        )

    async def abort_operation(self, operation_id: str) -> OperationAbortData:
        return await self._coordinator.abort_operation(operation_id)

    async def abort_source(self, source_id: str) -> SourceAbortData:
        return await self._coordinator.abort_source(source_id)

    async def _dispatch_webhook(
        self,
        operation_id: str,
        status: str,
        total_opportunities: int,
        succeeded_sources: list[str],
        failed_sources: list[str],
    ) -> None:
        await self._coordinator._dispatch_webhook(
            operation_id=operation_id,
            status=status,
            total_opportunities=total_opportunities,
            succeeded_sources=succeeded_sources,
            failed_sources=failed_sources,
        )

    async def get_operations_log(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        offset: int | None = None,
    ) -> tuple[list[Any], int]:
        return await self._coordinator.get_operations_log(
            skip=skip,
            limit=limit,
            status=status,
            offset=offset,
        )

    async def get_latest_operation(self) -> Any | None:
        return await self._coordinator.get_latest_operation()

    async def get_operation_by_id(self, operation_id: str) -> Any | None:
        return await self._coordinator.get_operation_by_id(operation_id)

    async def get_dead_letter_records(
        self,
        entity_type: str = "listings",
        skip: int = 0,
        limit: int = 50,
        offset: int | None = None,
    ) -> tuple[list[Any], int]:
        return await self._coordinator.get_dead_letter_records(
            entity_type=entity_type,
            skip=skip,
            limit=limit,
            offset=offset,
        )


__all__ = [
    "ScraperService",
    "STALE_LOCK_THRESHOLD_MINUTES",
    "DEFAULT_MAX_OPERATION_TIMEOUT_SEC",
]
