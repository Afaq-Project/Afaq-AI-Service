# [OMA-W005-T037] Secure document streaming and ingestion service to AWS S3

import io
import logging
import urllib.parse
from dataclasses import dataclass
from typing import Any, BinaryIO

import httpx
from safe_web_access.urls import validate_and_normalize_url

from src.modules.core.config.settings import Settings, get_settings
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)
from src.modules.infrastructure.storage.s3_storage_client import S3StorageClient

# [OMA-W006-T005] Import SSRF security exceptions for safe stream redirect validation
from src.modules.security.exceptions import (
    ERR_FILE_SIZE_EXCEEDED,
    ERR_SSRF_ATTEMPT_BLOCKED,
    FileSizeExceededError,
    SSRFAttemptBlockedError,
)
from src.modules.security.services.file_validator_service import (
    FileValidatorService,
)

# [OMA-W005-T037] Link validator for anti-SSRF pre-download verification
from src.modules.security.services.link_validator_service import LinkValidatorService

# [OMA-W004-FIX-CYCLE-2] Expose normalize_url on LinkValidatorService for circular redirect detection
if not hasattr(LinkValidatorService, "normalize_url"):

    def _normalize_url(url: str) -> str:
        """Normalizes URL for RFC 3986 canonicalization and circular redirect comparison."""
        try:
            return validate_and_normalize_url(url).normalized
        except Exception:
            return url.strip()

    LinkValidatorService.normalize_url = staticmethod(_normalize_url)  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)

# [OMA-W005-T037] Strict 25 MB maximum file stream limit (FR-023)
MAX_FILE_SIZE_BYTES: int = 25 * 1024 * 1024


# [OMA-W005-T037] Document upload result model
@dataclass(frozen=True)
class DocumentUploadResult:
    """Outcome of document stream ingestion, validation, and S3 storage."""

    s3_url: str
    s3_key: str
    sha256: str
    mime_type: str
    file_size: int
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "s3_url": self.s3_url,
            "s3_key": self.s3_key,
            "sha256": self.sha256,
            "mime_type": self.mime_type,
            "file_size": self.file_size,
            "cached": self.cached,
        }


