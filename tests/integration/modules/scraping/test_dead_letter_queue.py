# [OMA-W005-T034] [OMA-W005-T035] [OMA-W005-T039] [OMA-W007-T007] [OMA-W007-T008] Integration tests for Dead Letter Queue, bilingual pairing, S3 cache reuse, and file safety gates

import io
import zipfile
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient

from src.modules.core.config.settings import Settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
)
from src.modules.scraping.services.scraper_service import ScraperService
from src.modules.security.exceptions import (
    ERR_MALICIOUS_FILE_TYPE,
    ERR_SSRF_ATTEMPT_BLOCKED,
    ERR_ZIP_BOMB_DETECTED,
    FileSizeExceededError,
    MaliciousFileTypeError,
    SSRFAttemptBlockedError,
    ZipBombDetectedError,
)
from src.modules.security.services.file_validator_service import (
    FileValidatorService,
)
from src.modules.security.services.link_validator_service import (
    LinkValidatorService,
)


# [OMA-W005-T034] TEST-04: Bilingual pairing linking Arabic and English opportunities under identical opportunity_group_id
@pytest.mark.asyncio
async def test_bilingual_pairing_shared_opportunity_group(
    scraping_repo: ScrapingRepository,
    scraper_service: ScraperService,
) -> None:
    """Verifies that native Arabic and English opportunity extractions link under the

    identical opportunity_group_id UUID in raw_grant_details.
    """
    source = await scraping_repo.create_source(
        "https://bilingual.example.edu", name="Bilingual University Portal"
    )
    op = await scraping_repo.create_operation(
        triggered_by="admin_api", sources_attempted=[source.id]
    )

    ar_url = "https://bilingual.example.edu/ar/postgrad-scholarship"
    en_url = "https://bilingual.example.edu/en/postgrad-scholarship"

    # Step 1: Arabic detail page crawled first
    ar_group_id = await scraper_service._resolve_opportunity_group_id(
        source_id=source.id,
        source_url=ar_url,
        title="منحة الدراسات العليا 2026",
        detected_language="ar",
        alternate_links=[en_url],
    )
    assert ar_group_id
    ar_detail = await scraping_repo.create_grant_detail(
        operation_id=op.id,
        source_id=source.id,
        source_url=ar_url,
        raw_payload={"title": "منحة الدراسات العليا 2026", "body": "تفاصيل المنحة"},
        opportunity_group_id=ar_group_id,
        title_language="ar",
        body_language="ar",
        language_confidence=0.95,
        status="pending",
    )
    assert ar_detail.opportunity_group_id == ar_group_id

    # Step 2: English counterpart crawled with cross-link pointing to Arabic version
    en_group_id = await scraper_service._resolve_opportunity_group_id(
        source_id=source.id,
        source_url=en_url,
        title="Postgraduate Scholarship 2026",
        detected_language="en",
        alternate_links=[ar_url],
    )

    # Invariant: English resolution must discover existing Arabic group ID
    assert en_group_id == ar_group_id

    en_detail = await scraping_repo.create_grant_detail(
        operation_id=op.id,
        source_id=source.id,
        source_url=en_url,
        raw_payload={"title": "Postgraduate Scholarship 2026", "body": "Grant details"},
        opportunity_group_id=en_group_id,
        title_language="en",
        body_language="en",
        language_confidence=0.98,
        status="pending",
    )

    # Invariant: Both records in raw_grant_details share identical group UUID
    assert str(ar_detail.opportunity_group_id) == str(en_detail.opportunity_group_id)

    # Step 3: Test URL pattern derivation fallback (/ar/ <-> /en/) without explicit alternate_links
    url_ar_2 = "https://bilingual.example.edu/ar/fellowship-2026"
    url_en_2 = "https://bilingual.example.edu/en/fellowship-2026"

    group_2_first = await scraper_service._resolve_opportunity_group_id(
        source_id=source.id,
        source_url=url_ar_2,
        title="زمالة بحثية",
        detected_language="ar",
        alternate_links=[],
    )
    await scraping_repo.create_grant_detail(
        operation_id=op.id,
        source_id=source.id,
        source_url=url_ar_2,
        raw_payload={"title": "زمالة"},
        opportunity_group_id=group_2_first,
        title_language="ar",
    )

    group_2_derived = await scraper_service._resolve_opportunity_group_id(
        source_id=source.id,
        source_url=url_en_2,
        title="Research Fellowship",
        detected_language="en",
        alternate_links=[],
    )
    assert group_2_derived == group_2_first


