"""Tests for Preliminary Matching and Missing-Data Product Contract.

Validates:
1. isMatchable=True  -> normal/accurate matching executes, is_preliminary=False.
2. isMatchable=False -> matching still executes and ranked opportunities are returned, is_preliminary=True.
3. isMatchable=None  -> treated as incomplete/preliminary, is_preliminary=True.
4. Missing Field of Study -> Field score 0.0, weight 30 retained.
5. Missing GPA -> GPA score 0.0, weight 20 retained.
6. Missing Language -> Language score 0.0, weight 15 retained.
7. Missing Experience -> Experience score 0.0, weight 10 retained.
8. Missing ORM user data -> ORM score 0.0, weight 25 retained.
9. Scholarship without Field -> Field weight excluded by Layer 1 Option D regardless of user data.
10. Scholarship without GPA -> GPA weight excluded by Layer 1 Option D regardless of user data.
11. Missing user data never triggers hard rejection by itself.
12. completionPct does not alter Match Score.
13. requirements_coverage_pct does not change merely because user data is missing.
14. Concrete multi-category combination math: (100*30 + 0*20 + 100*15 + 0*25 + 100*10) / 100 = 55.0%.
"""

from uuid import uuid4

from src.modules.matching.models import (
    EducationDTO,
    ExtractedRequirement,
    LanguageDTO,
    OpportunityRequirementsDTO,
    RequirementStatus,
    RequirementType,
    TestResultDTO,
    UserProfileDTO,
)
from src.modules.matching.services.feed_ranker import rank_opportunities
from src.modules.matching.services.hard_filter_service import HardFilterService
from src.modules.matching.services.match_calculator import MatchCalculator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_profile(
    is_matchable: bool | None = True,
    completion_pct: int | None = 80,
    nationality: str = "Palestine",
    education_level: str = "Bachelor",
    major: str = "Computer Science",
    gpa: float = 3.6,
    ielts: float = 7.0,
    experiences: list[str] | None = None,
    has_financial_need: bool = True,
) -> UserProfileDTO:
    return UserProfileDTO(
        user_id=uuid4(),
        nationality=nationality,
        education_level=education_level,
        is_matchable=is_matchable,
        completion_pct=completion_pct,
        has_financial_need=has_financial_need,
        experiences=experiences
        if experiences is not None
        else ["Research assistant in ML"],
        languages=[LanguageDTO(name="English", proficiency="Upper Intermediate")],
        educations=[
            EducationDTO(
                degree="Bachelor",
                major=major,
                gpa_normalized_4=gpa,
            )
        ],
        test_results=[TestResultDTO(test_name="IELTS", score=ielts)],
    )


# ---------------------------------------------------------------------------
# Tests: isMatchable Preliminary Matching Contract
# ---------------------------------------------------------------------------


class TestIsMatchablePreliminaryMatching:
    """Tests that isMatchable controls is_preliminary metadata without blocking matching."""

    def test_is_matchable_true_produces_normal_matching(self):
        """is_matchable=True runs normal matching with is_preliminary=False."""
        profile = _make_profile(is_matchable=True)
        opps = [
            {
                "id": "opp-1",
                "title": "Scholarship",
                "study_levels": ["Bachelor"],
                "fields_of_study": ["Computer Science"],
            }
        ]

        result = rank_opportunities(profile, opps)

        assert result.is_preliminary is False
        assert result.total_evaluated == 1
        assert result.total_eligible == 1
        assert len(result.ranked_opportunities) == 1
        assert result.ranked_opportunities[0].match_score.is_preliminary is False

    def test_is_matchable_false_executes_preliminary_matching(self):
        """is_matchable=False must NOT block matching; returns ranked opportunities with is_preliminary=True."""
        profile = _make_profile(is_matchable=False)
        opps = [
            {
                "id": "opp-1",
                "title": "Scholarship 1",
                "study_levels": ["Bachelor"],
                "fields_of_study": ["Computer Science"],
            },
            {
                "id": "opp-2",
                "title": "Scholarship 2",
                "study_levels": ["Bachelor"],
                "fields_of_study": ["Medicine"],
            },
        ]

        result = rank_opportunities(profile, opps)

        assert result.is_preliminary is True
        assert result.total_evaluated == 2
        assert result.total_eligible == 1
        assert len(result.ranked_opportunities) == 1
        assert result.ranked_opportunities[0].match_score.is_preliminary is True

    def test_is_matchable_none_treated_as_preliminary(self):
        """is_matchable=None executes matching and marks is_preliminary=True."""
        profile = _make_profile(is_matchable=None)
        opps = [
            {
                "id": "opp-1",
                "title": "Scholarship",
                "study_levels": ["Bachelor"],
                "fields_of_study": ["Computer Science"],
            }
        ]

        result = rank_opportunities(profile, opps)

        assert result.is_preliminary is True
        assert len(result.ranked_opportunities) == 1


