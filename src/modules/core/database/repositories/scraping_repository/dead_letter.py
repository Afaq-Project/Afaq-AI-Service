# [OMA-W006-T006] Dead letter queue repository operations

import logging
from typing import Any

from prisma import Prisma

logger = logging.getLogger(__name__)


class DeadLetterRepositoryMixin:
    """Operations for querying permanently failed records from DLQ."""

    _db: Prisma

    async def fetch_dead_letter_queue(
        self,
        entity_type: str = "listings",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        """Fetch permanently failed items from RawListing or RawGrantDetail.

        Returns tuple of (items, total_count).
        """
        if entity_type == "details":
            where: dict[str, Any] = {
                "OR": [
                    {"status": "failed_permanently"},
                    {"retry_count": {"gte": 3}},
                ]
            }
            items = await self._db.rawgrantdetail.find_many(
                where=where,
                take=limit,
                skip=offset,
                order={"scraped_at": "desc"},
            )
            total_count = await self._db.rawgrantdetail.count(where=where)
            return items, total_count

        # Default: listings
        where_listings: dict[str, Any] = {
            "OR": [
                {"status": "failed_permanently"},
                {"retry_count": {"gte": 3}},
            ]
        }
        items = await self._db.rawlisting.find_many(
            where=where_listings,
            take=limit,
            skip=offset,
            order={"scraped_at": "desc"},
        )
        total_count = await self._db.rawlisting.count(where=where_listings)
        return items, total_count