# [OMA-W005-T034] TEST-05: S3 attachment cache reuse on redundant download requests
@pytest.mark.asyncio
async def test_s3_attachment_cache_reuse(
    scraping_repo: ScrapingRepository,
    test_settings: Settings,
) -> None:
    """Verifies that when an attachment URL already exists in raw_grant_details,

    the download stream is skipped and existing S3 metadata is returned with cached=True.
    """
    source = await scraping_repo.create_source(
        "https://portal.example.edu", name="Portal with Attachments"
    )
    op = await scraping_repo.create_operation(
        triggered_by="admin_api", sources_attempted=[source.id]
    )

    attachment_url = "https://portal.example.edu/downloads/application_form_2026.pdf"
    cached_s3_key = "attachments/source_1/e3b0c44298fc1c149afbf4c8996fb924.pdf"
    cached_metadata = {
        "sha256": "e3b0c44298fc1c149afbf4c8996fb924",
        "mime_type": "application/pdf",
        "file_size": 45000,
    }

    # Seed existing record with attachment metadata
    await scraping_repo.create_grant_detail(
        operation_id=op.id,
        source_id=source.id,
        source_url=attachment_url,
        raw_payload={"title": "Scholarship Form"},
        has_attachment=True,
        attachment_s3_key=cached_s3_key,
        attachment_metadata=cached_metadata,
        status="pending",
    )

    mock_http_client = AsyncMock(spec=httpx.AsyncClient)
    ingestion_service = DocumentIngestionService(
        repository=scraping_repo,
        http_client=mock_http_client,
        settings=test_settings,
    )

    result = await ingestion_service.ingest_document(
        attachment_url=attachment_url,
        source_id=source.id,
    )

    # Invariants: Cached result returned, zero network calls executed
    assert result.cached is True
    assert result.s3_key == cached_s3_key
    assert result.sha256 == "e3b0c44298fc1c149afbf4c8996fb924"
    assert result.file_size == 45000
    assert result.mime_type == "application/pdf"
    mock_http_client.stream.assert_not_called()