# ---------------------------------------------------------------------------
# Tests: Missing User Data = Score 0 with Retained Denominator
# ---------------------------------------------------------------------------


class TestMissingUserDataScoreZeroRetainedDenominator:
    """Validates missing user data scores 0.0 with category weight retained in denominator."""

    def test_missing_field_scores_zero_retains_30_weight(self):
        """Missing Field of Study -> Field score = 0, weight 30 retained in denominator."""
        calc = MatchCalculator()
        profile_no_field = UserProfileDTO(
            user_id=uuid4(),
            is_matchable=True,
            nationality="Palestine",
            education_level="Bachelor",
            fields_of_study=[],
            educations=[],  # No major
        )
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.FIELD_OF_STUDY,
                    status=RequirementStatus.REQUIRED,
                    value=["Computer Science"],
                )
            ]
        )

        res = calc.calculate_match_score(profile_no_field, reqs)

        fos_score = next(
            c for c in res.category_scores if c.category == "field_of_study"
        )
        assert fos_score.score == 0.0
        assert fos_score.is_applicable is True
        assert fos_score.weight == 30.0
        # Only Field is required by scholarship -> Total score = 0.0 / 30.0 = 0.0%
        assert res.total_score == 0.0
        assert res.requirements_coverage_pct == 30.0

    def test_missing_gpa_scores_zero_retains_20_weight(self):
        """Missing GPA -> GPA score = 0, weight 20 retained in denominator."""
        calc = MatchCalculator()
        profile_no_gpa = UserProfileDTO(
            user_id=uuid4(),
            is_matchable=True,
            educations=[
                EducationDTO(degree="Bachelor", major="CS", gpa_normalized_4=None)
            ],
        )
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.REQUIRED,
                    value={"min_gpa_normalized_4": 3.0, "type": "NUMERIC"},
                )
            ]
        )

        res = calc.calculate_match_score(profile_no_gpa, reqs)

        gpa_score = next(c for c in res.category_scores if c.category == "gpa")
        assert gpa_score.score == 0.0
        assert gpa_score.is_applicable is True
        assert gpa_score.weight == 20.0
        assert res.total_score == 0.0
        assert res.requirements_coverage_pct == 20.0

    def test_missing_language_scores_zero_retains_15_weight(self):
        """Missing Language test results -> Language score = 0, weight 15 retained."""
        calc = MatchCalculator()
        profile_no_lang = UserProfileDTO(
            user_id=uuid4(),
            is_matchable=True,
            test_results=[],
            languages=[],
        )
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.LANGUAGE,
                    status=RequirementStatus.REQUIRED,
                    value={"tests": [{"test": "IELTS", "min_score": 6.5}]},
                )
            ]
        )

        res = calc.calculate_match_score(profile_no_lang, reqs)

        lang_score = next(c for c in res.category_scores if c.category == "language")
        assert lang_score.score == 0.0
        assert lang_score.is_applicable is True
        assert lang_score.weight == 15.0
        assert res.total_score == 0.0
        assert res.requirements_coverage_pct == 15.0

    def test_missing_experience_scores_zero_retains_10_weight(self):
        """Missing Experience -> Experience score = 0, weight 10 retained."""
        calc = MatchCalculator()
        profile_no_exp = UserProfileDTO(
            user_id=uuid4(),
            is_matchable=True,
            experiences=[],
        )
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.EXPERIENCE,
                    status=RequirementStatus.REQUIRED,
                    value={"area": "research"},
                )
            ]
        )

        res = calc.calculate_match_score(profile_no_exp, reqs)

        exp_score = next(c for c in res.category_scores if c.category == "experience")
        assert exp_score.score == 0.0
        assert exp_score.is_applicable is True
        assert exp_score.weight == 10.0
        assert res.total_score == 0.0
        assert res.requirements_coverage_pct == 10.0

    def test_missing_orm_user_data_scores_zero_retains_25_weight(self):
        """Missing ORM user data when scholarship has PREFERRED reqs -> ORM score = 0, weight 25 retained."""
        calc = MatchCalculator()
        # Scholarship has PREFERRED financial need and PREFERRED age requirement
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.FINANCIAL_NEED,
                    status=RequirementStatus.PREFERRED,
                    value="financial_need_preferred",
                ),
                ExtractedRequirement(
                    req_type=RequirementType.AGE,
                    status=RequirementStatus.PREFERRED,
                    value={"maximum": 30},
                ),
            ]
        )
        # User profile has no financial need data (None) and no date_of_birth (None)
        profile_no_orm = UserProfileDTO(
            user_id=uuid4(),
            is_matchable=True,
            has_financial_need=None,
            date_of_birth=None,
        )

        res = calc.calculate_match_score(profile_no_orm, reqs)

        orm_score = next(
            c for c in res.category_scores if c.category == "opportunity_requirements"
        )
        assert orm_score.score == 0.0
        assert orm_score.is_applicable is True
        assert orm_score.weight == 25.0
        assert res.total_score == 0.0
        assert res.requirements_coverage_pct == 25.0


