"""Integration tests for FeedRanker evaluated against the 25 real opportunities dataset."""

import json
from pathlib import Path
from typing import Any

import pytest

from src.modules.matching.models import (
    FeedRankingResultDTO,
    RankedOpportunityDTO,
    UserProfileDTO,
)
from src.modules.matching.services.feed_ranker import FeedRanker


@pytest.fixture(scope="module")
def ranker() -> FeedRanker:
    return FeedRanker()


@pytest.fixture(scope="module")
def real_opportunities() -> list[dict[str, Any]]:
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "real_cleaned_opportunities_25.json"
    )
    if fixture_path.exists():
        with open(fixture_path, encoding="utf-8") as f:
            return json.load(f)[:25]

    scratch_path = Path(
        r"C:\Users\msi\.gemini\antigravity\brain\399f96b8-3165-4f5f-8dd6-9f60fd12604a\scratch\audited_opps_clean.json"
    )
    if scratch_path.exists():
        with open(scratch_path, encoding="utf-8") as f:
            return json.load(f)[:25]

    raise FileNotFoundError("Could not find 25 real opportunities fixture dataset.")


@pytest.fixture
def sample_profiles() -> dict[str, UserProfileDTO]:
    return {
        "palestinian_cs_bachelor": UserProfileDTO(
            user_id="u_pal_cs",
            nationality="Palestinian",
            education_level="bachelor",
            fields_of_study=[{"name": "Computer Science"}],
            skills=[
                {"name": "Python"},
                {"name": "Docker"},
                {"name": "Machine Learning"},
            ],
            educations=[
                {
                    "degree": "Bachelor of Science",
                    "major": "Computer Science",
                    "gpa_normalized_4": 3.85,
                }
            ],
            languages=[
                {"name": "Arabic", "proficiency": "native"},
                {"name": "English", "proficiency": "c1"},
            ],
            experience_level="3",
        ),
        "jordanian_master": UserProfileDTO(
            user_id="u_jor_master",
            nationality="Jordanian",
            education_level="master",
            fields_of_study=[{"name": "Business Administration"}],
            skills=[{"name": "Leadership"}, {"name": "Financial Analysis"}],
            educations=[
                {
                    "degree": "Master of Business Administration",
                    "major": "Management",
                    "gpa_normalized_4": 3.6,
                }
            ],
            languages=[
                {"name": "Arabic", "proficiency": "native"},
                {"name": "English", "proficiency": "b2"},
            ],
            experience_level="5",
        ),
    }


def test_real_data_feed_ranking_monotonicity(
    ranker: FeedRanker,
    real_opportunities: list[dict[str, Any]],
    sample_profiles: dict[str, UserProfileDTO],
) -> None:
    """Verifies that ranking across all 25 real opportunities produces strictly descending Match %."""
    for profile_name, user_profile in sample_profiles.items():
        feed_result = ranker.rank_opportunities(user_profile, real_opportunities)

        assert isinstance(feed_result, FeedRankingResultDTO)
        assert feed_result.total_eligible == len(feed_result.items)

        # Monotonicity check: score_pct[i] >= score_pct[i+1]
        for i in range(len(feed_result.items) - 1):
            curr_item = feed_result.items[i]
            next_item = feed_result.items[i + 1]

            assert isinstance(curr_item, RankedOpportunityDTO)
            assert curr_item.rank == i + 1
            assert curr_item.match_score.score_pct >= next_item.match_score.score_pct, (
                f"Monotonicity violation for {profile_name} at rank {i+1}: "
                f"{curr_item.match_score.score_pct} < {next_item.match_score.score_pct}"
            )


def test_real_data_feed_ranking_determinism(
    ranker: FeedRanker,
    real_opportunities: list[dict[str, Any]],
    sample_profiles: dict[str, UserProfileDTO],
) -> None:
    """Verifies that running feed ranking twice on real opportunities produces identical ordering."""
    user = sample_profiles["palestinian_cs_bachelor"]

    res1 = ranker.rank_opportunities(user, real_opportunities)
    res2 = ranker.rank_opportunities(user, real_opportunities)

    assert res1.total_eligible == res2.total_eligible
    assert len(res1.items) == len(res2.items)

    for i in range(len(res1.items)):
        item1 = res1.items[i]
        item2 = res2.items[i]
        assert item1.rank == item2.rank
        assert item1.match_score.score_pct == item2.match_score.score_pct
        assert item1.opportunity.get("id") == item2.opportunity.get("id")


def test_real_data_zero_match_relaxation(
    ranker: FeedRanker,
    real_opportunities: list[dict[str, Any]],
) -> None:
    """When a user is ineligible for a restricted subset of opportunities, relaxation includes all items with is_relaxed=True."""
    # Create a profile with a nationality that is excluded from specific country-only opportunities
    user = UserProfileDTO(
        user_id="u_restricted_nat",
        nationality="FictionalCountry",
        education_level="postdoc",  # study level where opps require bachelor/master
        fields_of_study=[{"name": "Computer Science"}],
        skills=[{"name": "Python"}],
    )

    # Pick an opportunity from real dataset that strictly requires master/bachelor
    # e.g., opps that have explicit study levels that exclude postdoc
    restricted_opps = [
        opp
        for opp in real_opportunities
        if opp.get("study_levels")
        and "postdoc" not in [str(s).lower() for s in opp.get("study_levels", [])]
    ][:3]

    if restricted_opps:
        # Standard filter produces 0 matches because study level mismatches
        res = ranker.rank_opportunities(user, restricted_opps, enable_relaxation=True)
        assert res.is_relaxed is True
        assert res.total_eligible == len(restricted_opps)
        assert len(res.items) == len(restricted_opps)


def test_real_data_core_completeness_flag(
    ranker: FeedRanker,
    real_opportunities: list[dict[str, Any]],
    sample_profiles: dict[str, UserProfileDTO],
) -> None:
    """Verifies that core_fields_complete flag is properly propagated in real feed results."""
    complete_user = sample_profiles["palestinian_cs_bachelor"]
    res_complete = ranker.rank_opportunities(complete_user, real_opportunities[:5])
    assert res_complete.core_fields_complete is True

    incomplete_user = UserProfileDTO(
        user_id="u_incomplete",
        nationality=None,
        education_level=None,
    )
    res_incomplete = ranker.rank_opportunities(incomplete_user, real_opportunities[:5])
    assert res_incomplete.core_fields_complete is False
