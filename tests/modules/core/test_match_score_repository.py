from datetime import UTC, datetime
from types import SimpleNamespace

from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)


class RecordingTable:

    def __init__(self, first=None, many=None):
        self.first = first
        self.many = many or []
        self.calls: list[tuple[str, dict]] = []

    async def find_first(self, **kwargs):
        self.calls.append(("find_first", kwargs))
        return self.first

    async def find_many(self, **kwargs):
        self.calls.append(("find_many", kwargs))
        return list(self.many)


class FakeDb:

    def __init__(self, matchscore=None, cleanedopportunity=None):
        self.matchscore = matchscore or RecordingTable()
        self.cleanedopportunity = cleanedopportunity or RecordingTable()


class TestMatchScoreRepository:
    async def test_score_lookup_is_scoped_to_the_user(self):
        db = FakeDb(matchscore=RecordingTable(first=SimpleNamespace(score_pct=72)))

        result = await MatchScoreRepository(db).get_for_user("user-1", "opp-1")

        assert result.score_pct == 72
        _, kwargs = db.matchscore.calls[0]
        assert kwargs["where"] == {"user_id": "user-1", "opportunity_id": "opp-1"}

    async def test_top_matches_are_scoped_ordered_and_capped(self):
        db = FakeDb(matchscore=RecordingTable(many=[SimpleNamespace(score_pct=90)]))

        await MatchScoreRepository(db).top_for_user("user-1", limit=500)

        _, kwargs = db.matchscore.calls[0]
        assert kwargs["where"] == {"user_id": "user-1"}
        assert kwargs["order"] == {"score_pct": "desc"}
        assert kwargs["take"] == 20

    async def test_limit_has_a_floor(self):
        db = FakeDb()

        await MatchScoreRepository(db).top_for_user("user-1", limit=0)

        assert db.matchscore.calls[0][1]["take"] == 1


class TestOpportunitySearch:
    async def test_only_cleaned_and_recent_opportunities(self):
        db = FakeDb()

        await OpportunityRepository(db).search_visible(
            now=datetime(2026, 10, 1, tzinfo=UTC)
        )

        _, kwargs = db.cleanedopportunity.calls[0]
        conditions = kwargs["where"]["AND"]
        assert {"status": "cleaned"} in conditions
        deadline_rule = next(c for c in conditions if "OR" in c)
        assert deadline_rule["OR"][1] == {"deadline": None}
        assert deadline_rule["OR"][0]["deadline"]["gte"] == datetime(
            2026, 9, 1, tzinfo=UTC
        )

    async def test_query_searches_title_description_and_organization(self):
        db = FakeDb()

        await OpportunityRepository(db).search_visible(query="  chevening  ")

        conditions = db.cleanedopportunity.calls[0][1]["where"]["AND"]
        text_rule = next(c for c in conditions if "OR" in c and "title" in c["OR"][0])
        fields = {list(entry)[0] for entry in text_rule["OR"]}
        assert fields == {"title", "description", "organization"}
        assert text_rule["OR"][0]["title"]["contains"] == "chevening"

    async def test_filters_are_optional(self):
        db = FakeDb()

        await OpportunityRepository(db).search_visible(
            opportunity_type="scholarship", country="Turkey", study_level="Master"
        )

        conditions = db.cleanedopportunity.calls[0][1]["where"]["AND"]
        assert {
            "opportunity_type": {"equals": "scholarship", "mode": "insensitive"}
        } in (conditions)
        assert {"country": {"contains": "Turkey", "mode": "insensitive"}} in conditions
        assert {"study_levels": {"has": "Master"}} in conditions
        assert not any("funding_type" in c for c in conditions)

    async def test_result_size_is_capped(self):
        db = FakeDb()

        await OpportunityRepository(db).search_visible(limit=100)

        assert db.cleanedopportunity.calls[0][1]["take"] == 20
