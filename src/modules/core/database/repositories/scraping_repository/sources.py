# [OMA-W006-T006] Sources and templates repository operations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from prisma.models import ScrapingTemplate, Source, SourceConfig

from prisma import Prisma

from .dto import to_json

logger = logging.getLogger(__name__)


class SourcesRepositoryMixin:
    """Operations for sources, configs, distributed locks, and template pool."""

    _db: Prisma

    async def get_source(self, source_id: str) -> Source | None:
        """Retrieve a Source by its UUID."""
        return await self._db.source.find_unique(where={"id": source_id})

    async def get_source_by_url(self, url: str) -> Source | None:
        """Retrieve a Source by its entry URL."""
        return await self._db.source.find_unique(where={"url": url})

    async def create_source(
        self,
        url: str,
        name: str | None = None,
        created_by: str | None = None,
        is_active: bool = True,
    ) -> Source:
        """Create a new Source record."""
        return await self._db.source.create(
            data={
                "url": url,
                "name": name,
                "created_by": created_by,
                "is_active": is_active,
            }
        )

    # [OMA-W008-T005] Reliable source deactivation
    async def deactivate_source(self, source_id: str) -> None:
        """Deactivate a source by setting is_active=False."""
        await self._db.source.update(where={"id": source_id}, data={"is_active": False})

    async def get_source_config(self, source_id: str) -> SourceConfig | None:
        """Retrieve SourceConfig by source UUID."""
        return await self._db.sourceconfig.find_unique(where={"source_id": source_id})

    async def upsert_source_config(
        self, source_id: str, config_data: dict[str, Any]
    ) -> SourceConfig:
        """Create or update technical crawling configuration for a source."""
        data = dict(config_data)
        if "pagination_config" in data and data["pagination_config"] is not None:
            data["pagination_config"] = to_json(data["pagination_config"])

        create_payload = dict(data)
        create_payload["source_id"] = source_id

        update_payload = dict(data)
        update_payload.pop("source_id", None)

        return await self._db.sourceconfig.upsert(
            where={"source_id": source_id},
            data={"create": create_payload, "update": update_payload},  # type: ignore[arg-type]
        )

    async def get_active_sources(self) -> list[Source]:
        """Fetch all active sources including their technical configurations."""
        return await self._db.source.find_many(
            where={"is_active": True},
            include={"config": True},
        )

    async def acquire_source_lock(
        self, source_id: str, stale_lock_threshold_minutes: int = 30
    ) -> bool:
        """Atomically acquire distributed lock for a source."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=stale_lock_threshold_minutes)

        count = await self._db.sourceconfig.update_many(
            where={
                "source_id": source_id,
                "OR": [
                    {"is_locked": False},
                    {"locked_at": {"lte": cutoff}},
                ],
            },
            data={
                "is_locked": True,
                "locked_at": now,
            },
        )
        return count > 0

    async def release_source_lock(self, source_id: str) -> bool:
        """Release the crawl lock for a specific source."""
        count = await self._db.sourceconfig.update_many(
            where={"source_id": source_id, "is_locked": True},
            data={"is_locked": False, "locked_at": None},
        )
        return count > 0

    async def release_all_source_locks(self, source_ids: list[str]) -> int:
        """Release crawl locks for an array of source UUIDs."""
        if not source_ids:
            return 0
        return await self._db.sourceconfig.update_many(
            where={"source_id": {"in": source_ids}, "is_locked": True},
            data={"is_locked": False, "locked_at": None},
        )

    async def break_stale_locks(self, stale_threshold_minutes: int = 30) -> int:
        """Break and reset any locks older than the stale threshold."""
        cutoff = datetime.now(UTC) - timedelta(minutes=stale_threshold_minutes)
        return await self._db.sourceconfig.update_many(
            where={"is_locked": True, "locked_at": {"lte": cutoff}},
            data={"is_locked": False, "locked_at": None},
        )

    async def update_source_status(
        self,
        source_id: str,
        *,
        consecutive_failures: int | None = None,
        cool_down_until: datetime | None = None,
        last_scraped_at: datetime | None = None,
        drift_detected: bool | None = None,
    ) -> SourceConfig | None:
        """Update operational telemetry fields on SourceConfig."""
        data: dict[str, Any] = {}
        if consecutive_failures is not None:
            data["consecutive_failures"] = consecutive_failures
        if cool_down_until is not None:
            data["cool_down_until"] = cool_down_until
        if last_scraped_at is not None:
            data["last_scraped_at"] = last_scraped_at
        if drift_detected is not None:
            data["drift_detected"] = drift_detected

        if not data:
            return await self.get_source_config(source_id)

        try:
            return await self._db.sourceconfig.update(
                where={"source_id": source_id},
                data=data,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                "Could not update source status for source %s: %s",
                source_id,
                exc,
            )
            return None

    async def record_source_failure(
        self, source_id: str, cool_down_seconds: float | None = None
    ) -> SourceConfig | None:
        """Increment failure count and optionally set cool-down timestamp."""
        config = await self.get_source_config(source_id)
        current_failures = config.consecutive_failures if config else 0
        new_failures = current_failures + 1

        cool_down_dt = None
        if cool_down_seconds is not None and cool_down_seconds > 0:
            cool_down_dt = datetime.now(UTC) + timedelta(seconds=cool_down_seconds)

        return await self.update_source_status(
            source_id,
            consecutive_failures=new_failures,
            cool_down_until=cool_down_dt,
        )

    async def record_source_success(self, source_id: str) -> SourceConfig | None:
        """Reset consecutive failures and refresh last scraped timestamp."""
        now = datetime.now(UTC)
        return await self.update_source_status(
            source_id,
            consecutive_failures=0,
            cool_down_until=None,
            last_scraped_at=now,
            drift_detected=False,
        )

    async def get_templates_for_source(
        self,
        source_id: str,
        level: int | None = None,
        is_active: bool = True,
    ) -> list[ScrapingTemplate]:
        """Fetch candidate templates for a source ordered by hit count DESC."""
        where: dict[str, Any] = {
            "source_id": source_id,
            "is_active": is_active,
        }
        if level is not None:
            where["level"] = level

        return await self._db.scrapingtemplate.find_many(
            where=where,
            order={"hit_count": "desc"},
        )

    async def get_template_by_id(self, template_id: str) -> ScrapingTemplate | None:
        """Retrieve a ScrapingTemplate by ID."""
        return await self._db.scrapingtemplate.find_unique(where={"id": template_id})

    async def create_template(
        self,
        source_id: str,
        level: int,
        layout_signature: str,
        template_schema: dict[str, Any],
        schema_type: str = "CSS",
        version: int | None = None,
        field_metrics: dict[str, Any] | None = None,
    ) -> ScrapingTemplate:
        """Create a new template record in the historical pool."""
        if version is None:
            existing = await self._db.scrapingtemplate.find_many(
                where={"source_id": source_id, "level": level},
                order={"version": "desc"},
                take=1,
            )
            version = (existing[0].version + 1) if existing else 1

        data: dict[str, Any] = {
            "source_id": source_id,
            "level": level,
            "layout_signature": layout_signature,
            "schema_type": schema_type,
            "template_schema": to_json(template_schema),
            "version": version,
            "is_active": True,
            "hit_count": 0,
        }
        if field_metrics is not None:
            data["field_metrics"] = to_json(field_metrics)

        return await self._db.scrapingtemplate.create(data=data)  # type: ignore[arg-type]

    async def record_template_hit(
        self,
        template_id: str,
        field_metrics: dict[str, Any] | None = None,
    ) -> ScrapingTemplate | None:
        """Increment template hit count and update metrics."""
        data: dict[str, Any] = {
            "hit_count": {"increment": 1},
            "last_successful_use_at": datetime.now(UTC),
        }
        if field_metrics is not None:
            data["field_metrics"] = to_json(field_metrics)

        try:
            return await self._db.scrapingtemplate.update(
                where={"id": template_id},
                data=data,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning("Could not record hit for template %s: %s", template_id, exc)
            return None

    async def update_field_metrics(
        self, template_id: str, field_metrics: dict[str, Any]
    ) -> ScrapingTemplate | None:
        """Update field metrics JSON on a template."""
        try:
            return await self._db.scrapingtemplate.update(
                where={"id": template_id},
                data={"field_metrics": to_json(field_metrics)},  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                "Could not update field metrics for template %s: %s",
                template_id,
                exc,
            )
            return None
