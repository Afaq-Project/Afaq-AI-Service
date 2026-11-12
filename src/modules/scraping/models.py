# [OMA-W005-T004] Pydantic domain models for scraping and extraction pipeline

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# [OMA-W005-T004] Batch operation execution lifecycle status
class OperationStatus(StrEnum):
    """Lifecycle statuses for batch scrape operations."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    PARTIALLY_ABORTED = "partially_aborted"
    TIMED_OUT = "timed_out"
    ABORTED = "aborted"


# [OMA-W005-T004] Target source crawling status
class SourceStatus(StrEnum):
    """Lifecycle and operational statuses for target scraping sources."""

    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ABORTED = "aborted"
    COOLDOWN = "cooldown"


# [OMA-W005-T004] Discovered listing and detail extraction processing status
class ExtractionStatus(StrEnum):
    """Status states for raw listings and grant details."""

    PENDING_DETAIL_CRAWL = "pending_detail_crawl"
    DETAILS_EXTRACTED = "details_extracted"
    PENDING = "pending"
    PROCESSING = "processing"
    CLEANED = "cleaned"
    FAILED = "failed"
    FAILED_PERMANENTLY = "failed_permanently"


# [OMA-W005-T004] Scraping template hierarchy page level
class PageType(StrEnum):
    """Target page hierarchy type."""

    CATALOG = "catalog"
    DETAIL = "detail"


# [OMA-W005-T004] Catalog pagination mechanism type
class PaginationType(StrEnum):
    """Pagination mechanics supported by catalog discovery engine."""

    NEXT_BUTTON = "next_button"
    URL_PARAM = "url_param"
    INFINITE_SCROLL = "infinite_scroll"
    NONE = "none"


# [OMA-W005-T004] Catalog opportunity ordering strategy
class OrderingStrategy(StrEnum):
    """Catalog publication ordering strategy for incremental cutoff decisions."""

    CHRONOLOGICAL_DESCENDING = "chronological_descending"
    DEADLINE_ASCENDING = "deadline_ascending"
    FEATURED_SPONSORED_MIXED = "featured_sponsored_mixed"
    UNKNOWN = "unknown"


# [OMA-W005-T004] Domain result model for Level 1 or Level 2 extraction pass
class ExtractionResult(BaseModel):
    """Domain model capturing raw extraction outcome from a single page."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    url: str
    # [OMA-W007-T006] Level 1 indicates Catalog extraction, level 2 indicates Detail extraction
    level: (
        int  # Level 1 indicates Catalog extraction, level 2 indicates Detail extraction
    )
    success: bool
    status: str = "success"
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retry_count: int = 0
    discovered_urls: list[str] = Field(default_factory=list)
    template_id: str | None = None
    template_version: int | None = None
    language: str | None = None
    language_confidence: float = 0.0
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# [OMA-W005-T004] Request payload to trigger scraping operation
class ScrapeRunRequest(BaseModel):
    """Request payload for triggering asynchronous scraping job."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    source_ids: list[str] | None = None


# [OMA-W005-T004] Response acknowledgment for accepted scraping trigger
class ScrapeRunAcceptedResponse(BaseModel):
    """Non-blocking 202 Accepted response envelope with operation tracking ID."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "accepted"
    operation_id: str
    sources_queued: int = 0
    sources_skipped_locked: int = 0
    message: str = (
        "Scrape operation started in background; a webhook notification will be dispatched on completion."
    )


# [OMA-W005-T004] Full telemetry and status response model for scrape operation
class ScrapeOperationResponse(BaseModel):
    """Operational progress, counts, and error summaries for a scraping operation."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    operation_id: str
    status: str
    is_currently_active: bool | None = None
    triggered_by: str = "admin_api"
    sources_attempted: list[str] = Field(default_factory=list)
    sources_succeeded: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
    total_listings_found: int = 0
    total_details_extracted: int = 0
    total_files_downloaded: int = 0
    error_summary: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime
    completed_at: datetime | None = None


# [OMA-W006-T010] Response envelope for single scrape operation status
class ScrapeOperationEnvelope(BaseModel):
    """Response envelope for single scrape operation details."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "success"
    data: ScrapeOperationResponse | None = None
    message: str = "Operation status retrieved successfully."


