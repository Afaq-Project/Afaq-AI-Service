# [OMA-W001-T001] Foundational exception hierarchy for security module

from typing import Any

# Standard security error codes
ERR_INVALID_URL_SYNTAX = "ERR_INVALID_URL_SYNTAX"
ERR_INVALID_SCHEME = "ERR_INVALID_SCHEME"
ERR_INVALID_PORT = "ERR_INVALID_PORT"
ERR_PATH_TRAVERSAL = "ERR_PATH_TRAVERSAL"
ERR_HOMOGRAPH_ATTACK = "ERR_HOMOGRAPH_ATTACK"
ERR_SSRF_ATTEMPT_BLOCKED = "ERR_SSRF_ATTEMPT_BLOCKED"
ERR_CIRCULAR_REDIRECT = "ERR_CIRCULAR_REDIRECT"
ERR_MAX_REDIRECTS_EXCEEDED = "ERR_MAX_REDIRECTS_EXCEEDED"
ERR_RATE_LIMITED_COOLDOWN = "ERR_RATE_LIMITED_COOLDOWN"
ERR_MALICIOUS_FILE_TYPE = "ERR_MALICIOUS_FILE_TYPE"
ERR_FILE_SIZE_EXCEEDED = "ERR_FILE_SIZE_EXCEEDED"
ERR_ZIP_BOMB_DETECTED = "ERR_ZIP_BOMB_DETECTED"
ERR_SCHEMA_SHAPE_INVALID = "ERR_SCHEMA_SHAPE_INVALID"
ERR_SELECTOR_SYNTAX_INVALID = "ERR_SELECTOR_SYNTAX_INVALID"
ERR_CSS_SELECTOR_REDOS_TIMEOUT = "ERR_CSS_SELECTOR_REDOS_TIMEOUT"


# [OMA-W001-T001] Base exception for all security module errors
class SecurityValidationError(Exception):
    """Base exception for all security validation errors."""

    def __init__(
        self,
        message: str = "Security validation error",
        error_code: str = "ERR_SECURITY_VALIDATION",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(error_code={self.error_code!r}, message={self.message!r})"


# [OMA-W001-T001] Link validation: invalid syntax
class InvalidUrlSyntaxError(SecurityValidationError):
    """Raised when URL syntax does not conform to RFC 3986."""

    def __init__(
        self,
        message: str = "Invalid URL syntax",
        error_code: str = ERR_INVALID_URL_SYNTAX,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Link validation: invalid scheme
class InvalidUrlSchemeError(SecurityValidationError):
    """Raised when URL scheme is not http or https, or missing when required."""

    def __init__(
        self,
        message: str = "Invalid URL scheme. Only http and https are allowed.",
        error_code: str = ERR_INVALID_SCHEME,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Network security: invalid port
class InvalidUrlPortError(SecurityValidationError):
    """Raised when URL port is not strictly 80 or 443."""

    def __init__(
        self,
        message: str = "Invalid URL port. Only ports 80 and 443 are allowed.",
        error_code: str = ERR_INVALID_PORT,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Link validation: path traversal
class PathTraversalError(SecurityValidationError):
    """Raised when path traversal sequences (../, %2e%2e) are detected."""

    def __init__(
        self,
        message: str = "Path traversal token detected in URL",
        error_code: str = ERR_PATH_TRAVERSAL,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Link security: homograph attack
class HomographAttackError(SecurityValidationError):
    """Raised when deceptive mixed-script domain names are detected."""

    def __init__(
        self,
        message: str = "IDN homograph attack detected",
        error_code: str = ERR_HOMOGRAPH_ATTACK,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Network security: SSRF attempt blocked
class SSRFAttemptBlockedError(SecurityValidationError):
    """Raised when destination IP belongs to private, loopback, or cloud metadata CIDRs."""

    def __init__(
        self,
        message: str = "SSRF attempt blocked: destination IP is in a private, loopback, or cloud metadata CIDR",
        error_code: str = ERR_SSRF_ATTEMPT_BLOCKED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Network traversal: circular redirect
class CircularRedirectError(SecurityValidationError):
    """Raised when a redirect loop is detected."""

    def __init__(
        self,
        message: str = "Circular redirect loop detected",
        error_code: str = ERR_CIRCULAR_REDIRECT,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Network traversal: max redirects exceeded
class MaxRedirectsExceededError(SecurityValidationError):
    """Raised when redirect chain exceeds maximum allowed hops (5)."""

    def __init__(
        self,
        message: str = "Maximum redirect hops (5) exceeded",
        error_code: str = ERR_MAX_REDIRECTS_EXCEEDED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Rate limiting: cooldown required
class RateLimitedCooldownError(SecurityValidationError):
    """Raised when server responds with 429/503 and Retry-After exceeding threshold."""

    def __init__(
        self,
        message: str = "Rate limit cooldown required",
        error_code: str = ERR_RATE_LIMITED_COOLDOWN,
        details: dict[str, Any] | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)
        self.retry_after = retry_after


# [OMA-W001-T001] Attachment safety: malicious file type
class MaliciousFileTypeError(SecurityValidationError):
    """Raised when file magic bytes match executable or disallowed formats."""

    def __init__(
        self,
        message: str = "Malicious or disallowed file type detected",
        error_code: str = ERR_MALICIOUS_FILE_TYPE,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Resource safety: file size exceeded
class FileSizeExceededError(SecurityValidationError):
    """Raised when file stream exceeds maximum allowed size (25 MB)."""

    def __init__(
        self,
        message: str = "File size exceeds the 25 MB stream limit",
        error_code: str = ERR_FILE_SIZE_EXCEEDED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Attachment safety: zip bomb detected
class ZipBombDetectedError(SecurityValidationError):
    """Raised when zip archive exceeds compression ratio or uncompressed size limits."""

    def __init__(
        self,
        message: str = "Zip bomb decompression hazard detected",
        error_code: str = ERR_ZIP_BOMB_DETECTED,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Schema safety: invalid shape
class SchemaShapeInvalidError(SecurityValidationError):
    """Raised when extraction schema fails Pydantic structural validation."""

    def __init__(
        self,
        message: str = "Extraction schema shape is invalid",
        error_code: str = ERR_SCHEMA_SHAPE_INVALID,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] Selector safety: syntax invalid
class SelectorSyntaxInvalidError(SecurityValidationError):
    """Raised when CSS selector syntax is invalid or fails compilation."""

    def __init__(
        self,
        message: str = "CSS selector syntax is invalid",
        error_code: str = ERR_SELECTOR_SYNTAX_INVALID,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)


# [OMA-W001-T001] ReDoS defense: selector timeout or complexity exceeded
class CssSelectorReDosTimeoutError(SecurityValidationError):
    """Raised when CSS selector exceeds complexity bounds or evaluation timeout (200ms)."""

    def __init__(
        self,
        message: str = "CSS selector evaluation exceeded ReDoS complexity or timeout threshold",
        error_code: str = ERR_CSS_SELECTOR_REDOS_TIMEOUT,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, error_code=error_code, details=details)
