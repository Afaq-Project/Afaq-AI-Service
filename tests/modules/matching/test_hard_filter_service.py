"""Unit tests for hard eligibility filtering (Task 5 + RequirementExtractor Integration)."""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from src.modules.matching.models import (
    ConfidenceLevel,
    EligibilityDecision,
    ExtractedRequirement,
    OpportunityRequirementsDTO,
    RequirementCondition,
    RequirementScope,
    RequirementStatus,
    RequirementType,
    UserProfileDTO,
)
from src.modules.matching.services.hard_filter_service import (
    HardFilterService,
    evaluate_hard_filters,
    filter_by_hard_eligibility,
    passes_education_filter,
    passes_nationality_filter,
)
from src.modules.scraping.models.cleaned_opportunity import CleanedOpportunityDTO
from src.modules.scraping.services.normalization_service import NormalizationService

# ============================================================================
# 1. Nationality Filter Tests (Preserved Baseline)
# ============================================================================


class TestNationalityFilter:
    """Tests for passes_nationality_filter."""

    def test_matching_nationality_in_list(self) -> None:
        assert passes_nationality_filter("Palestine", ["Palestine", "Jordan"]) is True
        assert passes_nationality_filter("Jordan", ["Palestine", "Jordan"]) is True

    def test_non_matching_nationality(self) -> None:
        assert passes_nationality_filter("Egypt", ["Palestine", "Jordan"]) is False

    def test_missing_user_nationality_with_restricted_opp(self) -> None:
        assert passes_nationality_filter(None, ["Jordan"]) is False
        assert passes_nationality_filter("", ["Jordan"]) is False
        assert passes_nationality_filter("   ", ["Jordan"]) is False

    def test_missing_user_nationality_with_unrestricted_opp(self) -> None:
        assert passes_nationality_filter(None, None) is True
        assert passes_nationality_filter("", None) is True
        assert passes_nationality_filter(None, []) is True
        assert passes_nationality_filter("", []) is True
        assert passes_nationality_filter(None, "") is True

    def test_empty_or_none_opportunity_eligibility(self) -> None:
        assert passes_nationality_filter("Palestine", None) is True
        assert passes_nationality_filter("Palestine", []) is True
        assert passes_nationality_filter("Palestine", "") is True
        assert passes_nationality_filter("Palestine", ["  "]) is True

    @pytest.mark.parametrize(
        "token",
        [
            "all",
            "ALL",
            "All",
            "all nationalities",
            "ALL NATIONALITIES",
            "international",
            "International",
            "any nationality",
            "جميع الجنسيات",
            "كافة الجنسيات",
            "مفتوح للجميع",
        ],
    )
    def test_open_to_all_nationalities_canonical_tokens(self, token: str) -> None:
        # Should pass even if user nationality is missing/None
        assert passes_nationality_filter(None, [token]) is True
        assert passes_nationality_filter("", [token]) is True
        # Should pass if user has any nationality
        assert passes_nationality_filter("Palestine", [token]) is True
        assert passes_nationality_filter("Egypt", [token]) is True

    def test_open_to_all_as_single_string(self) -> None:
        assert passes_nationality_filter(None, "all nationalities") is True
        assert passes_nationality_filter(None, "جميع الجنسيات") is True

    def test_country_normalization_arabic_to_english(self) -> None:
        # User has Arabic nationality, opp has English name
        assert passes_nationality_filter("مصر", ["Egypt"]) is True
        assert passes_nationality_filter("السعودية", ["Saudi Arabia"]) is True
        assert passes_nationality_filter("ألمانيا", ["Germany"]) is True
        assert passes_nationality_filter("تركيا", ["Turkey"]) is True
        assert passes_nationality_filter("أمريكا", ["United States"]) is True

    def test_country_normalization_english_to_arabic(self) -> None:
        # User has English nationality, opp has Arabic name
        assert passes_nationality_filter("Egypt", ["مصر"]) is True
        assert passes_nationality_filter("Saudi Arabia", ["السعودية"]) is True
        assert passes_nationality_filter("Germany", ["ألمانيا"]) is True
        assert passes_nationality_filter("Turkey", ["تركيا"]) is True
        assert passes_nationality_filter("United States", ["أمريكا"]) is True

    def test_case_and_whitespace_insensitivity(self) -> None:
        assert passes_nationality_filter("  palestine  ", [" PALESTINE "]) is True
        assert passes_nationality_filter("JORDAN", ["jordan"]) is True

    def test_single_string_eligible_nationalities(self) -> None:
        assert passes_nationality_filter("Palestine", "Palestine") is True
        assert passes_nationality_filter("Egypt", "مصر") is True
        assert passes_nationality_filter("Egypt", "Palestine") is False


