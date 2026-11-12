# [OMA-W006-T006] Operations repository operations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from prisma.models import ScrapeOperation

from prisma import Prisma

from .dto import to_json

logger = logging.getLogger(__name__)


class OperationsRepositoryMixin:
    """Operations for ScrapeOperation execution tracking, telemetry, and status."""

    _db: Prisma

    async def create_operation(
        self,
        idempotency_key: str | None = None,
        triggered_by: str = "admin_api",
        sources_attempted: list[str] | None = None,
    ) -> ScrapeOperation:
        """Create a new ScrapeOperation record."""
        return await self._db.scrapeoperation.create(
            data={
                "idempotency_key": idempotency_key,
                "status": "running",
                "triggered_by": triggered_by,
                "sources_attempted": sources_attempted or [],
                "sources_succeeded": [],
                "sources_failed": [],
                "total_listings_found": 0,
                "total_details_extracted": 0,
                "total_files_downloaded": 0,
                "error_summary": to_json({}),
            }  # type: ignore[arg-type]
        )

    async def get_operation_by_id(self, operation_id: str) -> ScrapeOperation | None:
        """Retrieve ScrapeOperation by UUID."""
        return await self._db.scrapeoperation.find_unique(where={"id": operation_id})

    async def get_operation_by_idempotency_key(
        self, idempotency_key: str, within_minutes: int = 15
    ) -> ScrapeOperation | None:
        """Find an operation with the given idempotency key started within sliding window."""
        cutoff = datetime.now(UTC) - timedelta(minutes=within_minutes)
        return await self._db.scrapeoperation.find_first(
            where={
                "idempotency_key": idempotency_key,
                "started_at": {"gte": cutoff},
            }
        )

    async def get_latest_operation(self) -> ScrapeOperation | None:
        """Retrieve currently running operation, or the latest historical operation."""
        running = await self._db.scrapeoperation.find_first(
            where={"status": "running"},
            order={"started_at": "desc"},
        )
        if running:
            return running

        return await self._db.scrapeoperation.find_first(order={"started_at": "desc"})

    async def list_operations(
        self,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ScrapeOperation]:
        """Fetch paginated operations ordered reverse-chronologically."""
        where: dict[str, Any] = {}
        if status is not None:
            where["status"] = status

        return await self._db.scrapeoperation.find_many(
            where=where,
            take=limit,
            skip=offset,
            order={"started_at": "desc"},
        )

    async def count_operations(self, status: str | None = None) -> int:
        """Count operations matching optional status filter."""
        where: dict[str, Any] = {}
        if status is not None:
            where["status"] = status
        return await self._db.scrapeoperation.count(where=where)

    async def update_operation_status(
        self,
        operation_id: str,
        status: str,
        completed: bool = False,
    ) -> ScrapeOperation | None:
        """Update operation status."""
        data: dict[str, Any] = {"status": status}
        if completed:
            data["completed_at"] = datetime.now(UTC)

        try:
            return await self._db.scrapeoperation.update(
                where={"id": operation_id},
                data=data,
            )
        except Exception as exc:
            logger.warning(
                "Could not update status for operation %s: %s",
                operation_id,
                exc,
            )
            return None

    async def update_operation_counts(
        self,
        operation_id: str,
        listings_found: int | None = None,
        details_extracted: int | None = None,
        files_downloaded: int | None = None,
    ) -> ScrapeOperation | None:
        """Update telemetry counts on an operation."""
        data: dict[str, Any] = {}
        if listings_found is not None:
            data["total_listings_found"] = listings_found
        if details_extracted is not None:
            data["total_details_extracted"] = details_extracted
        if files_downloaded is not None:
            data["total_files_downloaded"] = files_downloaded

        if not data:
            return await self.get_operation_by_id(operation_id)

        try:
            return await self._db.scrapeoperation.update(
                where={"id": operation_id},
                data=data,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                "Could not update counts for operation %s: %s",
                operation_id,
                exc,
            )
            return None

    async def update_operation_progress(
        self,
        operation_id: str,
        *,
        status: str | None = None,
        listings_found: int | None = None,
        details_extracted: int | None = None,
        files_downloaded: int | None = None,
        sources_succeeded: list[str] | None = None,
        sources_failed: list[str] | None = None,
        error_summary: dict[str, Any] | None = None,
        completed: bool = False,
    ) -> ScrapeOperation | None:
        """Update multiple telemetry and outcome fields on an operation."""
        data: dict[str, Any] = {}
        if status is not None:
            data["status"] = status
        if listings_found is not None:
            data["total_listings_found"] = listings_found
        if details_extracted is not None:
            data["total_details_extracted"] = details_extracted
        if files_downloaded is not None:
            data["total_files_downloaded"] = files_downloaded
        if sources_succeeded is not None:
            data["sources_succeeded"] = sources_succeeded
        if sources_failed is not None:
            data["sources_failed"] = sources_failed
        if error_summary is not None:
            data["error_summary"] = to_json(error_summary)
        if completed:
            data["completed_at"] = datetime.now(UTC)

        if not data:
            return await self.get_operation_by_id(operation_id)

        try:
            return await self._db.scrapeoperation.update(
                where={"id": operation_id},
                data=data,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                "Could not update progress for operation %s: %s",
                operation_id,
                exc,
            )
            return None
