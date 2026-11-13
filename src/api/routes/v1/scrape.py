# [OMA-W005-T020] FastAPI route controller for scraping and extraction pipeline operations

import logging
import uuid
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import JSONResponse

from src.api.dependencies import require_api_key

# [OMA-W004-FIX-CYCLE-2] Import service protocols and dependency providers from api.protocols
from src.api.protocols import (
    DiscoveryServiceProtocol,
    ScraperServiceProtocol,
    get_discovery_service,
    get_scraper_service,
)
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.scraping.exceptions import (
    AccessChallengeBlockedError,
    NotOpportunityPortalError,
    SourceLockedError,
    SourceNotFoundError,
)
from src.modules.scraping.models import (
    DeadLetterData,
    DeadLetterItem,
    DeadLetterResponse,
    OperationAbortResponse,
    OperationsLogData,
    OperationsLogItem,
    OperationsLogResponse,
    ScrapeOperationEnvelope,
    ScrapeOperationResponse,
    ScrapeRunAcceptedResponse,
    ScrapeRunRequest,
    SourceAbortResponse,
    SourceOnboardRequest,
    SourceOnboardResponse,
)
from src.modules.security.exceptions import (
    SecurityValidationError,
    SSRFAttemptBlockedError,
)

logger = logging.getLogger(__name__)

# [OMA-W005-T020] Router instance with prefix /api/v1/scrape
router = APIRouter(prefix="/api/v1/scrape", tags=["scrape"])


# [OMA-W005-T020] Legacy dependency provider stub preserved for test harness compatibility
def get_scraping_repository() -> Any:
    """Dependency injecting ScrapingRepository stub to prevent API layer coupling."""
    return None


# [OMA-W005-T020] Helper to validate UUID syntax and raise HTTP 422 if invalid
# [OMA-W006-T010] Use HTTP_422_UNPROCESSABLE_CONTENT
def _validate_uuid(
    val: str, location: str, field_name: str, index: int | None = None
) -> None:
    try:
        uuid.UUID(val)
    except (ValueError, AttributeError):
        loc = [location, field_name]
        if index is not None:
            loc.append(index)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=[{"loc": loc, "msg": "value is not a valid uuid"}],
        ) from None


# [OMA-W005-T020] Endpoint: Trigger scraping operation asynchronously
@router.post(
    "/run",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        202: {
            "description": "Scrape operation started in background",
            "model": ScrapeRunAcceptedResponse,
        },
        200: {
            "description": "Idempotency hit - operation already running or completed",
            "model": ScrapeRunAcceptedResponse,
        },
        401: {"description": "Invalid or missing API key"},
        409: {
            "description": "All target sources are currently locked by active operations"
        },
        422: {"description": "Malformed UUID or JSON payload syntax"},
    },
)
async def trigger_scrape_run(
    payload: ScrapeRunRequest,
    background_tasks: BackgroundTasks,
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    """Triggers an asynchronous scraping job across active or requested sources."""
    # Validate idempotency key syntax if provided
    if idempotency_key is not None:
        _validate_uuid(idempotency_key, "header", "Idempotency-Key")

    # Validate source_ids syntax if provided
    if payload.source_ids:
        for idx, sid in enumerate(payload.source_ids):
            _validate_uuid(sid, "body", "source_ids", idx)

    try:
        (
            operation,
            is_idempotent_hit,
            sources_queued,
            sources_skipped_locked,
        ) = await scraper_service.prepare_scrape_operation(
            source_ids=payload.source_ids,
            idempotency_key=idempotency_key,
            triggered_by="admin_api",
        )
    except SourceLockedError as exc:
        logger.warning("All candidate sources are locked: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="All target sources are currently locked by active operations",
        ) from exc
    except SourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if is_idempotent_hit:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "accepted",
                "operation_id": operation.id,
                "sources_queued": sources_queued,
                "sources_skipped_locked": 0,
                "message": "Operation already running or completed for this idempotency key.",
            },
        )

    # Queue execution in background task
    attempted_ids = operation.sources_attempted or []
    background_tasks.add_task(
        scraper_service.run_scrape_operation,
        operation.id,
        attempted_ids,
    )

    response_payload = ScrapeRunAcceptedResponse(
        operation_id=operation.id,
        sources_queued=sources_queued,
        sources_skipped_locked=sources_skipped_locked,
        message="Scrape operation started in background; a webhook notification will be dispatched on completion.",
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content=response_payload.model_dump(),
    )


