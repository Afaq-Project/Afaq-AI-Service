# [OMA-W005-T016] [OMA-W005-T017] [OMA-W005-T021] [OMA-W006-T002] [OMA-W008-T007] [OMA-W008-T008] Integration tests for batch scrape orchestration, lifecycle, locking, and abort control

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.modules.core.config.settings import Settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.webhook.webhook_client import WebhookClient
from src.modules.scraping.exceptions import OperationTimeoutError
from src.modules.scraping.models import OperationsLogResponse, OperationStatus
from src.modules.scraping.services.crawler_service import CrawlerService, CrawlResult
from src.modules.scraping.services.pagination_service import PaginationService
from src.modules.scraping.services.prioritization_service import (
    PrioritizationService,
)
from src.modules.scraping.services.scraper_service import ScraperService
from src.modules.scraping.services.scraper_service.token_manager import TokenManager


# [OMA-W005-T016] TEST-01: Full two-phase batch crawl (Phase 1 Catalog -> Phase 2 Details)
@pytest.mark.asyncio
async def test_two_phase_batch_crawl_e2e(
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
    mock_crawler: CrawlerService,
) -> None:
    """Verifies sequential two-phase batch crawl: Level 1 catalog saved to raw_listings,

    followed by Level 2 details extraction into raw_grant_details, and source lock release.
    """
    catalog_url = "https://scholarships.example.edu/catalog"
    source = await scraping_repo.create_source(catalog_url, name="Scholarships Catalog")
    await scraping_repo.upsert_source_config(
        source.id,
        {
            "domain": "scholarships.example.edu",
            "site_name": "Scholarships Platform",
            "max_pages_per_run": 1,
            "pagination_type": "none",
            "rate_limit_delay_sec": 0.0,
            "incremental_cutoff_enabled": False,
        },
    )

    catalog_html = """
    <html>
      <body>
        <div class="container">
          <article class="card">
            <a href="https://scholarships.example.edu/detail/grant-1">
              <h3>Merit Scholarship 2026</h3>
            </a>
            <p>Full funding for undergraduate engineering students.</p>
          </article>
          <article class="card">
            <a href="https://scholarships.example.edu/detail/grant-2">
              <h3>Research Fellowship 2026</h3>
            </a>
            <p>Postgraduate fellowship program in computer science.</p>
          </article>
        </div>
      </body>
    </html>
    """

    detail_1_html = """
    <html>
      <head><title>Merit Scholarship 2026</title></head>
      <body>
        <h1>Merit Scholarship 2026</h1>
        <article class="entry-content">
          Comprehensive scholarship providing 100% tuition coverage.
          <a href="https://scholarships.example.edu/apply-now" class="apply-btn">Apply Now</a>
        </article>
      </body>
    </html>
    """

    detail_2_html = """
    <html>
      <head><title>Research Fellowship 2026</title></head>
      <body>
        <h1>Research Fellowship 2026</h1>
        <article class="entry-content">
          Annual research grant supporting doctoral candidates.
          <a href="https://scholarships.example.edu/register" class="apply-btn">Register Application</a>
        </article>
      </body>
    </html>
    """

    async def mock_crawl(url: str, **kwargs: object) -> CrawlResult:
        if url == catalog_url:
            return CrawlResult(
                url=url, canonical_url=url, html=catalog_html, status_code=200
            )
        if "grant-1" in url:
            return CrawlResult(
                url=url, canonical_url=url, html=detail_1_html, status_code=200
            )
        if "grant-2" in url:
            return CrawlResult(
                url=url, canonical_url=url, html=detail_2_html, status_code=200
            )
        return CrawlResult(
            url=url, canonical_url=url, html="<html></html>", status_code=200
        )

    mock_crawler.crawl_page = AsyncMock(side_effect=mock_crawl)

    (
        operation,
        is_hit,
        queued_count,
        skipped_count,
    ) = await scraper_service.prepare_scrape_operation(source_ids=[source.id])
    assert is_hit is False
    assert queued_count == 1
    assert skipped_count == 0

    final_op = await scraper_service.run_scrape_operation(
        operation_id=operation.id,
        prioritized_source_ids=[source.id],
    )

    assert final_op.status == OperationStatus.COMPLETED.value
    assert final_op.total_listings_found == 2
    assert final_op.total_details_extracted == 2

    listings = await scraping_repo.get_listings_by_operation(operation.id)
    assert len(listings) == 2
    for lst in listings:
        assert lst.status == "details_extracted"

    details = await scraping_repo.get_grant_details_by_operation(operation.id)
    assert len(details) == 2
    urls = [d.source_url for d in details]
    assert "https://scholarships.example.edu/detail/grant-1" in urls
    assert "https://scholarships.example.edu/detail/grant-2" in urls

    cfg = await scraping_repo.get_source_config(source.id)
    assert cfg is not None
    assert cfg.is_locked is False


