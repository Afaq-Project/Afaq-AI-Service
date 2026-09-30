"""Focused tests for HardFilterService and OpportunityRequirementsMatcher in Afaq AI Matching Engine.

Option A Semantic Contract Verification & Experience Area Matching:
- REQUIRED = mandatory eligibility requirement -> evaluated by HardFilterService.
- PREFERRED = soft matching requirement -> evaluated by OpportunityRequirementsMatcher.
- REQUIRED criteria failing -> INELIGIBLE (is_eligible = False).
- REQUIRED criteria missing user data / uncomputable -> UNKNOWN (is_eligible = True, user NOT excluded).
- REQUIRED criteria in soft matcher -> EXCLUDED_HARD_FILTER (is_soft_candidate = False, zero double-counting).
- PREFERRED criteria in soft matcher -> soft match candidates (0-100% normalized score).
- NOT_REQUIRED / UNKNOWN / Missing User Data -> neutral across both services.

Covers all 10 required test scenarios plus targeted regression tests for EXPERIENCE areas:
1. required research + "Research assistant in ML" -> eligible
2. required volunteering + "Volunteer at Red Cross" -> eligible
3. required research + ["Teaching"] -> ineligible
4. required research + [] -> unknown (is_eligible = True)
5. preferred research + "Research assistant in ML" -> matched
6. preferred research + ["Teaching"] -> not matched
7. preferred research + [] -> neutral (omitted from denominator)
8. research must NOT rely on arbitrary substring matching
9. numeric years requirement is no longer produced/used
"""

from datetime import date
from uuid import uuid4

import pytest

from src.modules.matching.models import (
    ConfidenceLevel,
    EducationDTO,
    EligibilityDecision,
    ExtractedRequirement,
    FieldOfStudyDTO,
    LanguageDTO,
    OpportunityRequirementsDTO,
    RequirementCondition,
    RequirementStatus,
    RequirementType,
    TestResultDTO,
    UserProfileDTO,
)
from src.modules.matching.services.hard_filter_service import HardFilterService
from src.modules.matching.services.opportunity_requirements_matcher import (
    OpportunityRequirementsMatcher,
    RequirementMatchDecision,
)
from src.modules.matching.services.requirement_extractor import RequirementExtractor


@pytest.fixture
def base_user_profile() -> UserProfileDTO:
    """Base user profile with complete data for testing."""
    return UserProfileDTO(
        user_id=uuid4(),
        email="testuser@example.com",
        first_name="Ahmad",
        last_name="Hassan",
        nationality="Palestine",
        education_level="Bachelor",
        current_country="Palestine",
        current_city="Gaza",
        date_of_birth=date(1998, 5, 15),  # ~28 years old
        experience_level="Intermediate",
        has_financial_need=True,
        experiences=["Volunteer at Red Cross (2 years)", "Research assistant in ML"],
        languages=[
            LanguageDTO(name="Arabic", proficiency="Native"),
            LanguageDTO(name="English", proficiency="Upper Intermediate"),
        ],
        educations=[
            EducationDTO(
                degree="Bachelor",
                major="Computer Science",
                institution="Islamic University of Gaza",
                graduation_year=2021,
                gpa_normalized_4=3.6,
            )
        ],
        test_results=[
            TestResultDTO(test_name="IELTS", score=7.0),
            TestResultDTO(test_name="TOEFL", score=95.0),
        ],
    )


@pytest.fixture
def hard_filter() -> HardFilterService:
    return HardFilterService()


@pytest.fixture
def matcher() -> OpportunityRequirementsMatcher:
    return OpportunityRequirementsMatcher()


@pytest.fixture
def extractor() -> RequirementExtractor:
    return RequirementExtractor()


# ---------------------------------------------------------------------------
# Test 1 & 9: REQUIRED nationality & Hard-filter double-counting prevention
# ---------------------------------------------------------------------------


def test_required_nationality_hard_filter_and_soft_score_exclusion(
    hard_filter: HardFilterService,
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """Test 1 & 9: REQUIRED nationality must act as a hard filter in HardFilterService and be EXCLUDED from soft score."""
    reqs = OpportunityRequirementsDTO(
        opportunity_id="opp-nat",
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.NATIONALITY,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.IN,
                value=["Palestine"],
                description="Must be Palestinian",
            )
        ],
    )

    # 1. HardFilterService evaluation
    hard_res = hard_filter.evaluate_detailed(base_user_profile, reqs)
    assert hard_res.is_eligible is True
    assert hard_res.decision == EligibilityDecision.ELIGIBLE

    # 2. Soft Matcher evaluation -> EXCLUDED_HARD_FILTER
    res = matcher.evaluate(base_user_profile, reqs)
    assert len(res.evaluations) == 1
    ev = res.evaluations[0]
    assert ev.decision == RequirementMatchDecision.EXCLUDED_HARD_FILTER
    assert ev.is_soft_candidate is False
    assert res.is_applicable is False
    assert res.score is None


