import logging
from abc import ABC, abstractmethod
from typing import Any, Self

from src.modules.infrastructure.http.base_http_client import BaseHttpClient

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """الواجهة الموحدة لعقد جميع محولات مصادر البيانات (Adapters Contract)."""

    source_name: str = "base"
    base_url: str = ""
    api_endpoint: str = ""
    source_id: str = ""

    def __init__(
        self,
        source_config: dict[str, Any] | None = None,
        http_client: BaseHttpClient | None = None,
        source_id: str | None = None,
        source_name: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.config = source_config or {}
        self.source_id = source_id or self.config.get("id") or ""
        if source_name:
            self.source_name = source_name
        elif self.config.get("name"):
            self.source_name = self.config["name"]

        if base_url:
            self.base_url = base_url.rstrip("/")
        elif self.config.get("base_url"):
            self.base_url = self.config["base_url"].rstrip("/")

        if self.config.get("api_endpoint") is not None:
            self.api_endpoint = self.config["api_endpoint"]
        self.pagination_config = self.config.get("pagination_config") or {}
        self.field_mapping = self.config.get("field_mapping") or {}

        self.http_client = http_client or BaseHttpClient(
            base_url=self.base_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json, text/html, */*",
            },
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        """يغلق عميل الـ HTTP."""
        if self.http_client:
            await self.http_client.close()

    def is_opportunity(self, raw_item: dict[str, Any]) -> bool:
        """يحدد هل العنصر الخام يمثل فرصة حقيقية أم مقالاً عاماً / خبراً."""
        return True

    @abstractmethod
    async def fetch(self, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        """يجلب قائمة السجلات الخام من المصدر."""
        pass

    async def fetch_with_details(self, limit: int = 20, page: int = 1) -> list[dict[str, Any]]:
        """Default implementation delegating to fetch.

        Adapters that need detailed fetching can override this method.
        """
        return await self.fetch(limit=limit, page=page)
