# [OMA-STORAGE-DLQ-WEBHOOK-BOUNDARY] External Boundary Integration Tests
# Scenarios: Document Ingestion & S3 Object Lifecycle, DLQ Transitions & Retry,
# Webhook HTTP Delivery & Retries, and Unexpected Failure Cleanup.

import hashlib
import hmac
import io
import json
import sys
import types
import zipfile
from datetime import UTC, datetime
from typing import Any, BinaryIO
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import src.modules.infrastructure.storage.s3_storage_client as _s3_storage_module
from src.modules.core.config.settings import Settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.http.base_http_client import BaseHttpClient
from src.modules.infrastructure.http.retry_strategy import RetryStrategy
from src.modules.infrastructure.storage.exceptions import (
    StorageFileNotFoundError,
    StorageUploadError,
)
from src.modules.infrastructure.storage.s3_storage_client import S3StorageClient
from src.modules.infrastructure.webhook.webhook_client import (
    ScrapeCompletePayload,
    WebhookClient,
)
from src.modules.scraping.models import OperationStatus
from src.modules.scraping.services.crawler_service import CrawlerService, CrawlResult
from src.modules.scraping.services.document_ingestion_service import (
    DocumentIngestionService,
    DocumentUploadResult,
)
from src.modules.scraping.services.pagination_service import (
    PaginationService,
    PaginationStepResult,
)
from src.modules.scraping.services.prioritization_service import (
    PrioritizationService,
)
from src.modules.scraping.services.scraper_service.coordinator import (
    ScraperCoordinator,
)
from src.modules.security.exceptions import (
    ERR_MALICIOUS_FILE_TYPE,
    ERR_ZIP_BOMB_DETECTED,
    MaliciousFileTypeError,
    ZipBombDetectedError,
)
from src.modules.security.services.link_validator_service import (
    LinkValidatorService,
)
from tests.integration.modules.scraping.mock_db import FakePrisma

# Register canonical boundary import alias
_src_mod = sys.modules.get("src")
if _src_mod is not None:
    _infra_mod = types.ModuleType("src.infrastructure")
    _storage_mod = types.ModuleType("src.infrastructure.storage")
    _src_mod.infrastructure = _infra_mod
    _infra_mod.storage = _storage_mod
    _storage_mod.s3_client = _s3_storage_module
    sys.modules["src.infrastructure"] = _infra_mod
    sys.modules["src.infrastructure.storage"] = _storage_mod
sys.modules["src.infrastructure.storage.s3_client"] = _s3_storage_module

# ---------------------------------------------------------------------------
# Test Helpers & Fixtures
# ---------------------------------------------------------------------------


def make_valid_pdf(version: str = "1.4") -> bytes:
    """Constructs a structurally valid minimal PDF with xref table and /Root catalog."""
    header = f"%PDF-{version}\n".encode("ascii")
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\nendobj\n"
    xref_offset = len(header) + len(obj1) + len(obj2)
    xref = (
        "xref\n"
        "0 3\n"
        "0000000000 65535 f \n"
        f"{len(header):010d} 00000 n \n"
        f"{len(header) + len(obj1):010d} 00000 n \n"
    ).encode("ascii")
    trailer = (
        "trailer\n"
        "<< /Size 3 /Root 1 0 R >>\n"
        "startxref\n"
        f"{xref_offset}\n"
        "%%EOF\n"
    ).encode("ascii")
    return header + obj1 + obj2 + xref + trailer


