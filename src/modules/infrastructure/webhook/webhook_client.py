import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from ..http.base_http_client import BaseHttpClient
from ..http.exceptions import HttpClientError
from ..http.retry_strategy import RetryStrategy

logger = logging.getLogger(__name__)


class ScrapeCompletePayload(BaseModel):
    """حمولة إشعار اكتمال الجلب المرسلة للخدمة الرئيسية."""

    batch_id: str
    total_opportunities: int = Field(ge=0)
    succeeded_sources: list[str] = Field(default_factory=list)
    failed_sources: list[str] = Field(default_factory=list)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MatchingCompletePayload(BaseModel):
    """Payload for notifying the main backend when a matching operation completes."""

    operation_type: str  # "user_matching" | "opportunity_matching" | "full_rematch"
    operation_id: str
    user_id: str | None = None
    opportunity_id: str | None = None
    status: str = "success"
    matches_count: int = Field(default=0, ge=0)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)


class WebhookClient:
    """يرسل إشعارات إلى الخدمة الرئيسية عند اكتمال العمليات."""

    def __init__(
        self,
        webhook_url: str,
        secret: str = "",
        timeout: float = 15.0,
        http_client: BaseHttpClient | None = None,
    ) -> None:
        self._url = webhook_url
        self._secret = secret
        self._http = http_client or BaseHttpClient(
            timeout=timeout,
            retry_strategy=RetryStrategy(
                max_attempts=4, base_delay=1.0, max_delay=10.0
            ),
        )

    async def close(self) -> None:
        await self._http.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._secret:
            headers["X-Webhook-Secret"] = self._secret
        return headers

    async def notify_scrape_complete(self, payload: ScrapeCompletePayload) -> bool:
        """يرسل إشعار اكتمال الجلب. يرجع True عند النجاح و False عند الفشل النهائي."""
        if not self._url:
            logger.warning("Webhook URL not configured; skipping notification")
            return False

        try:
            await self._http.post(
                self._url,
                content=payload.model_dump_json(),
                headers=self._headers(),
            )
        except HttpClientError:
            logger.exception("Webhook delivery failed for batch %s", payload.batch_id)
            return False

        logger.info(
            "Webhook delivered for batch %s (%d opportunities)",
            payload.batch_id,
            payload.total_opportunities,
        )
        return True

    async def notify_matching_complete(self, payload: MatchingCompletePayload) -> bool:
        """يرسل إشعار اكتمال المطابقة للخدمة الرئيسية.

        يرجع True عند النجاح و False عند الفشل النهائي.
        لا يرفع استثناءً: فشل الإشعار لا يجب أن يُفشل عملية المطابقة الناجحة.
        """
        if not self._url:
            logger.warning("Matching Webhook URL not configured; skipping notification")
            return False

        try:
            await self._http.post(
                self._url,
                content=payload.model_dump_json(),
                headers=self._headers(),
            )
        except HttpClientError:
            logger.exception(
                "Matching webhook delivery failed for operation %s",
                payload.operation_id,
            )
            return False

        logger.info(
            "Matching webhook delivered for operation %s (%s, %d matches)",
            payload.operation_id,
            payload.operation_type,
            payload.matches_count,
        )
        return True
