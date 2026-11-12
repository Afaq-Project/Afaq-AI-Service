# [OMA-W006-T006] Public facade for ScrapingRepository package

from typing import Any

from prisma import Prisma

from .dead_letter import DeadLetterRepositoryMixin
from .dto import GrantDetailCreateInput, to_json
from .grants import GrantsRepositoryMixin
from .operations import OperationsRepositoryMixin
from .sources import SourcesRepositoryMixin

# Backward compatibility alias
_to_json = to_json


class ScrapingRepository(
    SourcesRepositoryMixin,
    GrantsRepositoryMixin,
    OperationsRepositoryMixin,
    DeadLetterRepositoryMixin,
):
    """Data access repository for scraping, extraction, templates, and telemetry."""

    def __init__(self, db: Prisma) -> None:
        self._db = db

    # [OMA-W008-T003] Alias for get_pending_listings_for_source batch retrieval
    async def get_pending_raw_listings(
        self, source_id: str, limit: int = 50
    ) -> list[Any]:
        """Fetch pending listings for Level 2 detail crawl pass."""
        return await self.get_pending_listings_for_source(source_id, limit=limit)


# [OMA-W008-T005] Export repository, DTOs, and mixins
__all__ = [
    "ScrapingRepository",
    "GrantDetailCreateInput",
    "_to_json",
    "SourcesRepositoryMixin",
]
