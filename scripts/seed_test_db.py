import asyncio
import hashlib
from datetime import datetime, timezone, timedelta
from prisma import Prisma

def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()

async def seed():
    db = Prisma()
    await db.connect()
    now = datetime.now(timezone.utc)
    
    # 1. API Key
    raw_key = "k6-test-key-secret-12345"
    key_hash = hash_key(raw_key)
    existing_key = await db.apikey.find_unique(where={"key": key_hash})
    if not existing_key:
        await db.apikey.create(
            data={
                "id": "00000000-0000-4000-8000-000000000001",
                "key": key_hash,
                "name": "k6-test-runner",
                "is_active": True,
            }
        )
        print("Created test API key.")
    else:
        print("Test API key already exists.")

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
                "pagination_config": "{\"param\": \"page\", \"step\": 1}",
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

    # Source 3: Inactive / Unlocked source for abort testing
    s3_id = "44444444-4444-4444-4444-444444444444"
    s3 = await db.source.find_unique(where={"id": s3_id})
    if not s3:
        await db.source.create(
            data={
                "id": s3_id,
                "url": "https://inactive-portal.example.edu/awards",
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
        await db.sourceconfig.update(where={"source_id": s3_id}, data={"is_locked": False})

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
                "error_summary": "{\"error\": \"DNS resolution failed\"}",
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
                "extraction_errors": "{\"stage\": \"catalog\", \"reason\": \"Parsing exception\"}",
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
                "extraction_errors": "{\"stage\": \"detail\", \"reason\": \"Invalid schema\"}",
            }
        )
        print("Created DLQ detail.")

    await db.disconnect()
    print("Database seeding completed successfully.")

if __name__ == "__main__":
    asyncio.run(seed())
