class LLMError(Exception):
    code = "ai_error"
    status_code = 500


class LLMTimeoutError(LLMError):
    code = "ai_timeout"
    status_code = 504


class LLMRateLimitError(LLMError):
    code = "ai_busy"
    status_code = 429


class LLMUnavailableError(LLMError):
    code = "ai_unavailable"
    status_code = 503


class LLMRefusalError(LLMError):
    code = "ai_refused"
    status_code = 422


class LLMIncompleteResponseError(LLMError):
    code = "ai_incomplete"
    status_code = 502
