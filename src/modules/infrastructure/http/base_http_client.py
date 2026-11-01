import logging
from typing import Any, Self

import httpx

from .exceptions import (
    HttpClientError,
    HttpConnectionError,
    HttpRateLimitError,
    HttpResponseError,
    HttpTimeoutError,
)
from .retry_strategy import RetryStrategy

logger = logging.getLogger(__name__)


class BaseHttpClient:
    """عميل HTTP غير متزامن موحد مع إعادة محاولة ومعالجة أخطاء."""

    def __init__(
        self,
        base_url: str = "",
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        retry_strategy: RetryStrategy | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._retry = retry_strategy or RetryStrategy()
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            headers=headers or {},
            follow_redirects=True,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        response = await self.get(url, **kwargs)
        return response.json()

    def _handle_request_exception(
        self, exc: Exception, method: str, url: str, attempt: int
    ) -> Exception:
        if isinstance(exc, httpx.TimeoutException):
            err: Exception = HttpTimeoutError(f"Timeout on {method} {url}")
        else:
            err = HttpConnectionError(f"Connection failed on {method} {url}")
        if not self._retry.should_retry(attempt, None):
            raise err from exc
        return err

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        last_error: Exception | None = None

        while attempt < self._retry.max_attempts:
            attempt += 1
            try:
                response = await self._client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_error = self._handle_request_exception(exc, method, url, attempt)
            else:
                if response.is_success:
                    return response

                last_error = self._build_error(response)
                if not self._retry.should_retry(attempt, response.status_code):
                    raise last_error

            logger.warning(
                "Retrying %s %s (attempt %d/%d)",
                method,
                url,
                attempt,
                self._retry.max_attempts,
            )
            await self._retry.wait(attempt)

        raise last_error or HttpClientError(f"Request failed: {method} {url}")

    @staticmethod
    def _build_error(response: httpx.Response) -> HttpResponseError:
        error_type = (
            HttpRateLimitError if response.status_code == 429 else HttpResponseError
        )
        return error_type(
            status_code=response.status_code,
            message=response.text[:200],
            url=str(response.request.url),
        )
