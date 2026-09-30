import anthropic
from google.api_core import exceptions as google_exceptions

from .exceptions import (
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
    LLMUnavailableError,
)

TIMEOUT_ERRORS = (
    anthropic.APITimeoutError,
    google_exceptions.DeadlineExceeded,
    TimeoutError,
)

RATE_LIMIT_ERRORS = (
    anthropic.RateLimitError,
    google_exceptions.ResourceExhausted,
    google_exceptions.TooManyRequests,
)

UNAVAILABLE_ERRORS = (
    anthropic.APIConnectionError,
    google_exceptions.ServiceUnavailable,
    google_exceptions.InternalServerError,
    google_exceptions.ServerError,
)


def translate_error(exc: BaseException) -> LLMError:
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, TIMEOUT_ERRORS):
        return LLMTimeoutError(str(exc) or "request timed out")
    if isinstance(exc, RATE_LIMIT_ERRORS):
        return LLMRateLimitError(str(exc))
    if isinstance(exc, UNAVAILABLE_ERRORS):
        return LLMUnavailableError(str(exc))
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return LLMUnavailableError(str(exc))
    return LLMError(f"{type(exc).__name__}: {exc}")
