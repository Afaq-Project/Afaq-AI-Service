import asyncio

import pytest
from wardhook.core import AgentGraph

from src.modules.ai.guardrails import build_chat_guardrails, build_tool_policy
from src.modules.ai.tools import build_chat_tools

from .fakes import (
    FakeMatchScoreRepository,
    FakeOpportunityRepository,
    make_opportunity,
    make_score,
    model_calling,
    tool_messages,
)

STUDENT = "student-1"
OTHER_STUDENT = "student-2"

SCORES = {
    STUDENT: [make_score("opp-1", 72, "Chevening Scholarship")],
    OTHER_STUDENT: [make_score("opp-9", 99, "Secret Scholarship")],
}


def context(*roles: str) -> dict:
    if not roles:
        return {}
    return {"principal": {"id": STUDENT, "roles": list(roles)}}


class TestPolicy:
    @pytest.fixture
    def policy(self):
        return build_tool_policy()

    @pytest.mark.parametrize(
        "tool",
        ["search_opportunities", "get_opportunity_details"],
    )
    def test_public_tools_are_open_to_every_role(self, policy, tool):
        for role in ("guest", "student", "advisor", "admin"):
            assert policy.on_tool_call(tool, {}, context(role)).allowed, role

    def test_personal_tools_need_more_than_guest(self, policy):
        assert policy.on_tool_call("get_my_top_matches", {}, context("guest")).blocked
        assert policy.on_tool_call("get_my_top_matches", {}, context("student")).allowed

    def test_unknown_principal_gets_nothing_personal(self, policy):
        assert policy.on_tool_call("get_my_match_score", {}, {}).blocked

    def test_unknown_role_grants_nothing(self, policy):
        assert policy.on_tool_call("get_my_match_score", {}, context("hacker")).blocked
        assert policy.on_tool_call(
            "search_opportunities", {}, context("hacker")
        ).blocked

    def test_principal_without_roles_falls_back_to_guest(self, policy):
        bare = {"principal": {"id": STUDENT}}

        assert policy.on_tool_call("search_opportunities", {}, bare).allowed
        assert policy.on_tool_call("get_my_top_matches", {}, bare).blocked

    def test_unlisted_tool_is_denied_even_for_students(self, policy):
        assert policy.on_tool_call("delete_everything", {}, context("student")).blocked

    def test_admin_may_call_anything(self, policy):
        assert policy.on_tool_call("delete_everything", {}, context("admin")).allowed

    def test_policy_is_part_of_the_chat_guardrails(self):
        names = [type(g).__name__ for g in build_chat_guardrails()]
        assert "RoleBasedToolPolicy" in names


async def run_agent(calls, roles, user_id=STUDENT):
    loop = asyncio.get_running_loop()
    tools = build_chat_tools(
        user_id=user_id,
        opportunities=FakeOpportunityRepository([make_opportunity()]),
        matches=FakeMatchScoreRepository(SCORES),
        loop=loop,
    )
    agent = AgentGraph(
        model=model_calling(*calls),
        tools=tools,
        guardrails=build_chat_guardrails(),
        name="test-chat",
    )
    principal = {"id": user_id, "roles": list(roles)} if roles else None
    return await agent.ainvoke("سؤال عن المنحة", principal=principal)


class TestAgentWithTools:
    async def test_student_reads_their_own_score(self):
        result = await run_agent(
            [("get_my_match_score", {"opportunity_id": "opp-1"})], ["student"]
        )

        assert result["blocked"] is False
        assert "score=72%" in tool_messages(result)[0]
        assert result["tool_calls"] == ["get_my_match_score"]

    async def test_guest_is_denied_personal_data(self):
        result = await run_agent([("get_my_top_matches", {})], ["guest"])

        message = tool_messages(result)[0]
        assert "denied by policy" in message
        assert "72" not in message
        assert any(
            event.get("action") == "block" and event.get("tool") == "get_my_top_matches"
            for event in result["guardrail_events"]
        )

    async def test_guest_still_searches_the_catalogue(self):
        result = await run_agent(
            [("search_opportunities", {"query": "Chevening"})], ["guest"]
        )

        assert "Chevening Scholarship" in tool_messages(result)[0]

    async def test_call_without_principal_is_denied(self):
        result = await run_agent([("get_my_top_matches", {})], None)

        assert "denied by policy" in tool_messages(result)[0]

    async def test_model_cannot_borrow_another_identity(self):
        result = await run_agent(
            [
                (
                    "get_my_match_score",
                    {"opportunity_id": "opp-9", "user_id": OTHER_STUDENT},
                )
            ],
            ["student"],
        )

        message = tool_messages(result)[0]
        assert "Secret Scholarship" not in message
        assert "99" not in message

    async def test_score_of_another_student_is_not_returned(self):
        result = await run_agent(
            [("get_my_match_score", {"opportunity_id": "opp-9"})], ["student"]
        )

        assert "No match score" in tool_messages(result)[0]