# [OMA-W005-T016] TEST-11: Idempotency-Key deduplication on POST /api/v1/scrape/run
@pytest.mark.asyncio
async def test_idempotency_key_deduplication(
    client: AsyncClient,
    scraping_repo: ScrapingRepository,
) -> None:
    """Verifies that submitting duplicate Idempotency-Key within 15 min window

    returns the existing operation ID with 200 OK.
    """
    source = await scraping_repo.create_source(
        "https://portal.example.org", name="Idempotent Source"
    )
    await scraping_repo.upsert_source_config(
        source.id,
        {"domain": "portal.example.org", "site_name": "Idempotent Portal"},
    )

    idempotency_key = str(uuid.uuid4())
    headers = {"Idempotency-Key": idempotency_key}
    payload = {"source_ids": [source.id]}

    # Initial trigger -> 202 Accepted
    resp1 = await client.post("/api/v1/scrape/run", json=payload, headers=headers)
    assert resp1.status_code == 202
    data1 = resp1.json()
    assert data1["status"] == "accepted"
    operation_id = data1["operation_id"]
    assert operation_id

    # Duplicate trigger with same key -> 200 OK with identical operation_id
    resp2 = await client.post("/api/v1/scrape/run", json=payload, headers=headers)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "accepted"
    assert data2["operation_id"] == operation_id
    assert "already running or completed" in data2["message"]

    # Invalid Idempotency-Key syntax -> 422 Unprocessable Entity
    resp_invalid = await client.post(
        "/api/v1/scrape/run", json=payload, headers={"Idempotency-Key": "not-a-uuid"}
    )
    assert resp_invalid.status_code == 422


# [OMA-W005-T017] TEST-14: Hard timeout ceiling aborts operation and transitions to timed_out
@pytest.mark.asyncio
async def test_operation_hard_timeout_ceiling(
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
) -> None:
    """Verifies that operation-level hard timeout cleanly aborts execution,

    transitions status to 'timed_out', and clears all acquired source locks.
    """
    source = await scraping_repo.create_source(
        "https://slow.example.edu", name="Slow Source"
    )
    await scraping_repo.upsert_source_config(
        source.id,
        {"domain": "slow.example.edu", "site_name": "Slow Portal", "is_locked": False},
    )

    op = await scraping_repo.create_operation(
        triggered_by="admin_api",
        sources_attempted=[source.id],
    )
    TokenManager.create_operation_token(op.id)
    scraper_service._operation_cancellation_tokens[op.id] = asyncio.Event()

    # Simulate TimeoutError during batch execution
    batch_target = getattr(scraper_service, "_coordinator", scraper_service)
    with (
        patch.object(
            batch_target,
            "_execute_batch",
            side_effect=TimeoutError("Operation timed out"),
        ),
        pytest.raises(OperationTimeoutError),
    ):
        await scraper_service.run_scrape_operation(
            operation_id=op.id,
            prioritized_source_ids=[source.id],
        )

    # Verify database state after timeout
    updated_op = await scraping_repo.get_operation_by_id(op.id)
    assert updated_op is not None
    assert updated_op.status == OperationStatus.TIMED_OUT.value
    assert "operation_timeout" in updated_op.error_summary

    cfg = await scraping_repo.get_source_config(source.id)
    assert cfg is not None
    assert cfg.is_locked is False


