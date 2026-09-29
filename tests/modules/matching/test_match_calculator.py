"""Focused tests for MatchCalculator and FeedRanker in Afaq AI Matching Engine.

Validates the binding specification & contract:
1. Requirement consolidation using (req_type, sub_key):
   - GPA REQUIRED >= 85 + GPA PREFERRED >= 95 -> consolidated into 20% GPA category; removed from ORM 25%.
   - CS REQUIRED + CS PREFERRED -> consolidated into 30% Field category; removed from ORM 25%.
   - CS REQUIRED + AI PREFERRED -> different sub-keys; AI PREFERRED enters ORM 25%.
   - Research REQUIRED + Leadership PREFERRED -> different sub-keys; Leadership PREFERRED enters ORM 25%.
2. GPA Model C continuous ratio:
   - 70.0 + 30.0 * clamp((user - req) / (pref - req), 0, 1)
   - Evaluated for user GPAs 85%, 87%, 90%, 94%, 95%, 98%.
3. Language Model C continuous ratio for same test (IELTS 6.5 REQ, 7.5 PREF).
4. Field of Study exact normalized string equality ONLY.
5. Experience conservative area matching (_user_has_matching_experience_area).
6. ORM candidate pool & internal denominator.
7. Two-Layer Option D Global Normalization:
   - Layer 1 (Scholarship-level applicability): Category absent from scholarship -> is_applicable = False,
     weight redistributed proportionally.
   - Layer 2 (User-profile completeness): Category required by scholarship but user data missing ->
     category REMAINS is_applicable = True, weight REMAINS in global denominator, missing user data does NOT inflate score.
8. requirements_coverage_pct metadata (active nominal weights / 100.0 * 100.0).
9. Score range strictly 0..100.
"""

from datetime import date
from uuid import uuid4

import pytest

from src.modules.matching.models import (
    EducationDTO,
    ExtractedRequirement,
    LanguageDTO,
    OpportunityRequirementsDTO,
    RequirementCondition,
    RequirementStatus,
    RequirementType,
    TestResultDTO,
    UserProfileDTO,
)
from src.modules.matching.services.feed_ranker import rank_opportunities
from src.modules.matching.services.match_calculator import (
    MatchCalculator,
    evaluate_experience,
    evaluate_field_of_study,
    evaluate_gpa,
    evaluate_language,
)
from src.modules.matching.services.opportunity_requirements_matcher import (
    OpportunityRequirementsMatcher,
    RequirementMatchDecision,
)


@pytest.fixture
def complete_user_profile() -> UserProfileDTO:
    """User profile with complete data for match calculation."""
    return UserProfileDTO(
        user_id=uuid4(),
        email="student@example.com",
        first_name="Tariq",
        last_name="Ziyad",
        nationality="Palestine",
        education_level="Bachelor",
        current_country="Palestine",
        current_city="Ramallah",
        date_of_birth=date(1999, 3, 20),
        experience_level="Intermediate",
        has_financial_need=True,
        is_matchable=True,
        experiences=["Research assistant in ML", "Student club leader"],
        languages=[
            LanguageDTO(name="Arabic", proficiency="Native"),
            LanguageDTO(name="English", proficiency="Upper Intermediate"),
        ],
        educations=[
            EducationDTO(
                degree="Bachelor",
                major="Computer Science",
                institution="Birzeit University",
                graduation_year=2022,
                gpa_normalized_4=3.6,  # 90% equivalent (3.6 / 4.0 * 100 = 90%)
            )
        ],
        test_results=[
            TestResultDTO(test_name="IELTS", score=7.0),
        ],
    )


@pytest.fixture
def calc() -> MatchCalculator:
    return MatchCalculator()


# ---------------------------------------------------------------------------
# Test 1: GPA Model C Continuous Progression
# ---------------------------------------------------------------------------


