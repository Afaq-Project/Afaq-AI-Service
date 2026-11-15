import asyncio
import hashlib
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote, urlsplit

from prisma import Prisma

API_KEY_ID = "00000000-0000-4000-8000-000000000001"


class SeedConfigurationError(ValueError):
    """Raised when the seeder cannot prove it targets a test database."""


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()


def _test_database_target(
    database_url: str, variable_name: str
) -> tuple[str, int, str]:
    """Return a local test database target; reject remote and ambiguous URLs."""
    try:
        parsed = urlsplit(database_url)
        database_name = unquote(parsed.path.removeprefix("/"))
        host = parsed.hostname
        port = parsed.port or 5432
    except ValueError as exc:
        raise SeedConfigurationError(
            f"{variable_name} is not a valid PostgreSQL connection URL."
        ) from exc

    if parsed.scheme not in {"postgres", "postgresql"} or not host:
        raise SeedConfigurationError(
            f"{variable_name} must be a PostgreSQL URL with an explicit host."
        )
    if host.lower() not in {"localhost", "127.0.0.1", "::1"}:
        raise SeedConfigurationError(
            f"{variable_name} must target PostgreSQL on this machine."
        )
    if not database_name or "/" in database_name:
        raise SeedConfigurationError(
            f"{variable_name} must identify exactly one database."
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]+_test", database_name, re.IGNORECASE):
        raise SeedConfigurationError(
            f"{variable_name} database name must end with '_test'."
        )
    return "loopback", port, database_name


def _load_test_api_key() -> str:
    """Require a caller-supplied test key; never fall back to a committed key."""
    raw_key = os.environ.get("TEST_API_KEY", "")
    if len(raw_key) < 16:
        raise SeedConfigurationError(
            "TEST_API_KEY must be provided and contain at least 16 characters."
        )
    return raw_key


