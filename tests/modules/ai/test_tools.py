import asyncio
import inspect

import pytest

from src.modules.ai.tools import NO_RESULTS, NOT_FOUND, TOOL_FAILED, build_chat_tools

from .fakes import (
    FakeMatchScoreRepository,
    FakeOpportunityRepository,
    make_opportunity,
    make_score,
)

USER = "user-1"
OTHER_USER = "user-2"


def build(opportunities=None, scores=None):
    opportunity_repo = FakeOpportunityRepository(
        opportunities if opportunities is not None else [make_opportunity()]
    )
    match_repo = FakeMatchScoreRepository(scores if scores is not None else {})
    tools = build_chat_tools(
        user_id=USER,
        opportunities=opportunity_repo,
        matches=match_repo,
        loop=asyncio.get_event_loop(),
    )
    return {t.__name__: t for t in tools}, opportunity_repo, match_repo


class TestToolSurface:
    async def test_exposes_the_expected_tools(self):
        tools, _, _ = build()

        assert sorted(tools) == [
            "get_my_match_score",
            "get_my_top_matches",
            "get_opportunity_details",
            "search_opportunities",
        ]

    async def test_no_tool_accepts_an_identity_argument(self):
        tools, _, _ = build()

        for name, tool in tools.items():
            params = set(inspect.signature(tool).parameters)
            assert not params & {"user_id", "student_id", "principal", "roles"}, name

    async def test_every_tool_is_documented(self):
        tools, _, _ = build()

        for name, tool in tools.items():
            assert (tool.__doc__ or "").strip(), name


class TestSearchOpportunities:
    async def test_lists_matches_with_ids(self):
        tools, repo, _ = build()

        result = await asyncio.to_thread(
            tools["search_opportunities"], "Chevening", "", "", "", "", 3
        )

        assert "Chevening Scholarship" in result
        assert "id=opp-1" in result
        assert repo.searches[0]["limit"] == 3

    async def test_passes_filters_through(self):
        tools, repo, _ = build()

        await asyncio.to_thread(
            tools["search_opportunities"], "", "scholarship", "Turkey", "", "Master"
        )

        call = repo.searches[0]
        assert call["opportunity_type"] == "scholarship"
        assert call["country"] == "Turkey"
        assert call["study_level"] == "Master"
        assert call["funding_type"] is None

    async def test_reports_empty_results(self):
        tools, _, _ = build()

        assert await asyncio.to_thread(tools["search_opportunities"], "nothing") == (
            NO_RESULTS
        )

    async def test_reports_failure_without_raising(self):
        tools, repo, _ = build()
        repo.search_error = RuntimeError("db down")

        assert (
            await asyncio.to_thread(tools["search_opportunities"], "x") == TOOL_FAILED
        )


class TestOpportunityDetails:
    async def test_returns_full_context(self):
        tools, _, _ = build()

        result = await asyncio.to_thread(tools["get_opportunity_details"], "opp-1")

        assert "Title: Chevening Scholarship" in result
        assert "Deadline: 2026-11-05" in result

    async def test_unknown_id(self):
        tools, _, _ = build()

        assert await asyncio.to_thread(tools["get_opportunity_details"], "nope") == (
            NOT_FOUND
        )

    async def test_hides_uncleaned_opportunity(self):
        tools, _, _ = build(opportunities=[make_opportunity(status="failed")])

        assert await asyncio.to_thread(tools["get_opportunity_details"], "opp-1") == (
            NOT_FOUND
        )


class TestPersonalTools:
    @pytest.fixture
    def scores(self):
        return {
            USER: [make_score(), make_score("opp-2", 51, "Stockholm Scholarship")],
            OTHER_USER: [make_score("opp-9", 99, "Secret Scholarship")],
        }

    async def test_match_score_is_read_for_the_bound_user(self, scores):
        tools, _, matches = build(scores=scores)

        result = await asyncio.to_thread(tools["get_my_match_score"], "opp-1")

        assert "score=72%" in result
        assert "field_of_study" in result
        assert matches.calls == [(USER, "opp-1")]

    async def test_another_users_score_is_unreachable(self, scores):
        tools, _, matches = build(scores=scores)

        result = await asyncio.to_thread(tools["get_my_match_score"], "opp-9")

        assert "No match score" in result
        assert matches.calls == [(USER, "opp-9")]

    async def test_top_matches_are_ranked_and_scoped(self, scores):
        tools, _, matches = build(scores=scores)

        result = await asyncio.to_thread(tools["get_my_top_matches"], 5)

        assert result.index("Chevening") < result.index("Stockholm")
        assert "Secret Scholarship" not in result
        assert matches.calls == [(USER, "top:5")]

    async def test_without_scores(self):
        tools, _, _ = build(scores={})

        assert "No match scores" in await asyncio.to_thread(tools["get_my_top_matches"])