# [OMA-W005-T035] TEST-16: File safety gates rejecting disguised executables and zip bombs
def test_file_safety_gates_disguised_executables_and_zip_bombs() -> None:
    """Verifies that FileValidatorService strictly rejects disguised Windows/Linux executables

    (MZ / ELF headers), disguised HTML/scripts, and high-ratio zip bombs (>100:1 ratio).
    """
    # 1. Disguised Windows PE executable with .pdf extension
    pe_stream = io.BytesIO(
        b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    )
    with pytest.raises(MaliciousFileTypeError) as exc_pe:
        FileValidatorService.validate_stream(pe_stream, filename="application_form.pdf")
    assert exc_pe.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Windows PE executable" in str(exc_pe.value)

    # 2. Disguised Linux ELF binary with .docx extension
    elf_stream = io.BytesIO(b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00")
    with pytest.raises(MaliciousFileTypeError) as exc_elf:
        FileValidatorService.validate_stream(elf_stream, filename="guidelines.docx")
    assert exc_elf.value.error_code == ERR_MALICIOUS_FILE_TYPE
    assert "Linux ELF binary" in str(exc_elf.value)

    # 3. Disguised HTML / script
    html_stream = io.BytesIO(b"<!doctype html><html><script>steal()</script></html>")
    with pytest.raises(MaliciousFileTypeError) as exc_html:
        FileValidatorService.validate_stream(html_stream, filename="rules.pdf")
    assert exc_html.value.error_code == ERR_MALICIOUS_FILE_TYPE

    # 4. Zip bomb (high compression ratio >100:1)
    zip_bomb_buf = io.BytesIO()
    with zipfile.ZipFile(zip_bomb_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "huge_file.txt", b"0" * (250 * 1024)
        )  # 250 KB compressing to ~300 bytes
    zip_bomb_buf.seek(0)

    with pytest.raises(ZipBombDetectedError) as exc_zip:
        FileValidatorService.validate_stream(zip_bomb_buf, filename="attachments.zip")
    assert exc_zip.value.error_code == ERR_ZIP_BOMB_DETECTED
    assert "exceeds 100:1 cap" in str(exc_zip.value)


# [OMA-W005-T035] TEST-16: 25 MB stream ceiling enforcement
@pytest.mark.asyncio
async def test_file_stream_ceiling_exceeded(test_settings: Settings) -> None:
    """Verifies that exceeding the 25 MB stream ceiling immediately halts download and raises FileSizeExceededError."""
    ingestion_service = DocumentIngestionService(settings=test_settings)

    # Mock response stream that delivers chunks beyond 25 MB ceiling
    chunk_10mb = b"X" * (10 * 1024 * 1024)

    async def mock_aiter_bytes(chunk_size: int = 64 * 1024):
        yield chunk_10mb
        yield chunk_10mb
        yield chunk_10mb  # Total = 30 MB > 25 MB ceiling

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.headers = {}
    mock_response.aiter_bytes = mock_aiter_bytes

    @asynccontextmanager
    async def mock_stream_context(method: str, url: str):
        yield mock_response

    mock_client = MagicMock()
    mock_client.stream = mock_stream_context

    with pytest.raises(FileSizeExceededError) as exc:
        await ingestion_service._stream_download(
            client=mock_client,
            url="https://portal.example.edu/downloads/huge_file.pdf",
        )
    assert "exceeds 25 MB stream ceiling" in str(exc.value)


# [OMA-W007-T007] Circular redirect loop SSRF defense in document stream downloads
@pytest.mark.asyncio
async def test_circular_redirect_ssrf_defense(test_settings: Settings) -> None:
    """Verifies that DocumentIngestionService detects circular redirect loops (A -> A or A -> B -> A)

    and immediately halts download by raising SSRFAttemptBlockedError with ERR_SSRF_ATTEMPT_BLOCKED.
    """
    ingestion_service = DocumentIngestionService(settings=test_settings)

    # 1. Direct self-redirect loop (A -> A)
    def self_redirect_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "https://portal.example.edu/downloads/loop.pdf"},
        )

    transport_self = httpx.MockTransport(self_redirect_handler)
    async with httpx.AsyncClient(transport=transport_self) as client_self:
        with pytest.raises(SSRFAttemptBlockedError) as exc_self:
            await ingestion_service._stream_download(
                client=client_self,
                url="https://portal.example.edu/downloads/loop.pdf",
            )
        assert exc_self.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED
        assert "Circular redirect detected" in str(exc_self.value)

    # 2. Multi-hop circular redirect cycle (A -> B -> A)
    def cycle_redirect_handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/downloads/a.pdf":
            return httpx.Response(
                302,
                headers={"Location": "https://portal.example.edu/downloads/b.pdf"},
            )
        if path == "/downloads/b.pdf":
            return httpx.Response(
                302,
                headers={"Location": "https://portal.example.edu/downloads/a.pdf"},
            )
        return httpx.Response(200)

    transport_cycle = httpx.MockTransport(cycle_redirect_handler)
    with patch.object(
        LinkValidatorService,
        "_resolve_host",
        new_callable=AsyncMock,
        return_value="93.184.216.34",
    ):
        async with httpx.AsyncClient(transport=transport_cycle) as client_cycle:
            with pytest.raises(SSRFAttemptBlockedError) as exc_cycle:
                await ingestion_service._stream_download(
                    client=client_cycle,
                    url="https://portal.example.edu/downloads/a.pdf",
                )
            assert exc_cycle.value.error_code == ERR_SSRF_ATTEMPT_BLOCKED
            assert "Circular redirect detected" in str(exc_cycle.value)
            assert "https://portal.example.edu/downloads/a.pdf" in str(exc_cycle.value)


