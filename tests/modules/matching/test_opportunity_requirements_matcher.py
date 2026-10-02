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


# ---------------------------------------------------------------------------
# Geographic Token Exclusion in Field of Study Regression Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "country_name",
    [
        "Netherlands",
        "Germany",
        "Canada",
        "Italy",
        "China",
        "Japan",
        "United States",
        "Australia",
    ],
)
def test_extract_field_of_study_excludes_country_names(country_name: str):
    """Country names must NOT be extracted as academic fields of study."""
    extractor = RequirementExtractor()
    opp = {
        "title": f"Scholarship in {country_name}",
        "fields_of_study": ["Masters Scholarships", country_name, "Scholarships"],
    }
    extracted = extractor.extract(opp)
    fos_reqs = extracted.by_type(RequirementType.FIELD_OF_STUDY)
    assert len(fos_reqs) == 0


def test_extract_field_of_study_preserves_legitimate_academic_field():
    """Legitimate academic fields must be preserved and extracted properly."""
    extractor = RequirementExtractor()
    opp = {
        "title": "Computer Science Fellowship",
        "fields_of_study": ["Computer Science"],
    }
    extracted = extractor.extract(opp)
    fos_reqs = extracted.by_type(RequirementType.FIELD_OF_STUDY)
    assert len(fos_reqs) == 1
    assert fos_reqs[0].value == ["Computer Science"]


def test_extract_field_of_study_filters_non_academic_and_country_in_mixed_input():
    """Mixed input with academic fields, countries, and non-academic tokens keeps only academic fields."""
    extractor = RequirementExtractor()
    opp = {
        "title": "International Tech Grant",
        "fields_of_study": [
            "Computer Science",
            "Netherlands",
            "Scholarships",
            "Europe",
            "Artificial Intelligence",
            "Germany",
            "Fully Funded",
        ],
    }
    extracted = extractor.extract(opp)
    fos_reqs = extracted.by_type(RequirementType.FIELD_OF_STUDY)
    assert len(fos_reqs) == 1
    assert fos_reqs[0].value == ["Computer Science", "Artificial Intelligence"]


def test_leiden_opportunity_no_longer_extracts_netherlands_field():
    """Leiden opportunity taxonomy with country tags must not produce field_of_study."""
    extractor = RequirementExtractor()
    opp = {
        "title": "Leiden University Fully Funded Scholarships in the Netherlands",
        "fields_of_study": [
            "Masters Scholarships",
            "Ph.D Scholarships",
            "Scholarships",
            "Undergraduate Scholarships",
            "Europe",
            "Netherlands",
        ],
    }
    extracted = extractor.extract(opp)
    fos_reqs = extracted.by_type(RequirementType.FIELD_OF_STUDY)
    assert len(fos_reqs) == 0


# ---------------------------------------------------------------------------
# Arabic Requirement Extraction Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("arabic_gpa_text", "expected_min", "expected_norm_4"),
    [
        ("معدل تراكمي لا يقل عن 3.0", 3.0, 3.0),
        ("المعدل التراكمي: 3.5 من 4", 3.5, 3.5),
        ("يشترط معدل 3.2 من أصل 4.0", 3.2, 3.2),
        ("معدل لا يقل عن 80%", 80.0, 3.2),
        ("يشترط معدل 75 بالمئة", 75.0, 3.0),
        ("المعدل التراكمي: 85 بالمائة", 85.0, 3.4),
    ],
)
def test_arabic_gpa_extraction(
    arabic_gpa_text: str, expected_min: float, expected_norm_4: float
):
    """Arabic absolute and percentage GPA phrases must be correctly extracted and normalized."""
    extractor = RequirementExtractor()
    opp = {
        "title": "منحة دراسية مميزة",
        "eligibility": {"eligibility_text": arabic_gpa_text},
    }
    extracted = extractor.extract(opp)
    gpa_reqs = extracted.by_type(RequirementType.GPA)
    assert len(gpa_reqs) == 1
    req = gpa_reqs[0]
    assert req.status == RequirementStatus.REQUIRED
    assert req.condition == RequirementCondition.GTE
    assert req.value["minimum"] == pytest.approx(expected_min)
    assert req.value["min_gpa_normalized_4"] == pytest.approx(expected_norm_4)


@pytest.mark.parametrize(
    ("arabic_degree_text", "expected_level"),
    [
        ("درجة البكالوريوس في الهندسة", "Bachelor"),
        ("يشترط الحصول على بكالوريوس", "Bachelor"),
        ("درجة الماجستير في العلوم", "Master"),
        ("مخصصة لطلاب ماجستير إدارة الأعمال", "Master"),
        ("درجة الدكتوراه في الطب", "PhD"),
        ("منح دكتوراه بحثية", "PhD"),
    ],
)
def test_arabic_education_level_extraction(
    arabic_degree_text: str, expected_level: str
):
    """Arabic education levels must normalize to canonical English degree names."""
    extractor = RequirementExtractor()
    opp = {
        "title": "منحة دراسية",
        "description": arabic_degree_text,
    }
    extracted = extractor.extract(opp)
    edu_reqs = extracted.by_type(RequirementType.EDUCATION)
    assert len(edu_reqs) == 1
    assert expected_level in edu_reqs[0].value


