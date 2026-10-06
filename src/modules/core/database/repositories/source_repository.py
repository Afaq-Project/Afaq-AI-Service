import logging
from datetime import UTC, datetime
from typing import Any

from prisma import Prisma

logger = logging.getLogger(__name__)


class SourceRepository:
    """يقرأ المصادر التقنية من قاعدة بيانات بايثون."""

    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def get_by_ids(self, source_ids: list[str]) -> list[Any]:
        """يجلب المصادر المطابقة للمعرفات الواردة في طلب الجلب."""
        if not source_ids:
            return []

        sources = await self._db.source.find_many(where={"id": {"in": source_ids}})

        found_ids = {s.id for s in sources}
        missing = set(source_ids) - found_ids
        if missing:
            logger.warning("Source ids not found: %s", ", ".join(sorted(missing)))

        return sources

    async def get_by_id(self, source_id: str) -> Any | None:
        return await self._db.source.find_unique(where={"id": source_id})

    async def get_by_name(self, name: str) -> Any | None:
        """يجلب مصدراً بمعرّفه النصي (مثل almin7)."""
        return await self._db.source.find_unique(where={"name": name})

    async def list_all(self) -> list[Any]:
        return await self._db.source.find_many()

    async def mark_scraped(self, source_id: str) -> Any:
        """يسجّل وقت آخر عملية جلب ناجحة للمصدر."""
        return await self._db.source.update(
            where={"id": source_id},
            data={"last_scraped_at": datetime.now(UTC)},
        )

    async def update_last_listing_hash(self, source_id: str, listing_hash: str) -> Any:
        """يسجل هاش محتوى صفحة الـ Listing الأخيرة داخل حقل pagination_config JSON بدون تعديل DB Schema."""
        source = await self.get_by_id(source_id)
        if not source:
            return None
        current_config = dict(getattr(source, "pagination_config", {}) or {})
        current_config["last_listing_hash"] = listing_hash
        return await self._db.source.update(
            where={"id": source_id},
            data={"pagination_config": current_config},
        )