# [OMA-W005-T017] TEST-15: Lock auto-reclamation for source locked >30 minutes
@pytest.mark.asyncio
async def test_stale_lock_auto_reclamation(
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
    client: AsyncClient,
) -> None:
    """Verifies that source locked >30 min is reclaimed, while active lock <30 min is skipped."""
    now = datetime.now(UTC)

    # Source 1: Stale lock (35 minutes old)
    source_stale = await scraping_repo.create_source(
        "https://stale.example.edu", name="Stale Locked Source"
    )
    await scraping_repo.upsert_source_config(
        source_stale.id,
        {
            "domain": "stale.example.edu",
            "site_name": "Stale Portal",
            "is_locked": True,
            "locked_at": now - timedelta(minutes=35),
        },
    )

    # Source 2: Active lock (5 minutes old)
    source_active = await scraping_repo.create_source(
        "https://active.example.edu", name="Actively Locked Source"
    )
    await scraping_repo.upsert_source_config(
        source_active.id,
        {
            "domain": "active.example.edu",
            "site_name": "Active Portal",
            "is_locked": True,
            "locked_at": now - timedelta(minutes=5),
        },
    )

    # Calling prepare_scrape_operation for the stale source: should break lock and queue
    op, is_hit, queued, skipped = await scraper_service.prepare_scrape_operation(
        source_ids=[source_stale.id]
    )
    assert is_hit is False
    assert queued == 1
    assert skipped == 0

    # Calling prepare_scrape_operation for the active locked source: should skip and report conflict
    resp_conflict = await client.post(
        "/api/v1/scrape/run", json={"source_ids": [source_active.id]}
    )
    assert resp_conflict.status_code == 409
    assert "locked by active operations" in resp_conflict.json()["detail"]