@pytest.mark.parametrize(
    ("arabic_nationality_text", "expected_country"),
    [
        ("الفئة المستهدفة: فلسطين", "Palestine"),
        ("الجنسية: فلسطيني", "Palestine"),
        ("مخصصة للطلاب الفلسطينيين", "Palestine"),
        ("الجنسية الفلسطينية مطلوبة", "Palestine"),
        ("الفئة المستهدفة: الأردن", "Jordan"),
        ("الجنسية: أردني", "Jordan"),
        ("مخصصة للطلاب الأردنيين", "Jordan"),
        ("الفئة المستهدفة: المملكة العربية السعودية", "Saudi Arabia"),
        ("الجنسية: سعودي", "Saudi Arabia"),
        ("مخصصة للطلاب السعوديين", "Saudi Arabia"),
    ],
)
def test_arabic_nationality_extraction(
    arabic_nationality_text: str, expected_country: str
):
    """Arabic nationality requirements and demonyms must extract canonical country names."""
    extractor = RequirementExtractor()
    opp = {
        "title": "منحة دراسية دولية",
        "eligibility": {"eligibility_text": arabic_nationality_text},
    }
    extracted = extractor.extract(opp)
    nat_reqs = extracted.by_type(RequirementType.NATIONALITY)
    assert len(nat_reqs) == 1
    assert nat_reqs[0].status == RequirementStatus.REQUIRED
    assert nat_reqs[0].condition == RequirementCondition.IN
    assert expected_country in nat_reqs[0].value


def test_arabic_english_extraction_and_matching_equivalence(
    base_user_profile: UserProfileDTO,
):
    """Opportunities with Arabic vs English text must produce equivalent extraction and match scores."""
    extractor = RequirementExtractor()
    hard_filter = HardFilterService()

    base_user_profile.nationality = "Palestine"
    base_user_profile.education_level = "Bachelor"
    base_user_profile.educations[0].gpa_normalized_4 = 3.5

    en_opp = {
        "title": "Master's Scholarship in Computer Science",
        "description": "Master's degree program for Palestinian students. Minimum GPA 3.0/4.0.",
        "eligibility": {
            "eligibility_text": "Target group: Palestine. Minimum GPA 3.0."
        },
    }

    ar_opp = {
        "title": "منحة ماجستير في علوم الحاسوب",
        "description": "برنامج درجة الماجستير للطلاب الفلسطينيين. معدل تراكمي لا يقل عن 3.0 من 4.",
        "eligibility": {
            "eligibility_text": "الفئة المستهدفة: فلسطين. معدل لا يقل عن 3.0."
        },
    }

    en_reqs = extractor.extract(en_opp)
    ar_reqs = extractor.extract(ar_opp)

    # Check requirement equivalence
    en_nat = en_reqs.by_type(RequirementType.NATIONALITY)[0]
    ar_nat = ar_reqs.by_type(RequirementType.NATIONALITY)[0]
    assert en_nat.value == ar_nat.value == ["Palestine"]

    en_edu = en_reqs.by_type(RequirementType.EDUCATION)[0]
    ar_edu = ar_reqs.by_type(RequirementType.EDUCATION)[0]
    assert "Master" in en_edu.value and "Master" in ar_edu.value

    en_gpa = en_reqs.by_type(RequirementType.GPA)[0]
    ar_gpa = ar_reqs.by_type(RequirementType.GPA)[0]
    assert (
        en_gpa.value["min_gpa_normalized_4"]
        == ar_gpa.value["min_gpa_normalized_4"]
        == 3.0
    )

    # Check hard filter equivalence
    en_filter_res = hard_filter.evaluate_detailed(base_user_profile, en_reqs)
    ar_filter_res = hard_filter.evaluate_detailed(base_user_profile, ar_reqs)
    assert en_filter_res.is_eligible == ar_filter_res.is_eligible
    assert en_filter_res.decision == ar_filter_res.decision


def test_arabic_ordinary_prose_no_false_positives():
    """General Arabic text without eligibility requirements must not produce spurious extractions."""
    extractor = RequirementExtractor()
    opp = {
        "title": "تاريخ التعليم العالي والتطوير الأكاديمي",
        "description": "تأسست الجامعة عام 1990 وتقدم خدمات تعليمية وبحثية متميزة في منطقة الشرق الأوسط والعالم.",
        "eligibility": {
            "eligibility_text": "يرجى زيارة الموقع الإلكتروني للمزيد من المعلومات العامة والتسجيل المبكر."
        },
    }
    extracted = extractor.extract(opp)
    assert len(extracted.by_type(RequirementType.GPA)) == 0
    assert len(extracted.by_type(RequirementType.NATIONALITY)) == 0