# [OMA-W005-T039] TEST-17: DLQ exhaustion transitions failed records to failed_permanently
@pytest.mark.asyncio
async def test_dlq_exhaustion_and_audit_endpoint(
    client: AsyncClient,
    scraping_repo: ScrapingRepository,
) -> None:
    """Verifies that records failing 3 extraction attempts transition to failed_permanently

    and are retrievable via GET /api/v1/scrape/dead-letter.
    """
    source = await scraping_repo.create_source(
        "https://dlq.example.edu", name="DLQ Test Portal"
    )
    op = await scraping_repo.create_operation(
        triggered_by="admin_api", sources_attempted=[source.id]
    )

    # 1. Test RawListing retry increment and permanent DLQ transition at attempt 3
    listing = await scraping_repo.create_listing(
        operation_id=op.id,
        source_id=source.id,
        discovered_url="https://dlq.example.edu/expired-grant-1",
        listing_page_url="https://dlq.example.edu/catalog",
        card_title_preview="Expired Grant 1",
    )
    assert listing.retry_count == 0
    assert listing.status == "pending_detail_crawl"

    # Attempt 1
    l1 = await scraping_repo.record_listing_failure(
        listing.id, error_message="Timeout 30s", error_code="ERR_TIMEOUT"
    )
    assert l1 is not None
    assert l1.retry_count == 1
    assert l1.status == "failed"

    # Attempt 2
    l2 = await scraping_repo.record_listing_failure(
        listing.id, error_message="Connection Reset", error_code="ERR_RESET"
    )
    assert l2 is not None
    assert l2.retry_count == 2
    assert l2.status == "failed"

    # Attempt 3 -> Permanent DLQ transition
    l3 = await scraping_repo.record_listing_failure(
        listing.id, error_message="HTTP 404: Not Found", error_code="ERR_404"
    )
    assert l3 is not None
    assert l3.retry_count == 3
    assert l3.status == "failed_permanently"
    errors = l3.extraction_errors or {}
    assert errors.get("last_error") == "HTTP 404: Not Found"
    assert len(errors.get("attempts", [])) == 3

    # 2. Test RawGrantDetail permanent DLQ transition
    detail = await scraping_repo.create_grant_detail(
        operation_id=op.id,
        source_id=source.id,
        source_url="https://dlq.example.edu/broken-detail",
        raw_payload={},
        status="pending",
    )
    await scraping_repo.record_detail_failure(detail.id, error_message="Err 1")
    await scraping_repo.record_detail_failure(detail.id, error_message="Err 2")
    d3 = await scraping_repo.record_detail_failure(
        detail.id, error_message="Corrupted DOM", error_code="ERR_PARSE"
    )
    assert d3 is not None
    assert d3.retry_count == 3
    assert d3.status == "failed_permanently"

    # 3. Test GET /api/v1/scrape/dead-letter?entity_type=listings
    resp_listings = await client.get(
        "/api/v1/scrape/dead-letter?entity_type=listings&limit=10"
    )
    assert resp_listings.status_code == 200
    body_listings = resp_listings.json()
    assert body_listings["status"] == "success"
    data_listings = body_listings["data"]
    assert data_listings["total_count"] >= 1
    assert data_listings["entity_type"] == "listings"
    listing_items = data_listings["items"]
    assert any(
        item["id"] == listing.id and item["status"] == "failed_permanently"
        for item in listing_items
    )

    # 4. Test GET /api/v1/scrape/dead-letter?entity_type=details
    resp_details = await client.get(
        "/api/v1/scrape/dead-letter?entity_type=details&limit=10"
    )
    assert resp_details.status_code == 200
    body_details = resp_details.json()
    assert body_details["status"] == "success"
    data_details = body_details["data"]
    assert data_details["total_count"] >= 1
    assert data_details["entity_type"] == "details"
    detail_items = data_details["items"]
    assert any(
        item["id"] == detail.id and item["status"] == "failed_permanently"
        for item in detail_items
    )

    # 5. Invalid entity_type query parameter returns 422
    resp_bad = await client.get(
        "/api/v1/scrape/dead-letter?entity_type=invalid_entities"
    )
    assert resp_bad.status_code == 422