# [OMA-W005-T021] TEST-18: GET /api/v1/scrape/operations log and /operations/latest
@pytest.mark.asyncio
async def test_operations_log_and_latest_endpoint(
    client: AsyncClient,
    scraping_repo: ScrapingRepository,
) -> None:
    """Verifies paginated historical operations query and latest operation resolution."""
    now = datetime.now(UTC)

    # Op 1: Completed run
    op1 = await scraping_repo.create_operation(triggered_by="admin_api")
    await scraping_repo.update_operation_progress(
        op1.id,
        status="completed",
        listings_found=10,
        details_extracted=10,
        completed=True,
    )
    # Set started_at in the past
    await scraping_repo._db.scrapeoperation.update(
        where={"id": op1.id},
        data={"started_at": now - timedelta(hours=2)},
    )

    # Op 2: Active running run
    op2 = await scraping_repo.create_operation(triggered_by="admin_api")
    await scraping_repo._db.scrapeoperation.update(
        where={"id": op2.id},
        data={"started_at": now - timedelta(minutes=10)},
    )

    # 1. Test GET /operations (pagination)
    resp = await client.get("/api/v1/scrape/operations?limit=10&offset=0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["total_count"] == 2
    assert len(body["data"]["operations"]) == 2

    # 2. Test GET /operations with status filter
    resp_filtered = await client.get("/api/v1/scrape/operations?status=completed")
    assert resp_filtered.status_code == 200
    body_filtered = resp_filtered.json()
    assert body_filtered["data"]["total_count"] == 1
    assert body_filtered["data"]["operations"][0]["operation_id"] == op1.id

    # 3. Test GET /operations/latest (should return the currently running operation op2)
    resp_latest = await client.get("/api/v1/scrape/operations/latest")
    assert resp_latest.status_code == 200
    latest_data = resp_latest.json()["data"]
    assert latest_data["operation_id"] == op2.id
    assert latest_data["status"] == "running"
    assert latest_data["is_currently_active"] is True

    # 4. Test GET /operations/{id}
    resp_single = await client.get(f"/api/v1/scrape/operations/{op1.id}")
    assert resp_single.status_code == 200
    assert resp_single.json()["data"]["operation_id"] == op1.id

    # 5. Non-existent operation returns 404
    non_existent = str(uuid.uuid4())
    resp_404 = await client.get(f"/api/v1/scrape/operations/{non_existent}")
    assert resp_404.status_code == 404


# [OMA-W005-T021] [OMA-W008-T007] TEST-19: POST /api/v1/scrape/operations/{id}/abort
@pytest.mark.asyncio
async def test_abort_entire_operation(
    client: AsyncClient,
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
    mock_crawler: CrawlerService,
) -> None:
    """Verifies cooperative cancellation, operation status set to 'aborted', and source lock release."""
    source = await scraping_repo.create_source(
        "https://abort-op.example.org", name="Abort Operation Target"
    )
    await scraping_repo.upsert_source_config(
        source.id,
        {
            "domain": "abort-op.example.org",
            "site_name": "Abort Target",
            "is_locked": False,
        },
    )

    op = await scraping_repo.create_operation(
        triggered_by="admin_api",
        sources_attempted=[source.id],
    )
    TokenManager.create_operation_token(op.id)

    step_started = asyncio.Event()
    step_can_finish = asyncio.Event()

    async def in_flight_crawl(url: str, **kwargs: object) -> CrawlResult:
        step_started.set()
        await step_can_finish.wait()
        return CrawlResult(
            url=url, canonical_url=url, html="<html></html>", status_code=200
        )

    mock_crawler.crawl_page = AsyncMock(side_effect=in_flight_crawl)

    task = asyncio.create_task(
        scraper_service.run_scrape_operation(
            operation_id=op.id,
            prioritized_source_ids=[source.id],
        )
    )
    await step_started.wait()

    # Trigger abort
    resp = await client.post(f"/api/v1/scrape/operations/{op.id}/abort")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["operation_id"] == op.id
    assert body["data"]["status"] == "aborted"
    assert body["data"]["sources_released"] >= 1

    # Verify operation status in DB
    updated_op = await scraping_repo.get_operation_by_id(op.id)
    assert updated_op is not None
    assert updated_op.status == "aborted"

    # Allow in-flight step to complete
    step_can_finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Verify source lock released in DB
    cfg = await scraping_repo.get_source_config(source.id)
    assert cfg is not None
    assert cfg.is_locked is False

    # Aborting already aborted operation returns 400 Bad Request
    resp_repeat = await client.post(f"/api/v1/scrape/operations/{op.id}/abort")
    assert resp_repeat.status_code == 400
    assert "not currently running" in resp_repeat.json()["detail"]

    # Aborting non-existent operation returns 404
    resp_missing = await client.post(f"/api/v1/scrape/operations/{uuid.uuid4()}/abort")
    assert resp_missing.status_code == 404


# [OMA-W005-T021] [OMA-W008-T007] TEST-20: POST /api/v1/scrape/sources/{id}/abort
@pytest.mark.asyncio
async def test_abort_specific_source(
    client: AsyncClient,
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
    mock_crawler: CrawlerService,
) -> None:
    """Verifies selective halting of a single source: aborted source does not release lock before the in-flight step completes."""
    source = await scraping_repo.create_source(
        "https://abort-src.example.org", name="Selective Source Abort"
    )
    await scraping_repo.upsert_source_config(
        source.id,
        {
            "domain": "abort-src.example.org",
            "site_name": "Abort Src",
            "is_locked": False,
        },
    )

    op = await scraping_repo.create_operation(
        triggered_by="admin_api",
        sources_attempted=[source.id],
    )
    TokenManager.create_operation_token(op.id)

    step_started = asyncio.Event()
    step_can_finish = asyncio.Event()

    async def in_flight_crawl(url: str, **kwargs: object) -> CrawlResult:
        step_started.set()
        await step_can_finish.wait()
        return CrawlResult(
            url=url, canonical_url=url, html="<html></html>", status_code=200
        )

    mock_crawler.crawl_page = AsyncMock(side_effect=in_flight_crawl)

    task = asyncio.create_task(
        scraper_service.run_scrape_operation(
            operation_id=op.id,
            prioritized_source_ids=[source.id],
        )
    )
    await step_started.wait()

    # Step is currently in-flight; source lock is held
    cfg_inflight = await scraping_repo.get_source_config(source.id)
    assert cfg_inflight is not None
    assert cfg_inflight.is_locked is True

    # Halt source crawl while in-flight
    resp = await client.post(f"/api/v1/scrape/sources/{source.id}/abort")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "success"
    assert body["data"]["source_id"] == source.id
    assert body["data"]["status"] == "aborted"

    # [OMA-W008-T007] Invariant: Aborted source does NOT release lock before the in-flight step completes!
    cfg_before_finish = await scraping_repo.get_source_config(source.id)
    assert cfg_before_finish is not None
    assert (
        cfg_before_finish.is_locked is True
    ), "Source lock was prematurely released while in-flight step was still running"

    # Now allow in-flight step to finish
    step_can_finish.set()
    await task

    # Invariant: Lock is cleanly released AFTER in-flight step completes
    cfg_after = await scraping_repo.get_source_config(source.id)
    assert cfg_after is not None
    assert cfg_after.is_locked is False

    # Halting an already unlocked source returns 400 Bad Request
    resp_unlocked = await client.post(f"/api/v1/scrape/sources/{source.id}/abort")
    assert resp_unlocked.status_code == 400
    assert "is not currently being scraped" in resp_unlocked.json()["detail"]

    # Halting a non-existent source returns 404
    resp_missing = await client.post(f"/api/v1/scrape/sources/{uuid.uuid4()}/abort")
    assert resp_missing.status_code == 404


# [OMA-W006-T002] TEST-21: Production entrypoint route registration in src.main.app
def test_production_entrypoint_mounts_scraping_routes() -> None:
    """Verifies that src.main.app canonically mounts all required scraping pipeline routes."""
    from src.main import app

    registered_paths = set(app.openapi()["paths"].keys())
    expected_scraping_routes = {
        "/api/v1/scrape/run",
        "/api/v1/scrape/operations",
        "/api/v1/scrape/operations/latest",
        "/api/v1/scrape/operations/{operation_id}",
        "/api/v1/scrape/operations/{operation_id}/abort",
        "/api/v1/scrape/sources/{source_id}/abort",
        "/api/v1/scrape/sources/onboard",
        "/api/v1/scrape/dead-letter",
    }
    for expected_route in expected_scraping_routes:
        assert (
            expected_route in registered_paths
        ), f"Missing canonical route in src.main.app: {expected_route}"


# [OMA-W008-T007] [OMA-W008-T008] TEST-22: Verify that timeout ceiling enforces <= 1200 seconds (FR-010)
@pytest.mark.asyncio
async def test_timeout_ceiling_enforces_le_1200_seconds(
    scraping_repo: ScrapingRepository,
    mock_crawler: CrawlerService,
    mock_pagination_service: PaginationService,
    mock_webhook_client: WebhookClient,
) -> None:
    """Verifies that operation timeout ceiling strictly enforces <= 1200s, capping excessive configurations."""
    # 1. Configured with excessive timeout (e.g. 5000s > 1200s) -> capped at 1200s
    excessive_settings = Settings(
        crawler_max_operation_timeout_sec=5000,
        s3_bucket="test-bucket",
    )
    service_excessive = ScraperService(
        repository=scraping_repo,
        crawler_service=mock_crawler,
        pagination_service=mock_pagination_service,
        prioritization_service=PrioritizationService(),
        webhook_client=mock_webhook_client,
        settings=excessive_settings,
    )

    source = await scraping_repo.create_source(
        "https://timeout-test.example.edu", name="Timeout Target"
    )
    await scraping_repo.upsert_source_config(
        source.id,
        {"domain": "timeout-test.example.edu", "site_name": "Timeout Portal"},
    )
    op = await scraping_repo.create_operation(
        triggered_by="admin_api",
        sources_attempted=[source.id],
    )
    TokenManager.create_operation_token(op.id)

    # Simulate timeout during execution
    batch_target = getattr(service_excessive, "_coordinator", service_excessive)
    with (
        patch.object(
            batch_target,
            "_execute_batch",
            side_effect=TimeoutError("Operation timed out"),
        ),
        pytest.raises(OperationTimeoutError) as exc_info,
    ):
        await service_excessive.run_scrape_operation(
            operation_id=op.id,
            prioritized_source_ids=[source.id],
        )

    # Invariant: timeout_sec is capped to <= 1200 seconds even though settings requested 5000s
    assert exc_info.value.timeout_sec <= 1200
    assert exc_info.value.timeout_sec == 1200

    # 2. Configured with lower timeout (e.g. 300s <= 1200s) -> honors 300s
    lower_settings = Settings(
        crawler_max_operation_timeout_sec=300,
        s3_bucket="test-bucket",
    )
    service_lower = ScraperService(
        repository=scraping_repo,
        crawler_service=mock_crawler,
        pagination_service=mock_pagination_service,
        prioritization_service=PrioritizationService(),
        webhook_client=mock_webhook_client,
        settings=lower_settings,
    )
    op2 = await scraping_repo.create_operation(
        triggered_by="admin_api",
        sources_attempted=[source.id],
    )
    with (
        patch.object(
            getattr(service_lower, "_coordinator", service_lower),
            "_execute_batch",
            side_effect=TimeoutError("Operation timed out"),
        ),
        pytest.raises(OperationTimeoutError) as exc_info2,
    ):
        await service_lower.run_scrape_operation(
            operation_id=op2.id,
            prioritized_source_ids=[source.id],
        )
    assert exc_info2.value.timeout_sec == 300
    assert exc_info2.value.timeout_sec <= 1200


# [OMA-W008-T007] [OMA-W008-T008] TEST-23: Verify that GET /api/v1/scrape/operations response matches OperationsLogResponse
@pytest.mark.asyncio
async def test_get_operations_log_matches_operations_log_response(
    client: AsyncClient,
    scraping_repo: ScrapingRepository,
) -> None:
    """Verifies that GET /api/v1/scrape/operations schema strictly conforms to OperationsLogResponse."""
    now = datetime.now(UTC)

    # Seed 2 distinct operations
    op1 = await scraping_repo.create_operation(
        triggered_by="admin_api", sources_attempted=["src-1"]
    )
    await scraping_repo.update_operation_progress(
        op1.id,
        status="completed",
        listings_found=25,
        details_extracted=24,
        files_downloaded=5,
        completed=True,
    )
    await scraping_repo._db.scrapeoperation.update(
        where={"id": op1.id},
        data={"started_at": now - timedelta(hours=3)},
    )

    op2 = await scraping_repo.create_operation(
        triggered_by="scheduler", sources_attempted=["src-2", "src-3"]
    )
    await scraping_repo.update_operation_progress(
        op2.id,
        status="timed_out",
        listings_found=5,
        details_extracted=2,
        files_downloaded=0,
        completed=True,
    )
    await scraping_repo._db.scrapeoperation.update(
        where={"id": op2.id},
        data={"started_at": now - timedelta(hours=1)},
    )

    # 1. Full operations log fetch
    resp = await client.get("/api/v1/scrape/operations?limit=10&offset=0")
    assert resp.status_code == 200
    json_data = resp.json()

    # Validate strictly against Pydantic OperationsLogResponse model
    log_response = OperationsLogResponse.model_validate(json_data)
    assert log_response.status == "success"
    assert log_response.data.total_count >= 2
    assert log_response.data.limit == 10
    assert log_response.data.offset == 0
    assert len(log_response.data.operations) >= 2

    # Verify structural and type conformance of items
    for item in log_response.data.operations:
        assert isinstance(item.operation_id, str)
        assert len(item.operation_id) > 0
        assert item.status in {
            "pending",
            "running",
            "completed",
            "failed",
            "partial",
            "timed_out",
            "aborted",
            "partially_aborted",
        }
        assert isinstance(item.triggered_by, str)
        assert item.sources_count >= 0
        assert item.total_listings_found >= 0
        assert item.total_details_extracted >= 0
        assert item.total_files_downloaded >= 0
        assert item.started_at is not None

    # 2. Filtered query strictly parses into OperationsLogResponse
    resp_filtered = await client.get("/api/v1/scrape/operations?status=completed")
    assert resp_filtered.status_code == 200
    filtered_response = OperationsLogResponse.model_validate(resp_filtered.json())
    assert filtered_response.status == "success"
    for item in filtered_response.data.operations:
        assert item.status == "completed"

    # 3. Empty result strictly parses into OperationsLogResponse with 0 count
    resp_empty = await client.get(
        "/api/v1/scrape/operations?status=non_existent_status"
    )
    assert resp_empty.status_code == 200
    empty_response = OperationsLogResponse.model_validate(resp_empty.json())
    assert empty_response.status == "success"
    assert empty_response.data.total_count == 0
    assert len(empty_response.data.operations) == 0
