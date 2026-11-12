# [OMA-W005-T003] Standardized domain error codes and exceptions for scraping module

from typing import Any

# [OMA-W005-T003] Standardized domain error code constants
ERR_NOT_OPPORTUNITY_PORTAL = "ERR_NOT_OPPORTUNITY_PORTAL"
ERR_ACCESS_CHALLENGE_BLOCKED = "ERR_ACCESS_CHALLENGE_BLOCKED"
ERR_RATE_LIMITED_COOLDOWN = "ERR_RATE_LIMITED_COOLDOWN"
ERR_OPERATION_TIMEOUT = "ERR_OPERATION_TIMEOUT"
ERR_CSS_SELECTOR_REDOS_TIMEOUT = "ERR_CSS_SELECTOR_REDOS_TIMEOUT"
ERR_TEMPLATE_NOT_FOUND = "ERR_TEMPLATE_NOT_FOUND"
ERR_EXTRACTION_FAILED = "ERR_EXTRACTION_FAILED"
ERR_SOURCE_NOT_FOUND = "ERR_SOURCE_NOT_FOUND"
ERR_SOURCE_LOCKED = "ERR_SOURCE_LOCKED"
ERR_IRRELEVANT_CONTENT_REJECTED = "ERR_IRRELEVANT_CONTENT_REJECTED"
ERR_PAGINATION_LOOP_DETECTED = "ERR_PAGINATION_LOOP_DETECTED"
ERR_MALICIOUS_FILE_TYPE = "ERR_MALICIOUS_FILE_TYPE"
ERR_ZIP_BOMB_DETECTED = "ERR_ZIP_BOMB_DETECTED"
ERR_SSRF_ATTEMPT_BLOCKED = "ERR_SSRF_ATTEMPT_BLOCKED"


# [OMA-W005-T003] Base exception for all scraping module errors
class ScrapingException(Exception):
    """Base exception for all scraping and extraction pipeline errors."""

    def __init__(
        self,
        message: str = "Scraping pipeline error",
        code: str = "ERR_SCRAPING_PIPELINE",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.error_code = code
        self.details = details or {}

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(code={self.code!r}, message={self.message!r})"
        )


# [OMA-W005-T003] Alias for ScrapingException hierarchy compatibility
ScrapingError = ScrapingException


# [OMA-W005-T003] Domain error: Stage 0 relevance check failed
class NotOpportunityPortalError(ScrapingException):
    """Raised when target domain is not an educational opportunity or scholarship portal."""

    def __init__(
        self,
        message: str = "Target website does not contain educational opportunities",
        code: str = ERR_NOT_OPPORTUNITY_PORTAL,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: Cloudflare Turnstile, CAPTCHA, or bot challenge encountered
class AccessChallengeBlockedError(ScrapingException):
    """Raised when the crawler encounters an anti-bot access challenge (Cloudflare, CAPTCHA)."""

    def __init__(
        self,
        message: str = "Crawl blocked by access challenge or bot protection",
        code: str = ERR_ACCESS_CHALLENGE_BLOCKED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: HTTP 429/503 rate-limiting cooldown triggered
class RateLimitedCooldownError(ScrapingException):
    """Raised when remote host imposes rate-limiting (HTTP 429/503) requiring cooldown."""

    def __init__(
        self,
        message: str = "Target host rate-limited requests; cooldown initiated",
        code: str = ERR_RATE_LIMITED_COOLDOWN,
        details: dict[str, Any] | None = None,
        cool_down_seconds: float | None = None,
    ) -> None:
        details_payload = dict(details or {})
        if cool_down_seconds is not None:
            details_payload["cool_down_seconds"] = cool_down_seconds
        super().__init__(message=message, code=code, details=details_payload)
        self.cool_down_seconds = cool_down_seconds


# [OMA-W005-T003] Domain error: Operation hard timeout ceiling breached
class OperationTimeoutError(ScrapingException):
    """Raised when scraping operation breaches the operation-level hard timeout ceiling."""

    def __init__(
        self,
        message: str = "Scrape operation exceeded maximum allowed timeout ceiling",
        code: str = ERR_OPERATION_TIMEOUT,
        details: dict[str, Any] | None = None,
        timeout_sec: int | None = None,
    ) -> None:
        details_payload = dict(details or {})
        if timeout_sec is not None:
            details_payload["timeout_sec"] = timeout_sec
        super().__init__(message=message, code=code, details=details_payload)
        self.timeout_sec = timeout_sec


# [OMA-W005-T003] Domain error: CSS selector evaluation timed out (ReDoS / complex backtracking)
class CSSSelectorReDoSTimeoutError(ScrapingException):
    """Raised when CSS selector evaluation times out during dry-run or extraction."""

    def __init__(
        self,
        message: str = "CSS selector execution exceeded evaluation timeout ceiling",
        code: str = ERR_CSS_SELECTOR_REDOS_TIMEOUT,
        details: dict[str, Any] | None = None,
        failing_selector: str | None = None,
    ) -> None:
        details_payload = dict(details or {})
        if failing_selector is not None:
            details_payload["failing_selector"] = failing_selector
        super().__init__(message=message, code=code, details=details_payload)
        self.failing_selector = failing_selector


# [OMA-W005-T003] Domain error: Matching template not found in pool
class TemplateNotFoundError(ScrapingException):
    """Raised when no matching template exists in historical pool and synthesis is needed."""

    def __init__(
        self,
        message: str = "No matching template found for target page layout",
        code: str = ERR_TEMPLATE_NOT_FOUND,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: Extraction attempt failed
class ExtractionFailedError(ScrapingException):
    """Raised when extraction strategy fails on target page DOM."""

    def __init__(
        self,
        message: str = "Data extraction failed for target page",
        code: str = ERR_EXTRACTION_FAILED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: Source configuration not found
class SourceNotFoundError(ScrapingException):
    """Raised when specified source entity or configuration does not exist in registry."""

    def __init__(
        self,
        message: str = "Target source not found in registry",
        code: str = ERR_SOURCE_NOT_FOUND,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: Source is locked by another active operation
class SourceLockedError(ScrapingException):
    """Raised when attempting to scrape a source that is currently locked by another worker."""

    def __init__(
        self,
        message: str = "Target source is currently locked by an active crawl operation",
        code: str = ERR_SOURCE_LOCKED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: Extracted content rejected as irrelevant
class IrrelevantContentRejectedError(ScrapingException):
    """Raised when extracted content does not qualify as an educational grant or scholarship."""

    def __init__(
        self,
        message: str = "Extracted content does not meet opportunity relevance criteria",
        code: str = ERR_IRRELEVANT_CONTENT_REJECTED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)


# [OMA-W005-T003] Domain error: Circular or stagnant pagination loop detected
class PaginationLoopDetectedError(ScrapingException):
    """Raised when pagination traversal detects a circular or stagnant card fingerprint loop."""

    def __init__(
        self,
        message: str = "Circular or stagnant pagination loop detected across catalog pages",
        code: str = ERR_PAGINATION_LOOP_DETECTED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, details=details)
