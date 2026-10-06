import asyncio
import logging
from typing import Any

from prisma import Prisma
from src.api.protocols import ScrapeResult
from src.modules.core.config.settings import Settings, get_settings
from src.modules.core.database.prisma_client import get_client
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.core.database.repositories.source_repository import SourceRepository
from src.modules.infrastructure.webhook.webhook_client import (
    ScrapeCompletePayload,
    WebhookClient,
)

from ..adapters.adapter_factory import AdapterFactory
from .cleaning_service import CleaningService
from .deduplication_service import DeduplicationService
from .normalization_service import NormalizationService

logger = logging.getLogger(__name__)


class ScraperService:
    """الخدمة الرئيسية لتنسيق عمليات الجلب والتنظيف والتوحيد والتخزين والإشعار."""

    def __init__(
        self,
        db: Prisma | None = None,
        source_repo: SourceRepository | None = None,
        opportunity_repo: OpportunityRepository | None = None,
        cleaning_service: CleaningService | None = None,
        normalization_service: NormalizationService | None = None,
        deduplication_service: DeduplicationService | None = None,
        webhook_client: WebhookClient | None = None,
        gemini_generator: Any | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._source_repo = source_repo or (SourceRepository(db) if db else None)
        self._opportunity_repo = opportunity_repo or (
            OpportunityRepository(db) if db else None
        )
        self._cleaning_service = cleaning_service or CleaningService()
        self._normalization_service = normalization_service or NormalizationService()
        self._deduplication_service = deduplication_service or DeduplicationService(
            self._opportunity_repo
        )

        from ..templates.template_generator import GeminiTemplateGenerator

        self._gemini_generator = gemini_generator or GeminiTemplateGenerator()

        app_settings = settings or get_settings()
        self._webhook_client = webhook_client or WebhookClient(
            webhook_url=app_settings.main_service_webhook_url,
            secret=app_settings.main_service_webhook_secret,
            timeout=app_settings.webhook_timeout,
        )

    async def run(self, source_ids: list[str], batch_id: str) -> ScrapeResult:
        """ينفذ عملية الجلب لجميع المصادر المحددة ويسجل النتائج ويرسل Webhook."""
        logger.info(
            "Starting scrape run for batch %s with %d source IDs",
            batch_id,
            len(source_ids),
        )

        # Ensure repos are initialized if db is provided or fetched
        if self._source_repo is None:
            db_client = self._db or get_client()
            self._source_repo = SourceRepository(db_client)
            self._opportunity_repo = OpportunityRepository(db_client)
            self._deduplication_service = DeduplicationService(self._opportunity_repo)

        # Reset deduplication cache for the new batch
        self._deduplication_service.reset_batch()

        # Fetch sources from repository
        sources = (
            await self._source_repo.get_by_ids(source_ids)
            if source_ids
            else await self._source_repo.list_all()
        )

        succeeded_sources: list[str] = []
        failed_sources: list[str] = []
        total_opportunities = 0

        for source in sources:
            source_identifier = str(
                getattr(source, "name", None) or getattr(source, "id", str(source))
            )
            try:
                logger.info(
                    "Processing source '%s' (ID: %s)",
                    getattr(source, "name", ""),
                    getattr(source, "id", ""),
                )
                count = await self._process_source(source)
                total_opportunities += count
                succeeded_sources.append(source_identifier)

                # Mark source as scraped
                if hasattr(source, "id") and self._source_repo:
                    await self._source_repo.mark_scraped(source.id)
            except Exception as exc:
                logger.exception(
                    "Failed to process source '%s': %s", source_identifier, exc
                )
                failed_sources.append(source_identifier)

        # Record any missing source IDs that weren't found in DB
        found_ids = {getattr(s, "id", "") for s in sources}
        for sid in source_ids:
            if sid not in found_ids and sid not in failed_sources:
                failed_sources.append(sid)

        logger.info(
            "Scrape run %s completed: %d total opportunities, %d succeeded, %d failed",
            batch_id,
            total_opportunities,
            len(succeeded_sources),
            len(failed_sources),
        )

        # Notify main service via webhook
        payload = ScrapeCompletePayload(
            batch_id=batch_id,
            total_opportunities=total_opportunities,
            succeeded_sources=succeeded_sources,
            failed_sources=failed_sources,
        )
        try:
            await self._webhook_client.notify_scrape_complete(payload)
        except Exception as exc:
            logger.warning(
                "Failed to deliver webhook notification for batch %s: %s", batch_id, exc
            )

        return ScrapeResult(
            batch_id=batch_id,
            total_opportunities=total_opportunities,
            succeeded_sources=succeeded_sources,
            failed_sources=failed_sources,
        )

    async def _process_source(self, source: Any) -> int:
        """يعالج مصدراً واحداً: يجلب، يصفي بالـ is_opportunity، يحلل، ينظف، يوحّد، ويخزن الفرص."""
        from ..adapters.generic_template_adapter import GenericTemplateAdapter
        from ..templates.change_detector import ChangeDetectionStatus, PageFetchResult

        source_name = getattr(source, "name", "wordpress_api")
        source_id = getattr(source, "id", "")
        method = getattr(source, "method", "wordpress_api")
        base_url = getattr(source, "base_url", "")
        template_input = getattr(source, "template", None)
        if not template_input or not isinstance(template_input, (dict, str)):
            raw_cfg = getattr(source, "template_config", None)
            if isinstance(raw_cfg, (dict, str)):
                template_input = raw_cfg
            else:
                src_cfg = getattr(source, "source_config", None)
                if isinstance(src_cfg, dict):
                    template_input = src_cfg.get("template")
                else:
                    template_input = None
        raw_baseline = getattr(source, "baseline_score", None)
        baseline_score = (
            float(raw_baseline) if isinstance(raw_baseline, (int, float)) else None
        )
        pagination_config = getattr(source, "pagination_config", {}) or {}
        if not isinstance(pagination_config, dict):
            pagination_config = {}

        source_config = {
            "base_url": base_url,
            "api_endpoint": getattr(source, "api_endpoint", ""),
            "method": method,
            "pagination_config": pagination_config,
            "field_mapping": getattr(source, "field_mapping", {}) or {},
            "template": template_input,
            "baseline_score": baseline_score,
        }

        # Scenario C: Template Missing Check BEFORE creating adapter
        is_template_source = (
            method in ("generic_template", "template")
            or "template" in source_name.lower()
        )
        if is_template_source and not template_input:
            logger.warning(
                "No active template found for template source '%s'. Fetching HTML to generate candidate template via Gemini...",
                source_name,
            )
            # Fetch listing HTML sample directly
            listing_fetches = []
            if base_url:
                try:
                    import httpx

                    async with httpx.AsyncClient(timeout=30.0) as client:
                        resp = await client.get(base_url)
                        html_text = resp.text
                        listing_fetches.append(
                            PageFetchResult(
                                url=base_url,
                                success=True,
                                status_code=resp.status_code,
                                html=html_text,
                            )
                        )
                except Exception as fetch_exc:
                    logger.warning(
                        "Failed to fetch HTML for candidate generation for %s: %s",
                        source_name,
                        fetch_exc,
                    )

            candidate_result = await self._gemini_generator.generate_candidate(
                detail_fetches=[],
                listing_fetches=listing_fetches,
                current_template=None,
                source_name=source_name,
                base_url=base_url,
            )
            logger.info(
                "Candidate template generated for source '%s' with status: %s (Valid: %s)",
                source_name,
                candidate_result.status.value,
                candidate_result.valid,
            )
            return 0  # No extraction without active template

        # Get adapter for existing template / specialized adapter
        adapter = AdapterFactory.get_adapter(source_name, source_config=source_config)
        cleaned_count = 0

        try:
            limit = (
                pagination_config.get("limit", 50)
                if isinstance(pagination_config, dict)
                else 50
            )

            # Scenario A & B: Listing Content Change Check for GenericTemplateAdapter
            if isinstance(adapter, GenericTemplateAdapter):
                previous_hash = pagination_config.get("last_listing_hash")
                raw_items = await adapter.fetch_with_details(
                    limit=limit, previous_hash=previous_hash
                )

                if previous_hash and not adapter.has_listing_content_changed(
                    previous_hash
                ):
                    logger.info(
                        "Listing content unchanged for template source '%s' (hash: %s). Skipping detail page fetching and extraction.",
                        source_name,
                        previous_hash,
                    )
                    return 0  # Scenario A: Skip detail fetching & extraction

                # Content changed -> Scenario B: Update listing hash in DB
                if self._source_repo and adapter.last_listing_hash and source_id:
                    try:
                        res = self._source_repo.update_last_listing_hash(
                            source_id, adapter.last_listing_hash
                        )
                        if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                            await res
                    except Exception as hash_exc:
                        logger.warning(
                            "Failed to persist listing hash for %s: %s",
                            source_name,
                            hash_exc,
                        )
            else:
                raw_items = await adapter.fetch_with_details(limit=limit)

            # Scenario D: Template Change & Degradation Detection
            if isinstance(adapter, GenericTemplateAdapter):
                detection_result = adapter.run_change_detection(
                    baseline_score=baseline_score
                )
                status = detection_result.status

                if status == ChangeDetectionStatus.VALID:
                    logger.info(
                        "Template change detection passed for source '%s' (Quality score: %.2f)",
                        source_name,
                        detection_result.quality_score,
                    )
                elif status in (
                    ChangeDetectionStatus.STRUCTURE_CHANGED,
                    ChangeDetectionStatus.EXTRACTION_DEGRADED,
                ):
                    logger.warning(
                        "Template structure change/degradation detected for source '%s' (Status: %s). Invoking Gemini for Candidate Template...",
                        source_name,
                        status.value,
                    )
                    candidate_result = await self._gemini_generator.generate_candidate(
                        detail_fetches=adapter.last_detail_fetches,
                        listing_fetches=adapter.last_listing_fetches,
                        current_template=adapter.template,
                        source_name=source_name,
                        base_url=adapter.base_url,
                        baseline_score=baseline_score,
                        failed_fields=detection_result.errors,
                    )
                    logger.info(
                        "Candidate template generated for source '%s' with status: %s (Quality Score: %.2f)",
                        source_name,
                        candidate_result.status.value,
                        candidate_result.quality_score,
                    )
                else:
                    logger.info(
                        "Template evaluation status for '%s': %s",
                        source_name,
                        status.value,
                    )

            # 3. Process each raw item with opportunity filtering
            for item in raw_items:
                # Filter out non-opportunity articles (guides, ranking articles, etc.)
                if not adapter.is_opportunity(item):
                    logger.debug(
                        "Filtered out non-opportunity item from %s", source_name
                    )
                    continue

                # Parse item
                parsed = adapter.parse(item)
                source_url = parsed.get("source_url") or item.get("link") or ""

                # Store raw opportunity
                raw_record = None
                if self._opportunity_repo:
                    raw_record = await self._opportunity_repo.create_raw(
                        source_id=source_id,
                        raw_payload=item,
                        status="processing",
                        source_url=source_url,
                    )

                raw_id = (
                    getattr(raw_record, "id", None) if raw_record else "mock-raw-id"
                )

                try:
                    # Clean
                    cleaned = self._cleaning_service.clean(parsed)
                    if not cleaned.get("title"):
                        raise ValueError(
                            "Opportunity title is required and cannot be empty"
                        )

                    # Normalize
                    normalized = self._normalization_service.normalize(cleaned)

                    # Deduplication check
                    content_hash = self._deduplication_service.generate_content_hash(
                        normalized
                    )
                    is_dup = await self._deduplication_service.is_duplicate(
                        normalized, content_hash
                    )

                    if is_dup:
                        logger.debug(
                            "Duplicate opportunity detected: '%s'",
                            normalized.get("title"),
                        )
                        if (
                            self._opportunity_repo
                            and raw_id
                            and raw_id != "mock-raw-id"
                        ):
                            await self._opportunity_repo.mark_raw_status(
                                raw_id, status="duplicate"
                            )
                        continue

                    # Register in deduplication service
                    self._deduplication_service.mark_as_seen(
                        content_hash, normalized.get("source_url")
                    )

                    # Store cleaned opportunity
                    if self._opportunity_repo and raw_id and raw_id != "mock-raw-id":
                        try:
                            await self._opportunity_repo.create_cleaned(
                                {
                                    "raw_opportunity_id": raw_id,
                                    "source_id": source_id,
                                    "title": normalized["title"],
                                    "organization": normalized.get("organization"),
                                    "opportunity_type": normalized.get(
                                        "opportunity_type"
                                    ),
                                    "description": normalized.get("description"),
                                    "eligibility": normalized.get("eligibility"),
                                    "location": normalized.get("location"),
                                    "is_remote": normalized.get("is_remote", False),
                                    "funding_type": normalized.get("funding_type"),
                                    "deadline": normalized.get("deadline"),
                                    "application_url": normalized.get(
                                        "application_url"
                                    ),
                                    "source_url": normalized.get("source_url")
                                    or source_url,
                                    "country": normalized.get("country"),
                                    "study_levels": normalized.get("study_levels")
                                    or [],
                                    "fields_of_study": normalized.get("fields_of_study")
                                    or [],
                                    "status": "cleaned",
                                    "content_hash": content_hash,
                                }
                            )
                            await self._opportunity_repo.mark_raw_status(
                                raw_id, status="cleaned"
                            )
                            cleaned_count += 1
                        except Exception as create_exc:
                            # Handle rare race condition / unique constraint collision on content_hash
                            exc_str = str(create_exc).lower()
                            if (
                                "unique" in exc_str
                                or "p2002" in exc_str
                                or "content_hash" in exc_str
                            ):
                                logger.warning(
                                    "Unique constraint collision on content_hash '%s': %s",
                                    content_hash,
                                    create_exc,
                                )
                                await self._opportunity_repo.mark_raw_status(
                                    raw_id, status="duplicate"
                                )
                            else:
                                raise create_exc
                    else:
                        cleaned_count += 1
                except Exception as item_exc:
                    logger.warning(
                        "Error processing raw item '%s': %s", source_url, item_exc
                    )
                    if self._opportunity_repo and raw_id and raw_id != "mock-raw-id":
                        await self._opportunity_repo.mark_raw_status(
                            raw_id, status="failed", error_message=str(item_exc)
                        )
        finally:
            # Ensure adapter HTTP client connections are cleanly closed
            await adapter.close()

        return cleaned_count