# [OMA-W005-T037] Document ingestion and S3 streaming orchestrator
class DocumentIngestionService:
    """Streams and validates application documents and uploads them to S3.

    Enforces:
      - 25 MB stream download ceiling with immediate abort on breach (FR-023)
      - S3 Cache Reuse: skips download if source_url or sha256 is already recorded in raw_grant_details
      - Deep binary validation via FileValidatorService (magic bytes, footer, zip-bomb defenses)
      - Partitioned S3 object key derivation: attachments/{source_id}/{sha256}.{ext}
      - Zero unvalidated local disk storage (direct in-memory buffer streaming)
    """

    MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_BYTES

    def __init__(
        self,
        repository: ScrapingRepository | None = None,
        s3_client: S3StorageClient | None = None,
        file_validator: type[FileValidatorService] | None = None,
        http_client: httpx.AsyncClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._s3_client = s3_client
        self._file_validator = file_validator or FileValidatorService
        self._http_client = http_client
        self._settings = settings or get_settings()

    # [OMA-W005-T037] Lazy initializer for S3 client
    def _get_s3_client(self) -> S3StorageClient:
        """Returns configured S3 storage client."""
        if self._s3_client is None:
            self._s3_client = S3StorageClient(settings=self._settings)
        return self._s3_client

    # [OMA-W005-T037] Helper to determine bucket name
    def _get_bucket_name(self) -> str:
        """Determines configured S3 bucket name."""
        if self._s3_client is not None:
            return self._s3_client.bucket_name
        return self._settings.s3_bucket or "default-bucket"

    # [OMA-W005-T037] Ingest remote document link with S3 cache check, stream size check, and validation
    async def ingest_document(
        self,
        attachment_url: str,
        source_id: str,
        filename: str | None = None,
    ) -> DocumentUploadResult:
        """Streams remote document URL, validates payload safety, and persists to S3.

        Skips network transfer if attachment URL or checksum exists in repository.
        """
        # 1. S3 Cache Reuse: check existing attachment metadata by URL
        if self._repository is not None:
            cached = await self._repository.find_existing_attachment_metadata(
                source_url=attachment_url
            )
            if cached and cached.get("attachment_s3_key"):
                s3_key = str(cached["attachment_s3_key"])
                meta = cached.get("attachment_metadata") or {}
                if isinstance(meta, dict):
                    sha256 = str(meta.get("sha256") or "")
                    mime_type = str(meta.get("mime_type") or "application/octet-stream")
                    file_size = int(meta.get("file_size") or 0)
                else:
                    sha256 = ""
                    mime_type = "application/octet-stream"
                    file_size = 0

                bucket = self._get_bucket_name()
                s3_url = f"s3://{bucket}/{s3_key}"
                logger.info(
                    "S3 Cache hit for attachment URL %s -> %s (skipping download)",
                    attachment_url,
                    s3_key,
                )
                return DocumentUploadResult(
                    s3_url=s3_url,
                    s3_key=s3_key,
                    sha256=sha256,
                    mime_type=mime_type,
                    file_size=file_size,
                    cached=True,
                )

        # [OMA-W005-T037] Validate attachment URL against SSRF and security constraints before streaming
        validated = await LinkValidatorService.validate_url(
            attachment_url, allow_redirects=True
        )
        effective_url = validated.canonical_url

        # 2. Stream download enforcing 25 MB max limit
        buffer = bytearray()
        content_disposition: str | None = None

        if self._http_client is not None:
            buffer, content_disposition = await self._stream_download(
                self._http_client, effective_url
            )
        else:
            # [OMA-W006-T005] Enforce follow_redirects=False to prevent SSRF bypass via unvalidated redirects
            async with httpx.AsyncClient(
                timeout=30.0, follow_redirects=False
            ) as client:
                buffer, content_disposition = await self._stream_download(
                    client, effective_url
                )

        # 3. Stream validation via FileValidatorService (magic bytes, zip bomb, footer)
        stream = io.BytesIO(buffer)
        validation_res = self._file_validator.validate_stream(
            stream=stream,
            filename=filename,
            source_id=source_id,
            content_disposition=content_disposition,
            source_url=effective_url,
            raise_on_error=True,
        )

        # 4. S3 Cache Reuse: check by derived SHA256 checksum
        if self._repository is not None:
            cached_sha = await self._repository.find_existing_attachment_metadata(
                sha256_checksum=validation_res.sha256_checksum
            )
            if cached_sha and cached_sha.get("attachment_s3_key"):
                s3_key = str(cached_sha["attachment_s3_key"])
                bucket = self._get_bucket_name()
                logger.info(
                    "S3 Cache hit by checksum %s -> %s (skipping upload)",
                    validation_res.sha256_checksum,
                    s3_key,
                )
                return DocumentUploadResult(
                    s3_url=f"s3://{bucket}/{s3_key}",
                    s3_key=s3_key,
                    sha256=validation_res.sha256_checksum,
                    mime_type=validation_res.mime_type,
                    file_size=validation_res.file_size_bytes,
                    cached=True,
                )

        # 5. Partitioned S3 object key: attachments/{source_id}/{sha256}.{ext}
        ext = validation_res.file_extension.lstrip(".")
        s3_key = f"attachments/{source_id}/{validation_res.sha256_checksum}.{ext}"

        # 6. Upload stream to S3
        s3_client = self._get_s3_client()
        await s3_client.upload_file(
            file_data=bytes(buffer),
            object_key=s3_key,
            content_type=validation_res.mime_type,
            metadata={
                "source_id": source_id,
                "sha256": validation_res.sha256_checksum,
                "mime_type": validation_res.mime_type,
                "original_url": attachment_url,
            },
        )

        bucket = s3_client.bucket_name
        s3_url = f"s3://{bucket}/{s3_key}"
        logger.info(
            "Document streamed and uploaded to S3: %s (%d bytes, sha: %s)",
            s3_url,
            validation_res.file_size_bytes,
            validation_res.sha256_checksum[:8],
        )

        return DocumentUploadResult(
            s3_url=s3_url,
            s3_key=s3_key,
            sha256=validation_res.sha256_checksum,
            mime_type=validation_res.mime_type,
            file_size=validation_res.file_size_bytes,
            cached=False,
        )

    # [OMA-W006-T005] Helper to stream download with 25 MB ceiling and safe per-hop redirect traversal
    async def _stream_download(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> tuple[bytearray, str | None]:
        """Streams URL enforcing 25 MB maximum byte ceiling and safe redirect traversal."""
        current_url = url
        redirect_hops = 0
        max_redirect_hops = 5
        # [OMA-W004-FIX-CYCLE-2] Canonicalize current URL before circular redirect comparison
        canonical_current = LinkValidatorService.normalize_url(current_url)
        visited: set[str] = {canonical_current}

        while True:
            try:
                stream_ctx = client.stream("GET", current_url, follow_redirects=False)
            except TypeError:
                stream_ctx = client.stream("GET", current_url)

            async with stream_ctx as response:
                is_redirect = response.status_code in (
                    301,
                    302,
                    303,
                    307,
                    308,
                ) or (
                    300 <= response.status_code < 400
                    and getattr(response, "is_redirect", False)
                )

                if is_redirect:
                    redirect_hops += 1
                    if redirect_hops > max_redirect_hops:
                        raise SSRFAttemptBlockedError(
                            f"Maximum redirect hops ({max_redirect_hops}) exceeded during stream download",
                            error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                        )
                    location = response.headers.get("location")
                    if not location:
                        raise SSRFAttemptBlockedError(
                            "Redirect response missing Location header",
                            error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                        )
                    redirect_url = urllib.parse.urljoin(current_url, location).strip()
                    # [OMA-W004-FIX-CYCLE-2] Check canonicalized redirect URL against visited set
                    canonical_redirect = LinkValidatorService.normalize_url(
                        redirect_url
                    )
                    if canonical_redirect in visited:
                        raise SSRFAttemptBlockedError(
                            f"Circular redirect detected to visited URL: {redirect_url}",
                            error_code=ERR_SSRF_ATTEMPT_BLOCKED,
                        )
                    visited.add(canonical_redirect)

                    # Validate target redirect URL against SSRF and IP blocklist
                    validated = await LinkValidatorService.validate_url(
                        redirect_url, allow_redirects=False
                    )
                    current_url = validated.canonical_url
                    continue

                response.raise_for_status()
                content_disposition = response.headers.get("content-disposition")
                buffer = bytearray()
                total_bytes = 0
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    total_bytes += len(chunk)
                    if total_bytes > self.MAX_FILE_SIZE_BYTES:
                        raise FileSizeExceededError(
                            f"File size exceeds 25 MB stream ceiling: {total_bytes} bytes",
                            error_code=ERR_FILE_SIZE_EXCEEDED,
                        )
                    buffer.extend(chunk)

                return buffer, content_disposition

    # [OMA-W005-T037] Ingest direct stream or bytes
    async def ingest_stream(
        self,
        stream: BinaryIO,
        source_id: str,
        filename: str | None = None,
        source_url: str = "",
        content_disposition: str | None = None,
    ) -> DocumentUploadResult:
        """Validates and uploads an existing in-memory stream to S3."""
        validation_res = self._file_validator.validate_stream(
            stream=stream,
            filename=filename,
            source_id=source_id,
            content_disposition=content_disposition,
            source_url=source_url,
            raise_on_error=True,
        )

        # Check repository cache by sha256
        if self._repository is not None:
            cached_sha = await self._repository.find_existing_attachment_metadata(
                sha256_checksum=validation_res.sha256_checksum
            )
            if cached_sha and cached_sha.get("attachment_s3_key"):
                s3_key = str(cached_sha["attachment_s3_key"])
                bucket = self._get_bucket_name()
                return DocumentUploadResult(
                    s3_url=f"s3://{bucket}/{s3_key}",
                    s3_key=s3_key,
                    sha256=validation_res.sha256_checksum,
                    mime_type=validation_res.mime_type,
                    file_size=validation_res.file_size_bytes,
                    cached=True,
                )

        ext = validation_res.file_extension.lstrip(".")
        s3_key = f"attachments/{source_id}/{validation_res.sha256_checksum}.{ext}"

        # Rewind and read stream
        if hasattr(stream, "seek"):
            stream.seek(0)
        data = stream.read()

        s3_client = self._get_s3_client()
        await s3_client.upload_file(
            file_data=data,
            object_key=s3_key,
            content_type=validation_res.mime_type,
            metadata={
                "source_id": source_id,
                "sha256": validation_res.sha256_checksum,
                "mime_type": validation_res.mime_type,
                "original_url": source_url,
            },
        )

        bucket = s3_client.bucket_name
        return DocumentUploadResult(
            s3_url=f"s3://{bucket}/{s3_key}",
            s3_key=s3_key,
            sha256=validation_res.sha256_checksum,
            mime_type=validation_res.mime_type,
            file_size=validation_res.file_size_bytes,
            cached=False,
        )