# ---------------------------------------------------------------------------
# Tests: Scholarship-Level Non-Applicability (Option D Layer 1)
# ---------------------------------------------------------------------------


class TestScholarshipLevelApplicability:
    """Tests that genuinely absent scholarship categories are excluded from denominator."""

    def test_scholarship_without_field_excludes_field_weight(self):
        """Scholarship with NO field requirement excludes Field 30% from denominator."""
        calc = MatchCalculator()
        profile = _make_profile(major="Computer Science", gpa=3.6)
        # Scholarship requires only GPA 3.0
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.REQUIRED,
                    value={"min_gpa_normalized_4": 3.0, "type": "NUMERIC"},
                )
            ]
        )

        res = calc.calculate_match_score(profile, reqs)

        fos_score = next(
            c for c in res.category_scores if c.category == "field_of_study"
        )
        assert fos_score.is_applicable is False
        assert fos_score.score is None

        # Only GPA is applicable (20%) -> Total score = (100 * 20) / 20 = 100.0%
        assert res.total_score == 100.0
        assert res.requirements_coverage_pct == 20.0

    def test_scholarship_without_gpa_excludes_gpa_weight(self):
        """Scholarship with NO GPA requirement excludes GPA 20% from denominator."""
        calc = MatchCalculator()
        profile = _make_profile(major="Computer Science", gpa=2.0)
        # Scholarship requires only Field of Study
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.FIELD_OF_STUDY,
                    status=RequirementStatus.REQUIRED,
                    value=["Computer Science"],
                )
            ]
        )

        res = calc.calculate_match_score(profile, reqs)

        gpa_score = next(c for c in res.category_scores if c.category == "gpa")
        assert gpa_score.is_applicable is False
        assert gpa_score.score is None

        # Only Field is applicable (30%) -> Total score = (100 * 30) / 30 = 100.0%
        assert res.total_score == 100.0
        assert res.requirements_coverage_pct == 30.0


# ---------------------------------------------------------------------------
# Test: Multi-Category Complex Mathematical Contract (55% Example)
# ---------------------------------------------------------------------------