# ============================================================================
# 2. Strict Education Level Filter Tests (Preserved Baseline)
# ============================================================================


class TestEducationLevelFilter:
    """Tests for passes_education_filter."""

    def test_matching_education_level(self) -> None:
        assert passes_education_filter("bachelor", ["bachelor", "master"]) is True
        assert passes_education_filter("master", ["bachelor", "master"]) is True
        assert passes_education_filter("phd", ["phd"]) is True

    def test_non_matching_education_level(self) -> None:
        assert passes_education_filter("high_school", ["bachelor", "master"]) is False
        assert passes_education_filter("bachelor", ["master", "phd"]) is False

    def test_missing_user_education_with_required_levels(self) -> None:
        assert passes_education_filter(None, ["bachelor"]) is False
        assert passes_education_filter("", ["bachelor"]) is False
        assert passes_education_filter("   ", ["bachelor"]) is False

    def test_missing_user_education_with_unrestricted_opp(self) -> None:
        assert passes_education_filter(None, None) is True
        assert passes_education_filter("", None) is True
        assert passes_education_filter(None, []) is True
        assert passes_education_filter("", []) is True
        assert passes_education_filter(None, "") is True

    def test_empty_or_none_opportunity_study_levels(self) -> None:
        assert passes_education_filter("bachelor", None) is True
        assert passes_education_filter("bachelor", []) is True
        assert passes_education_filter("bachelor", "") is True
        assert passes_education_filter("bachelor", ["  "]) is True

    def test_study_level_normalization_arabic_to_english(self) -> None:
        assert passes_education_filter("بكالوريوس", ["bachelor"]) is True
        assert passes_education_filter("ماجستير", ["master"]) is True
        assert passes_education_filter("دكتوراه", ["phd"]) is True
        assert passes_education_filter("ثانوية عامة", ["high_school"]) is True

    def test_study_level_normalization_english_to_arabic(self) -> None:
        assert passes_education_filter("bachelor", ["بكالوريوس"]) is True
        assert passes_education_filter("master", ["ماجستير"]) is True
        assert passes_education_filter("phd", ["دكتوراه"]) is True

    def test_study_level_raw_variations(self) -> None:
        assert passes_education_filter("Bachelor's Degree", ["undergraduate"]) is True
        assert passes_education_filter("Master of Science", ["postgraduate"]) is True
        assert passes_education_filter("High School Diploma", ["secondary"]) is True

    def test_multiple_required_study_levels(self) -> None:
        # Matches one -> PASS
        assert (
            passes_education_filter("bachelor", ["master", "bachelor", "phd"]) is True
        )
        # Matches none -> FAIL
        assert (
            passes_education_filter("diploma", ["master", "bachelor", "phd"]) is False
        )

    def test_single_string_required_study_levels(self) -> None:
        assert passes_education_filter("bachelor", "bachelor") is True
        assert passes_education_filter("bachelor", "master") is False
        assert passes_education_filter("بكالوريوس", "bachelor") is True


# ============================================================================
# 3. Combined Hard Filter Evaluation Tests (Preserved Baseline)
# ============================================================================