# [OMA-W005-T020] Endpoint: Retrieve historical operations log
# [OMA-W008-T006] Explicit response_model
@router.get(
    "/operations",
    status_code=status.HTTP_200_OK,
    response_model=OperationsLogResponse,
    responses={
        200: {
            "description": "Historical operations log retrieved",
            "model": OperationsLogResponse,
        },
        401: {"description": "Invalid or missing API key"},
    },
)
async def list_operations_log(
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OperationsLogResponse:
    """Retrieves a paginated list of historical and active scraping operations."""
    records, total_count = await scraper_service.get_operations_log(
        skip=offset,
        limit=limit,
        status=status_filter,
    )

    operations_list: list[OperationsLogItem] = []
    for op in records:
        attempted = op.sources_attempted or []
        operations_list.append(
            OperationsLogItem(
                operation_id=op.id,
                status=op.status,
                triggered_by=op.triggered_by,
                sources_count=len(attempted),
                total_listings_found=op.total_listings_found,
                total_details_extracted=op.total_details_extracted,
                total_files_downloaded=op.total_files_downloaded,
                started_at=op.started_at,
                completed_at=op.completed_at,
            )
        )

    return OperationsLogResponse(
        status="success",
        data=OperationsLogData(
            total_count=total_count,
            limit=limit,
            offset=offset,
            operations=operations_list,
        ),
        message="Operations log retrieved successfully.",
    )


# [OMA-W005-T020] Endpoint: Get current running or most recent historical operation
# [OMA-W006-T010] Enforce typed response_model=ScrapeOperationEnvelope
@router.get(
    "/operations/latest",
    status_code=status.HTTP_200_OK,
    response_model=ScrapeOperationEnvelope,
    responses={
        200: {
            "description": "Latest operation status retrieved or null if empty",
            "model": ScrapeOperationEnvelope,
        },
        401: {"description": "Invalid or missing API key"},
    },
)
async def get_latest_operation(
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
) -> ScrapeOperationEnvelope:
    """Retrieves active running operation or latest completed operation without ID."""
    op = await scraper_service.get_latest_operation()
    if not op:
        return ScrapeOperationEnvelope(
            status="success",
            data=None,
            message="No scraping operations have been executed yet.",
        )

    op_response = ScrapeOperationResponse(
        operation_id=op.id,
        status=op.status,
        is_currently_active=(op.status == "running"),
        triggered_by=op.triggered_by,
        sources_attempted=op.sources_attempted or [],
        sources_succeeded=op.sources_succeeded or [],
        sources_failed=op.sources_failed or [],
        total_listings_found=op.total_listings_found,
        total_details_extracted=op.total_details_extracted,
        total_files_downloaded=op.total_files_downloaded,
        error_summary=op.error_summary or {},
        started_at=op.started_at,
        completed_at=op.completed_at,
    )
    return ScrapeOperationEnvelope(
        status="success",
        data=op_response,
        message="Latest operation status retrieved successfully.",
    )


# [OMA-W005-T020] Endpoint: Get specific operation details by UUID
# [OMA-W006-T010] Enforce typed response_model=ScrapeOperationEnvelope
@router.get(
    "/operations/{operation_id}",
    status_code=status.HTTP_200_OK,
    response_model=ScrapeOperationEnvelope,
    responses={
        200: {
            "description": "Operation details and telemetry retrieved",
            "model": ScrapeOperationEnvelope,
        },
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Operation not found"},
        422: {"description": "Invalid operation UUID syntax"},
    },
)
async def get_operation_by_id(
    operation_id: str,
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
) -> ScrapeOperationEnvelope:
    """Retrieves operational progress, counts, and error summaries for an operation."""
    _validate_uuid(operation_id, "path", "operation_id")

    op = await scraper_service.get_operation_by_id(operation_id)
    if not op:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scrape operation '{operation_id}' not found",
        )

    op_response = ScrapeOperationResponse(
        operation_id=op.id,
        status=op.status,
        is_currently_active=(op.status == "running"),
        triggered_by=op.triggered_by,
        sources_attempted=op.sources_attempted or [],
        sources_succeeded=op.sources_succeeded or [],
        sources_failed=op.sources_failed or [],
        total_listings_found=op.total_listings_found,
        total_details_extracted=op.total_details_extracted,
        total_files_downloaded=op.total_files_downloaded,
        error_summary=op.error_summary or {},
        started_at=op.started_at,
        completed_at=op.completed_at,
    )
    return ScrapeOperationEnvelope(
        status="success",
        data=op_response,
        message="Operation status retrieved successfully.",
    )


