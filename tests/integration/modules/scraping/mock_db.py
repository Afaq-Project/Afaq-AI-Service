# [OMA-W005-T016] [OMA-W005-T022] [OMA-W005-T034] In-memory Prisma database mock for offline integration tests

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from typing import Any


class FakeRecord:
    """Generic record matching Prisma model attribute access."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)

    def __getattr__(self, name: str) -> Any:
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __repr__(self) -> str:
        return f"FakeRecord({self.__dict__})"


class FakePrismaCollection:
    """In-memory async collection emulating a Prisma model table."""

    def __init__(self, name: str, prisma: FakePrisma | None = None) -> None:
        self.name = name
        self.prisma = prisma
        self._records: dict[str, FakeRecord] = {}

    def _matches(self, record: FakeRecord, where: dict[str, Any]) -> bool:
        """Evaluates whether a record matches a Prisma where clause."""
        if not where:
            return True

        for key, val in where.items():
            if key == "OR":
                # OR list: at least one condition must match
                or_matches = any(self._matches(record, branch) for branch in val)
                if not or_matches:
                    return False
            elif key == "AND":
                # AND list: all conditions must match
                and_matches = all(self._matches(record, branch) for branch in val)
                if not and_matches:
                    return False
            elif isinstance(val, dict):
                # Operator checks: lte, gte, in
                rec_val = getattr(record, key, None)
                if "lte" in val:
                    if rec_val is None or rec_val > val["lte"]:
                        return False
                if "gte" in val:
                    if rec_val is None or rec_val < val["gte"]:
                        return False
                if "in" in val:
                    if rec_val not in val["in"]:
                        return False
            else:
                rec_val = getattr(record, key, None)
                if rec_val != val:
                    return False

        return True

    async def find_unique(
        self, where: dict[str, Any], include: dict[str, Any] | None = None
    ) -> FakeRecord | None:
        return await self.find_first(where=where, include=include)

    async def find_first(
        self,
        where: dict[str, Any] | None = None,
        include: dict[str, Any] | None = None,
        order: dict[str, str] | None = None,
    ) -> FakeRecord | None:
        results = await self.find_many(
            where=where, include=include, order=order, take=1
        )
        return results[0] if results else None

    async def find_many(
        self,
        where: dict[str, Any] | None = None,
        include: dict[str, Any] | None = None,
        order: dict[str, str] | None = None,
        take: int | None = None,
        skip: int = 0,
    ) -> list[FakeRecord]:
        where = where or {}
        matches = [r for r in self._records.values() if self._matches(r, where)]

        # Sorting
        if order:
            for sort_field, direction in order.items():
                reverse = direction.lower() == "desc"
                matches.sort(
                    key=lambda r: getattr(r, sort_field, None)
                    or datetime.min.replace(tzinfo=UTC),
                    reverse=reverse,
                )

        # Pagination
        if skip:
            matches = matches[skip:]
        if take is not None:
            matches = matches[:take]

        results = [copy.copy(m) for m in matches]
        if include and self.name == "source" and include.get("config") and self.prisma:
            for res in results:
                cfg = next(
                    (
                        c
                        for c in self.prisma.sourceconfig._records.values()
                        if c.source_id == res.id
                    ),
                    None,
                )
                res.config = copy.copy(cfg) if cfg else None

        return results

    async def create(self, data: dict[str, Any]) -> FakeRecord:
        record_id = data.get("id") or str(uuid.uuid4())
        rec_data: dict[str, Any] = {}
        for k, v in data.items():
            rec_data[k] = v.data if hasattr(v, "data") else v

        rec_data["id"] = record_id
        now = datetime.now(UTC)
        if "created_at" not in rec_data:
            rec_data["created_at"] = now
        if "updated_at" not in rec_data:
            rec_data["updated_at"] = now
        if "scraped_at" not in rec_data and self.name in {
            "rawlisting",
            "rawgrantdetail",
        }:
            rec_data["scraped_at"] = now
        if "started_at" not in rec_data and self.name == "scrapeoperation":
            rec_data["started_at"] = now

        # Defaults for models
        if self.name == "scrapeoperation":
            rec_data.setdefault("idempotency_key", None)
            rec_data.setdefault("status", "running")
            rec_data.setdefault("triggered_by", "admin_api")
            rec_data.setdefault("sources_attempted", [])
            rec_data.setdefault("sources_succeeded", [])
            rec_data.setdefault("sources_failed", [])
            rec_data.setdefault("total_listings_found", 0)
            rec_data.setdefault("total_details_extracted", 0)
            rec_data.setdefault("total_files_downloaded", 0)
            rec_data.setdefault("error_summary", {})
            rec_data.setdefault("completed_at", None)
        elif self.name == "source":
            rec_data.setdefault("name", None)
            rec_data.setdefault("is_active", True)
            rec_data.setdefault("created_by", None)
        elif self.name == "sourceconfig":
            rec_data.setdefault("site_description", None)
            rec_data.setdefault("supported_languages", ["ar", "en"])
            rec_data.setdefault("pagination_type", "next_button")
            rec_data.setdefault("pagination_config", {})
            rec_data.setdefault("ordering_strategy", "chronological_descending")
            rec_data.setdefault("is_locked", False)
            rec_data.setdefault("locked_at", None)
            rec_data.setdefault("consecutive_failures", 0)
            rec_data.setdefault("rate_limit_delay_sec", 1.0)
            rec_data.setdefault("max_pages_per_run", 10)
            rec_data.setdefault("incremental_cutoff_enabled", True)
            rec_data.setdefault("max_operation_timeout_sec", 1200)
            rec_data.setdefault("page_timeout_sec", 30)
            rec_data.setdefault("max_concurrent_crawls", 1)
            rec_data.setdefault("last_scraped_at", None)
            rec_data.setdefault("cool_down_until", None)
        elif self.name == "rawlisting":
            rec_data.setdefault("card_title_preview", None)
            rec_data.setdefault("card_snippet_preview", None)
            rec_data.setdefault("card_image_url", None)
            rec_data.setdefault("page_number", 1)
            rec_data.setdefault("retry_count", 0)
            rec_data.setdefault("max_retries", 3)
            rec_data.setdefault("status", "pending_detail_crawl")
            rec_data.setdefault("extraction_errors", {})
        elif self.name == "rawgrantdetail":
            rec_data.setdefault("listing_id", None)
            rec_data.setdefault("opportunity_group_id", None)
            rec_data.setdefault("template_id", None)
            rec_data.setdefault("template_version", 1)
            rec_data.setdefault("image_url", None)
            rec_data.setdefault("title_language", "und")
            rec_data.setdefault("body_language", "und")
            rec_data.setdefault("language_confidence", 0.0)
            rec_data.setdefault("has_attachment", False)
            rec_data.setdefault("attachment_s3_key", None)
            rec_data.setdefault("attachment_metadata", None)
            rec_data.setdefault("final_application_url", None)
            rec_data.setdefault("retry_count", 0)
            rec_data.setdefault("max_retries", 3)
            rec_data.setdefault("status", "pending")
            rec_data.setdefault("extraction_errors", {})

        record = FakeRecord(**rec_data)
        self._records[record_id] = record
        return copy.copy(record)

    async def create_many(
        self, data: list[dict[str, Any]], skip_duplicates: bool = True
    ) -> int:
        count = 0
        for item in data:
            if skip_duplicates and "discovered_url" in item and "source_id" in item:
                exists = any(
                    r.source_id == item["source_id"]
                    and r.discovered_url == item["discovered_url"]
                    for r in self._records.values()
                )
                if exists:
                    continue
            await self.create(item)
            count += 1
        return count

    async def update(self, where: dict[str, Any], data: dict[str, Any]) -> FakeRecord:
        target = await self.find_first(where)
        if not target:
            raise RuntimeError(f"Record matching {where} not found in {self.name}")

        rec = self._records[target.id]
        for k, v in data.items():
            if isinstance(v, dict) and "increment" in v:
                curr = getattr(rec, k, 0) or 0
                setattr(rec, k, curr + v["increment"])
            else:
                val = v.data if hasattr(v, "data") else v
                setattr(rec, k, val)
        rec.updated_at = datetime.now(UTC)
        return copy.copy(rec)

    async def update_many(self, where: dict[str, Any], data: dict[str, Any]) -> int:
        matches = [r for r in self._records.values() if self._matches(r, where)]
        for rec in matches:
            for k, v in data.items():
                if isinstance(v, dict) and "increment" in v:
                    curr = getattr(rec, k, 0) or 0
                    setattr(rec, k, curr + v["increment"])
                else:
                    setattr(rec, k, v)
            rec.updated_at = datetime.now(UTC)
        return len(matches)

    async def upsert(self, where: dict[str, Any], data: dict[str, Any]) -> FakeRecord:
        existing = await self.find_first(where)
        if existing:
            return await self.update(where, data.get("update", {}))
        create_payload = dict(data.get("create", {}))
        return await self.create(create_payload)

    async def delete(self, where: dict[str, Any]) -> FakeRecord:
        target = await self.find_first(where)
        if not target:
            raise RuntimeError(f"Record matching {where} not found in {self.name}")
        rec = self._records.pop(target.id)
        return copy.copy(rec)

    async def count(self, where: dict[str, Any] | None = None) -> int:
        where = where or {}
        matches = [r for r in self._records.values() if self._matches(r, where)]
        return len(matches)


class FakePrisma:
    """In-memory Prisma client harness."""

    def __init__(self) -> None:
        self.source = FakePrismaCollection("source", self)
        self.sourceconfig = FakePrismaCollection("sourceconfig", self)
        self.scrapingtemplate = FakePrismaCollection("scrapingtemplate", self)
        self.rawlisting = FakePrismaCollection("rawlisting", self)
        self.rawgrantdetail = FakePrismaCollection("rawgrantdetail", self)
        self.scrapeoperation = FakePrismaCollection("scrapeoperation", self)

    def is_connected(self) -> bool:
        return True

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass
