# [OMA-W005-T016] [OMA-W005-T022] [OMA-W005-T034] [OMA-W006-T002] Integration test fixtures and configuration for scraping pipeline

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.dependencies import require_api_key
from src.api.routes.v1 import scrape

# [OMA-W006-T002] Import canonical FastAPI application instance
from src.main import app
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.core.config.settings import Settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.webhook.webhook_client import WebhookClient
from src.modules.scraping.services.crawler_service import (
    CrawlerService,
    CrawlResult,
)
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
from tests.integration.modules.scraping.mock_db import FakePrisma


@pytest.fixture
def fake_db() -> FakePrisma:
    """Fresh in-memory Prisma client harness."""
    return FakePrisma()


@pytest.fixture
def scraping_repo(fake_db: FakePrisma) -> ScrapingRepository:
    """ScrapingRepository backed by in-memory FakePrisma."""
    return ScrapingRepository(db=fake_db)  # type: ignore[arg-type]


@pytest.fixture
def mock_crawler() -> CrawlerService:
    """Mock CrawlerService with mock crawl_page returning valid CrawlResult."""
    crawler = MagicMock(spec=CrawlerService)
    crawler.crawl_page = AsyncMock(
        return_value=CrawlResult(
            url="https://example.org",
            canonical_url="https://example.org",
            html="<html><body><div class='card'><a href='https://example.org/1'>Grant</a></div></body></html>",
            status_code=200,
        )
    )
    return crawler


@pytest.fixture
def mock_webhook_client() -> WebhookClient:
    """Mock WebhookClient for capturing scrape complete events."""
    client = MagicMock(spec=WebhookClient)
    client.post_event = AsyncMock(return_value=True)
    return client


@pytest.fixture
def mock_pagination_service() -> PaginationService:
    """Mock PaginationService providing evaluate_step required by ScraperService."""
    service = MagicMock(spec=PaginationService)
    from src.modules.scraping.services.pagination_service import (
        PaginationStepResult,
    )

    service.evaluate_step = MagicMock(
        return_value=PaginationStepResult(
            current_url="",
            next_url=None,
            is_terminated=True,
            termination_signal="single_page",
            page_fingerprint="",
            card_count=2,
            new_card_count=2,
            consecutive_existing_pages=0,
        )
    )
    return service


@pytest.fixture
def test_settings() -> Settings:
    """Settings configured for fast and deterministic integration testing."""
    return Settings(
        crawler_max_operation_timeout_sec=1200,
        s3_bucket="test-bucket",
    )


@pytest.fixture
def scraper_service(
    scraping_repo: ScrapingRepository,
    mock_crawler: CrawlerService,
    mock_pagination_service: PaginationService,
    mock_webhook_client: WebhookClient,
    test_settings: Settings,
) -> ScraperService:
    """Fully wired ScraperService coordinator using test fixtures."""
    return ScraperService(
        repository=scraping_repo,
        crawler_service=mock_crawler,
        pagination_service=mock_pagination_service,
        prioritization_service=PrioritizationService(),
        webhook_client=mock_webhook_client,
        language_classifier=LanguageClassifierService(),
        document_ingestion=DocumentIngestionService(
            repository=scraping_repo,
            settings=test_settings,
        ),
        settings=test_settings,
    )


@pytest.fixture
def discovery_service(
    scraping_repo: ScrapingRepository,
    mock_crawler: CrawlerService,
    test_settings: Settings,
) -> DiscoveryService:
    """Fully wired DiscoveryService for Stage 0 onboarding."""
    return DiscoveryService(
        repository=scraping_repo,
        crawler=mock_crawler,
        settings=test_settings,
    )


@pytest.fixture
async def client(
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
    discovery_service: DiscoveryService,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient configured with dependency overrides for the test harness."""
    mock_api_key = ApiKeyInfo(
        id="test_key_id",
        name="test_partner",
        is_active=True,
    )

    app.dependency_overrides[require_api_key] = lambda: mock_api_key
    app.dependency_overrides[scrape.get_scraping_repository] = lambda: scraping_repo
    app.dependency_overrides[scrape.get_scraper_service] = lambda: scraper_service
    app.dependency_overrides[scrape.get_discovery_service] = lambda: discovery_service

    # Reset global singleton scraper service in route module
    scrape._singleton_scraper_service = scraper_service

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-API-Key": "test_partner"},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    scrape._singleton_scraper_service = None