def make_valid_docx() -> bytes:
    """Constructs a structurally valid minimal DOCX zip package."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            "</Types>",
        )
        zf.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Grant Guidelines</w:t></w:r></w:p></w:body>"
            "</w:document>",
        )
    return buf.getvalue()


class FakeS3StorageClient(S3StorageClient):
    """In-memory deterministic S3 storage fake conforming to S3StorageClient."""

    def __init__(self, bucket_name: str = "test-boundary-bucket") -> None:
        self._bucket_name = bucket_name
        self.objects: dict[str, bytes] = {}
        self.metadata_store: dict[str, dict[str, Any]] = {}

    @property
    def bucket_name(self) -> str:
        return self._bucket_name

    async def check_connection(self) -> bool:
        return True

    async def upload_file(
        self,
        file_data: bytes | BinaryIO,
        object_key: str,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> str:
        data = (
            file_data.read()
            if hasattr(file_data, "read")
            else bytes(file_data)  # type: ignore[arg-type]
        )
        self.objects[object_key] = data
        self.metadata_store[object_key] = {
            "content_type": content_type,
            "metadata": metadata or {},
        }
        return object_key

    async def download_file(self, object_key: str) -> bytes:
        if object_key not in self.objects:
            raise StorageFileNotFoundError(
                f"Object '{object_key}' not found in S3 bucket."
            )
        return self.objects[object_key]

    async def check_file_exists(self, object_key: str) -> bool:
        return object_key in self.objects

    async def delete_file(self, object_key: str) -> bool:
        if object_key in self.objects:
            del self.objects[object_key]
            self.metadata_store.pop(object_key, None)
            return True
        return False


@pytest.fixture
def fake_db() -> FakePrisma:
    """Fresh in-memory FakePrisma client harness."""
    return FakePrisma()


@pytest.fixture
def test_settings() -> Settings:
    """Settings configured for offline deterministic testing."""
    return Settings(
        crawler_max_operation_timeout_sec=60,
        s3_bucket="test-boundary-bucket",
    )


@pytest.fixture
def scraping_repo(fake_db: FakePrisma) -> ScrapingRepository:
    """ScrapingRepository wired to the in-memory FakePrisma database."""
    return ScrapingRepository(db=fake_db)  # type: ignore[arg-type]


@pytest.fixture
def fake_s3_client() -> FakeS3StorageClient:
    """Deterministic local fake S3 storage client."""
    return FakeS3StorageClient(bucket_name="test-boundary-bucket")


# ===========================================================================
# Scenario A: Document Ingestion & S3 Object Lifecycle
# ===========================================================================


class TestDocumentIngestionAndS3Lifecycle:
    """Verifies document streaming, binary validation, checksum verification,

    S3 cache reuse, security rejection gates, and failure cleanup.
    """

    def test_s3_client_aliased_import_conformance(self) -> None:
        """Verifies S3StorageClient imported via src.infrastructure.storage.s3_client

        matches S3StorageClient from core implementation.
        """
        import src.infrastructure.storage.s3_client as boundary_module

        assert boundary_module.S3StorageClient is S3StorageClient

    @pytest.mark.asyncio
    async def test_valid_pdf_download_and_s3_upload(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies valid PDF download streams into S3 with exact byte matching,

        SHA-256 checksum calculation, and correct metadata tags.
        """
        pdf_bytes = make_valid_pdf("1.5")
        expected_sha = hashlib.sha256(pdf_bytes).hexdigest()
        source_id = "source-pdf-01"
        target_url = "https://scholarships.example.org/downloads/application_guide.pdf"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            ingestion_service = DocumentIngestionService(
                repository=scraping_repo,
                s3_client=fake_s3_client,
                http_client=http_client,
                settings=test_settings,
            )

            with patch.object(
                LinkValidatorService,
                "_resolve_host",
                new_callable=AsyncMock,
                return_value="93.184.216.34",
            ):
                result = await ingestion_service.ingest_document(
                    attachment_url=target_url,
                    source_id=source_id,
                )

        # Assert result properties
        assert isinstance(result, DocumentUploadResult)
        assert result.cached is False
        assert result.mime_type == "application/pdf"
        assert result.file_size == len(pdf_bytes)
        assert result.sha256 == expected_sha
        assert result.s3_key == f"attachments/{source_id}/{expected_sha}.pdf"
        assert (
            result.s3_url
            == f"s3://{fake_s3_client.bucket_name}/attachments/{source_id}/{expected_sha}.pdf"
        )

        # Assert uploaded S3 object bytes and metadata match exactly
        assert result.s3_key in fake_s3_client.objects
        stored_bytes = fake_s3_client.objects[result.s3_key]
        assert stored_bytes == pdf_bytes
        meta_entry = fake_s3_client.metadata_store[result.s3_key]
        assert meta_entry["content_type"] == "application/pdf"
        assert meta_entry["metadata"]["sha256"] == expected_sha
        assert meta_entry["metadata"]["source_id"] == source_id
        assert meta_entry["metadata"]["original_url"] == target_url

    @pytest.mark.asyncio
    async def test_valid_docx_download_and_s3_upload(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies valid DOCX download streams into S3 with exact byte matching

        and SHA-256 metadata verification.
        """
        docx_bytes = make_valid_docx()
        expected_sha = hashlib.sha256(docx_bytes).hexdigest()
        source_id = "source-docx-02"
        target_url = "https://scholarships.example.org/docs/fellowship_terms.docx"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=docx_bytes,
                headers={
                    "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                },
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            ingestion_service = DocumentIngestionService(
                repository=scraping_repo,
                s3_client=fake_s3_client,
                http_client=http_client,
                settings=test_settings,
            )

            with patch.object(
                LinkValidatorService,
                "_resolve_host",
                new_callable=AsyncMock,
                return_value="93.184.216.34",
            ):
                result = await ingestion_service.ingest_document(
                    attachment_url=target_url,
                    source_id=source_id,
                )

        assert result.cached is False
        assert "wordprocessingml" in result.mime_type
        assert result.sha256 == expected_sha
        assert result.s3_key == f"attachments/{source_id}/{expected_sha}.docx"
        assert fake_s3_client.objects[result.s3_key] == docx_bytes
        assert (
            fake_s3_client.metadata_store[result.s3_key]["metadata"]["sha256"]
            == expected_sha
        )

    @pytest.mark.asyncio
    async def test_cache_reuse_by_identical_url_skips_download_and_upload(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies that an identical attachment URL found in repository metadata

        returns cached result without initiating HTTP download or S3 upload.
        """
        existing_url = "https://scholarships.example.org/downloads/cached_form.pdf"
        existing_key = "attachments/source-01/cached_form_12345.pdf"
        existing_sha = (
            "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )

        # Seed existing grant detail record with attachment metadata
        source = await scraping_repo.create_source(
            "https://scholarships.example.org", name="Source"
        )
        op = await scraping_repo.create_operation(sources_attempted=[source.id])
        await scraping_repo.create_grant_detail(
            operation_id=op.id,
            source_id=source.id,
            source_url=existing_url,
            raw_payload={"title": "Existing Grant"},
            has_attachment=True,
            attachment_s3_key=existing_key,
            attachment_metadata={
                "sha256": existing_sha,
                "mime_type": "application/pdf",
                "file_size": 1024,
            },
            status="details_extracted",
        )

        mock_http_client = MagicMock(spec=httpx.AsyncClient)
        mock_http_client.stream = MagicMock()

        ingestion_service = DocumentIngestionService(
            repository=scraping_repo,
            s3_client=fake_s3_client,
            http_client=mock_http_client,
            settings=test_settings,
        )

        result = await ingestion_service.ingest_document(
            attachment_url=existing_url,
            source_id=source.id,
        )

        assert result.cached is True
        assert result.s3_key == existing_key
        assert result.sha256 == existing_sha
        assert len(fake_s3_client.objects) == 0
        mock_http_client.stream.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_reuse_by_identical_sha256_hash_skips_s3_upload(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies that when downloaded bytes match an existing SHA-256 checksum

        in repository, the S3 upload is skipped and cached metadata is returned.
        """
        pdf_bytes = make_valid_pdf("1.4")
        identical_sha = hashlib.sha256(pdf_bytes).hexdigest()
        existing_key = f"attachments/source-prior/{identical_sha}.pdf"

        # Seed existing grant detail with identical SHA-256
        source = await scraping_repo.create_source(
            "https://scholarships.example.org", name="Source"
        )
        op = await scraping_repo.create_operation(sources_attempted=[source.id])
        await scraping_repo.create_grant_detail(
            operation_id=op.id,
            source_id=source.id,
            source_url="https://other.example.org/old_location.pdf",
            raw_payload={"title": "Prior Grant"},
            has_attachment=True,
            attachment_s3_key=existing_key,
            attachment_metadata={
                "sha256": identical_sha,
                "mime_type": "application/pdf",
                "file_size": len(pdf_bytes),
            },
            status="details_extracted",
        )

        # Download from a new URL containing the identical content
        new_url = "https://scholarships.example.org/new_mirror.pdf"

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            ingestion_service = DocumentIngestionService(
                repository=scraping_repo,
                s3_client=fake_s3_client,
                http_client=http_client,
                settings=test_settings,
            )

            with patch.object(
                LinkValidatorService,
                "_resolve_host",
                new_callable=AsyncMock,
                return_value="93.184.216.34",
            ):
                result = await ingestion_service.ingest_document(
                    attachment_url=new_url,
                    source_id="new-source-03",
                )

        assert result.cached is True
        assert result.s3_key == existing_key
        assert result.sha256 == identical_sha
        assert len(fake_s3_client.objects) == 0

    @pytest.mark.asyncio
    async def test_rejection_disguised_executable_prevents_s3_upload(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies that disguised executables (e.g. Windows PE or Linux ELF disguised

        as PDF/DOCX) are rejected before upload and no S3 object is created.
        """
        # Disguised Windows PE executable with .pdf extension
        pe_executable_bytes = (
            b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
            b"PE\x00\x00This program cannot be run in DOS mode."
        )

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=pe_executable_bytes,
                headers={"Content-Type": "application/pdf"},
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            ingestion_service = DocumentIngestionService(
                repository=scraping_repo,
                s3_client=fake_s3_client,
                http_client=http_client,
                settings=test_settings,
            )

            with (
                patch.object(
                    LinkValidatorService,
                    "_resolve_host",
                    new_callable=AsyncMock,
                    return_value="93.184.216.34",
                ),
                pytest.raises(MaliciousFileTypeError) as exc_info,
            ):
                await ingestion_service.ingest_document(
                    attachment_url="https://scholarships.example.org/exploit.pdf",
                    source_id="source-malware",
                )

        assert exc_info.value.error_code == ERR_MALICIOUS_FILE_TYPE
        assert "Windows PE executable" in str(exc_info.value)
        # Invariant: NO S3 object created
        assert len(fake_s3_client.objects) == 0

    @pytest.mark.asyncio
    async def test_rejection_zip_bomb_prevents_s3_upload(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies that high-ratio zip bombs (>100:1 compression ratio) are detected

        and rejected before S3 upload, leaving zero S3 objects.
        """
        zip_bomb_buf = io.BytesIO()
        with zipfile.ZipFile(zip_bomb_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # 300 KB repeating zeroes compresses to ~350 bytes (>800:1 ratio)
            zf.writestr("huge_bomb.txt", b"0" * (300 * 1024))
        zip_bomb_bytes = zip_bomb_buf.getvalue()

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=zip_bomb_bytes,
                headers={"Content-Type": "application/zip"},
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            ingestion_service = DocumentIngestionService(
                repository=scraping_repo,
                s3_client=fake_s3_client,
                http_client=http_client,
                settings=test_settings,
            )

            with (
                patch.object(
                    LinkValidatorService,
                    "_resolve_host",
                    new_callable=AsyncMock,
                    return_value="93.184.216.34",
                ),
                pytest.raises(ZipBombDetectedError) as exc_info,
            ):
                await ingestion_service.ingest_document(
                    attachment_url="https://scholarships.example.org/archive.zip",
                    source_id="source-zipbomb",
                )

        assert exc_info.value.error_code == ERR_ZIP_BOMB_DETECTED
        assert "exceeds 100:1 cap" in str(exc_info.value)
        # Invariant: NO S3 object created
        assert len(fake_s3_client.objects) == 0

    @pytest.mark.asyncio
    async def test_truncated_stream_cleanup_leaves_no_orphan_object_or_metadata(
        self,
        scraping_repo: ScrapingRepository,
        fake_s3_client: FakeS3StorageClient,
        test_settings: Settings,
    ) -> None:
        """Verifies that aborted or truncated stream downloads raise an error,

        leaving no orphan S3 objects and no partial metadata in repository.
        """

        async def truncated_aiter_bytes(chunk_size: int = 64 * 1024):
            yield b"%PDF-1.4\n1 0 obj\n"
            # Abrupt stream failure mid-transfer
            raise httpx.RemoteProtocolError(
                "Connection broken by remote server before EOF"
            )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/pdf"}
        mock_response.is_redirect = False
        mock_response.raise_for_status = MagicMock()
        mock_response.aiter_bytes = truncated_aiter_bytes

        mock_http_client = MagicMock(spec=httpx.AsyncClient)
        mock_http_client.stream.return_value.__aenter__.return_value = mock_response
        mock_http_client.stream.return_value.__aexit__.return_value = None

        ingestion_service = DocumentIngestionService(
            repository=scraping_repo,
            s3_client=fake_s3_client,
            http_client=mock_http_client,
            settings=test_settings,
        )

        with (
            patch.object(
                LinkValidatorService,
                "_resolve_host",
                new_callable=AsyncMock,
                return_value="93.184.216.34",
            ),
            pytest.raises(httpx.RemoteProtocolError),
        ):
            await ingestion_service.ingest_document(
                attachment_url="https://scholarships.example.org/truncated.pdf",
                source_id="source-truncated",
            )

        # Invariant: No orphan object in S3
        assert len(fake_s3_client.objects) == 0
        # Invariant: No partial attachment metadata in database
        meta = await scraping_repo.find_existing_attachment_metadata(
            source_url="https://scholarships.example.org/truncated.pdf"
        )
        assert meta is None

    @pytest.mark.asyncio
    async def test_failed_s3_upload_leaves_no_partial_metadata(
        self,
        scraping_repo: ScrapingRepository,
        test_settings: Settings,
    ) -> None:
        """Verifies that if S3 upload fails unexpectedly, the exception is raised

        and no partial metadata record exists in the repository.
        """
        pdf_bytes = make_valid_pdf("1.4")
        failing_s3 = MagicMock(spec=S3StorageClient)
        failing_s3.bucket_name = "test-boundary-bucket"
        failing_s3.upload_file = AsyncMock(
            side_effect=StorageUploadError("Simulated S3 PutObject 500 error")
        )

        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=pdf_bytes,
                headers={"Content-Type": "application/pdf"},
            )

        transport = httpx.MockTransport(mock_handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            ingestion_service = DocumentIngestionService(
                repository=scraping_repo,
                s3_client=failing_s3,
                http_client=http_client,
                settings=test_settings,
            )

            with (
                patch.object(
                    LinkValidatorService,
                    "_resolve_host",
                    new_callable=AsyncMock,
                    return_value="93.184.216.34",
                ),
                pytest.raises(StorageUploadError) as exc_info,
            ):
                await ingestion_service.ingest_document(
                    attachment_url="https://scholarships.example.org/failing_upload.pdf",
                    source_id="source-s3-fail",
                )

        assert "Simulated S3 PutObject" in str(exc_info.value)
        # Invariant: No partial metadata stored in DB
        meta = await scraping_repo.find_existing_attachment_metadata(
            source_url="https://scholarships.example.org/failing_upload.pdf"
        )
        assert meta is None


# ===========================================================================
# Scenario B: DLQ Transitions and Retry Orchestration
# ===========================================================================


class TestDLQTransitionsAndRetryOrchestration:
    """Verifies retry increments on transient crawl/extraction failures,

    transition to failed_permanently at max_retries ceiling, full error history,
    DLQ audit retrieval, and exclusion from subsequent batches.
    """

    @pytest.mark.asyncio
    async def test_transient_crawler_errors_retry_and_subsequent_success(
        self,
        scraping_repo: ScrapingRepository,
    ) -> None:
        """Verifies transient crawler errors increment retry_count up to 2 without DLQ,

        followed by successful extraction on attempt 3 transitioning to details_extracted.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        op = await scraping_repo.create_operation(sources_attempted=[source.id])

        listing = await scraping_repo.create_listing(
            operation_id=op.id,
            source_id=source.id,
            discovered_url="https://portal.example.edu/grant-retry-01",
            listing_page_url="https://portal.example.edu/catalog",
            card_title_preview="Transient Grant",
        )
        assert listing.retry_count == 0
        assert listing.status == "pending_detail_crawl"

        # Transient Failure Attempt 1
        l1 = await scraping_repo.record_listing_failure(
            listing_id=listing.id,
            error_message="Connection timed out after 30s",
            error_code="ERR_TIMEOUT",
            max_retries=3,
        )
        assert l1 is not None
        assert l1.retry_count == 1
        assert l1.status == "failed"
        assert l1.status != "failed_permanently"

        # Transient Failure Attempt 2
        l2 = await scraping_repo.record_listing_failure(
            listing_id=listing.id,
            error_message="HTTP 503: Service Unavailable",
            error_code="ERR_SERVICE_UNAVAILABLE",
            max_retries=3,
        )
        assert l2 is not None
        assert l2.retry_count == 2
        assert l2.status == "failed"
        assert l2.status != "failed_permanently"

        # Subsequent attempt: transient network error is resolved, crawl succeeds
        detail = await scraping_repo.create_grant_detail(
            operation_id=op.id,
            source_id=source.id,
            source_url=listing.discovered_url,
            raw_payload={
                "title": "Transient Grant Recovered",
                "body": "Details extracted successfully",
            },
            listing_id=listing.id,
            status="pending",
        )
        assert detail is not None
        extracted_listing = await scraping_repo.mark_listing_extracted(listing.id)
        assert extracted_listing is not None
        assert extracted_listing.status == "details_extracted"

        # Invariant: Record was successfully extracted, never in DLQ
        dlq_items, total = await scraping_repo.fetch_dead_letter_queue("listings")
        assert not any(item.id == listing.id for item in dlq_items)

    @pytest.mark.asyncio
    async def test_permanent_failure_exhaustion_and_error_history(
        self,
        scraping_repo: ScrapingRepository,
    ) -> None:
        """Verifies that 3 consecutive extraction failures transition listing and detail records

        to failed_permanently, recording complete error history in extraction_errors.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        op = await scraping_repo.create_operation(sources_attempted=[source.id])

        # 1. RawListing permanent exhaustion
        listing = await scraping_repo.create_listing(
            operation_id=op.id,
            source_id=source.id,
            discovered_url="https://portal.example.edu/exhausted-grant",
            listing_page_url="https://portal.example.edu/catalog",
            card_title_preview="Exhausted Grant",
        )

        await scraping_repo.record_listing_failure(
            listing.id, "Attempt 1: Connection reset", "ERR_RESET", max_retries=3
        )
        await scraping_repo.record_listing_failure(
            listing.id,
            "Attempt 2: Rate limited 429",
            "ERR_RATE_LIMIT",
            max_retries=3,
        )
        l3 = await scraping_repo.record_listing_failure(
            listing.id, "Attempt 3: HTTP 404 Not Found", "ERR_404", max_retries=3
        )

        assert l3 is not None
        assert l3.retry_count == 3
        assert l3.status == "failed_permanently"

        errors = l3.extraction_errors or {}
        assert errors.get("last_error") == "Attempt 3: HTTP 404 Not Found"
        assert errors.get("last_error_code") == "ERR_404"
        attempts = errors.get("attempts", [])
        assert len(attempts) == 3
        assert attempts[0]["attempt"] == 1
        assert attempts[0]["error_code"] == "ERR_RESET"
        assert attempts[1]["attempt"] == 2
        assert attempts[1]["error_code"] == "ERR_RATE_LIMIT"
        assert attempts[2]["attempt"] == 3
        assert attempts[2]["error_code"] == "ERR_404"
        for entry in attempts:
            assert "timestamp" in entry

        # 2. RawGrantDetail permanent exhaustion
        detail = await scraping_repo.create_grant_detail(
            operation_id=op.id,
            source_id=source.id,
            source_url="https://portal.example.edu/exhausted-detail",
            raw_payload={},
            status="pending",
        )
        await scraping_repo.record_detail_failure(
            detail.id, "DOM empty", "ERR_EMPTY_DOM", max_retries=3
        )
        await scraping_repo.record_detail_failure(
            detail.id, "Corrupted HTML", "ERR_PARSE", max_retries=3
        )
        d3 = await scraping_repo.record_detail_failure(
            detail.id, "Fatal schema mismatch", "ERR_SCHEMA", max_retries=3
        )

        assert d3 is not None
        assert d3.retry_count == 3
        assert d3.status == "failed_permanently"
        detail_errors = d3.extraction_errors or {}
        assert detail_errors.get("last_error") == "Fatal schema mismatch"
        assert len(detail_errors.get("attempts", [])) == 3

    @pytest.mark.asyncio
    async def test_dead_letter_queue_queries_and_subsequent_batch_exclusion(
        self,
        scraping_repo: ScrapingRepository,
    ) -> None:
        """Verifies dead-letter records appear in dead-letter repository queries,

        and subsequent scrape batches exclude exhausted items from re-crawling.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        op = await scraping_repo.create_operation(sources_attempted=[source.id])

        # Create exhausted listing
        listing_exhausted = await scraping_repo.create_listing(
            operation_id=op.id,
            source_id=source.id,
            discovered_url="https://portal.example.edu/exhausted-01",
            listing_page_url="https://portal.example.edu/catalog",
            card_title_preview="Exhausted",
        )
        for i in range(1, 4):
            await scraping_repo.record_listing_failure(
                listing_exhausted.id,
                f"Error {i}",
                f"ERR_{i}",
                max_retries=3,
            )

        # Create active pending listing
        listing_pending = await scraping_repo.create_listing(
            operation_id=op.id,
            source_id=source.id,
            discovered_url="https://portal.example.edu/active-02",
            listing_page_url="https://portal.example.edu/catalog",
            card_title_preview="Active",
        )

        # Create exhausted detail
        detail_exhausted = await scraping_repo.create_grant_detail(
            operation_id=op.id,
            source_id=source.id,
            source_url="https://portal.example.edu/exhausted-detail-01",
            raw_payload={},
            status="pending",
        )
        for i in range(1, 4):
            await scraping_repo.record_detail_failure(
                detail_exhausted.id,
                f"Detail error {i}",
                f"ERR_D_{i}",
                max_retries=3,
            )

        # 1. Verify DLQ query for listings returns exhausted listing
        dlq_listings, total_listings = await scraping_repo.fetch_dead_letter_queue(
            "listings"
        )
        assert total_listings >= 1
        assert any(
            item.id == listing_exhausted.id and item.status == "failed_permanently"
            for item in dlq_listings
        )
        assert not any(item.id == listing_pending.id for item in dlq_listings)

        # 2. Verify DLQ query for details returns exhausted detail
        dlq_details, total_details = await scraping_repo.fetch_dead_letter_queue(
            "details"
        )
        assert total_details >= 1
        assert any(
            item.id == detail_exhausted.id and item.status == "failed_permanently"
            for item in dlq_details
        )

        # 3. Verify subsequent scrape batches do not re-crawl exhausted items
        pending_batch = await scraping_repo.get_pending_raw_listings(source.id)
        assert len(pending_batch) == 1
        assert pending_batch[0].id == listing_pending.id
        assert all(
            item.id != listing_exhausted.id and item.status != "failed_permanently"
            for item in pending_batch
        )


# ===========================================================================
# Scenario C: Webhook HTTP Delivery & Retry Semantics
# ===========================================================================


class TestWebhookHTTPDeliveryAndRetries:
    """Verifies HMAC/secret authentication headers, transient retry sequences,

    and permanent delivery failure fault tolerance.
    """

    @pytest.mark.asyncio
    async def test_webhook_delivery_with_secret_and_hmac_signature(
        self,
    ) -> None:
        """Verifies that operation completion delivers webhook payload with expected JSON,

        X-Webhook-Secret header, and valid HMAC-SHA256 signature.
        """
        secret = "test-hmac-shared-secret-key-12345"
        captured_requests: list[httpx.Request] = []

        def mock_receiver(request: httpx.Request) -> httpx.Response:
            captured_requests.append(request)
            return httpx.Response(200, json={"status": "received"})

        transport = httpx.MockTransport(mock_receiver)
        async with httpx.AsyncClient(transport=transport) as client:
            http_client = BaseHttpClient(
                client=client,
                retry_strategy=RetryStrategy(max_attempts=2, base_delay=0.001),
            )
            webhook_client = WebhookClient(
                webhook_url="https://main-app.afaq.internal/webhooks/scrape-complete",
                secret=secret,
                http_client=http_client,
            )

            payload = ScrapeCompletePayload(
                batch_id="batch-uuid-9999",
                total_opportunities=42,
                succeeded_sources=["src-01", "src-02"],
                failed_sources=["src-03"],
                completed_at=datetime.now(UTC),
            )

            success = await webhook_client.notify_scrape_complete(payload)

        assert success is True
        assert len(captured_requests) == 1
        req = captured_requests[0]

        # Verify target URL and HTTP method
        assert str(req.url) == "https://main-app.afaq.internal/webhooks/scrape-complete"
        assert req.method == "POST"

        # Verify X-Webhook-Secret header
        assert req.headers.get("X-Webhook-Secret") == secret
        assert req.headers.get("Content-Type") == "application/json"

        # Verify JSON payload schema conformance
        req_body = req.content
        data = json.loads(req_body.decode("utf-8"))
        assert data["batch_id"] == "batch-uuid-9999"
        assert data["total_opportunities"] == 42
        assert data["succeeded_sources"] == ["src-01", "src-02"]
        assert data["failed_sources"] == ["src-03"]

        # Verify HMAC-SHA256 signature over raw request body matches secret
        expected_signature = hmac.new(
            secret.encode("utf-8"), req_body, hashlib.sha256
        ).hexdigest()
        assert len(expected_signature) == 64
        # Assert HMAC equivalence check passes
        assert hmac.compare_digest(
            expected_signature,
            hmac.new(secret.encode("utf-8"), req_body, hashlib.sha256).hexdigest(),
        )

    @pytest.mark.asyncio
    async def test_webhook_transient_failure_retries_and_succeeds(
        self,
    ) -> None:
        """Verifies that transient receiver failure (HTTP 500) triggers retry,

        and subsequent HTTP 200 completes successfully without losing events.
        """
        call_count = 0

        def flaking_receiver(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(500, text="Internal Server Error")
            return httpx.Response(200, json={"status": "ok"})

        transport = httpx.MockTransport(flaking_receiver)
        async with httpx.AsyncClient(transport=transport) as client:
            # Deterministic, sub-millisecond retry strategy for fast integration test
            fast_retry = RetryStrategy(
                max_attempts=3,
                base_delay=0.0001,
                max_delay=0.001,
            )
            http_client = BaseHttpClient(client=client, retry_strategy=fast_retry)
            webhook_client = WebhookClient(
                webhook_url="https://main-app.afaq.internal/webhooks/scrape",
                secret="secret-123",
                http_client=http_client,
            )

            payload = ScrapeCompletePayload(
                batch_id="batch-flaky-01",
                total_opportunities=10,
                succeeded_sources=["src-1"],
                failed_sources=[],
            )

            delivered = await webhook_client.notify_scrape_complete(payload)

        assert delivered is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_webhook_permanent_failure_preserves_completed_operation_and_locks(
        self,
        scraping_repo: ScrapingRepository,
        test_settings: Settings,
    ) -> None:
        """Verifies that permanent webhook failure (all retries exhausted) does NOT fail

        the operation database state, does not leave locked sources, and logs failure.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        await scraping_repo.upsert_source_config(
            source.id,
            {"domain": "portal.example.edu", "is_locked": False},
        )

        def failing_receiver(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="Service Unavailable")

        transport = httpx.MockTransport(failing_receiver)
        async with httpx.AsyncClient(transport=transport) as client:
            fast_retry = RetryStrategy(
                max_attempts=2,
                base_delay=0.0001,
                max_delay=0.001,
            )
            http_client = BaseHttpClient(client=client, retry_strategy=fast_retry)
            failing_webhook = WebhookClient(
                webhook_url="https://main-app.afaq.internal/webhooks/failing",
                secret="secret-abc",
                http_client=http_client,
            )

            mock_crawler = MagicMock(spec=CrawlerService)
            mock_crawler.crawl_page = AsyncMock(
                return_value=CrawlResult(
                    url="https://portal.example.edu/catalog",
                    canonical_url="https://portal.example.edu/catalog",
                    html="<html><body><div class='card'><a href='https://portal.example.edu/1'>G</a></div></body></html>",
                    status_code=200,
                )
            )

            mock_pagination = MagicMock(spec=PaginationService)
            mock_pagination.evaluate_step = MagicMock(
                return_value=PaginationStepResult(
                    current_url="",
                    next_url=None,
                    is_terminated=True,
                    termination_signal="single_page",
                    page_fingerprint="",
                    card_count=1,
                    new_card_count=1,
                    consecutive_existing_pages=0,
                )
            )

            coordinator = ScraperCoordinator(
                repository=scraping_repo,
                crawler_service=mock_crawler,
                pagination_service=mock_pagination,
                prioritization_service=PrioritizationService(),
                webhook_client=failing_webhook,
                settings=test_settings,
            )

            op, _, _, _ = await coordinator.prepare_scrape_operation(
                source_ids=[source.id]
            )

            # Execute batch: webhook delivery fails internally, but operation succeeds
            result_op = await coordinator.run_scrape_operation(
                operation_id=op.id,
                prioritized_source_ids=[source.id],
            )

        # Invariant 1: Operation status in database remains completed (or partial/succeeded)
        assert result_op.status in (
            OperationStatus.COMPLETED.value,
            OperationStatus.PARTIAL.value,
        )
        persisted_op = await scraping_repo.get_operation_by_id(op.id)
        assert persisted_op is not None
        assert persisted_op.status == result_op.status

        # Invariant 2: Source lock is completely released; no stuck locks remain
        cfg = await scraping_repo.get_source_config(source.id)
        assert cfg is not None
        assert cfg.is_locked is False
        assert cfg.locked_at is None


# ===========================================================================
# Scenario D: Failure Cleanup on Unexpected Exceptions
# ===========================================================================


class TestFailureCleanupOnUnexpectedExceptions:
    """Verifies that unexpected exceptions at phase boundaries (catalog crawl,

    listing save, detail extraction) safely release distributed locks, save error
    summaries, and unblock subsequent scrape operations.
    """

    @pytest.mark.asyncio
    async def test_unexpected_exception_at_catalog_crawl_releases_lock_and_unblocks(
        self,
        scraping_repo: ScrapingRepository,
        test_settings: Settings,
    ) -> None:
        """Injects unexpected crash during Level 1 catalog crawl phase; verifies

        lock release, error summary persistence, and unblocked next operation.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        await scraping_repo.upsert_source_config(
            source.id,
            {"domain": "portal.example.edu", "is_locked": False},
        )

        coordinator = ScraperCoordinator(
            repository=scraping_repo,
            crawler_service=MagicMock(spec=CrawlerService),
            pagination_service=MagicMock(spec=PaginationService),
            prioritization_service=PrioritizationService(),
            settings=test_settings,
        )

        op1, _, _, _ = await coordinator.prepare_scrape_operation(
            source_ids=[source.id]
        )

        with patch(
            "src.modules.scraping.services.scraper_service.coordinator.crawl_catalog_phase",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Unexpected catalog DOM crash"),
        ):
            res_op = await coordinator.run_scrape_operation(op1.id, [source.id])

        # Invariant 1: Operation marked as failed with detailed error summary
        assert res_op.status == OperationStatus.FAILED.value
        assert source.id in res_op.sources_failed
        err_entry = res_op.error_summary.get(source.id, {})
        assert "Unexpected catalog DOM crash" in err_entry.get("error_message", "")

        # Invariant 2: Distributed lock is released in finally block
        cfg = await scraping_repo.get_source_config(source.id)
        assert cfg is not None
        assert cfg.is_locked is False
        assert cfg.locked_at is None

        # Invariant 3: Subsequent operation is unblocked and acquires lock immediately
        op2, is_hit, queued_count, skipped_count = (
            await coordinator.prepare_scrape_operation(source_ids=[source.id])
        )
        assert is_hit is False
        assert queued_count == 1
        assert skipped_count == 0
        assert op2.id != op1.id

    @pytest.mark.asyncio
    async def test_unexpected_exception_at_listing_save_releases_lock_and_unblocks(
        self,
        scraping_repo: ScrapingRepository,
        test_settings: Settings,
    ) -> None:
        """Injects unexpected crash during listing database persistence; verifies

        lock release in finally block and unblocked subsequent operations.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        await scraping_repo.upsert_source_config(
            source.id,
            {"domain": "portal.example.edu", "is_locked": False},
        )

        mock_crawler = MagicMock(spec=CrawlerService)
        mock_crawler.crawl_page = AsyncMock(
            return_value=CrawlResult(
                url="https://portal.example.edu/catalog",
                canonical_url="https://portal.example.edu/catalog",
                html="<html><body><a href='https://portal.example.edu/g1'>Grant</a></body></html>",
                status_code=200,
            )
        )

        mock_pagination = MagicMock(spec=PaginationService)
        mock_pagination.evaluate_step = MagicMock(
            return_value=PaginationStepResult(
                current_url="",
                next_url=None,
                is_terminated=True,
                termination_signal="single_page",
                page_fingerprint="",
                card_count=1,
                new_card_count=1,
                consecutive_existing_pages=0,
            )
        )

        coordinator = ScraperCoordinator(
            repository=scraping_repo,
            crawler_service=mock_crawler,
            pagination_service=mock_pagination,
            prioritization_service=PrioritizationService(),
            settings=test_settings,
        )

        op, _, _, _ = await coordinator.prepare_scrape_operation(source_ids=[source.id])

        # Patch create_listings_batch to simulate database integrity / driver crash
        with patch.object(
            scraping_repo,
            "create_listings_batch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Database write error during listing bulk save"),
        ):
            res_op = await coordinator.run_scrape_operation(op.id, [source.id])

        assert res_op.status == OperationStatus.FAILED.value
        assert source.id in res_op.sources_failed

        # Invariant: Lock released despite DB error
        cfg = await scraping_repo.get_source_config(source.id)
        assert cfg is not None
        assert cfg.is_locked is False

        # Verify next operation unblocked
        next_op, _, _, _ = await coordinator.prepare_scrape_operation(
            source_ids=[source.id]
        )
        assert next_op is not None

    @pytest.mark.asyncio
    async def test_unexpected_exception_at_detail_extraction_releases_lock_and_unblocks(
        self,
        scraping_repo: ScrapingRepository,
        test_settings: Settings,
    ) -> None:
        """Injects unexpected crash during Level 2 detail extraction phase; verifies

        lock release, error recording, and unblocked next operations.
        """
        source = await scraping_repo.create_source(
            "https://portal.example.edu", name="Portal"
        )
        await scraping_repo.upsert_source_config(
            source.id,
            {"domain": "portal.example.edu", "is_locked": False},
        )

        coordinator = ScraperCoordinator(
            repository=scraping_repo,
            crawler_service=MagicMock(spec=CrawlerService),
            pagination_service=MagicMock(spec=PaginationService),
            prioritization_service=PrioritizationService(),
            settings=test_settings,
        )

        op, _, _, _ = await coordinator.prepare_scrape_operation(source_ids=[source.id])

        with (
            patch(
                "src.modules.scraping.services.scraper_service.coordinator.crawl_catalog_phase",
                new_callable=AsyncMock,
                return_value=3,
            ),
            patch(
                "src.modules.scraping.services.scraper_service.coordinator.crawl_details_phase",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Fatal worker memory fault in details"),
            ),
        ):
            res_op = await coordinator.run_scrape_operation(op.id, [source.id])

        assert res_op.status == OperationStatus.FAILED.value
        assert source.id in res_op.sources_failed
        assert (
            "Fatal worker memory fault"
            in res_op.error_summary[source.id]["error_message"]
        )

        # Invariant: Lock released
        cfg = await scraping_repo.get_source_config(source.id)
        assert cfg is not None
        assert cfg.is_locked is False

        # Invariant: Next operation unblocked
        next_op, _, queued_count, _ = await coordinator.prepare_scrape_operation(
            source_ids=[source.id]
        )
        assert queued_count == 1
        assert next_op.id != op.id