# ---------------------------------------------------------------------------
# Test 2: REQUIRED GPA threshold in HardFilterService
# ---------------------------------------------------------------------------


def test_required_gpa_hard_eligibility_filter(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """Test 2: REQUIRED GPA threshold causes INELIGIBLE when user GPA is below threshold."""
    # User GPA = 3.6
    req_pass = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.GTE,
                value={"min_gpa_normalized_4": 3.0, "type": "NUMERIC"},
                description="Minimum GPA 3.0",
            )
        ]
    )
    req_fail = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.GTE,
                value={"min_gpa_normalized_4": 3.8, "type": "NUMERIC"},
                description="Minimum GPA 3.8",
            )
        ]
    )

    pass_res = hard_filter.evaluate_detailed(base_user_profile, req_pass)
    assert pass_res.is_eligible is True
    assert pass_res.decision == EligibilityDecision.ELIGIBLE

    fail_res = hard_filter.evaluate_detailed(base_user_profile, req_fail)
    assert fail_res.is_eligible is False
    assert fail_res.decision == EligibilityDecision.INELIGIBLE
    assert "below required GPA" in fail_res.failure_reasons[0]


# ---------------------------------------------------------------------------
# Test 3: REQUIRED age limit in HardFilterService
# ---------------------------------------------------------------------------


def test_required_age_hard_eligibility_filter(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """Test 3: REQUIRED age limit causes INELIGIBLE when user age violates maximum age limit."""
    # User age = ~28
    req_pass = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.AGE,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.LTE,
                value={"maximum": 30},
                description="Under 30 years old",
            )
        ]
    )
    req_fail = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.AGE,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.LTE,
                value={"maximum": 25},
                description="Under 25 years old",
            )
        ]
    )

    pass_res = hard_filter.evaluate_detailed(base_user_profile, req_pass)
    assert pass_res.is_eligible is True

    fail_res = hard_filter.evaluate_detailed(base_user_profile, req_fail)
    assert fail_res.is_eligible is False
    assert fail_res.decision == EligibilityDecision.INELIGIBLE


# ---------------------------------------------------------------------------
# Test 5: NOT_REQUIRED requirement is neutral
# ---------------------------------------------------------------------------


def test_not_required_is_neutral(
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """Test 5: NOT_REQUIRED status is treated as neutral in soft matcher."""
    req_nr = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.LANGUAGE,
                status=RequirementStatus.NOT_REQUIRED,
                condition=None,
                value="no_certificate_required",
                description="No IELTS required",
            )
        ]
    )

    res = matcher.evaluate(base_user_profile, req_nr)

    assert res.evaluations[0].decision == RequirementMatchDecision.NEUTRAL_NOT_REQUIRED
    assert res.evaluations[0].is_soft_candidate is False


# ---------------------------------------------------------------------------
# Test 6: UNKNOWN requirement is neutral
# ---------------------------------------------------------------------------


def test_unknown_requirement_is_neutral(
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """Test 6: UNKNOWN requirement status is treated as neutral in soft matcher."""
    req_unk = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.APPLICATION,
                status=RequirementStatus.UNKNOWN,
                confidence=ConfidenceLevel.LOW,
                description="Unclear application condition",
            )
        ]
    )

    res = matcher.evaluate(base_user_profile, req_unk)

    assert res.evaluations[0].decision == RequirementMatchDecision.NEUTRAL_UNKNOWN
    assert res.evaluations[0].is_soft_candidate is False


# ---------------------------------------------------------------------------
# Test 7: Missing user data does NOT mean failure (decision = UNKNOWN, is_eligible = True)
# ---------------------------------------------------------------------------