class TestCombinedHardFilterEvaluation:
    """Tests for evaluate_hard_filters and filter_by_hard_eligibility."""

    @pytest.fixture
    def user_dto(self) -> UserProfileDTO:
        return UserProfileDTO(
            user_id=uuid4(),
            nationality="Palestine",
            education_level="bachelor",
        )

    def test_both_pass(self, user_dto: UserProfileDTO) -> None:
        opp = {
            "title": "Scholarship A",
            "eligibility": {"eligible_nationalities": ["Palestine", "Jordan"]},
            "study_levels": ["bachelor", "master"],
        }
        assert evaluate_hard_filters(user_dto, opp) is True

    def test_fail_nationality_pass_education(self, user_dto: UserProfileDTO) -> None:
        opp = {
            "title": "Scholarship B",
            "eligibility": {"eligible_nationalities": ["Egypt", "Saudi Arabia"]},
            "study_levels": ["bachelor", "master"],
        }
        assert evaluate_hard_filters(user_dto, opp) is False

    def test_pass_nationality_fail_education(self, user_dto: UserProfileDTO) -> None:
        opp = {
            "title": "Scholarship C",
            "eligibility": {"eligible_nationalities": ["Palestine"]},
            "study_levels": ["phd"],
        }
        assert evaluate_hard_filters(user_dto, opp) is False

    def test_fail_both(self, user_dto: UserProfileDTO) -> None:
        opp = {
            "title": "Scholarship D",
            "eligibility": {"eligible_nationalities": ["Germany"]},
            "study_levels": ["phd"],
        }
        assert evaluate_hard_filters(user_dto, opp) is False

    def test_unrestricted_opp_passes_both(self, user_dto: UserProfileDTO) -> None:
        opp = {
            "title": "Open Opportunity",
            "eligibility": {},
            "study_levels": [],
        }
        assert evaluate_hard_filters(user_dto, opp) is True

    def test_with_cleaned_opportunity_object(self, user_dto: UserProfileDTO) -> None:
        passing_opp = CleanedOpportunityDTO(
            source_id=uuid4(),
            source_url="https://example.com/1",
            title="Passing Opportunity",
            country="Turkey",
            eligibility={"eligible_nationalities": ["Palestine"]},
            study_levels=["bachelor"],
        )
        failing_opp = CleanedOpportunityDTO(
            source_id=uuid4(),
            source_url="https://example.com/2",
            title="Failing Opportunity",
            country="Turkey",
            eligibility={"eligible_nationalities": ["Morocco"]},
            study_levels=["bachelor"],
        )
        assert evaluate_hard_filters(user_dto, passing_opp) is True
        assert evaluate_hard_filters(user_dto, failing_opp) is False

    def test_filter_by_hard_eligibility_list(self, user_dto: UserProfileDTO) -> None:
        opp1 = {
            "id": 1,
            "eligibility": {"eligible_nationalities": ["Palestine"]},
            "study_levels": ["bachelor"],
        }
        opp2 = {
            "id": 2,
            "eligibility": {"eligible_nationalities": ["Morocco"]},
            "study_levels": ["bachelor"],
        }
        opp3 = {
            "id": 3,
            "eligibility": {"eligible_nationalities": ["all"]},
            "study_levels": ["bachelor", "master"],
        }
        opp4 = {
            "id": 4,
            "eligibility": {"eligible_nationalities": ["Palestine"]},
            "study_levels": ["phd"],
        }

        results = filter_by_hard_eligibility(user_dto, [opp1, opp2, opp3, opp4])
        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[1]["id"] == 3

    def test_user_and_opportunity_immutability(self, user_dto: UserProfileDTO) -> None:
        opp = {
            "id": 100,
            "eligibility": {"eligible_nationalities": ["Palestine"]},
            "study_levels": ["bachelor"],
        }
        original_user_dict = user_dto.model_dump()
        original_opp_dict = dict(opp)

        evaluate_hard_filters(user_dto, opp)
        filter_by_hard_eligibility(user_dto, [opp])

        assert user_dto.model_dump() == original_user_dict
        assert opp == original_opp_dict


# ============================================================================
# 4. HardFilterService Class Tests
# ============================================================================


