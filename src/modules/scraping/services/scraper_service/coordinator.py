# [OMA-W006-T009] Master batch orchestrator and lifecycle coordinator for ScraperService

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from prisma.errors import UniqueViolationError

from src.modules.core.config.settings import Settings, get_settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.webhook.webhook_client import (
    ScrapeCompletePayload,
    WebhookClient,
)
from src.modules.scraping.exceptions import (
    ERR_OPERATION_TIMEOUT,
    OperationTimeoutError,
    RateLimitedCooldownError,
    SourceLockedError,
    SourceNotFoundError,
)
from src.modules.scraping.models import (
    OperationAbortData,
    OperationStatus,
    SourceAbortData,
)
from src.modules.scraping.services.crawler_service import CrawlerService
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
)
from src.modules.scraping.services.language_classifier_service import (
    LanguageClassifierService,
)
from src.modules.scraping.services.pagination_service import PaginationService
from src.modules.scraping.services.template_engine_service import (
    TemplateEngineService,
)
from src.modules.scraping.services.prioritization_service import PrioritizationService

from .catalog_phase import crawl_catalog_phase
from .details_phase import crawl_details_phase
from .lock_manager import STALE_LOCK_THRESHOLD_MINUTES, LockManager
from .token_manager import TokenManager

logger = logging.getLogger(__name__)

DEFAULT_MAX_OPERATION_TIMEOUT_SEC: int = 1200