# [OMA-W005-T020] Endpoint: Abort entire in-progress operation
# [OMA-W008-T006] Explicit response_model
@router.post(
    "/operations/{operation_id}/abort",
    status_code=status.HTTP_200_OK,
    response_model=OperationAbortResponse,
    responses={
        200: {
            "description": "Operation aborted successfully and locks released",
            "model": OperationAbortResponse,
        },
        400: {"description": "Operation is not currently running"},
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Operation not found"},
        422: {"description": "Invalid operation UUID syntax"},
    },
)
async def abort_operation(
    operation_id: str,
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
) -> OperationAbortResponse:
    """Gracefully cancels an in-progress scraping operation and releases all locks."""
    _validate_uuid(operation_id, "path", "operation_id")

    try:
        abort_data = await scraper_service.abort_operation(operation_id)
        return OperationAbortResponse(
            status="success",
            data=abort_data,
            message="Operation aborted.",
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Scrape operation '{operation_id}' not found",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# [OMA-W005-T020] Endpoint: Selectively halt a specific target source
# [OMA-W008-T006] Explicit response_model
@router.post(
    "/sources/{source_id}/abort",
    status_code=status.HTTP_200_OK,
    response_model=SourceAbortResponse,
    responses={
        200: {
            "description": "Source crawl halted successfully and lock released",
            "model": SourceAbortResponse,
        },
        400: {"description": "Source is not currently being scraped"},
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Source not found"},
        422: {"description": "Invalid source UUID syntax"},
    },
)
async def abort_source(
    source_id: str,
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
) -> SourceAbortResponse:
    """Selectively halts scraping for a specific source and releases its lock."""
    _validate_uuid(source_id, "path", "source_id")

    try:
        abort_data = await scraper_service.abort_source(source_id)
        return SourceAbortResponse(
            status="success",
            data=abort_data,
            message="Source halted.",
        )
    except SourceNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source '{source_id}' not found",
        ) from None
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# [OMA-W005-T026] Endpoint: Stage 0 Source Onboarding Discovery
@router.post(
    "/sources/onboard",
    status_code=status.HTTP_200_OK,
    response_model=SourceOnboardResponse,
    responses={
        200: {
            "description": "Source onboarded and technical configuration populated successfully",
            "model": SourceOnboardResponse,
        },
        400: {
            "description": "Domain is unreachable, parking domain, or not an opportunity portal"
        },
        401: {"description": "Invalid or missing API key"},
        422: {"description": "URL failed security inspection or bad syntax"},
    },
)
async def onboard_source(
    payload: SourceOnboardRequest,
    api_key_info: Annotated[ApiKeyInfo, Depends(require_api_key)],
    discovery_service: Annotated[
        DiscoveryServiceProtocol, Depends(get_discovery_service)
    ],
) -> SourceOnboardResponse:
    """Triggers autonomous Stage 0 discovery for a target educational portal."""
    try:
        return await discovery_service.onboard_source(
            url=payload.url,
            name=payload.name,
            created_by=api_key_info.name if api_key_info else None,
        )
    # [OMA-W006-T010] Catch explicit domain exceptions with appropriate HTTP status codes per spec
    except NotOpportunityPortalError as exc:
        logger.warning("Portal onboarding rejected relevance gate: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ERR_NOT_OPPORTUNITY_PORTAL: {exc.message}",
        ) from exc
    # [OMA-W006-T010] URL security inspection failures return 422 Unprocessable Entity per spec
    except SSRFAttemptBlockedError as exc:
        logger.warning("SSRF blocked during onboarding: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"ERR_SSRF_ATTEMPT_BLOCKED: {exc.message}",
        ) from exc
    except SecurityValidationError as exc:
        logger.warning("Security validation failed during onboarding: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AccessChallengeBlockedError as exc:
        logger.warning("Access challenge encountered during onboarding: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"ERR_ACCESS_CHALLENGE_BLOCKED: {exc.message}",
        ) from exc


# [OMA-W005-T038] Endpoint: Dead Letter Queue Audit for permanently failed records (FR-024)
@router.get(
    "/dead-letter",
    status_code=status.HTTP_200_OK,
    response_model=DeadLetterResponse,
    responses={
        200: {
            "description": "Dead letter items retrieved successfully",
            "model": DeadLetterResponse,
        },
        401: {"description": "Invalid or missing API key"},
        422: {"description": "Invalid query parameters"},
    },
)
async def get_dead_letter_queue(
    _: Annotated[ApiKeyInfo, Depends(require_api_key)],
    scraper_service: Annotated[ScraperServiceProtocol, Depends(get_scraper_service)],
    entity_type: Annotated[str, Query(pattern="^(listings|details)$")] = "listings",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    page: Annotated[int | None, Query(ge=1)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> DeadLetterResponse:
    """Allows administrators to inspect records that permanently failed after exceeding maximum retry attempts."""
    effective_limit = page_size if page_size is not None else limit
    effective_offset = (page - 1) * effective_limit if page is not None else offset

    items, total_count = await scraper_service.get_dead_letter_records(
        entity_type=entity_type,
        skip=effective_offset,
        limit=effective_limit,
    )

    dead_letter_items: list[DeadLetterItem] = []
    for item in items:
        raw_errors = item.extraction_errors
        if raw_errors is not None and not isinstance(raw_errors, dict):
            try:
                import json

                parsed_errors = json.loads(str(raw_errors))
            except Exception:
                parsed_errors = {"raw": str(raw_errors)}
        else:
            parsed_errors = raw_errors

        dead_letter_items.append(
            DeadLetterItem(
                id=item.id,
                source_id=item.source_id,
                discovered_url=getattr(item, "discovered_url", None),
                source_url=getattr(item, "source_url", None),
                card_title_preview=getattr(item, "card_title_preview", None),
                retry_count=item.retry_count,
                max_retries=item.max_retries,
                status=item.status,
                extraction_errors=parsed_errors,
                scraped_at=item.scraped_at,
            )
        )

    return DeadLetterResponse(
        status="success",
        data=DeadLetterData(
            total_count=total_count,
            entity_type=entity_type,
            items=dead_letter_items,
        ),
        message="Dead letter items retrieved successfully.",
    )