class TestHardFilterServiceClass:
    """Tests for HardFilterService instance methods."""

    def test_service_delegation(self) -> None:
        service = HardFilterService()

        # passes_nationality
        assert service.passes_nationality("Palestine", ["Palestine"]) is True
        assert service.passes_nationality("Jordan", ["Palestine"]) is False

        # passes_education
        assert service.passes_education("bachelor", ["bachelor"]) is True
        assert service.passes_education("bachelor", ["master"]) is False

        # evaluate
        user = {"nationality": "Palestine", "education_level": "bachelor"}
        opp = {
            "eligibility": {"eligible_nationalities": ["Palestine"]},
            "study_levels": ["bachelor"],
        }
        assert service.evaluate(user, opp) is True

        # filter_opportunities
        filtered = service.filter_opportunities(user, [opp])
        assert len(filtered) == 1

    def test_service_with_custom_normalizer(self) -> None:
        norm = NormalizationService()
        service = HardFilterService(normalization_service=norm)
        assert service.normalizer is norm
        assert service.passes_nationality("مصر", ["Egypt"]) is True


# ============================================================================
# 5. Structured Requirement Integration & Edge Cases (Cases A - P)
# ============================================================================


class TestStructuredHardFilterEvaluation:
    """Tests for evaluate_detailed with structured OpportunityRequirementsDTO."""

    @pytest.fixture
    def service(self) -> HardFilterService:
        return HardFilterService()

    def test_case_a_required_nationality_matching_user(
        self, service: HardFilterService
    ) -> None:
        """Case A: Required nationality + matching user -> ELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"countries": ["Palestine", "Jordan"]},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(
            user_id=uuid4(), nationality="Palestine", education_level="bachelor"
        )
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.ELIGIBLE
        assert res.decision == EligibilityDecision.ELIGIBLE
        assert res.is_eligible is True
        assert len(res.failure_reasons) == 0

    def test_case_b_required_nationality_mismatching_user(
        self, service: HardFilterService
    ) -> None:
        """Case B: Required nationality + mismatching user -> INELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"countries": ["Jordan"]},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(
            user_id=uuid4(), nationality="Egypt", education_level="bachelor"
        )
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.INELIGIBLE
        assert res.decision == EligibilityDecision.INELIGIBLE
        assert res.is_eligible is False
        assert len(res.failure_reasons) == 1
        assert "Egypt" in res.failure_reasons[0]

    def test_case_c_required_nationality_missing_user_nationality(
        self, service: HardFilterService
    ) -> None:
        """Case C: Required nationality + missing user nationality -> UNKNOWN (is_eligible=True, no hard exclusion)."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"countries": ["Palestine"]},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(
            user_id=uuid4(), nationality=None, education_level="bachelor"
        )
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.UNKNOWN
        assert res.decision == EligibilityDecision.UNKNOWN
        # Missing user data must NOT become a hard failure
        assert res.is_eligible is True
        assert len(res.failure_reasons) == 0
        assert len(res.unknown_reasons) == 1

    def test_case_d_open_to_all_nationality(self, service: HardFilterService) -> None:
        """Case D: Open-to-all nationality -> ELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.NOT_REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"open_to_all": True},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), nationality=None)
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.ELIGIBLE
        assert res.is_eligible is True

    def test_case_e_no_nationality_requirement_silent(
        self, service: HardFilterService
    ) -> None:
        """Case E: No nationality requirement (silent) -> UNKNOWN / no hard failure."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.UNKNOWN,
                    requirement_type=RequirementType.ELIGIBILITY,
                    confidence=ConfidenceLevel.LOW,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), nationality="Egypt")
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.UNKNOWN
        assert res.is_eligible is True

    def test_case_f_required_education_matching_user(
        self, service: HardFilterService
    ) -> None:
        """Case F: Required education + matching user -> ELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"degree_levels": ["Master", "PhD"]},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), education_level="master")
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["education"].decision == EligibilityDecision.ELIGIBLE
        assert res.decision == EligibilityDecision.ELIGIBLE
        assert res.is_eligible is True

    def test_case_g_required_education_mismatching_user(
        self, service: HardFilterService
    ) -> None:
        """Case G: Required education + mismatching user -> INELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"degree_levels": ["Master"]},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), education_level="high_school")
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["education"].decision == EligibilityDecision.INELIGIBLE
        assert res.decision == EligibilityDecision.INELIGIBLE
        assert res.is_eligible is False
        assert len(res.failure_reasons) == 1

    def test_case_h_required_education_missing_user_education(
        self, service: HardFilterService
    ) -> None:
        """Case H: Required education + missing user education -> UNKNOWN (is_eligible=True, no hard failure)."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"degree_levels": ["PhD"]},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), education_level=None)
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["education"].decision == EligibilityDecision.UNKNOWN
        assert res.decision == EligibilityDecision.UNKNOWN
        assert res.is_eligible is True
        assert len(res.failure_reasons) == 0

    def test_case_i_unknown_requirement_no_hard_exclusion(
        self, service: HardFilterService
    ) -> None:
        """Case I: UNKNOWN requirement category -> no hard exclusion."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.UNKNOWN,
                    requirement_type=RequirementType.ELIGIBILITY,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), education_level="bachelor")
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["education"].decision == EligibilityDecision.UNKNOWN
        assert res.is_eligible is True

    def test_case_j_not_required_no_hard_exclusion(
        self, service: HardFilterService
    ) -> None:
        """Case J: NOT_REQUIRED -> no hard exclusion (ELIGIBLE)."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="education",
                    status=RequirementStatus.NOT_REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                )
            ]
        )
        user = UserProfileDTO(user_id=uuid4(), education_level=None)
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["education"].decision == EligibilityDecision.ELIGIBLE
        assert res.is_eligible is True

    def test_case_k_low_confidence_requirement_unknown_no_exclusion(
        self, service: HardFilterService
    ) -> None:
        """Case K: LOW-confidence requirement -> UNKNOWN (never hard exclusion)."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    value={"countries": ["France"]},
                    confidence=ConfidenceLevel.LOW,
                )
            ]
        )
        # User is Palestinian; under LOW confidence extraction, it must not become INELIGIBLE
        user = UserProfileDTO(user_id=uuid4(), nationality="Palestine")
        res = service.evaluate_detailed(user, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.UNKNOWN
        assert res.is_eligible is True

    def test_case_l_application_requirement_must_not_cause_hard_exclusion(
        self, service: HardFilterService
    ) -> None:
        """Case L: Application documents (letters, proposals) must not be evaluated as hard eligibility failures."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="application",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.APPLICATION,
                    value={"document": "recommendation_letter", "quantity": 3},
                )
            ]
        )
        user = UserProfileDTO(
            user_id=uuid4(), nationality="Palestine", education_level="bachelor"
        )
        res = service.evaluate_detailed(user, reqs)
        assert res.is_eligible is True
        assert res.decision in (
            EligibilityDecision.ELIGIBLE,
            EligibilityDecision.UNKNOWN,
        )

    def test_case_m_admission_only_language_not_scholarship_hard_filter(
        self, service: HardFilterService
    ) -> None:
        """Case M: Admission-only language requirement must not cause scholarship hard exclusion."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="language",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    scope=RequirementScope.ADMISSION,
                    value={"test": "IELTS", "min_score": 7.5},
                    confidence=ConfidenceLevel.HIGH,
                )
            ]
        )
        user = UserProfileDTO(
            user_id=uuid4(), nationality="Palestine", education_level="bachelor"
        )
        res = service.evaluate_detailed(user, reqs)
        assert res.is_eligible is True

    def test_case_n_and_condition_evaluation(self, service: HardFilterService) -> None:
        """Case N: Compound AND condition: both sub-conditions must pass for ELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    confidence=ConfidenceLevel.HIGH,
                    conditions=RequirementCondition(
                        operator="AND",
                        items=[
                            ExtractedRequirement(
                                category="nationality",
                                status=RequirementStatus.REQUIRED,
                                value={"countries": ["Palestine"]},
                                confidence=ConfidenceLevel.HIGH,
                            ),
                            ExtractedRequirement(
                                category="nationality",
                                status=RequirementStatus.REQUIRED,
                                value={"countries": ["Jordan", "Palestine"]},
                                confidence=ConfidenceLevel.HIGH,
                            ),
                        ],
                    ),
                )
            ]
        )
        user_pass = UserProfileDTO(user_id=uuid4(), nationality="Palestine")
        res_pass = service.evaluate_detailed(user_pass, reqs)
        assert res_pass.criteria["nationality"].decision == EligibilityDecision.ELIGIBLE

        user_fail = UserProfileDTO(user_id=uuid4(), nationality="Jordan")
        res_fail = service.evaluate_detailed(user_fail, reqs)
        assert (
            res_fail.criteria["nationality"].decision == EligibilityDecision.INELIGIBLE
        )

    def test_case_o_or_condition_evaluation(self, service: HardFilterService) -> None:
        """Case O: Compound OR condition: any passing sub-condition makes it ELIGIBLE."""
        reqs = OpportunityRequirementsDTO(
            requirements=[
                ExtractedRequirement(
                    category="nationality",
                    status=RequirementStatus.REQUIRED,
                    requirement_type=RequirementType.ELIGIBILITY,
                    confidence=ConfidenceLevel.HIGH,
                    conditions=RequirementCondition(
                        operator="OR",
                        items=[
                            ExtractedRequirement(
                                category="nationality",
                                status=RequirementStatus.REQUIRED,
                                value={"countries": ["Palestine"]},
                                confidence=ConfidenceLevel.HIGH,
                            ),
                            ExtractedRequirement(
                                category="nationality",
                                status=RequirementStatus.REQUIRED,
                                value={"countries": ["Jordan"]},
                                confidence=ConfidenceLevel.HIGH,
                            ),
                        ],
                    ),
                )
            ]
        )
        user_jordan = UserProfileDTO(user_id=uuid4(), nationality="Jordan")
        res = service.evaluate_detailed(user_jordan, reqs)
        assert res.criteria["nationality"].decision == EligibilityDecision.ELIGIBLE

        user_egypt = UserProfileDTO(user_id=uuid4(), nationality="Egypt")
        res_egypt = service.evaluate_detailed(user_egypt, reqs)
        assert (
            res_egypt.criteria["nationality"].decision == EligibilityDecision.INELIGIBLE
        )

    def test_case_p_geography_metadata_not_nationality_restriction(
        self, service: HardFilterService
    ) -> None:
        """Case P: Host country/geography metadata (Japan, USA) must not become nationality restrictions."""
        opp = {
            "title": "Scholarship in Japan",
            "country": "Japan",
            "fields_of_study": ["Japan", "Scholarships"],
            "study_levels": ["Bachelor"],
            "description": "Scholarship to study at Tokyo University in Japan.",
        }
        user = UserProfileDTO(
            user_id=uuid4(), nationality="Palestine", education_level="bachelor"
        )
        res = service.evaluate_detailed(user, opp)
        # Japanese host country does NOT restrict Palestinian user
        assert res.criteria["nationality"].decision == EligibilityDecision.UNKNOWN
        assert res.is_eligible is True


