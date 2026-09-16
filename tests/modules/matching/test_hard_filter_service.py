"""Unit tests for hard eligibility filtering (Task 5: nationality + strict education level)."""

from uuid import uuid4

import pytest

from src.modules.matching.models import UserProfileDTO
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
# 1. Nationality Filter Tests
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
# 2. Strict Education Level Filter Tests
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
# 3. Combined Hard Filter Evaluation Tests
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
            "eligibility": {"eligible_nationalities": ["Syria"]},
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
            "study_levels": ["master"],
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
