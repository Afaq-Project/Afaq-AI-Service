# [OMA-W006-T009] LockManager: Distributed locking and 30-min auto-reclamation

import logging

from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)

logger = logging.getLogger(__name__)

STALE_LOCK_THRESHOLD_MINUTES: int = 30


class LockManager:
    """Manages atomic distributed locks and 30-min auto-reclamation for scraping sources."""

    @staticmethod
    async def acquire_lock(
        repository: ScrapingRepository,
        source_id: str,
        stale_threshold_minutes: int = STALE_LOCK_THRESHOLD_MINUTES,
    ) -> bool:
        """Atomically acquires distributed lock for a source."""
        return await repository.acquire_source_lock(
            source_id=source_id,
            stale_lock_threshold_minutes=stale_threshold_minutes,
        )

    @staticmethod
    async def release_lock(repository: ScrapingRepository, source_id: str) -> bool:
        """Releases the crawl lock for a specific source."""
        return await repository.release_source_lock(source_id)

    @staticmethod
    async def release_all_locks(
        repository: ScrapingRepository, source_ids: list[str]
    ) -> int:
        """Releases locks for an array of source UUIDs."""
        return await repository.release_all_source_locks(source_ids)

    @staticmethod
    async def break_stale_locks(
        repository: ScrapingRepository,
        stale_threshold_minutes: int = STALE_LOCK_THRESHOLD_MINUTES,
    ) -> int:
        """Breaks abandoned locks exceeding the threshold."""
        return await repository.break_stale_locks(stale_threshold_minutes)