class TestComplexMathematicalContract:
    """Validates: (100*30 + 0*20 + 100*15 + 0*25 + 100*10) / 100 = 55.0%."""

    def test_exact_55_percent_scenario(self):
        calc = MatchCalculator()
        # Scholarship has all 5 categories active (sum = 100)
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    req_type=RequirementType.FIELD_OF_STUDY,
                    status=RequirementStatus.REQUIRED,
                    value=["Computer Science"],
                ),
                ExtractedRequirement(
                    req_type=RequirementType.GPA,
                    status=RequirementStatus.REQUIRED,
                    value={"min_gpa_normalized_4": 3.5, "type": "NUMERIC"},
                ),
                ExtractedRequirement(
                    req_type=RequirementType.LANGUAGE,
                    status=RequirementStatus.REQUIRED,
                    value={"tests": [{"test": "IELTS", "min_score": 6.5}]},
                ),
                ExtractedRequirement(
                    req_type=RequirementType.FINANCIAL_NEED,
                    status=RequirementStatus.PREFERRED,
                    value="financial_need_preferred",
                ),
                ExtractedRequirement(
                    req_type=RequirementType.EXPERIENCE,
                    status=RequirementStatus.REQUIRED,
                    value={"area": "research"},
                ),
            ]
        )

        # User profile:
        # Field = CS (100%)
        # GPA = missing (0%)
        # Language = IELTS 7.0 (100%)
        # ORM = missing has_financial_need (0%)
        # Experience = research (100%)
        profile = UserProfileDTO(
            user_id=uuid4(),
            is_matchable=True,
            nationality="Palestine",
            education_level="Bachelor",
            educations=[
                EducationDTO(
                    degree="Bachelor",
                    major="Computer Science",
                    gpa_normalized_4=None,  # Missing GPA
                )
            ],
            test_results=[TestResultDTO(test_name="IELTS", score=7.0)],
            experiences=["Research assistant in ML"],
            has_financial_need=None,  # Missing financial need for ORM
        )

        res = calc.calculate_match_score(profile, reqs)

        # Coverage must be 100.0% (all 5 categories are in scholarship)
        assert res.requirements_coverage_pct == 100.0

        # Category checks:
        fos = next(c for c in res.category_scores if c.category == "field_of_study")
        gpa = next(c for c in res.category_scores if c.category == "gpa")
        lng = next(c for c in res.category_scores if c.category == "language")
        orm = next(
            c for c in res.category_scores if c.category == "opportunity_requirements"
        )
        exp = next(c for c in res.category_scores if c.category == "experience")

        assert fos.score == 100.0 and fos.weight == 30.0 and fos.is_applicable is True
        assert gpa.score == 0.0 and gpa.weight == 20.0 and gpa.is_applicable is True
        assert lng.score == 100.0 and lng.weight == 15.0 and lng.is_applicable is True
        assert orm.score == 0.0 and orm.weight == 25.0 and orm.is_applicable is True
        assert exp.score == 100.0 and exp.weight == 10.0 and exp.is_applicable is True

        # Calculation: (100*30 + 0*20 + 100*15 + 0*25 + 100*10) / 100 = 55.0%
        assert res.total_score == 55.0


# ---------------------------------------------------------------------------
# Test: Hard Filter Safety & completionPct Isolation
# ---------------------------------------------------------------------------


class TestHardFilterAndCompletionPctIsolation:
    def test_missing_data_never_triggers_hard_filter_rejection(self):
        """Missing user data produces UNKNOWN in hard filter, never INELIGIBLE."""
        service = HardFilterService()
        empty_profile = UserProfileDTO(
            user_id=uuid4(),
            nationality=None,
            education_level=None,
        )
        opp = {
            "id": "opp-1",
            "study_levels": ["Bachelor"],
            "eligibility": {"eligible_nationalities": ["Palestine"]},
        }

        result = service.evaluate_detailed(empty_profile, opp)
        assert result.is_eligible is True
        assert result.decision.value == "UNKNOWN"

    def test_completion_pct_does_not_modify_match_score(self):
        """Different completion_pct values produce identical Match Score."""
        calc = MatchCalculator()
        p1 = _make_profile(completion_pct=10)
        p2 = _make_profile(completion_pct=100)
        opp = {"id": "opp", "fields_of_study": ["Computer Science"]}

        s1 = calc.calculate_match_score(p1, opp)
        s2 = calc.calculate_match_score(p2, opp)

        assert s1.total_score == s2.total_score