def _validate_seed_environment() -> str:
    """Fail closed unless the explicit database and key are test-only values."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SeedConfigurationError(
            "DATABASE_URL must be explicitly set; refusing implicit .env configuration."
        )

    database_target = _test_database_target(database_url, "DATABASE_URL")
    direct_url = os.environ.get("DIRECT_URL")
    if direct_url:
        direct_database_target = _test_database_target(direct_url, "DIRECT_URL")
        if direct_database_target != database_target:
            raise SeedConfigurationError(
                "DIRECT_URL and DATABASE_URL must target the same local test database."
            )

    return _load_test_api_key()


async def seed():
    raw_key = _validate_seed_environment()

    db = Prisma()
    await db.connect()
    now = datetime.now(UTC)

    # 1. API Key (the raw key is provided through TEST_API_KEY and never logged)
    key_hash = hash_key(raw_key)
    existing_key = await db.apikey.find_unique(where={"key": key_hash})
    if not existing_key:
        key_with_reserved_id = await db.apikey.find_unique(where={"id": API_KEY_ID})
        if key_with_reserved_id:
            await db.apikey.update(
                where={"id": API_KEY_ID},
                data={"key": key_hash, "is_active": True},
            )
            print("Updated the test API key record (raw key redacted).")
        else:
            await db.apikey.create(
                data={
                    "id": API_KEY_ID,
                    "key": key_hash,
                    "name": "k6-test-runner",
                    "is_active": True,
                }
            )
            print("Created test API key record (raw key redacted).")
    else:
        print("Test API key record already exists.")

    # 2. Test Sources
    # Source 1: Active, unlocked source
    s1_id = "22222222-2222-4222-8222-222222222222"
    s1 = await db.source.find_unique(where={"id": s1_id})
    if not s1:
        await db.source.create(
            data={
                "id": s1_id,
                "url": "https://test-portal.example.edu/scholarships",
                "name": "Test University Scholarships",
                "is_active": True,
            }
        )
        await db.sourceconfig.create(
            data={
                "source_id": s1_id,
                "domain": "test-portal.example.edu",
                "site_name": "Test University Scholarships",
                "supported_languages": ["en"],
                "pagination_type": "url_param",
                "pagination_config": '{"param": "page", "step": 1}',
                "ordering_strategy": "chronological_descending",
                "rate_limit_delay_sec": 1.0,
                "max_pages_per_run": 5,
                "is_locked": False,
            }
        )
        print("Created Source 1 (unlocked).")

    # Source 2: Locked source
    s2_id = "33333333-3333-4333-8333-333333333333"
    s2 = await db.source.find_unique(where={"id": s2_id})
    if not s2:
        await db.source.create(
            data={
                "id": s2_id,
                "url": "https://locked-portal.example.edu/grants",
                "name": "Locked Portal",
                "is_active": True,
            }
        )
        await db.sourceconfig.create(
            data={
                "source_id": s2_id,
                "domain": "locked-portal.example.edu",
                "site_name": "Locked Portal",
                "supported_languages": ["en"],
                "pagination_type": "none",
                "pagination_config": "{}",
                "is_locked": True,
                "locked_at": now,
            }
        )
        print("Created Source 2 (locked).")
    else:
        await db.source.update(where={"id": s2_id}, data={"is_active": True})
        await db.sourceconfig.update(
            where={"source_id": s2_id},
            data={"is_locked": True, "locked_at": now},
        )

    # Source 3: Inactive / Unlocked source for abort testing
    s3_id = "44444444-4444-4444-8444-444444444444"
    s3 = await db.source.find_unique(where={"id": s3_id})
    if not s3:
        await db.source.create(
            data={
                "id": s3_id,
                "url": "https://inactive-portal.example.edu/awards-k6",
                "name": "Inactive Portal",
                "is_active": False,
            }
        )
        await db.sourceconfig.create(
            data={
                "source_id": s3_id,
                "domain": "inactive-portal.example.edu",
                "site_name": "Inactive Portal",
                "supported_languages": ["en"],
                "is_locked": False,
            }
        )
        print("Created Source 3 (inactive & unlocked for abort check).")
    else:
        await db.source.update(where={"id": s3_id}, data={"is_active": False})
        await db.sourceconfig.update(
            where={"source_id": s3_id}, data={"is_locked": False}
        )

    # 3. Operations for OPS-01 through OPS-08
    op1_id = "11111111-1111-4111-8111-111111111111"
    op1 = await db.scrapeoperation.find_unique(where={"id": op1_id})
    if not op1:
        await db.scrapeoperation.create(
            data={
                "id": op1_id,
                "idempotency_key": "fixed-idemp-001",
                "status": "completed",
                "triggered_by": "admin_api",
                "sources_attempted": [s1_id],
                "sources_succeeded": [s1_id],
                "sources_failed": [],
                "total_listings_found": 10,
                "total_details_extracted": 8,
                "total_files_downloaded": 2,
                "error_summary": "{}",
                "started_at": now - timedelta(hours=3),
                "completed_at": now - timedelta(hours=3) + timedelta(minutes=5),
            }
        )
        print("Created Operation 1 (completed).")

    op2_id = "55555555-5555-4555-8555-555555555555"
    op2 = await db.scrapeoperation.find_unique(where={"id": op2_id})
    if not op2:
        await db.scrapeoperation.create(
            data={
                "id": op2_id,
                "idempotency_key": "fixed-idemp-002",
                "status": "failed",
                "triggered_by": "cron",
                "sources_attempted": [s2_id],
                "sources_succeeded": [],
                "sources_failed": [s2_id],
                "total_listings_found": 0,
                "total_details_extracted": 0,
                "total_files_downloaded": 0,
                "error_summary": '{"error": "DNS resolution failed"}',
                "started_at": now - timedelta(hours=2),
                "completed_at": now - timedelta(hours=2) + timedelta(minutes=1),
            }
        )
        print("Created Operation 2 (failed).")

    op3_id = "66666666-6666-4666-8666-666666666666"
    op3 = await db.scrapeoperation.find_unique(where={"id": op3_id})
    if not op3:
        await db.scrapeoperation.create(
            data={
                "id": op3_id,
                "idempotency_key": "fixed-idemp-003",
                "status": "completed",
                "triggered_by": "admin_api",
                "sources_attempted": [s1_id, s2_id],
                "sources_succeeded": [s1_id],
                "sources_failed": [s2_id],
                "total_listings_found": 5,
                "total_details_extracted": 4,
                "total_files_downloaded": 1,
                "error_summary": "{}",
                "started_at": now - timedelta(hours=1),
                "completed_at": now - timedelta(hours=1) + timedelta(minutes=4),
            }
        )
        print("Created Operation 3 (completed).")

    # 4. Dead Letter Queue items
    # Listing in DLQ
    dlq_listing_id = "77777777-7777-4777-8777-777777777777"
    dl1 = await db.rawlisting.find_unique(where={"id": dlq_listing_id})
    if not dl1:
        await db.rawlisting.create(
            data={
                "id": dlq_listing_id,
                "operation_id": op1_id,
                "source_id": s1_id,
                "discovered_url": "https://test-portal.example.edu/scholarships/broken-link",
                "card_title_preview": "Failed Scholarship Listing",
                "listing_page_url": "https://test-portal.example.edu/scholarships",
                "status": "failed_permanently",
                "retry_count": 3,
                "max_retries": 3,
                "extraction_errors": '{"stage": "catalog", "reason": "Parsing exception"}',
            }
        )
        print("Created DLQ listing.")

    # Detail in DLQ
    dlq_detail_id = "88888888-8888-4888-8888-888888888888"
    dl2 = await db.rawgrantdetail.find_unique(where={"id": dlq_detail_id})
    if not dl2:
        await db.rawgrantdetail.create(
            data={
                "id": dlq_detail_id,
                "listing_id": dlq_listing_id,
                "operation_id": op1_id,
                "source_id": s1_id,
                "source_url": "https://test-portal.example.edu/scholarships/broken-detail",
                "status": "failed_permanently",
                "retry_count": 3,
                "max_retries": 3,
                "extraction_errors": '{"stage": "detail", "reason": "Invalid schema"}',
            }
        )
        print("Created DLQ detail.")

    await db.disconnect()
    print("Database seeding completed successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    except SeedConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
