"""Unit tests for MatchCalculator and Dynamic Denominator normalization in Afaq AI Matching Engine."""

import pytest

from src.modules.matching.models import (
    ExtractedRequirement,
    MatchScoreResultDTO,
    OpportunityRequirementsDTO,
    RequirementStatus,
    UserProfileDTO,
)
from src.modules.matching.services.match_calculator import (
    MatchCalculator,
    calculate_match_score,
)


class TestMatchCalculatorDynamicDenominator:
    @pytest.fixture
    def calculator(self):
        return MatchCalculator()

    def test_all_five_categories_active_full_match(self, calculator):
        """When all 5 categories are active and matched 100%, score = 100%, coverage = 100%."""
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            skills=[{"name": "Python"}, {"name": "Docker"}],
            educations=[
                {
                    "degree": "Bachelor",
                    "major": "Computer Science",
                    "gpa_normalized_4": 3.8,
                }
            ],
            languages=[{"name": "English", "proficiency": "c1"}],
            experience_level="3",
        )
        reqs = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
            skills=ExtractedRequirement(
                category="skills",
                status=RequirementStatus.REQUIRED,
                value={"skills": ["Python", "Docker"]},
            ),
            gpa=ExtractedRequirement(
                category="gpa",
                status=RequirementStatus.REQUIRED,
                value={"min_gpa_normalized_4": 3.5},
            ),
            language=ExtractedRequirement(
                category="language",
                status=RequirementStatus.REQUIRED,
                value={"languages": [{"name": "English", "min_proficiency": "b2"}]},
            ),
            experience=ExtractedRequirement(
                category="experience",
                status=RequirementStatus.REQUIRED,
                value={"min_years": 2},
            ),
        )

        res = calculator.calculate_match_score(user, reqs)
        assert res.score_pct == 100
        assert res.raw_score == 100.0
        assert res.coverage_pct == 100.0
        assert len(res.applicable_categories) == 5
        assert len(res.uncomputable_categories) == 0
        assert len(res.missing_user_categories) == 0
        assert len(res.silent_opportunity_categories) == 0

    def test_subset_categories_active_dynamic_denominator(self, calculator):
        """Opportunity specifies ONLY Field of Study (30%) and Skills (25%).

        Active categories = 2.
        Dynamic Denominator D = 0.30 + 0.25 = 0.55.
        Coverage = 55.0%.
        User matches Field 100% and Skills 100%.
        Score = (0.30*1.0 + 0.25*1.0) / 0.55 = 100%.
        """
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            skills=[{"name": "Python"}],
        )
        reqs = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
            skills=ExtractedRequirement(
                category="skills",
                status=RequirementStatus.REQUIRED,
                value={"skills": ["Python"]},
            ),
            gpa=None,
            language=None,
            experience=None,
        )

        res = calculator.calculate_match_score(user, reqs)
        assert res.coverage_pct == 55.0
        assert res.score_pct == 100
        assert res.raw_score == 100.0
        assert set(res.applicable_categories) == {"field_of_study", "skills"}
        assert set(res.silent_opportunity_categories) == {
            "gpa",
            "language",
            "experience",
        }

    def test_partial_match_dynamic_denominator(self, calculator):
        """Opportunity specifies Field of Study (30%) and GPA (20%). D = 0.50.

        User matches Field 100%, but fails GPA (0%).
        Sum weighted pct = 0.30 * 1.0 + 0.20 * 0.0 = 0.30.
        Score = 0.30 / 0.50 * 100 = 60%.
        """
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            educations=[{"degree": "Bachelor", "gpa_normalized_4": 2.8}],
        )
        reqs = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
            gpa=ExtractedRequirement(
                category="gpa",
                status=RequirementStatus.REQUIRED,
                value={"min_gpa_normalized_4": 3.5},
            ),
        )

        res = calculator.calculate_match_score(user, reqs)
        assert res.coverage_pct == 50.0
        assert res.score_pct == 60
        assert res.raw_score == 60.0

    def test_required_missing_user_data_penalized_in_denominator(self, calculator):
        """REQUIRED GPA specified (20%), user has NO GPA in profile.

        Field (30%) is matched 100%.
        D = 0.50.
        GPA gets score_pct = 0% and remains in D.
        Score = 0.30 / 0.50 * 100 = 60%.
        'gpa' is recorded in missing_user_categories.
        """
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            educations=[],  # No education/GPA
        )
        reqs = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
            gpa=ExtractedRequirement(
                category="gpa",
                status=RequirementStatus.REQUIRED,
                value={"min_gpa_normalized_4": 3.0},
            ),
        )

        res = calculator.calculate_match_score(user, reqs)
        assert res.coverage_pct == 50.0
        assert res.score_pct == 60
        assert "gpa" in res.missing_user_categories

    def test_preferred_missing_user_data_excluded_from_denominator(self, calculator):
        """PREFERRED Language specified (15%), user has NO languages in profile.

        Field (30%) is REQUIRED and matched 100%.
        Language is PREFERRED and missing -> excluded from D (neutral, no penalty).
        D = 0.30.
        Score = 0.30 / 0.30 * 100 = 100%.
        Coverage = 30.0%.
        """
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            languages=[],
        )
        reqs = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
            language=ExtractedRequirement(
                category="language",
                status=RequirementStatus.PREFERRED,
                value={"languages": [{"name": "French", "min_proficiency": "b1"}]},
            ),
        )

        res = calculator.calculate_match_score(user, reqs)
        assert res.coverage_pct == 30.0
        assert res.score_pct == 100
        assert "language" not in res.applicable_categories
        assert "language" not in res.missing_user_categories

    def test_uncomputable_category_excluded_from_denominator(self, calculator):
        """Opportunity specifies qualitative experience ('leadership required').

        Experience is marked UNCOMPUTABLE, excluded from D, and tracked in uncomputable_categories.
        Field (30%) is matched 100%.
        D = 0.30.
        Score = 100%.
        """
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            experience_level="mid",
        )
        reqs = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
            experience=ExtractedRequirement(
                category="experience",
                status=RequirementStatus.REQUIRED,
                value={"text": "Senior leadership level required"},
            ),
        )

        res = calculator.calculate_match_score(user, reqs)
        assert res.coverage_pct == 30.0
        assert res.score_pct == 100
        assert "experience" in res.uncomputable_categories
        assert "experience" not in res.applicable_categories

    def test_zero_applicable_categories_denominator_zero(self, calculator):
        """Opportunity has NO scoring requirements (or all are uncomputable/neutral).

        D = 0.
        Score = 0%, Coverage = 0.0%.
        """
        user = UserProfileDTO(
            user_id="u1", fields_of_study=[{"name": "Computer Science"}]
        )
        reqs = OpportunityRequirementsDTO()  # all None

        res = calculator.calculate_match_score(user, reqs)
        assert res.score_pct == 0
        assert res.raw_score == 0.0
        assert res.coverage_pct == 0.0
        assert len(res.applicable_categories) == 0

    def test_age_requirement_does_not_affect_scoring(self, calculator):
        """Age is strictly an Eligibility Hard Filter, NEVER a scoring category.

        Opportunity specifies Age requirement + Field of Study (30%).
        Verify:
        - Categories dict contains exactly the 5 scoring categories (no 'age').
        - Denominator D only counts Field of Study (0.30).
        - Coverage is 30.0%.
        """
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
        )
        reqs = OpportunityRequirementsDTO(
            age=ExtractedRequirement(
                category="age",
                status=RequirementStatus.REQUIRED,
                value={"max_age": 30},
            ),
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            ),
        )

        res = calculator.calculate_match_score(user, reqs)
        assert "age" not in res.categories
        assert res.coverage_pct == 30.0
        assert res.score_pct == 100

    def test_batch_calculate_match_scores(self, calculator):
        """Batch calculation returns a list of MatchScoreResultDTO."""
        user = UserProfileDTO(
            user_id="u1", fields_of_study=[{"name": "Computer Science"}]
        )
        opp1 = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            )
        )
        opp2 = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Literature"]},
            )
        )

        results = calculator.calculate_match_scores(user, [opp1, opp2])
        assert len(results) == 2
        assert results[0].score_pct == 100
        assert results[1].score_pct == 0

    def test_convenience_function(self):
        """calculate_match_score standalone function works identically."""
        user = UserProfileDTO(
            user_id="u1", fields_of_study=[{"name": "Computer Science"}]
        )
        opp = OpportunityRequirementsDTO(
            field_of_study=ExtractedRequirement(
                category="field_of_study",
                status=RequirementStatus.REQUIRED,
                value={"fields": ["Computer Science"]},
            )
        )
        res = calculate_match_score(user, opp)
        assert isinstance(res, MatchScoreResultDTO)
        assert res.score_pct == 100
