import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from prisma import Json, Prisma

logger = logging.getLogger(__name__)


class OpportunityRepository:
    """يكتب الفرص الخام والنظيفة في قاعدة بيانات بايثون."""

    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def create_raw(
        self,
        source_id: str,
        raw_payload: dict[str, Any],
        status: str = "pending",
        source_url: str | None = None,
    ) -> Any:
        """يخزّن فرصة خام كما وردت من المصدر."""
        data: dict[str, Any] = {
            "source_id": source_id,
            "raw_payload": Json(raw_payload),
            "status": status,
        }
        if source_url is not None:
            data["source_url"] = source_url
        return await self._db.rawopportunity.create(data=data)  # type: ignore[arg-type]

    async def create_many_raw(
        self, source_id: str, payloads: list[dict[str, Any]]
    ) -> list[Any]:
        """يخزّن دفعة من الفرص الخام ويرجع السجلات المنشأة."""
        created = []
        for payload in payloads:
            created.append(await self.create_raw(source_id, payload))

        logger.info(
            "Stored %d raw opportunities for source %s", len(created), source_id
        )
        return created

    async def mark_raw_status(
        self, raw_id: str, status: str, error_message: str | None = None
    ) -> Any:
        """يحدّث حالة معالجة فرصة خام."""
        return await self._db.rawopportunity.update(
            where={"id": raw_id},
            data={"status": status, "error_message": error_message},
        )

    async def create_cleaned(self, data: dict[str, Any]) -> Any:
        """يخزّن فرصة نظيفة. يتوقع raw_opportunity_id و title و source_url."""
        payload = dict(data)
        if "eligibility" in payload and payload["eligibility"] is not None:
            payload["eligibility"] = Json(payload["eligibility"])

        return await self._db.cleanedopportunity.create(data=payload)  # type: ignore[arg-type]

    async def exists_by_content_hash(self, content_hash: str) -> bool:
        """يفحص وجود فرصة نظيفة بنفس البصمة (لمنع التكرار)."""
        found = await self._db.cleanedopportunity.find_first(
            where={"content_hash": content_hash}
        )
        return found is not None

    async def count_cleaned_by_source(self, source_id: str) -> int:
        """يعدّ الفرص النظيفة لمصدر معيّن."""
        return await self._db.cleanedopportunity.count(where={"source_id": source_id})

    async def find_within_visibility_window(
        self,
        now: date | datetime | None = None,
        retention_days: int = 30,
        include_null_deadlines: bool = True,
    ) -> list[Any]:
        """يسترجع الفرص النظيفة التي تقع ضمن نافذة الرؤية (المفتوحة + المغلقة خلال 30 يوماً).

        تعتمد المقارنة على تاريخ اليوم بالتقويم (Date-Only).
        تستثنى الفرص التي مر على موعدها النهائي أكثر من 30 يوماً.
        لا تقوم هذه الدالة بتعديل أو تحديث أي سجلات في قاعدة البيانات (Read-Only).
        """
        if now is None:
            current_date = datetime.now(UTC).date()
        elif isinstance(now, datetime):
            current_date = now.date()
        else:
            current_date = now

        cutoff_date = current_date - timedelta(days=retention_days)
        cutoff_dt = datetime.combine(cutoff_date, datetime.min.time()).replace(
            tzinfo=UTC
        )

        where: dict[str, Any]
        if include_null_deadlines:
            where = {
                "OR": [
                    {"deadline": {"gte": cutoff_dt}},
                    {"deadline": None},
                ]
            }
        else:
            where = {"deadline": {"gte": cutoff_dt}}

        return await self._db.cleanedopportunity.find_many(where=where)  # type: ignore[arg-type]