class ScraperCoordinator:
    """Master batch orchestrator enforcing two-phase execution, locking, and timeouts."""

    def __init__(
        self,
        repository: ScrapingRepository,
        crawler_service: CrawlerService,
        pagination_service: PaginationService,
        prioritization_service: PrioritizationService,
        webhook_client: WebhookClient | None = None,
        language_classifier: LanguageClassifierService | None = None,
        document_ingestion: DocumentIngestionService | None = None,
        template_engine: TemplateEngineService | None = None,
        llm_client: Any = None,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings or get_settings()
        self._crawler_service = crawler_service
        self._pagination_service = pagination_service
        self._prioritization_service = prioritization_service
        self._webhook_client = webhook_client
        self._language_classifier = language_classifier or LanguageClassifierService()
        self._document_ingestion = document_ingestion
        self._template_engine = template_engine or TemplateEngineService(
            repository=repository, settings=self._settings, llm_client=llm_client
        )

    def _filter_eligible_sources(
        self, candidate_sources: list[Any], cutoff: datetime
    ) -> tuple[list[Any], int]:
        eligible: list[Any] = []
        skipped_count = 0
        for src in candidate_sources:
            cfg = getattr(src, "config", None)
            is_locked = bool(cfg and cfg.is_locked)
            if is_locked and cfg and cfg.locked_at:
                locked_at = (
                    cfg.locked_at.replace(tzinfo=UTC)
                    if cfg.locked_at.tzinfo is None
                    else cfg.locked_at
                )
                age_minutes = (cutoff - locked_at).total_seconds() / 60.0
                if age_minutes < STALE_LOCK_THRESHOLD_MINUTES:
                    skipped_count += 1
                    logger.info(
                        "Source %s is locked (locked %.1f min ago); skipping",
                        src.id,
                        age_minutes,
                    )
                    continue
            eligible.append(src)
        return eligible, skipped_count

    async def prepare_scrape_operation(
        self,
        source_ids: list[str] | None = None,
        idempotency_key: str | None = None,
        triggered_by: str = "admin_api",
    ) -> tuple[Any, bool, int, int]:
        if idempotency_key:
            existing_op = await self._repository.get_operation_by_idempotency_key(
                idempotency_key=idempotency_key, within_minutes=15
            )
            if existing_op:
                logger.info("Idempotency hit for key %s", idempotency_key)
                queued_count = len(existing_op.sources_attempted or [])
                return existing_op, True, queued_count, 0

        reclaimed = await LockManager.break_stale_locks(self._repository)
        if reclaimed > 0:
            logger.info("Reclaimed %d stale source locks", reclaimed)

        candidate_sources: list[Any] = []
        if source_ids:
            for sid in source_ids:
                src = await self._repository.get_source(sid)
                if not src:
                    raise SourceNotFoundError(f"Source '{sid}' not found")
                cfg = await self._repository.get_source_config(sid)
                src.config = cfg  # type: ignore[attr-defined]
                candidate_sources.append(src)
        else:
            candidate_sources = await self._repository.get_active_sources()

        if not candidate_sources:
            op, is_idempotent_hit = await self._create_or_get_idempotent_operation(
                idempotency_key=idempotency_key,
                triggered_by=triggered_by,
                sources_attempted=[],
            )
            if is_idempotent_hit:
                return op, True, len(op.sources_attempted or []), 0
            await self._repository.update_operation_status(
                op.id, status="completed", completed=True
            )
            return op, False, 0, 0

        cutoff = datetime.now(UTC)
        eligible_sources, skipped_locked_count = self._filter_eligible_sources(
            candidate_sources, cutoff
        )

        if source_ids and not eligible_sources and skipped_locked_count > 0:
            raise SourceLockedError(
                "All target sources are currently locked by active operations"
            )

        prioritized = self._prioritization_service.prioritize_sources(
            eligible_sources, manual_source_ids=source_ids
        )
        sources_attempted_ids = [str(s.id) for s in prioritized]

        operation, is_idempotent_hit = await self._create_or_get_idempotent_operation(
            idempotency_key=idempotency_key,
            triggered_by=triggered_by,
            sources_attempted=sources_attempted_ids,
        )
        if is_idempotent_hit:
            return operation, True, len(operation.sources_attempted or []), 0

        TokenManager.create_operation_token(operation.id)
        return operation, False, len(sources_attempted_ids), skipped_locked_count

    async def _create_or_get_idempotent_operation(
        self,
        idempotency_key: str | None,
        triggered_by: str,
        sources_attempted: list[str],
    ) -> tuple[Any, bool]:
        """Create the operation, or return the winner of a concurrent retry race."""
        try:
            operation = await self._repository.create_operation(
                idempotency_key=idempotency_key,
                triggered_by=triggered_by,
                sources_attempted=sources_attempted,
            )
            return operation, False
        except UniqueViolationError:
            if idempotency_key is None:
                raise
            existing_op = await self._repository.get_operation_by_idempotency_key(
                idempotency_key=idempotency_key, within_minutes=15
            )
            if existing_op is None:
                raise
            logger.info(
                "Concurrent idempotency retry reused operation %s", existing_op.id
            )
            return existing_op, True

    # [OMA-W008-T002] Enforce 20-min hard ceiling (FR-010)
    async def run_scrape_operation(
        self,
        operation_id: str,
        prioritized_source_ids: list[str],
    ) -> Any:
        timeout_sec = min(
            int(
                self._settings.crawler_max_operation_timeout_sec
                or DEFAULT_MAX_OPERATION_TIMEOUT_SEC
            ),
            1200,
        )
        try:
            async with asyncio.timeout(timeout_sec):
                return await self._execute_batch(
                    operation_id=operation_id,
                    source_ids=prioritized_source_ids,
                )
        except TimeoutError as err:
            logger.warning(
                "Scrape operation %s exceeded timeout of %ss", operation_id, timeout_sec
            )
            await LockManager.release_all_locks(
                self._repository, prioritized_source_ids
            )
            await self._repository.update_operation_progress(
                operation_id,
                status=OperationStatus.TIMED_OUT.value,
                error_summary={
                    "operation_timeout": {
                        "error_code": ERR_OPERATION_TIMEOUT,
                        "error_message": f"Operation breached hard ceiling of {timeout_sec}s",
                    }
                },
                completed=True,
            )
            await self._dispatch_webhook(
                operation_id=operation_id,
                status=OperationStatus.TIMED_OUT.value,
                total_opportunities=0,
                succeeded_sources=[],
                failed_sources=prioritized_source_ids,
            )
            TokenManager.clear_operation_token(operation_id)
            raise OperationTimeoutError(
                f"Scrape operation exceeded maximum allowed timeout ceiling ({timeout_sec}s)",
                timeout_sec=timeout_sec,
            ) from err
        except asyncio.CancelledError:
            logger.info(
                "Operation %s cancelled externally; releasing locks", operation_id
            )
            await LockManager.release_all_locks(
                self._repository, prioritized_source_ids
            )
            await self._repository.update_operation_status(
                operation_id=operation_id,
                status=OperationStatus.ABORTED.value,
                completed=True,
            )
            TokenManager.clear_operation_token(operation_id)
            raise

    # [OMA-W007-T003] Remove redundant source_id parameter to satisfy Sonar S1172
    async def _crawl_source_two_phases(
        self,
        operation_id: str,
        source: Any,
        config_obj: Any,
        operation_token: asyncio.Event | None,
        source_token: asyncio.Event,
    ) -> tuple[int, int]:
        listings = await crawl_catalog_phase(
            crawler_service=self._crawler_service,
            pagination_service=self._pagination_service,
            repository=self._repository,
            operation_id=operation_id,
            source=source,
            config=config_obj,
            operation_token=operation_token,
            source_token=source_token,
            template_engine=self._template_engine,
        )
        if (operation_token and operation_token.is_set()) or source_token.is_set():
            raise asyncio.CancelledError("Crawl halted between phases")

        details = await crawl_details_phase(
            crawler_service=self._crawler_service,
            language_classifier=self._language_classifier,
            document_ingestion=self._document_ingestion,
            repository=self._repository,
            operation_id=operation_id,
            source=source,
            config=config_obj,
            operation_token=operation_token,
            source_token=source_token,
            template_engine=self._template_engine,
        )
        return listings, details

    @staticmethod
    def _resolve_batch_final_status(
        is_op_cancelled: bool,
        sources_aborted: list[str],
        sources_succeeded: list[str],
        sources_failed: list[str],
    ) -> str:
        if is_op_cancelled:
            return OperationStatus.ABORTED.value
        if sources_aborted:
            return OperationStatus.PARTIALLY_ABORTED.value
        if not sources_failed and sources_succeeded:
            return OperationStatus.COMPLETED.value
        if sources_succeeded and sources_failed:
            return OperationStatus.PARTIAL.value
        if sources_failed and not sources_succeeded:
            return OperationStatus.FAILED.value
        return OperationStatus.COMPLETED.value

    async def _execute_batch(self, operation_id: str, source_ids: list[str]) -> Any:
        total_listings = 0
        total_details = 0
        sources_succeeded: list[str] = []
        sources_failed: list[str] = []
        sources_aborted: list[str] = []
        error_summary: dict[str, Any] = {}
        operation_cancelled = False

        operation_token = TokenManager.get_operation_token(operation_id)

        for source_id in source_ids:
            if operation_token and operation_token.is_set():
                operation_cancelled = True
                break

            acquired = await LockManager.acquire_lock(self._repository, source_id)
            if not acquired:
                error_summary[source_id] = {
                    "error_code": "ERR_SOURCE_LOCKED",
                    "error_message": "Source locked by concurrent process",
                }
                sources_failed.append(source_id)
                continue

            # [OMA-W008-T002] Wrap try/finally immediately after acquire_lock; release lock in finally:
            source_token = TokenManager.create_source_token(source_id)
            try:
                source_obj = await self._repository.get_source(source_id)
                config_obj = await self._repository.get_source_config(source_id)

                if not source_obj:
                    continue

                # [OMA-W007-T003] Updated call site with source=source_obj
                listings, details = await self._crawl_source_two_phases(
                    operation_id=operation_id,
                    source=source_obj,
                    config_obj=config_obj,
                    operation_token=operation_token,
                    source_token=source_token,
                )
                total_listings += listings
                total_details += details
                await self._repository.record_source_success(source_id)
                sources_succeeded.append(source_id)
            except RateLimitedCooldownError as rle:
                await self._repository.record_source_failure(
                    source_id, cool_down_seconds=rle.cool_down_seconds
                )
                sources_failed.append(source_id)
                error_summary[source_id] = {
                    "error_code": rle.code,
                    "error_message": str(rle),
                }
            # [OMA-W007-T002] Selective source cancellation; operation abort is re-raised after batch cleanup (Sonar S7497)
            except asyncio.CancelledError:  # NOSONAR
                if source_token.is_set() and not (
                    operation_token and operation_token.is_set()
                ):
                    logger.info("Source %s crawl aborted selectively", source_id)
                    sources_aborted.append(source_id)
                    error_summary[source_id] = {
                        "error_code": "ABORTED",
                        "error_message": "Halted by user",
                    }
                else:
                    logger.info("Operation %s cancelled during batch", operation_id)
                    error_summary[source_id] = {
                        "error_code": "ABORTED",
                        "error_message": "Operation cancelled",
                    }
                    sources_aborted.append(source_id)
                    operation_cancelled = True
                    break
            except Exception as exc:
                logger.exception("Error crawling source %s: %s", source_id, exc)
                await self._repository.record_source_failure(source_id)
                sources_failed.append(source_id)
                err_code = getattr(exc, "code", "ERR_EXTRACTION_FAILED")
                error_summary[source_id] = {
                    "error_code": err_code,
                    "error_message": str(exc),
                }
            finally:
                await LockManager.release_lock(self._repository, source_id)
                TokenManager.clear_source_token(source_id)
                await self._repository.update_operation_counts(
                    operation_id=operation_id,
                    listings_found=total_listings,
                    details_extracted=total_details,
                    files_downloaded=0,
                )

        # [OMA-W008-T002] Persist sources_aborted into error_summary
        if sources_aborted:
            error_summary["sources_aborted"] = sources_aborted

        final_status = self._resolve_batch_final_status(
            operation_cancelled or bool(operation_token and operation_token.is_set()),
            sources_aborted,
            sources_succeeded,
            sources_failed,
        )

        updated_op = await self._repository.update_operation_progress(
            operation_id=operation_id,
            status=final_status,
            listings_found=total_listings,
            details_extracted=total_details,
            files_downloaded=0,
            sources_succeeded=sources_succeeded,
            sources_failed=sources_failed,
            error_summary=error_summary,
            completed=True,
        )

        TokenManager.clear_operation_token(operation_id)
        await self._dispatch_webhook(
            operation_id=operation_id,
            status=final_status,
            total_opportunities=total_details,
            succeeded_sources=sources_succeeded,
            failed_sources=sources_failed,
        )

        if operation_cancelled:
            # Re-raise CancelledError to obey asyncio contract when cancelled externally
            raise asyncio.CancelledError(f"Operation {operation_id} was aborted")

        return updated_op

    # [OMA-W008-T002] Signal cancellation token instead of releasing locks directly
    async def abort_operation(self, operation_id: str) -> OperationAbortData:
        op = await self._repository.get_operation_by_id(operation_id)
        if not op:
            raise KeyError(f"Scrape operation '{operation_id}' not found")

        terminal_statuses = (
            OperationStatus.COMPLETED.value,
            OperationStatus.FAILED.value,
            OperationStatus.ABORTED.value,
            OperationStatus.PARTIALLY_ABORTED.value,
            OperationStatus.TIMED_OUT.value,
        )
        if op.status in terminal_statuses:
            raise ValueError(
                f"Operation '{operation_id}' is not currently running (status: {op.status})"
            )

        TokenManager.cancel_operation(operation_id)
        sources = op.sources_attempted or []

        await self._repository.update_operation_status(
            operation_id=operation_id,
            status=OperationStatus.ABORTED.value,
            completed=True,
        )

        return OperationAbortData(
            operation_id=operation_id,
            status=OperationStatus.ABORTED.value,
            sources_released=len(sources),
        )

    # [OMA-W008-T002] Signal source cancellation token instead of releasing lock directly
    async def abort_source(self, source_id: str) -> SourceAbortData:
        src = await self._repository.get_source(source_id)
        if not src:
            raise SourceNotFoundError(f"Source '{source_id}' not found")

        cfg = await self._repository.get_source_config(source_id)
        if not cfg or not cfg.is_locked:
            raise ValueError(f"Source '{source_id}' is not currently being scraped")

        TokenManager.cancel_source(source_id)

        return SourceAbortData(
            source_id=source_id,
            is_locked=False,
            status="aborted",
            message="Source crawl halted successfully. Lock released.",
        )

    async def _dispatch_webhook(
        self,
        operation_id: str,
        status: str,
        total_opportunities: int,
        succeeded_sources: list[str],
        failed_sources: list[str],
    ) -> None:
        if not self._webhook_client:
            return
        payload = ScrapeCompletePayload(
            batch_id=operation_id,
            total_opportunities=total_opportunities,
            succeeded_sources=succeeded_sources,
            failed_sources=failed_sources,
            completed_at=datetime.now(UTC),
        )
        try:
            await self._webhook_client.notify_scrape_complete(payload)
        except Exception as e:
            logger.warning(
                "Failed to dispatch webhook for operation %s: %s", operation_id, e
            )

    async def get_operations_log(
        self,
        skip: int = 0,
        limit: int = 20,
        status: str | None = None,
        offset: int | None = None,
    ) -> tuple[list[Any], int]:
        effective_offset = offset if offset is not None else skip
        total_count = await self._repository.count_operations(status=status)
        records = await self._repository.list_operations(
            status=status,
            limit=limit,
            offset=effective_offset,
        )
        return records, total_count

    async def get_latest_operation(self) -> Any | None:
        return await self._repository.get_latest_operation()

    async def get_operation_by_id(self, operation_id: str) -> Any | None:
        return await self._repository.get_operation_by_id(operation_id)

    async def get_dead_letter_records(
        self,
        entity_type: str = "listings",
        skip: int = 0,
        limit: int = 50,
        offset: int | None = None,
    ) -> tuple[list[Any], int]:
        effective_offset = offset if offset is not None else skip
        return await self._repository.fetch_dead_letter_queue(
            entity_type=entity_type,
            limit=limit,
            offset=effective_offset,
        )
