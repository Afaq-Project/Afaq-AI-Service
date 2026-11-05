# [OMA-W001-T001] Foundational domain models for security module

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# [OMA-W001-T001] Verified destination URL domain model
class ValidatedUrl(BaseModel):
    """Represents an immutable, verified destination URL that has passed RFC 3986

    syntax validation, port/scheme filtering, Anti-SSRF inspection, and safe
    redirect resolution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    original_url: str
    canonical_url: str
    scheme: Literal["http", "https"]
    host: str
    port: int
    resolved_ip: str
    is_https: bool
    redirect_hops: int = 0
    redirect_chain: list[str] = Field(default_factory=list)
    dns_pinned_rule: str
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# [OMA-W001-T001] File and attachment validation result model
class FileValidationResult(BaseModel):
    """Outcome of attachment downloading and binary magic-byte inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    source_url: str = ""
    mime_type: str = ""
    file_extension: str = ""
    file_size_bytes: int = 0
    sha256_checksum: str = ""
    suggested_s3_key: str = ""
    magic_bytes_hex: str = ""
    error_code: str | None = None
    rejection_reason: str | None = None
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# [OMA-W001-T001] Template schema validation result model
class TemplateSchemaValidationResult(BaseModel):
    """Outcome of extraction template schema and CSS selector safety inspection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_valid: bool
    schema_name: str
    selector_count: int
    selectors_validated: list[str] = Field(default_factory=list)
    dry_run_latency_ms: float = 0.0
    error_code: str | None = None
    rejection_reason: str | None = None
    failing_selector: str | None = None
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# [OMA-W001-T001] Request body model for diagnostic inspect-url endpoint
class InspectUrlRequest(BaseModel):
    """Request payload for the URL security inspection diagnostic endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    base_url: str | None = None
    allow_redirects: bool = True


# [OMA-W001-T001] Response envelope model for diagnostic inspect-url endpoint
class InspectUrlResponse(BaseModel):
    """Response payload for the URL security inspection diagnostic endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: str = "success"
    data: ValidatedUrl
    message: str = "URL verified as safe."