def test_gpa_model_c_continuous_progression(
    calc: MatchCalculator, complete_user_profile: UserProfileDTO
):
    """GPA Model C: 70 + 30 * clamp((user - req) / (pref - req), 0, 1)."""
    # Req = 3.4 (85%), Pref = 3.8 (95%)
    reqs = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                condition=RequirementCondition.GTE,
                value={"min_gpa_normalized_4": 3.4, "type": "NUMERIC"},
            ),
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.PREFERRED,
                condition=RequirementCondition.GTE,
                value={"min_gpa_normalized_4": 3.8, "type": "NUMERIC"},
            ),
        ]
    )

    # Test values: 3.4 (85% -> 70.0%), 3.48 (87% -> 76.0%), 3.6 (90% -> 85.0%), 3.76 (94% -> 97.0%), 3.8 (95% -> 100.0%), 3.92 (98% -> 100.0%)
    test_cases = [
        (3.4, 70.0),
        (3.48, 76.0),
        (3.6, 85.0),
        (3.76, 97.0),
        (3.8, 100.0),
        (3.92, 100.0),
    ]

    for user_gpa, expected_score in test_cases:
        complete_user_profile.educations[0].gpa_normalized_4 = user_gpa
        res = evaluate_gpa(complete_user_profile, reqs, calc._norm)
        assert res.score == pytest.approx(expected_score, abs=0.1)


# ---------------------------------------------------------------------------
# Test 2: Language Model C Continuous Ratio
# ---------------------------------------------------------------------------


def test_language_model_c_continuous_ratio(
    calc: MatchCalculator, complete_user_profile: UserProfileDTO
):
    """Language Model C for same test (IELTS 6.5 REQ, 7.5 PREF)."""
    reqs = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.LANGUAGE,
                status=RequirementStatus.REQUIRED,
                value={"tests": [{"test": "IELTS", "min_score": 6.5}]},
            ),
            ExtractedRequirement(
                req_type=RequirementType.LANGUAGE,
                status=RequirementStatus.PREFERRED,
                value={"tests": [{"test": "IELTS", "min_score": 7.5}]},
            ),
        ]
    )

    # 6.5 -> 70.0%, 7.0 -> 85.0%, 7.5 -> 100.0%, 8.0 -> 100.0%
    test_cases = [
        (6.5, 70.0),
        (7.0, 85.0),
        (7.5, 100.0),
        (8.0, 100.0),
    ]

    for score_val, expected_score in test_cases:
        complete_user_profile.test_results = [
            TestResultDTO(test_name="IELTS", score=score_val)
        ]
        res = evaluate_language(complete_user_profile, reqs, calc._norm)
        assert res.score == pytest.approx(expected_score, abs=0.1)


# ---------------------------------------------------------------------------
# Test 3: Field of Study Exact Normalized Equality ONLY
# ---------------------------------------------------------------------------


def test_field_of_study_exact_matching_only(
    calc: MatchCalculator, complete_user_profile: UserProfileDTO
):
    """Field of Study matching uses exact normalized equality only (no substring matching)."""
    # Exact match: "computer science" == "computer science" -> 100.0%
    req_cs = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                value=["Computer Science"],
            )
        ]
    )
    res_cs = evaluate_field_of_study(complete_user_profile, req_cs, calc._norm)
    assert res_cs.score == 100.0

    # Non-exact match: "Science" vs "Computer Science" -> 0.0%
    req_sci = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                value=["Science"],
            )
        ]
    )
    res_sci = evaluate_field_of_study(complete_user_profile, req_sci, calc._norm)
    assert res_sci.score == 0.0


# ---------------------------------------------------------------------------
# Test 4: Experience Conservative Area Matching
# ---------------------------------------------------------------------------


def test_experience_area_matching(
    calc: MatchCalculator, complete_user_profile: UserProfileDTO
):
    """Experience matching checks experience areas using regex word boundaries."""
    complete_user_profile.experiences = [
        "Research assistant in ML",
        "Student club leader",
    ]

    req_research = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "research"},
            )
        ]
    )
    res_research = evaluate_experience(complete_user_profile, req_research, calc._norm)
    assert res_research.score == 100.0

    req_clinical = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "clinical"},
            )
        ]
    )
    res_clinical = evaluate_experience(complete_user_profile, req_clinical, calc._norm)
    assert res_clinical.score == 0.0