# [OMA-W005-T004] Request payload for Stage 0 source onboarding
class SourceOnboardRequest(BaseModel):
    """Request payload to onboard and analyze a target portal entry URL."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    url: str
    name: str | None = None


# [OMA-W005-T004] Data payload for onboarded source configuration
class SourceOnboardData(BaseModel):
    """Technical configuration populated during Stage 0 onboarding."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    source_id: str
    domain: str
    site_name: str
    supported_languages: list[str] = Field(default_factory=list)
    pagination_type: str = "next_button"
    pagination_config: dict[str, Any] = Field(default_factory=dict)
    ordering_strategy: str = "chronological_descending"
    rate_limit_delay_sec: float = 1.0
    is_active: bool = True


# [OMA-W005-T004] Response envelope for Stage 0 source onboarding
class SourceOnboardResponse(BaseModel):
    """Response envelope for Stage 0 source onboarding discovery."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "success"
    data: SourceOnboardData
    message: str = (
        "Source onboarded and technical configuration populated successfully."
    )


# [OMA-W005-T004] Operations log list item representation
class OperationsLogItem(BaseModel):
    """Summary item in historical operations log."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    operation_id: str
    status: str
    triggered_by: str
    sources_count: int
    total_listings_found: int
    total_details_extracted: int
    total_files_downloaded: int
    started_at: datetime
    completed_at: datetime | None = None


# [OMA-W005-T004] Operations log paginated payload data
class OperationsLogData(BaseModel):
    """Paginated operations list container."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    total_count: int
    limit: int
    offset: int
    operations: list[OperationsLogItem] = Field(default_factory=list)


# [OMA-W005-T004] Response envelope for historical operations log
class OperationsLogResponse(BaseModel):
    """Response envelope for paginated historical operations log."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "success"
    data: OperationsLogData
    message: str = "Operations log retrieved successfully."


# [OMA-W005-T004] Data container for source-level crawl halt
class SourceAbortData(BaseModel):
    """Confirmation payload for selective source abort."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    source_id: str
    is_locked: bool = False
    status: str = "aborted"
    message: str = "Source crawl halted successfully. Lock released."


# [OMA-W005-T004] Response envelope for selective source abort
class SourceAbortResponse(BaseModel):
    """Response envelope for selective source abort."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "success"
    data: SourceAbortData
    message: str = "Source halted."


# [OMA-W005-T004] Data container for operation abort
class OperationAbortData(BaseModel):
    """Confirmation payload for graceful batch operation abort."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    operation_id: str
    status: str = "aborted"
    aborted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sources_released: int = 0
    message: str = (
        "Scrape operation aborted successfully. All acquired source locks have been released."
    )


# [OMA-W005-T004] Response envelope for operation abort
class OperationAbortResponse(BaseModel):
    """Response envelope for graceful batch operation abort."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "success"
    data: OperationAbortData
    message: str = "Operation aborted."


# [OMA-W005-T004] Item representation in Dead Letter Queue
class DeadLetterItem(BaseModel):
    """Dead letter queue record representation."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    source_id: str
    discovered_url: str | None = None
    source_url: str | None = None
    card_title_preview: str | None = None
    retry_count: int
    max_retries: int
    status: str
    extraction_errors: dict[str, Any] | None = None
    scraped_at: datetime


# [OMA-W005-T004] Dead Letter Queue paginated payload data
class DeadLetterData(BaseModel):
    """Paginated dead letter queue items container."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    total_count: int
    entity_type: str = "listings"
    items: list[DeadLetterItem] = Field(default_factory=list)


# [OMA-W005-T004] Response envelope for Dead Letter Queue audit endpoint
class DeadLetterResponse(BaseModel):
    """Response envelope for dead letter queue audit."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    status: str = "success"
    data: DeadLetterData
    message: str = "Dead letter items retrieved successfully."


# [OMA-W005-T004] Webhook payload dispatched on scrape operation completion
class ScrapeWebhookPayload(BaseModel):
    """Telemetry payload embedded in completion webhook."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    operation_id: str
    status: str
    triggered_by: str
    total_listings_found: int
    total_details_extracted: int
    total_files_downloaded: int
    sources_succeeded: list[str] = Field(default_factory=list)
    sources_failed: list[str] = Field(default_factory=list)
    error_summary: dict[str, Any] = Field(default_factory=dict)


# [OMA-W005-T004] Webhook event envelope
class ScrapeWebhookEvent(BaseModel):
    """Standardized webhook event envelope dispatched upon operation termination."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    event: str = "scrape.operation.completed"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: ScrapeWebhookPayload
