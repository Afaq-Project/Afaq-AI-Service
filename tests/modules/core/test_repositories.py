from types import SimpleNamespace

from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.core.database.repositories.source_repository import SourceRepository


class FakeTable:
    """جدول وهمي يسجّل الاستدعاءات ويرجع نتائج محضّرة."""

    def __init__(self, records=None):
        self.records = records or []
        self.created = []
        self.updated = []
        self.find_many_calls = []

    async def create(self, data):
        record = SimpleNamespace(id=f"rec-{len(self.created)}", **data)
        self.created.append(data)
        return record

    async def update(self, where, data):
        self.updated.append((where, data))
        return SimpleNamespace(id=where["id"], **data)

    async def find_many(self, where=None):
        self.find_many_calls.append(where)
        if where and "id" in where:
            wanted = set(where["id"]["in"])
            return [r for r in self.records if r.id in wanted]
        return list(self.records)

    async def find_unique(self, where):
        key, value = next(iter(where.items()))
        return next((r for r in self.records if getattr(r, key) == value), None)

    async def find_first(self, where):
        key, value = next(iter(where.items()))
        return next((r for r in self.records if getattr(r, key) == value), None)

    async def count(self, where=None):
        return len(self.records)


class FakeDb:
    def __init__(self, raw=None, cleaned=None, sources=None):
        self.rawopportunity = FakeTable(raw)
        self.cleanedopportunity = FakeTable(cleaned)
        self.source = FakeTable(sources)


def make_source(id_="src-1", name="almin7"):
    return SimpleNamespace(id=id_, name=name, last_scraped_at=None)


class TestOpportunityRepository:
    async def test_create_raw_stores_payload(self):
        db = FakeDb()
        repo = OpportunityRepository(db)
        await repo.create_raw("src-1", {"title": "Scholarship"})

        assert len(db.rawopportunity.created) == 1
        assert db.rawopportunity.created[0]["source_id"] == "src-1"

    async def test_create_raw_defaults_to_pending(self):
        db = FakeDb()
        repo = OpportunityRepository(db)
        await repo.create_raw("src-1", {})

        assert db.rawopportunity.created[0]["status"] == "pending"

    async def test_create_many_raw_stores_all(self):
        db = FakeDb()
        repo = OpportunityRepository(db)
        created = await repo.create_many_raw("src-1", [{"a": 1}, {"b": 2}, {"c": 3}])

        assert len(created) == 3
        assert len(db.rawopportunity.created) == 3

    async def test_create_many_raw_handles_empty_list(self):
        db = FakeDb()
        repo = OpportunityRepository(db)
        assert await repo.create_many_raw("src-1", []) == []

    async def test_mark_raw_status_records_error(self):
        db = FakeDb()
        repo = OpportunityRepository(db)
        await repo.mark_raw_status("raw-1", "failed", "parse error")

        where, data = db.rawopportunity.updated[0]
        assert where["id"] == "raw-1"
        assert data["status"] == "failed"
        assert data["error_message"] == "parse error"

    async def test_create_cleaned_stores_record(self):
        db = FakeDb()
        repo = OpportunityRepository(db)
        await repo.create_cleaned(
            {
                "raw_opportunity_id": "raw-1",
                "title": "Fulbright",
                "source_url": "https://example.com/1",
            }
        )

        assert db.cleanedopportunity.created[0]["title"] == "Fulbright"

    async def test_exists_by_content_hash_true(self):
        existing = SimpleNamespace(id="c-1", content_hash="abc123")
        repo = OpportunityRepository(FakeDb(cleaned=[existing]))

        assert await repo.exists_by_content_hash("abc123") is True

    async def test_exists_by_content_hash_false(self):
        repo = OpportunityRepository(FakeDb(cleaned=[]))
        assert await repo.exists_by_content_hash("nothing") is False

    async def test_find_within_visibility_window_queries_cutoff_date(self):
        from datetime import UTC, datetime, timedelta

        db = FakeDb(cleaned=[])
        repo = OpportunityRepository(db)
        fixed_now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

        await repo.find_within_visibility_window(
            now=fixed_now, retention_days=30, include_null_deadlines=True
        )

        assert len(db.cleanedopportunity.find_many_calls) == 1
        where = db.cleanedopportunity.find_many_calls[0]
        assert "OR" in where
        cutoff_date = fixed_now.date() - timedelta(days=30)
        expected_cutoff = datetime.combine(cutoff_date, datetime.min.time()).replace(
            tzinfo=UTC
        )
        assert where["OR"][0] == {"deadline": {"gte": expected_cutoff}}
        assert where["OR"][1] == {"deadline": None}

    async def test_find_within_visibility_window_excludes_null_when_requested(self):
        from datetime import UTC, datetime, timedelta

        db = FakeDb(cleaned=[])
        repo = OpportunityRepository(db)
        fixed_now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)

        await repo.find_within_visibility_window(
            now=fixed_now, retention_days=30, include_null_deadlines=False
        )

        assert len(db.cleanedopportunity.find_many_calls) == 1
        where = db.cleanedopportunity.find_many_calls[0]
        cutoff_date = fixed_now.date() - timedelta(days=30)
        expected_cutoff = datetime.combine(cutoff_date, datetime.min.time()).replace(
            tzinfo=UTC
        )
        assert where == {"deadline": {"gte": expected_cutoff}}


class TestSourceRepository:
    async def test_get_by_ids_returns_matching(self):
        sources = [make_source("src-1"), make_source("src-2", "grab")]
        repo = SourceRepository(FakeDb(sources=sources))

        result = await repo.get_by_ids(["src-1", "src-2"])
        assert len(result) == 2

    async def test_get_by_ids_ignores_missing(self):
        repo = SourceRepository(FakeDb(sources=[make_source("src-1")]))

        result = await repo.get_by_ids(["src-1", "does-not-exist"])
        assert len(result) == 1
        assert result[0].id == "src-1"

    async def test_get_by_ids_empty_input_returns_empty(self):
        repo = SourceRepository(FakeDb(sources=[make_source()]))
        assert await repo.get_by_ids([]) == []

    async def test_get_by_name_finds_source(self):
        repo = SourceRepository(FakeDb(sources=[make_source(name="almin7")]))
        found = await repo.get_by_name("almin7")

        assert found is not None
        assert found.name == "almin7"

    async def test_get_by_name_returns_none_when_absent(self):
        repo = SourceRepository(FakeDb(sources=[make_source(name="almin7")]))
        assert await repo.get_by_name("unknown") is None

    async def test_list_all_returns_everything(self):
        sources = [make_source("src-1"), make_source("src-2", "grab")]
        repo = SourceRepository(FakeDb(sources=sources))

        assert len(await repo.list_all()) == 2

    async def test_mark_scraped_sets_timestamp(self):
        db = FakeDb(sources=[make_source("src-1")])
        repo = SourceRepository(db)
        await repo.mark_scraped("src-1")

        where, data = db.source.updated[0]
        assert where["id"] == "src-1"
        assert data["last_scraped_at"] is not None
