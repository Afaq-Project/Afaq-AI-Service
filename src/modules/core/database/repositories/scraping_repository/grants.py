# [OMA-W006-T006] Grants and listings repository operations

import logging
from datetime import UTC, datetime
from typing import Any

from prisma.models import RawGrantDetail, RawListing

from prisma import Prisma

from .dto import GrantDetailCreateInput, to_json

logger = logging.getLogger(__name__)

_GRANT_DETAIL_PARAM_NAMES = [
    "operation_id",
    "source_id",
    "source_url",
    "raw_payload",
    "listing_id",
    "opportunity_group_id",
    "template_id",
    "template_version",
    "image_url",
    "title_language",
    "body_language",
    "language_confidence",
    "link_verification_status",
    "final_application_url",
    "is_legitimate_domain",
    "has_attachment",
    "attachment_s3_key",
    "attachment_metadata",
    "status",
]


class GrantsRepositoryMixin:
    """Operations for RawListing and RawGrantDetail persistence and DLQ transitions."""

    _db: Prisma

    # -------------------------------------------------------------------------
    # 1. RawListing Operations
    # -------------------------------------------------------------------------

    async def create_listing(
        self,
        operation_id: str,
        source_id: str,
        discovered_url: str,
        listing_page_url: str,
        card_title_preview: str | None = None,
        card_snippet_preview: str | None = None,
        card_image_url: str | None = None,
        page_number: int = 1,
        parent_id: str | None = None,
        root_listing_id: str | None = None,
        tree_depth: int = 0,
        status: str = "pending_detail_crawl",
    ) -> RawListing:
        """Create a single RawListing record."""
        return await self._db.rawlisting.create(
            data={
                "operation_id": operation_id,
                "source_id": source_id,
                "discovered_url": discovered_url,
                "listing_page_url": listing_page_url,
                "card_title_preview": card_title_preview,
                "card_snippet_preview": card_snippet_preview,
                "card_image_url": card_image_url,
                "page_number": page_number,
                "parent_id": parent_id,
                "root_listing_id": root_listing_id,
                "tree_depth": tree_depth,
                "status": status,
            }  # type: ignore[arg-type]
        )

    async def create_listings_batch(
        self, listings: list[dict[str, Any]], skip_duplicates: bool = True
    ) -> int:
        """Persist a batch of discovered listings, skipping duplicates."""
        if not listings:
            return 0
        formatted_listings: list[dict[str, Any]] = []
        for item in listings:
            copy_item = dict(item)
            if (
                "extraction_errors" in copy_item
                and copy_item["extraction_errors"] is not None
            ):
                copy_item["extraction_errors"] = to_json(copy_item["extraction_errors"])
            formatted_listings.append(copy_item)

        return await self._db.rawlisting.create_many(
            data=formatted_listings,  # type: ignore[arg-type]
            skip_duplicates=skip_duplicates,
        )

    async def get_listing_by_id(self, listing_id: str) -> RawListing | None:
        """Retrieve a RawListing by its UUID."""
        return await self._db.rawlisting.find_unique(where={"id": listing_id})

    async def get_listing_by_url(
        self, source_id: str, discovered_url: str
    ) -> RawListing | None:
        """Retrieve a RawListing by unique compound key (source_id, discovered_url)."""
        return await self._db.rawlisting.find_first(
            where={
                "source_id": source_id,
                "discovered_url": discovered_url,
            }
        )

    async def get_pending_listings_for_source(
        self, source_id: str, limit: int = 50
    ) -> list[RawListing]:
        """Fetch pending listings for Level 2 detail crawl pass."""
        return await self._db.rawlisting.find_many(
            where={
                "source_id": source_id,
                "status": "pending_detail_crawl",
            },
            take=limit,
            order={"page_number": "asc"},
        )

    async def get_listings_by_operation(
        self, operation_id: str, limit: int = 100, offset: int = 0
    ) -> list[RawListing]:
        """Fetch listings associated with an operation."""
        return await self._db.rawlisting.find_many(
            where={"operation_id": operation_id},
            take=limit,
            skip=offset,
            order={"scraped_at": "asc"},
        )

    async def count_listings_by_operation(self, operation_id: str) -> int:
        """Count total listings associated with an operation."""
        return await self._db.rawlisting.count(where={"operation_id": operation_id})

    async def update_listing_status(
        self,
        listing_id: str,
        status: str,
        errors: dict[str, Any] | None = None,
    ) -> RawListing | None:
        """Update listing status and optional error log."""
        data: dict[str, Any] = {"status": status}
        if errors is not None:
            data["extraction_errors"] = to_json(errors)

        try:
            return await self._db.rawlisting.update(
                where={"id": listing_id},
                data=data,  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                "Could not update status for listing %s: %s", listing_id, exc
            )
            return None

    async def mark_listing_extracted(self, listing_id: str) -> RawListing | None:
        """Mark listing as details_extracted."""
        return await self.update_listing_status(listing_id, "details_extracted")

    async def record_listing_failure(
        self,
        listing_id: str,
        error_message: str,
        error_code: str | None = None,
        max_retries: int = 3,
    ) -> RawListing | None:
        """Increment retry count and transition to DLQ if max retries reached."""
        listing = await self.get_listing_by_id(listing_id)
        if not listing:
            return None

        new_retry_count = listing.retry_count + 1
        new_status = (
            "failed_permanently" if new_retry_count >= max_retries else "failed"
        )

        current_errors = listing.extraction_errors or {}
        if not isinstance(current_errors, dict):
            current_errors = {}
        error_list = current_errors.get("attempts", [])
        if not isinstance(error_list, list):
            error_list = []
        error_list.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "error_code": error_code,
                "error_message": error_message,
                "attempt": new_retry_count,
            }
        )

        updated_errors = {
            "last_error": error_message,
            "last_error_code": error_code,
            "attempts": error_list,
        }

        return await self._db.rawlisting.update(
            where={"id": listing_id},
            data={
                "retry_count": new_retry_count,
                "status": new_status,
                "extraction_errors": to_json(updated_errors),
            },  # type: ignore[arg-type]
        )

    # -------------------------------------------------------------------------
    # 2. RawGrantDetail Operations
    # -------------------------------------------------------------------------

    async def create_grant_detail(
        self,
        data: GrantDetailCreateInput | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> RawGrantDetail:
        """Create a new comprehensive Level 2 RawGrantDetail record.

        Accepts a `GrantDetailCreateInput` DTO, or keyword/positional arguments
        for backward compatibility.
        """
        if isinstance(data, GrantDetailCreateInput):
            input_dto = data
        else:
            merged: dict[str, Any] = {}
            if data is not None:
                # First positional arg is operation_id
                merged["operation_id"] = data
            for idx, arg_val in enumerate(args, start=1):
                if idx < len(_GRANT_DETAIL_PARAM_NAMES):
                    merged[_GRANT_DETAIL_PARAM_NAMES[idx]] = arg_val
            merged.update(kwargs)
            input_dto = GrantDetailCreateInput(**merged)

        payload_dict = {
            "operation_id": input_dto.operation_id,
            "source_id": input_dto.source_id,
            "source_url": input_dto.source_url,
            "raw_payload": to_json(input_dto.raw_payload),
            "listing_id": input_dto.listing_id,
            "opportunity_group_id": input_dto.opportunity_group_id,
            "template_id": input_dto.template_id,
            "template_version": input_dto.template_version,
            "image_url": input_dto.image_url,
            "title_language": input_dto.title_language,
            "body_language": input_dto.body_language,
            "language_confidence": input_dto.language_confidence,
            "link_verification_status": input_dto.link_verification_status,
            "final_application_url": input_dto.final_application_url,
            "is_legitimate_domain": input_dto.is_legitimate_domain,
            "has_attachment": input_dto.has_attachment,
            "attachment_s3_key": input_dto.attachment_s3_key,
            "attachment_metadata": to_json(input_dto.attachment_metadata),
            "status": input_dto.status,
        }

        return await self._db.rawgrantdetail.create(
            data=payload_dict  # type: ignore[arg-type]
        )

    async def upsert_grant_detail(
        self,
        operation_id: str,
        source_id: str,
        source_url: str,
        raw_payload: dict[str, Any],
        listing_id: str | None = None,
        opportunity_group_id: str | None = None,
        template_id: str | None = None,
        template_version: int = 1,
        **kwargs: Any,
    ) -> RawGrantDetail:
        """Create or update a RawGrantDetail matching source_id and source_url."""
        existing = await self._db.rawgrantdetail.find_first(
            where={
                "source_id": source_id,
                "source_url": source_url,
            }
        )

        update_payload: dict[str, Any] = {
            "operation_id": operation_id,
            "raw_payload": to_json(raw_payload),
            "template_id": template_id,
            "template_version": template_version,
        }
        if listing_id is not None:
            update_payload["listing_id"] = listing_id
        if opportunity_group_id is not None:
            update_payload["opportunity_group_id"] = opportunity_group_id

        for key, val in kwargs.items():
            if key in {"attachment_metadata", "extraction_errors"}:
                update_payload[key] = to_json(val)
            else:
                update_payload[key] = val

        if existing:
            return await self._db.rawgrantdetail.update(
                where={"id": existing.id},
                data=update_payload,  # type: ignore[arg-type]
            )

        create_payload = dict(update_payload)
        create_payload["source_id"] = source_id
        create_payload["source_url"] = source_url
        if "status" not in create_payload:
            create_payload["status"] = "pending"

        return await self._db.rawgrantdetail.create(
            data=create_payload  # type: ignore[arg-type]
        )

    async def get_grant_detail_by_id(self, detail_id: str) -> RawGrantDetail | None:
        """Retrieve a RawGrantDetail by ID."""
        return await self._db.rawgrantdetail.find_unique(where={"id": detail_id})

    async def get_grant_detail_by_source_url(
        self, source_id: str, source_url: str
    ) -> RawGrantDetail | None:
        """Retrieve a RawGrantDetail by source_id and source_url."""
        return await self._db.rawgrantdetail.find_first(
            where={
                "source_id": source_id,
                "source_url": source_url,
            }
        )

    async def get_grant_detail_by_listing_id(
        self, listing_id: str
    ) -> RawGrantDetail | None:
        """Retrieve RawGrantDetail linked to a listing_id."""
        return await self._db.rawgrantdetail.find_first(
            where={"listing_id": listing_id}
        )

    async def get_grant_details_by_operation(
        self, operation_id: str, limit: int = 100, offset: int = 0
    ) -> list[RawGrantDetail]:
        """Fetch grant details for an operation."""
        return await self._db.rawgrantdetail.find_many(
            where={"operation_id": operation_id},
            take=limit,
            skip=offset,
            order={"scraped_at": "asc"},
        )

    async def count_grant_details_by_operation(self, operation_id: str) -> int:
        """Count total grant details extracted in an operation."""
        return await self._db.rawgrantdetail.count(where={"operation_id": operation_id})

    async def link_opportunity_group(
        self, detail_id: str, opportunity_group_id: str
    ) -> RawGrantDetail | None:
        """Link opportunity record to a shared bilingual opportunity group."""
        try:
            return await self._db.rawgrantdetail.update(
                where={"id": detail_id},
                data={"opportunity_group_id": opportunity_group_id},
            )
        except Exception as exc:
            logger.warning(
                "Could not link opportunity group for detail %s: %s",
                detail_id,
                exc,
            )
            return None

    async def find_existing_attachment_metadata(
        self,
        source_url: str | None = None,
        sha256_checksum: str | None = None,
    ) -> dict[str, Any] | None:
        """Find existing valid attachment metadata to skip redundant S3 downloads."""
        where: dict[str, Any] = {"has_attachment": True}
        if source_url:
            where["source_url"] = source_url

        records = await self._db.rawgrantdetail.find_many(
            where=where,
            take=10,
            order={"scraped_at": "desc"},
        )

        for record in records:
            if not record.attachment_s3_key or not record.attachment_metadata:
                continue
            meta = record.attachment_metadata
            if isinstance(meta, dict):
                if sha256_checksum and meta.get("sha256") != sha256_checksum:
                    continue
                return {
                    "attachment_s3_key": record.attachment_s3_key,
                    "attachment_metadata": meta,
                }
        return None

    async def update_grant_detail_attachment(
        self,
        detail_id: str,
        s3_key: str,
        attachment_metadata: dict[str, Any],
    ) -> RawGrantDetail | None:
        """Store S3 key and attachment metadata on detail record."""
        try:
            return await self._db.rawgrantdetail.update(
                where={"id": detail_id},
                data={
                    "has_attachment": True,
                    "attachment_s3_key": s3_key,
                    "attachment_metadata": to_json(attachment_metadata),
                },  # type: ignore[arg-type]
            )
        except Exception as exc:
            logger.warning(
                "Could not update attachment metadata for detail %s: %s",
                detail_id,
                exc,
            )
            return None

    async def record_detail_failure(
        self,
        detail_id: str,
        error_message: str,
        error_code: str | None = None,
        max_retries: int = 3,
    ) -> RawGrantDetail | None:
        """Increment retry count on detail record and transition to DLQ if needed."""
        detail = await self.get_grant_detail_by_id(detail_id)
        if not detail:
            return None

        new_retry_count = detail.retry_count + 1
        new_status = (
            "failed_permanently" if new_retry_count >= max_retries else "failed"
        )

        current_errors = detail.extraction_errors or {}
        if not isinstance(current_errors, dict):
            current_errors = {}
        error_list = current_errors.get("attempts", [])
        if not isinstance(error_list, list):
            error_list = []
        error_list.append(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "error_code": error_code,
                "error_message": error_message,
                "attempt": new_retry_count,
            }
        )

        updated_errors = {
            "last_error": error_message,
            "last_error_code": error_code,
            "attempts": error_list,
        }

        return await self._db.rawgrantdetail.update(
            where={"id": detail_id},
            data={
                "retry_count": new_retry_count,
                "status": new_status,
                "error_message": error_message,
                "extraction_errors": to_json(updated_errors),
            },  # type: ignore[arg-type]
        )