# ============================================================================
# 6. Real-Data Validation with Representative Profiles (25 Audited Opps)
# ============================================================================


class TestHardFilterRealDataIntegration:
    """Evaluates HardFilterService against all 25 real cleaned opportunities."""

    @pytest.fixture(scope="module")
    def real_opportunities(self) -> list[dict[str, Any]]:
        fixture_path = (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "real_cleaned_opportunities_25.json"
        )
        if fixture_path.exists():
            with open(fixture_path, encoding="utf-8") as f:
                return json.load(f)[:25]
        raise FileNotFoundError("real_cleaned_opportunities_25.json not found")

    def test_evaluate_detailed_across_all_25_real_opportunities(
        self, real_opportunities: list[dict[str, Any]]
    ) -> None:
        service = HardFilterService()

        user_palestinian_bachelor = UserProfileDTO(
            user_id=uuid4(),
            nationality="Palestine",
            education_level="bachelor",
        )
        user_missing_data = UserProfileDTO(
            user_id=uuid4(),
            nationality=None,
            education_level=None,
        )

        for idx, opp in enumerate(real_opportunities, 1):
            res_user = service.evaluate_detailed(user_palestinian_bachelor, opp)
            assert isinstance(res_user.decision, EligibilityDecision)
            assert isinstance(res_user.is_eligible, bool)

            # User with missing data must NEVER be marked INELIGIBLE
            res_missing = service.evaluate_detailed(user_missing_data, opp)
            assert res_missing.decision in (
                EligibilityDecision.ELIGIBLE,
                EligibilityDecision.UNKNOWN,
            )
            assert (
                res_missing.is_eligible is True
            ), f"Opp {idx} ('{opp['title']}') failed user with missing data!"