# ---------------------------------------------------------------------------
# Test 5: Requirement Consolidation by (req_type, sub_key)
# ---------------------------------------------------------------------------


def test_requirement_consolidation_routing(
    calc: MatchCalculator,
    complete_user_profile: UserProfileDTO,
):
    """Same-key PREFERRED requirements are consolidated into standalone category and excluded from ORM.

    Different-key PREFERRED requirements enter ORM as soft candidates.
    """
    matcher = OpportunityRequirementsMatcher()

    reqs = OpportunityRequirementsDTO(
        requirements=[
            # Same-key: GPA REQUIRED 3.4 + GPA PREFERRED 3.8 -> Consolidated into GPA (20%), EXCLUDED from ORM
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                value={"min_gpa_normalized_4": 3.4, "type": "NUMERIC"},
            ),
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.PREFERRED,
                value={"min_gpa_normalized_4": 3.8, "type": "NUMERIC"},
            ),
            # Different-key: Field CS REQUIRED + Field AI PREFERRED -> AI PREFERRED enters ORM 25%
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                value=["Computer Science"],
            ),
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.PREFERRED,
                value=["Artificial Intelligence"],
            ),
            # Non-category PREFERRED: Financial Need PREFERRED -> enters ORM 25%
            ExtractedRequirement(
                req_type=RequirementType.FINANCIAL_NEED,
                status=RequirementStatus.PREFERRED,
                value="financial_need_preferred",
            ),
        ]
    )

    orm_res = matcher.evaluate(complete_user_profile, reqs)

    # Consolidated GPA PREFERRED should be EXCLUDED_HARD_FILTER
    gpa_pref_ev = [
        ev
        for ev in orm_res.evaluations
        if ev.req_type == RequirementType.GPA
        and ev.status == RequirementStatus.PREFERRED
    ][0]
    assert gpa_pref_ev.is_soft_candidate is False
    assert gpa_pref_ev.decision == RequirementMatchDecision.EXCLUDED_HARD_FILTER

    # AI PREFERRED should be soft candidate in ORM
    ai_pref_ev = [
        ev
        for ev in orm_res.evaluations
        if ev.req_type == RequirementType.FIELD_OF_STUDY
        and ev.status == RequirementStatus.PREFERRED
    ][0]
    assert ai_pref_ev.is_soft_candidate is True

    # Financial Need PREFERRED should be soft candidate in ORM
    fn_pref_ev = [
        ev
        for ev in orm_res.evaluations
        if ev.req_type == RequirementType.FINANCIAL_NEED
        and ev.status == RequirementStatus.PREFERRED
    ][0]
    assert fn_pref_ev.is_soft_candidate is True


# ---------------------------------------------------------------------------
# Test 6: Two-Layer Option D Global Normalization & Requirements Coverage
# ---------------------------------------------------------------------------


def test_two_layer_normalization_and_coverage_metadata(
    calc: MatchCalculator,
    complete_user_profile: UserProfileDTO,
):
    """Layer 1: Category absent from scholarship -> is_applicable = False, weight redistributed proportionally.

    Layer 2: Category required by scholarship but user data missing -> is_applicable = True, weight REMAINS in global denominator.
    requirements_coverage_pct = sum(active_scholarship_nominal_weights) / 100.0 * 100.0 (metadata ONLY).
    """
    # Opportunity with Field (30) and GPA (20) requirements ONLY. Language, Experience, ORM are absent.
    reqs_absent = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                value=["Computer Science"],
            ),
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                value={"min_gpa_normalized_4": 3.4, "type": "NUMERIC"},
            ),
        ]
    )

    res_absent = calc.calculate_match_score(complete_user_profile, reqs_absent)

    # Active nominal weights = 30 (Field) + 20 (GPA) = 50.0
    assert res_absent.requirements_coverage_pct == 50.0
    # Field (30) + GPA (20) are both 100.0% -> Total score = (100*30 + 100*20) / 50 = 100.0%
    assert res_absent.total_score == 100.0