def test_missing_user_data_does_not_cause_ineligibility(
    hard_filter: HardFilterService,
    matcher: OpportunityRequirementsMatcher,
):
    """Test 7: Missing user profile data returns UNKNOWN (is_eligible = True, NOT excluded)."""
    empty_profile = UserProfileDTO(
        user_id=uuid4(),
        nationality=None,
        education_level=None,
        date_of_birth=None,
        has_financial_need=None,
        educations=[],
        test_results=[],
        experiences=[],
    )

    req_required_gpa = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.GTE,
                value={"min_gpa_normalized_4": 3.5, "type": "NUMERIC"},
                description="Minimum GPA 3.5",
            )
        ]
    )

    # 1. Hard Filter -> decision = UNKNOWN, but is_eligible = True (DO NOT EXCLUDE)
    hard_res = hard_filter.evaluate_detailed(empty_profile, req_required_gpa)
    assert hard_res.is_eligible is True
    assert hard_res.decision == EligibilityDecision.UNKNOWN
    assert "missing from profile" in hard_res.unknown_reasons[0]

    # 2. Soft Matcher -> missing user data is neutral
    req_preferred_gpa = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.PREFERRED,
                condition=RequirementCondition.GTE,
                value={"min_gpa_normalized_4": 3.5, "type": "NUMERIC"},
                description="Minimum GPA 3.5 preferred",
            )
        ]
    )
    soft_res = matcher.evaluate(empty_profile, req_preferred_gpa)
    assert (
        soft_res.evaluations[0].decision
        == RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA
    )
    assert soft_res.is_applicable is True
    assert soft_res.score == 0.0


# ---------------------------------------------------------------------------
# Test 8: Multiple requirements in one eligibility paragraph
# ---------------------------------------------------------------------------


def test_multiple_requirements_paragraph_extraction_and_routing(
    extractor: RequirementExtractor,
    hard_filter: HardFilterService,
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """Test 8: Extract and correctly route multiple requirements from a single text block."""
    raw_opportunity = {
        "title": "Beijing Normal University CSC Scholarship 2026",
        "description": "Fully funded scholarship in China for international students.",
        "eligibility": {
            "eligibility_text": (
                "Applicants must be non-Chinese citizens in good health. "
                "Master's applicants: Hold a Bachelor's degree, under the age of 35. "
                "Must demonstrate financial need. IELTS score of 6.5 or TOEFL 80 required."
            )
        },
        "study_levels": ["Master"],
    }

    reqs = extractor.extract(raw_opportunity)
    assert len(reqs.requirements) >= 3

    # Hard filter evaluation
    hard_res = hard_filter.evaluate_detailed(base_user_profile, reqs)
    assert hard_res.is_eligible is True

    # Soft matcher evaluation
    soft_res = matcher.evaluate(base_user_profile, reqs)
    # All REQUIRED criteria in text receive EXCLUDED_HARD_FILTER in soft matcher
    for ev in soft_res.evaluations:
        if ev.status == RequirementStatus.REQUIRED:
            assert ev.decision == RequirementMatchDecision.EXCLUDED_HARD_FILTER


# ---------------------------------------------------------------------------
# Targeted Regression Tests for EXPERIENCE Area Matching (1-9)
# ---------------------------------------------------------------------------


def test_required_research_and_research_assistant_is_eligible(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """1. required research + 'Research assistant in ML' -> ELIGIBLE."""
    base_user_profile.experiences = ["Research assistant in ML"]
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "research"},
                description="Research experience required",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req)

    assert res.is_eligible is True
    assert res.decision == EligibilityDecision.ELIGIBLE


def test_required_volunteering_and_volunteer_red_cross_is_eligible(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """2. required volunteering + 'Volunteer at Red Cross' -> ELIGIBLE."""
    base_user_profile.experiences = ["Volunteer at Red Cross"]
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "volunteering"},
                description="Volunteering experience required",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req)

    assert res.is_eligible is True
    assert res.decision == EligibilityDecision.ELIGIBLE


def test_required_research_and_teaching_only_is_ineligible(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """3. required research + ['Teaching'] -> INELIGIBLE."""
    base_user_profile.experiences = ["Teaching assistant"]
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "research"},
                description="Research experience required",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req)

    assert res.is_eligible is False
    assert res.decision == EligibilityDecision.INELIGIBLE


def test_required_research_and_empty_experiences_is_unknown(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """4. required research + [] -> UNKNOWN (is_eligible = True, never reject for missing data)."""
    base_user_profile.experiences = []
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "research"},
                description="Research experience required",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req)

    assert res.is_eligible is True
    assert res.decision == EligibilityDecision.UNKNOWN


def test_preferred_research_and_research_assistant_is_matched(
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """5. preferred research + 'Research assistant in ML' -> MATCHED."""
    base_user_profile.experiences = ["Research assistant in ML"]
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.PREFERRED,
                value={"area": "research"},
                description="Research experience preferred",
            )
        ]
    )

    res = matcher.evaluate(base_user_profile, req)

    assert res.evaluations[0].decision == RequirementMatchDecision.MATCHED
    assert res.score == 100.0


