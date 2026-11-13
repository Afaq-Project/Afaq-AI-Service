"""Real PostgreSQL + Prisma integration test suite for repository consistency.

Verifies transactional semantics, distributed locking, unique constraints,
idempotency, and pagination against real PostgreSQL.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
from prisma.errors import UniqueViolationError
from prisma.models import (
    ScrapeOperation,
    Source,
    SourceConfig,
)

from prisma import Prisma
from src.modules.core.database.repositories.scraping_repository import (
    ScrapingRepository,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres@127.0.0.1:5438/afaq_codespaces_test?sslmode=disable",
)

# Safety check: enforce that test suite strictly connects to a test database target
if "test" not in DATABASE_URL.lower():
    raise RuntimeError(
        f"Safety gate triggered: DATABASE_URL '{DATABASE_URL}' does not contain 'test'. "
        "Refusing to execute tests against non-test target."
    )


class DatabaseTestHarness:
    """Helper harness managing real PostgreSQL Prisma client and lifecycle tracking."""

    def __init__(self, db: Prisma, repo: ScrapingRepository) -> None:
        self.db = db
        self.repo = repo
        self.created_sources: list[str] = []
        self.created_operations: list[str] = []

    async def create_source(self, name_prefix: str = "test-source") -> Source:
        """Create a tracked source with unique URL."""
        source_uuid = str(uuid.uuid4())
        source = await self.repo.create_source(
            url=f"https://{name_prefix}-{source_uuid}.example.edu",
            name=f"{name_prefix} {source_uuid[:8]}",
        )
        self.created_sources.append(source.id)
        return source

    async def create_source_with_config(
        self,
        name_prefix: str = "test-source",
        is_locked: bool = False,
        locked_at: datetime | None = None,
    ) -> tuple[Source, SourceConfig]:
        """Create a tracked source along with its technical crawl configuration."""
        source = await self.create_source(name_prefix=name_prefix)
        config_data = {
            "domain": f"{name_prefix}.example.edu",
            "site_name": f"Site {name_prefix}",
            "is_locked": is_locked,
        }
        if locked_at is not None:
            config_data["locked_at"] = locked_at

        config = await self.repo.upsert_source_config(source.id, config_data)
        return source, config

    async def create_operation(
        self,
        idempotency_key: str | None = None,
        sources_attempted: list[str] | None = None,
        triggered_by: str = "admin_api",
    ) -> ScrapeOperation:
        """Create a tracked scrape operation."""
        op = await self.repo.create_operation(
            idempotency_key=idempotency_key,
            triggered_by=triggered_by,
            sources_attempted=sources_attempted or [],
        )
        self.created_operations.append(op.id)
        return op

    async def cleanup(self) -> None:
        """Explicitly purge test rows created by this harness."""
        if self.created_operations:
            await self.db.rawgrantdetail.delete_many(
                where={"operation_id": {"in": self.created_operations}}
            )
            await self.db.rawlisting.delete_many(
                where={"operation_id": {"in": self.created_operations}}
            )
            await self.db.scrapeoperation.delete_many(
                where={"id": {"in": self.created_operations}}
            )

        if self.created_sources:
            await self.db.sourceconfig.delete_many(
                where={"source_id": {"in": self.created_sources}}
            )
            await self.db.scrapingtemplate.delete_many(
                where={"source_id": {"in": self.created_sources}}
            )
            await self.db.rawlisting.delete_many(
                where={"source_id": {"in": self.created_sources}}
            )
            await self.db.rawgrantdetail.delete_many(
                where={"source_id": {"in": self.created_sources}}
            )
            await self.db.source.delete_many(where={"id": {"in": self.created_sources}})


@pytest.fixture
async def pg_harness() -> AsyncGenerator[DatabaseTestHarness, None]:
    """Pytest fixture initializing real Prisma PostgreSQL connection and teardown."""
    if "test" not in DATABASE_URL.lower():
        pytest.fail(f"DATABASE_URL '{DATABASE_URL}' does not contain 'test'")

    client = Prisma(datasource={"url": DATABASE_URL})
    await client.connect()
    repo = ScrapingRepository(db=client)
    harness = DatabaseTestHarness(db=client, repo=repo)

    try:
        yield harness
    finally:
        await harness.cleanup()
        if client.is_connected():
            await client.disconnect()


# =============================================================================
# Scenario A: Concurrent same-key idempotency
# =============================================================================
@pytest.mark.asyncio
async def test_concurrent_same_key_idempotency(pg_harness: DatabaseTestHarness) -> None:
    """Verifies that multiple simultaneous requests with the same idempotency_key

    result in exactly one database record created, with all requests resolving
    to the identical operation record.
    """
    idempotency_key = f"idemp-{uuid.uuid4()}"
    source = await pg_harness.create_source(name_prefix="idemp-source")

    async def idempotent_request() -> ScrapeOperation:
        # Atomic check-or-create simulating concurrent worker triggers
        existing = await pg_harness.repo.get_operation_by_idempotency_key(
            idempotency_key
        )
        if existing:
            return existing
        try:
            return await pg_harness.repo.create_operation(
                idempotency_key=idempotency_key,
                sources_attempted=[source.id],
            )
        except UniqueViolationError:
            # Race condition lost: fetch existing operation row
            res = await pg_harness.repo.get_operation_by_idempotency_key(
                idempotency_key
            )
            assert res is not None
            return res

    # Launch 5 concurrent simultaneous requests with the same idempotency_key
    operations = await asyncio.gather(
        idempotent_request(),
        idempotent_request(),
        idempotent_request(),
        idempotent_request(),
        idempotent_request(),
    )

    # Track operation id for fixture cleanup
    pg_harness.created_operations.append(operations[0].id)

    # Invariant 1: All concurrent requests returned the exact same operation record
    first_op_id = operations[0].id
    for op in operations:
        assert op.id == first_op_id
        assert op.idempotency_key == idempotency_key

    # Invariant 2: Direct DB verification confirms exactly ONE row exists
    matching_rows = await pg_harness.db.scrapeoperation.find_many(
        where={"idempotency_key": idempotency_key}
    )
    assert len(matching_rows) == 1
    assert matching_rows[0].id == first_op_id

    # Invariant 3: find_unique query directly confirms persisted state
    db_op = await pg_harness.db.scrapeoperation.find_unique(where={"id": first_op_id})
    assert db_op is not None
    assert db_op.idempotency_key == idempotency_key
    assert db_op.status == "running"


# =============================================================================
# Scenario B: Competing source locks
# =============================================================================
@pytest.mark.asyncio
async def test_competing_source_locks_mutual_exclusion(
    pg_harness: DatabaseTestHarness,
) -> None:
    """Verifies that two concurrent operations attempting to acquire a lock on the

    same unlocked source result in exactly one winner and one rejected loser.
    """
    source, _ = await pg_harness.create_source_with_config(
        name_prefix="competing-lock",
        is_locked=False,
    )

    # Launch two simultaneous lock acquisitions against the unlocked source
    lock_results = await asyncio.gather(
        pg_harness.repo.acquire_source_lock(source.id),
        pg_harness.repo.acquire_source_lock(source.id),
    )

    # Invariant 1: Exactly one succeeded (True) and one was rejected (False)
    assert lock_results.count(True) == 1
    assert lock_results.count(False) == 1

    # Invariant 2: Direct DB assertion proves source is locked in PostgreSQL
    db_config = await pg_harness.db.sourceconfig.find_unique(
        where={"source_id": source.id}
    )
    assert db_config is not None
    assert db_config.is_locked is True
    assert db_config.locked_at is not None

    # Invariant 3: Subsequent sequential attempt while still locked is also rejected
    subsequent_result = await pg_harness.repo.acquire_source_lock(source.id)
    assert subsequent_result is False


# =============================================================================
# Scenario C: Unique listing / detail writes
# =============================================================================
@pytest.mark.asyncio
async def test_unique_listing_writes_and_idempotent_batch(
    pg_harness: DatabaseTestHarness,
) -> None:
    """Verifies unique listing URL constraints, duplicate write prevention,

    and batch insertion idempotency with skip_duplicates=True.
    """
    source = await pg_harness.create_source(name_prefix="unique-listings")
    operation = await pg_harness.create_operation(sources_attempted=[source.id])

    url_1 = f"https://unique.example.edu/grants/{uuid.uuid4()}"
    url_2 = f"https://unique.example.edu/grants/{uuid.uuid4()}"
    listing_page = "https://unique.example.edu/grants?page=1"

    # Step 1: Create initial listing row
    listing_1 = await pg_harness.repo.create_listing(
        operation_id=operation.id,
        source_id=source.id,
        discovered_url=url_1,
        listing_page_url=listing_page,
        card_title_preview="Original Grant 1",
    )
    assert listing_1.id is not None

    # Step 2: Attempting to insert duplicate listing with identical (source_id, discovered_url)
    with pytest.raises(UniqueViolationError):
        await pg_harness.repo.create_listing(
            operation_id=operation.id,
            source_id=source.id,
            discovered_url=url_1,
            listing_page_url=listing_page,
            card_title_preview="Duplicate Grant 1",
        )

    # Step 3: Batch insert containing existing url_1 and new url_2 with skip_duplicates=True
    batch_payload = [
        {
            "operation_id": operation.id,
            "source_id": source.id,
            "discovered_url": url_1,
            "listing_page_url": listing_page,
            "card_title_preview": "Duplicate Batch Item",
        },
        {
            "operation_id": operation.id,
            "source_id": source.id,
            "discovered_url": url_2,
            "listing_page_url": listing_page,
            "card_title_preview": "New Unique Batch Item",
        },
    ]
    inserted_count = await pg_harness.repo.create_listings_batch(
        batch_payload, skip_duplicates=True
    )
    assert inserted_count == 1

    # Invariant 4: Direct DB verification shows exactly 2 distinct rows for this source
    db_listings = await pg_harness.db.rawlisting.find_many(
        where={"source_id": source.id}
    )
    assert len(db_listings) == 2
    discovered_urls = {row.discovered_url for row in db_listings}
    assert discovered_urls == {url_1, url_2}

    # Step 4: Write grant detail associated with listing_1 and assert directly
    detail = await pg_harness.repo.create_grant_detail(
        operation_id=operation.id,
        source_id=source.id,
        source_url=url_1,
        raw_payload={"title": "Original Grant 1", "amount": 50000},
        listing_id=listing_1.id,
        attachment_metadata={},
    )
    assert detail.id is not None

    db_detail = await pg_harness.db.rawgrantdetail.find_unique(where={"id": detail.id})
    assert db_detail is not None
    assert db_detail.source_url == url_1
    assert db_detail.listing_id == listing_1.id
    assert db_detail.operation_id == operation.id


# =============================================================================
# Scenario D: Stale-lock auto-reclamation
# =============================================================================
@pytest.mark.asyncio
async def test_stale_lock_auto_reclamation(pg_harness: DatabaseTestHarness) -> None:
    """Verifies that a source locked in the past past TTL (> 900s) is automatically

    reclaimed when a new operation requests the lock.
    """
    now = datetime.now(UTC)
    stale_lock_time = now - timedelta(seconds=1200)  # 20 min ago (> 900s TTL)

    source, _ = await pg_harness.create_source_with_config(
        name_prefix="stale-reclaim",
        is_locked=True,
        locked_at=stale_lock_time,
    )

    # Step 1: Recent lock threshold (e.g. 60 min) considers it NOT stale and denies acquisition
    denied = await pg_harness.repo.acquire_source_lock(
        source.id, stale_lock_threshold_minutes=60
    )
    assert denied is False

    # Direct DB assertion: row remains locked at original timestamp
    db_cfg_initial = await pg_harness.db.sourceconfig.find_unique(
        where={"source_id": source.id}
    )
    assert db_cfg_initial is not None
    assert db_cfg_initial.is_locked is True

    # Step 2: 15-min TTL (900s) detects lock is stale and reclaims it automatically
    reclaimed = await pg_harness.repo.acquire_source_lock(
        source.id, stale_lock_threshold_minutes=15
    )
    assert reclaimed is True

    # Direct DB assertion: lock is held with a refreshed locked_at timestamp
    db_cfg_reclaimed = await pg_harness.db.sourceconfig.find_unique(
        where={"source_id": source.id}
    )
    assert db_cfg_reclaimed is not None
    assert db_cfg_reclaimed.is_locked is True
    assert db_cfg_reclaimed.locked_at is not None
    assert db_cfg_reclaimed.locked_at > stale_lock_time

    # Step 3: Verify break_stale_locks explicitly resets abandoned locks
    past_stale_time = datetime.now(UTC) - timedelta(minutes=45)
    await pg_harness.db.sourceconfig.update(
        where={"source_id": source.id},
        data={"is_locked": True, "locked_at": past_stale_time},
    )

    broken_count = await pg_harness.repo.break_stale_locks(stale_threshold_minutes=30)
    assert broken_count >= 1

    db_cfg_broken = await pg_harness.db.sourceconfig.find_unique(
        where={"source_id": source.id}
    )
    assert db_cfg_broken is not None
    assert db_cfg_broken.is_locked is False
    assert db_cfg_broken.locked_at is None


# =============================================================================
# Scenario E: Transaction rollback / failure consistency
# =============================================================================
@pytest.mark.asyncio
async def test_transaction_rollback_consistency(
    pg_harness: DatabaseTestHarness,
) -> None:
    """Verifies that database writes inside an aborted transaction roll back completely,

    leaving no orphaned rows in PostgreSQL.
    """
    rolled_back_source_id = str(uuid.uuid4())
    rolled_back_op_id = str(uuid.uuid4())

    with pytest.raises(RuntimeError, match="Simulated mid-transaction failure"):
        async with pg_harness.db.tx() as tx:
            await tx.source.create(
                data={
                    "id": rolled_back_source_id,
                    "url": f"https://tx-fail-{rolled_back_source_id}.example.edu",
                    "name": "Failing Transaction Source",
                }
            )
            await tx.scrapeoperation.create(
                data={
                    "id": rolled_back_op_id,
                    "status": "running",
                }
            )
            raise RuntimeError("Simulated mid-transaction failure")

    # Direct DB assertions: neither the source nor operation exists in PostgreSQL
    source_check = await pg_harness.db.source.find_unique(
        where={"id": rolled_back_source_id}
    )
    assert source_check is None

    op_check = await pg_harness.db.scrapeoperation.find_unique(
        where={"id": rolled_back_op_id}
    )
    assert op_check is None


@pytest.mark.asyncio
async def test_aborted_operation_releases_source_locks(
    pg_harness: DatabaseTestHarness,
) -> None:
    """Verifies that an aborted or failed operation cleanly releases distributed source locks."""
    source, _ = await pg_harness.create_source_with_config(
        name_prefix="abort-lock",
        is_locked=False,
    )
    operation = await pg_harness.create_operation(sources_attempted=[source.id])

    # Acquire lock for operation
    acquired = await pg_harness.repo.acquire_source_lock(source.id)
    assert acquired is True

    # Direct DB check: source is locked
    cfg_locked = await pg_harness.db.sourceconfig.find_unique(
        where={"source_id": source.id}
    )
    assert cfg_locked is not None
    assert cfg_locked.is_locked is True

    # Simulate operation abort / release
    released = await pg_harness.repo.release_all_source_locks([source.id])
    assert released == 1

    await pg_harness.repo.update_operation_status(
        operation.id, status="aborted", completed=True
    )

    # Invariant 1: Source lock is released in PostgreSQL
    cfg_released = await pg_harness.db.sourceconfig.find_unique(
        where={"source_id": source.id}
    )
    assert cfg_released is not None
    assert cfg_released.is_locked is False
    assert cfg_released.locked_at is None

    # Invariant 2: ScrapeOperation status is updated to aborted with completed_at timestamp
    op_db = await pg_harness.db.scrapeoperation.find_unique(where={"id": operation.id})
    assert op_db is not None
    assert op_db.status == "aborted"
    assert op_db.completed_at is not None


# =============================================================================
# Scenario F: Operation ordering and pagination
# =============================================================================
@pytest.mark.asyncio
async def test_operation_ordering_and_pagination(
    pg_harness: DatabaseTestHarness,
) -> None:
    """Verifies that querying operations returns descending chronological order

    with accurate limit/offset pagination and correct counting.
    """
    now = datetime.now(UTC)
    custom_ops: list[ScrapeOperation] = []

    # Create 5 distinct operations spaced chronologically
    for i in range(5):
        op_time = now - timedelta(hours=(5 - i))  # op 0 oldest, op 4 newest
        op = await pg_harness.db.scrapeoperation.create(
            data={
                "status": "completed",
                "triggered_by": "pagination_test",
                "started_at": op_time,
            }
        )
        pg_harness.created_operations.append(op.id)
        custom_ops.append(op)

    # Page 1: take 2, skip 0
    page_1 = await pg_harness.repo.list_operations(
        status="completed", limit=2, offset=0
    )
    assert len(page_1) == 2

    # Page 2: take 2, skip 2
    page_2 = await pg_harness.repo.list_operations(
        status="completed", limit=2, offset=2
    )
    assert len(page_2) == 2

    # Invariant 1: Descending chronological order within page_1
    assert page_1[0].started_at >= page_1[1].started_at

    # Invariant 2: Descending chronological order across pages (page 1 strictly newer than page 2)
    assert page_1[1].started_at >= page_2[0].started_at
    assert page_2[0].started_at >= page_2[1].started_at

    # Invariant 3: Disjoint pagination sets (no duplicated items across page 1 and page 2)
    page_1_ids = {op.id for op in page_1}
    page_2_ids = {op.id for op in page_2}
    assert page_1_ids.isdisjoint(page_2_ids)

    # Invariant 4: Direct DB verification confirms pagination matches repository query
    db_page_1 = await pg_harness.db.scrapeoperation.find_many(
        where={"status": "completed"},
        take=2,
        skip=0,
        order={"started_at": "desc"},
    )
    assert [op.id for op in page_1] == [op.id for op in db_page_1]

    # Invariant 5: Count matches total completed operations
    total_completed = await pg_harness.repo.count_operations(status="completed")
    assert total_completed >= 5