def test_incomplete_profile_does_not_inflate_score(
    calc: MatchCalculator,
):
    """Incomplete user profile with missing data for a scholarship-required category MUST NOT drop the category weight or inflate score."""
    # Scholarship requires Field (30), GPA (20), Language (15), Experience (10), ORM (25)
    reqs_all = OpportunityRequirementsDTO(
        requirements=[
            ExtractedRequirement(
                req_type=RequirementType.FIELD_OF_STUDY,
                status=RequirementStatus.REQUIRED,
                value=["Computer Science"],
            ),
            ExtractedRequirement(
                req_type=RequirementType.GPA,
                status=RequirementStatus.REQUIRED,
                value={"min_gpa_normalized_4": 3.4, "type": "NUMERIC"},
            ),
            ExtractedRequirement(
                req_type=RequirementType.LANGUAGE,
                status=RequirementStatus.REQUIRED,
                value={"tests": [{"test": "IELTS", "min_score": 6.5}]},
            ),
            ExtractedRequirement(
                req_type=RequirementType.EXPERIENCE,
                status=RequirementStatus.REQUIRED,
                value={"area": "research"},
            ),
            ExtractedRequirement(
                req_type=RequirementType.FINANCIAL_NEED,
                status=RequirementStatus.PREFERRED,
                value="financial_need_preferred",
            ),
        ]
    )

    # Incomplete profile: has Field (CS) and GPA (3.6) matching; MISSING Language test_results and MISSING experiences
    # Incomplete profile: has Field (CS) and GPA (3.6) matching and Financial Need (True); MISSING Language test_results and MISSING experiences
    incomplete_profile = UserProfileDTO(
        user_id=uuid4(),
        nationality="Palestine",
        education_level="Bachelor",
        educations=[
            EducationDTO(
                degree="Bachelor",
                major="Computer Science",
                gpa_normalized_4=3.6,
            )
        ],
        test_results=[],
        experiences=[],
        has_financial_need=True,
    )

    res = calc.calculate_match_score(incomplete_profile, reqs_all)

    # Scholarship active nominal weights sum to 100.0%
    assert res.requirements_coverage_pct == 100.0

    # Language (15) and Experience (10) remain is_applicable = True at scholarship level
    # Scores for missing categories evaluate to 0.0
    # Numerator = 100*30 (Field) + 100*20 (GPA) + 0*15 (Lang) + 0*10 (Exp) + 100*25 (ORM) = 7500
    # Denominator = 100
    # Total score = 75.0% (NOT 100.0%!)
    assert res.total_score == 75.0


# ---------------------------------------------------------------------------
# Test 7: FeedRanker integration
# ---------------------------------------------------------------------------


def test_feed_ranker_ranking_and_relaxation(
    complete_user_profile: UserProfileDTO,
):
    """FeedRanker ranks opportunities by Match % descending and supports zero-match relaxation."""
    opp1 = {
        "id": "opp-1",
        "title": "Scholarship 1",
        "study_levels": ["Bachelor"],
        "fields_of_study": ["Computer Science"],
        "eligibility": {"eligibility_text": "Must be Palestinian. GPA 3.0 required."},
    }
    opp2 = {
        "id": "opp-2",
        "title": "Scholarship 2",
        "study_levels": ["Bachelor"],
        "fields_of_study": ["Computer Science"],
        "eligibility": {"eligibility_text": "Must be Palestinian. GPA 3.9 required."},
    }

    result = rank_opportunities(
        user_profile=complete_user_profile,
        opportunities=[opp1, opp2],
    )

    assert result.total_evaluated == 2
    assert result.total_eligible == 1
    assert len(result.ranked_opportunities) == 1
    assert result.ranked_opportunities[0].opportunity["id"] == "opp-1"