def test_preferred_research_and_teaching_only_is_not_matched(
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """6. preferred research + ['Teaching'] -> NOT_MATCHED."""
    base_user_profile.experiences = ["Teaching assistant"]
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.PREFERRED,
                value={"area": "research"},
                description="Research experience preferred",
            )
        ]
    )

    res = matcher.evaluate(base_user_profile, req)

    assert res.evaluations[0].decision == RequirementMatchDecision.NOT_MATCHED
    assert res.score == 0.0


def test_preferred_research_and_empty_experiences_is_neutral(
    matcher: OpportunityRequirementsMatcher,
    base_user_profile: UserProfileDTO,
):
    """7. preferred research + [] -> NEUTRAL_MISSING_USER_DATA (omitted from denominator)."""
    base_user_profile.experiences = []
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.PREFERRED,
                value={"area": "research"},
                description="Research experience preferred",
            )
        ]
    )

    res = matcher.evaluate(base_user_profile, req)

    assert (
        res.evaluations[0].decision
        == RequirementMatchDecision.NEUTRAL_MISSING_USER_DATA
    )
    assert res.is_applicable is True
    assert res.score == 0.0


def test_research_matching_does_not_use_naive_substring(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """8. research must NOT rely on arbitrary substring matching (e.g. 'art' does not match 'Artificial Intelligence')."""
    base_user_profile.experiences = ["Artificial Intelligence developer"]
    req = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "art"},
                description="Art experience required",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req)

    assert res.is_eligible is False
    assert res.decision == EligibilityDecision.INELIGIBLE


def test_numeric_years_experience_no_longer_produced(
    extractor: RequirementExtractor,
):
    """9. RequirementExtractor extracts experience area/type instead of numeric years."""
    opp = {
        "title": "PhD Fellowship 2026",
        "description": "Applicants must have at least 3 years of research experience.",
        "eligibility": {
            "eligibility_text": "Minimum 3 years of research experience required."
        },
    }

    reqs = extractor.extract(opp)
    exp_reqs = reqs.by_type(RequirementType.EXPERIENCE)

    assert len(exp_reqs) == 1
    req = exp_reqs[0]
    # Value is experience area dict {"area": "research"}, NOT {"minimum_years": 3}
    assert isinstance(req.value, dict)
    assert req.value.get("area") == "research"
    assert "minimum_years" not in req.value


# ---------------------------------------------------------------------------
# Targeted Semantic Regression Tests: Exact Field of Study
# ---------------------------------------------------------------------------


def test_field_of_study_art_vs_artificial_intelligence_does_not_match(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """REQUIRED 'Art' vs user major 'Artificial Intelligence' must NOT match (INELIGIBLE)."""
    base_user_profile.fields_of_study = [
        FieldOfStudyDTO(name="Artificial Intelligence")
    ]
    base_user_profile.educations[0].major = "Artificial Intelligence"

    req_art = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.IN,
                value=["Art"],
                description="Field of study: Art",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req_art)

    assert res.is_eligible is False
    assert res.decision == EligibilityDecision.INELIGIBLE


def test_field_of_study_science_vs_computer_science_does_not_match(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """REQUIRED 'Science' vs user major 'Computer Science' must NOT match."""
    req_sci = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.IN,
                value=["Science"],
                description="Field of study: Science",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req_sci)

    assert res.is_eligible is False
    assert res.decision == EligibilityDecision.INELIGIBLE


def test_field_of_study_engineering_vs_computer_engineering_does_not_match(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """REQUIRED 'Engineering' vs user major 'Computer Engineering' must NOT automatically match."""
    req_eng = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.IN,
                value=["Engineering"],
                description="Field of study: Engineering",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req_eng)

    assert res.is_eligible is False
    assert res.decision == EligibilityDecision.INELIGIBLE


def test_exact_case_insensitive_field_of_study_equality_matches(
    hard_filter: HardFilterService,
    base_user_profile: UserProfileDTO,
):
    """Exact case-insensitive normalized string match -> ELIGIBLE."""
    req_cs = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.IN,
                value=["computer science"],
                description="Field of study: computer science",
            )
        ]
    )

    res = hard_filter.evaluate_detailed(base_user_profile, req_cs)

    assert res.is_eligible is True
    assert res.decision == EligibilityDecision.ELIGIBLE
