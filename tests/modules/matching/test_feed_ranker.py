"""Unit tests for FeedRanker service (Task 9: Sort feed by Match %)."""

import pytest

from src.modules.matching.models import (
    FeedRankingResultDTO,
    UserProfileDTO,
)
from src.modules.matching.services.feed_ranker import (
    FeedRanker,
    rank_opportunities,
)


@pytest.fixture
def ranker() -> FeedRanker:
    return FeedRanker()


@pytest.fixture
def candidate_profile() -> UserProfileDTO:
    return UserProfileDTO(
        user_id="u_rank_test",
        nationality="Palestinian",
        education_level="bachelor",
        fields_of_study=[{"name": "Computer Science"}],
        skills=[{"name": "Python"}, {"name": "Docker"}],
        educations=[
            {
                "degree": "Bachelor of Science",
                "major": "Computer Science",
                "gpa_normalized_4": 3.8,
            }
        ],
        languages=[{"name": "English", "proficiency": "c1"}],
        experience_level="3",
    )


class TestFeedRankerSorting:
    def test_sorts_opportunities_by_match_score_descending(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """Feed results must be ordered by Match % descending with 1-indexed ranks."""
        # Opp 1: Matches Field (30%) + Skills (25%) + GPA (20%) -> 100%
        opp1 = {
            "id": "opp-high",
            "title": "High Match Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["Palestinian"]},
            "fields_of_study": ["Computer Science"],
            "skills": ["Python", "Docker"],
            "description": "Minimum GPA 3.5. Computer Science bachelor program for Palestinian students.",
        }
        # Opp 2: Matches Field (30%), fails GPA (20%) -> 60%
        opp2 = {
            "id": "opp-mid",
            "title": "Mid Match Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["Palestinian"]},
            "fields_of_study": ["Computer Science"],
            "description": "Minimum GPA 3.95. Computer Science bachelor program.",
        }
        # Opp 3: Mismatches Field (30%) -> 0%
        opp3 = {
            "id": "opp-low",
            "title": "Low Match Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["Palestinian"]},
            "fields_of_study": ["Fine Arts"],
            "description": "Fine Arts bachelor program.",
        }

        result = ranker.rank_opportunities(candidate_profile, [opp3, opp1, opp2])

        assert isinstance(result, FeedRankingResultDTO)
        assert result.total_eligible == 3
        assert result.is_relaxed is False
        assert len(result.items) == 3

        # Verify descending order
        assert result.items[0].opportunity["id"] == "opp-high"
        assert result.items[0].rank == 1
        assert result.items[0].match_score.score_pct == 100

        assert result.items[1].opportunity["id"] == "opp-mid"
        assert result.items[1].rank == 2
        assert result.items[1].match_score.score_pct == 60

        assert result.items[2].opportunity["id"] == "opp-low"
        assert result.items[2].rank == 3
        assert result.items[2].match_score.score_pct == 0

    def test_stable_sorting_on_tie_scores(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """When two opportunities have identical Match %, sort order must be stable."""
        opp_a = {
            "id": "opp-tie-a",
            "title": "Tie Opportunity A",
            "study_levels": ["bachelor"],
            "fields_of_study": ["Computer Science"],
        }
        opp_b = {
            "id": "opp-tie-b",
            "title": "Tie Opportunity B",
            "study_levels": ["bachelor"],
            "fields_of_study": ["Computer Science"],
        }

        # Input order: [opp_a, opp_b]
        res1 = ranker.rank_opportunities(candidate_profile, [opp_a, opp_b])
        assert res1.items[0].opportunity["id"] == "opp-tie-a"
        assert res1.items[1].opportunity["id"] == "opp-tie-b"

        # Input order: [opp_b, opp_a]
        res2 = ranker.rank_opportunities(candidate_profile, [opp_b, opp_a])
        assert res2.items[0].opportunity["id"] == "opp-tie-b"
        assert res2.items[1].opportunity["id"] == "opp-tie-a"

    def test_hard_filter_ineligible_excluded_from_standard_ranking(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """Opportunities that fail hard filters must NOT appear in the standard ranked feed."""
        eligible_opp = {
            "id": "opp-eligible",
            "title": "Eligible Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["Palestinian"]},
            "fields_of_study": ["Computer Science"],
        }
        ineligible_nationality_opp = {
            "id": "opp-ineligible-nat",
            "title": "Ineligible Nationality Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {
                "eligible_nationalities": ["French"]
            },  # User is Palestinian
            "fields_of_study": ["Computer Science"],
        }
        ineligible_education_opp = {
            "id": "opp-ineligible-edu",
            "title": "Ineligible Education Opportunity",
            "study_levels": ["phd"],  # User is bachelor
            "eligibility": {"eligible_nationalities": ["Palestinian"]},
            "fields_of_study": ["Computer Science"],
        }

        result = ranker.rank_opportunities(
            candidate_profile,
            [ineligible_nationality_opp, eligible_opp, ineligible_education_opp],
        )

        assert result.total_eligible == 1
        assert len(result.items) == 1
        assert result.items[0].opportunity["id"] == "opp-eligible"
        assert result.items[0].rank == 1

    def test_unknown_hard_filter_retained_in_ranking(self, ranker: FeedRanker) -> None:
        """Missing user data under explicit requirement results in UNKNOWN decision (retained, not excluded)."""
        # User has no nationality
        user = UserProfileDTO(
            user_id="u_no_nat",
            nationality=None,
            education_level="bachelor",
            fields_of_study=[{"name": "Computer Science"}],
        )
        opp = {
            "id": "opp-german-only",
            "title": "German Scholarship",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["Germany"]},
            "fields_of_study": ["Computer Science"],
        }

        result = ranker.rank_opportunities(user, [opp])
        assert result.total_eligible == 1
        assert len(result.items) == 1
        assert result.items[0].opportunity["id"] == "opp-german-only"

    def test_empty_opportunity_list_returns_zero_eligible(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """Empty input list returns empty result safely."""
        result = ranker.rank_opportunities(candidate_profile, [])
        assert result.total_eligible == 0
        assert len(result.items) == 0
        assert result.is_relaxed is False

    def test_rank_opportunities_convenience_function(
        self, candidate_profile: UserProfileDTO
    ) -> None:
        """Convenience rank_opportunities function produces valid FeedRankingResultDTO."""
        opp = {
            "id": "opp-1",
            "title": "Test Opp",
            "study_levels": ["bachelor"],
            "fields_of_study": ["Computer Science"],
        }
        res = rank_opportunities(candidate_profile, [opp])
        assert isinstance(res, FeedRankingResultDTO)
        assert res.total_eligible == 1
        assert res.items[0].rank == 1
        assert res.core_fields_complete is True


class TestZeroMatchRelaxation:
    """Tests for Task 12: Zero-match relaxation fallback."""

    def test_zero_match_triggers_relaxation_when_enabled(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """When 0 opportunities pass hard filters and relaxation is enabled, all opportunities are ranked with is_relaxed=True."""
        # Both opportunities explicitly require French nationality (candidate is Palestinian)
        opp1 = {
            "id": "opp-french-cs",
            "title": "French CS Scholarship",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["French"]},
            "fields_of_study": ["Computer Science"],
            "skills": ["Python"],
        }
        opp2 = {
            "id": "opp-french-arts",
            "title": "French Arts Scholarship",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["French"]},
            "fields_of_study": ["Fine Arts"],
        }

        # By default enable_relaxation=True
        result = ranker.rank_opportunities(
            candidate_profile, [opp2, opp1], enable_relaxation=True
        )

        assert result.is_relaxed is True
        assert result.total_eligible == 2
        assert len(result.items) == 2
        # CS opp has higher match % (field + skills match) than Arts opp
        assert result.items[0].opportunity["id"] == "opp-french-cs"
        assert result.items[0].rank == 1
        assert (
            result.items[0].match_score.score_pct
            > result.items[1].match_score.score_pct
        )
        assert result.items[1].opportunity["id"] == "opp-french-arts"
        assert result.items[1].rank == 2

    def test_zero_match_does_not_trigger_relaxation_when_disabled(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """When 0 opportunities pass and relaxation is disabled, empty feed is returned with is_relaxed=False."""
        opp1 = {
            "id": "opp-french-cs",
            "title": "French CS Scholarship",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["French"]},
            "fields_of_study": ["Computer Science"],
        }

        result = ranker.rank_opportunities(
            candidate_profile, [opp1], enable_relaxation=False
        )

        assert result.is_relaxed is False
        assert result.total_eligible == 0
        assert len(result.items) == 0

    def test_no_relaxation_when_at_least_one_opportunity_eligible(
        self, ranker: FeedRanker, candidate_profile: UserProfileDTO
    ) -> None:
        """Relaxation must NOT occur if at least 1 opportunity is eligible."""
        eligible_opp = {
            "id": "opp-eligible",
            "title": "Eligible Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["Palestinian"]},
            "fields_of_study": ["Computer Science"],
        }
        ineligible_opp = {
            "id": "opp-ineligible",
            "title": "Ineligible Opportunity",
            "study_levels": ["bachelor"],
            "eligibility": {"eligible_nationalities": ["French"]},
            "fields_of_study": ["Computer Science"],
        }

        result = ranker.rank_opportunities(
            candidate_profile, [ineligible_opp, eligible_opp], enable_relaxation=True
        )

        assert result.is_relaxed is False
        assert result.total_eligible == 1
        assert len(result.items) == 1
        assert result.items[0].opportunity["id"] == "opp-eligible"


class TestCoreFieldsCompleteness:
    """Tests for Task 14: Return core_fields_complete."""

    def test_core_fields_complete_true_when_all_core_fields_present(
        self, ranker: FeedRanker
    ) -> None:
        profile = UserProfileDTO(
            user_id="u_complete",
            nationality="Jordanian",
            education_level="Master",
            fields_of_study=[{"name": "Engineering"}],
            skills=[{"name": "AutoCAD"}],
        )
        assert profile.core_fields_complete is True

        opp = {
            "id": "opp-1",
            "title": "Eng Scholarship",
            "study_levels": ["master"],
            "fields_of_study": ["Engineering"],
        }
        result = ranker.rank_opportunities(profile, [opp])
        assert result.core_fields_complete is True

    def test_core_fields_complete_false_when_nationality_missing(
        self, ranker: FeedRanker
    ) -> None:
        profile = UserProfileDTO(
            user_id="u_missing_nat",
            nationality=None,
            education_level="Master",
            fields_of_study=[{"name": "Engineering"}],
            skills=[{"name": "AutoCAD"}],
        )
        assert profile.core_fields_complete is False

        opp = {
            "id": "opp-1",
            "title": "Eng Scholarship",
            "study_levels": ["master"],
            "fields_of_study": ["Engineering"],
        }
        result = ranker.rank_opportunities(profile, [opp])
        assert result.core_fields_complete is False

    def test_core_fields_complete_false_when_education_level_missing(self) -> None:
        profile = UserProfileDTO(
            user_id="u_missing_edu",
            nationality="Jordanian",
            education_level="",
            fields_of_study=[{"name": "Engineering"}],
            skills=[{"name": "AutoCAD"}],
        )
        assert profile.core_fields_complete is False

    def test_core_fields_complete_false_when_skills_empty(self) -> None:
        profile = UserProfileDTO(
            user_id="u_no_skills",
            nationality="Jordanian",
            education_level="Bachelor",
            fields_of_study=[{"name": "Engineering"}],
            skills=[],
        )
        assert profile.core_fields_complete is False

    def test_core_fields_complete_false_when_fields_of_study_empty(self) -> None:
        profile = UserProfileDTO(
            user_id="u_no_fos",
            nationality="Jordanian",
            education_level="Bachelor",
            fields_of_study=[],
            skills=[{"name": "Python"}],
        )
        assert profile.core_fields_complete is False
