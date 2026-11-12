# [OMA-W005-T002] Scraping services package initialization
# [OMA-W005-T011] [OMA-W005-T012] [OMA-W005-T013] Export core scraping services
"""Scraping and extraction pipeline services package."""

from src.modules.scraping.services.crawler_service import CrawlerService, CrawlResult

# [OMA-W005-T024] [OMA-W005-T025] Export Stage 0 discovery service
from src.modules.scraping.services.discovery_service import DiscoveryService

# [OMA-W005-T037] Export document ingestion service and upload result model
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
    DocumentUploadResult,
)

# [OMA-W005-T036] Export language classifier service and models
from src.modules.scraping.services.language_classifier_service import (
    LanguageClassifierService,
    OpportunityLanguageResult,
)
from src.modules.scraping.services.pagination_service import (
    PaginationService,
    PaginationState,
    PaginationStepResult,
)
from src.modules.scraping.services.prioritization_service import (
    PrioritizationService,
)
from src.modules.scraping.services.scraper_service import ScraperService

# [OMA-W005-T030] [OMA-W005-T031] Export template engine service and field metrics model
from src.modules.scraping.services.template_engine_service import (
    FieldMetrics,
    TemplateEngineService,
)

__all__ = [
    "CrawlerService",
    "CrawlResult",
    "DiscoveryService",
    "DocumentIngestionService",
    "DocumentUploadResult",
    "FieldMetrics",
    "LanguageClassifierService",
    "OpportunityLanguageResult",
    "PaginationService",
    "PaginationState",
    "PaginationStepResult",
    "PrioritizationService",
    "ScraperService",
    "TemplateEngineService",
]
