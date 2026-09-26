"""Unit and integration tests for RequirementExtractor v1."""

from uuid import uuid4

import pytest

from src.modules.matching.models import (
    ConfidenceLevel,
    RequirementStatus,
)
from src.modules.matching.services.requirement_extractor import (
    RequirementExtractor,
)
from src.modules.scraping.models.cleaned_opportunity import CleanedOpportunityDTO


@pytest.fixture
def extractor() -> RequirementExtractor:
    return RequirementExtractor()


# ============================================================================
# 1. Nationality & Residency Tests
# ============================================================================


class TestNationalityExtraction:
    def test_explicit_nationality_structured(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Scholarship for Palestine",
            "eligibility": {"eligible_nationalities": ["Palestine", "Jordan"]},
            "description": "Full scholarship for Palestinians.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.confidence == ConfidenceLevel.HIGH
        assert "Palestine" in req.value["countries"]

    def test_open_to_all_nationalities(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Global Scholarship",
            "eligibility": {"eligible_nationalities": ["all"]},
            "description": "Open to all students worldwide.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.NOT_REQUIRED
        assert req.value == {"open_to_all": True}

    def test_open_to_all_in_text(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "University Scholarship",
            "eligibility": {},
            "description": "Eligibility: Open to all international students.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.NOT_REQUIRED

    def test_silent_nationality_is_unknown(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Local University Grant",
            "eligibility": {},
            "description": "A research grant for studying chemistry.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN
        assert req.confidence == ConfidenceLevel.LOW

    def test_open_to_international_followed_by_country_list_is_required(
        self, extractor: RequirementExtractor
    ) -> None:
        """Rhodes case: 'open to international students from Australia, Canada...' must be REQUIRED."""
        opp = {
            "title": "Rhodes Scholarships at Oxford University",
            "eligibility": {
                "eligibility_text": "Target group: Australia, Bermuda, Canada, China, Germany, Hong Kong"
            },
            "description": "2026-27 Rhodes Scholarships are open to international students from Australia, Bermuda, Canada, China, Germany, Hong Kong.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED

    def test_open_to_international_followed_by_developing_countries_is_required(
        self, extractor: RequirementExtractor
    ) -> None:
        """DAAD Development case: 'open to international students from developing countries' must be REQUIRED."""
        opp = {
            "title": "DAAD Scholarships in Germany for Development-Related Postgraduate Courses",
            "eligibility": {
                "eligibility_text": "Target group: Students from eligible countries\nEligibility: Is a national of a country listed on the OECD-DAC list"
            },
            "description": "2027/2028 DAAD Scholarships are open to international students from developing countries.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED

    def test_negative_exclusion_wording_does_not_extract_false_required(
        self, extractor: RequirementExtractor
    ) -> None:
        """AU Emerging case: 'not U.S. citizens...dual citizens of the U.S.' must NOT extract U.S. as REQUIRED."""
        opp = {
            "title": "AU Emerging Global Leader Scholarship Program",
            "eligibility": {
                "eligibility_text": (
                    "Target group: The scholarships are targeted to international students from any country "
                    "who are not U.S. citizens, U.S. permanent residents, or dual citizens of the U.S. and another country.\n"
                    "You are NOT eligible to apply if: You are a U.S. citizen, U.S. permanent resident, or dual citizen of the U.S."
                )
            },
            "description": "AU Emerging Global Leader Scholarship Program for international students.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        # Must not be REQUIRED (which would falsely restrict to U.S. citizens)
        assert req.status != RequirementStatus.REQUIRED

    def test_target_group_unrestricted_is_not_required(
        self, extractor: RequirementExtractor
    ) -> None:
        """Unrestricted target groups like 'All applicants from any country' or 'International students' -> NOT_REQUIRED."""
        for phrase in [
            "All applicants from any country",
            "All students including international students",
            "National and International Students",
            "International and EU students",
            "International students",
        ]:
            opp = {
                "title": "Global Excellence Scholarship",
                "eligibility": {
                    "eligibility_text": f"Target group: {phrase}\nEligibility: Outstanding academic record."
                },
                "description": "A prestigious scholarship program.",
            }
            res = extractor.extract_requirements(opp)
            req = res.get_first_by_category("nationality")
            assert req is not None, f"Failed for {phrase}"
            assert (
                req.status == RequirementStatus.NOT_REQUIRED
            ), f"Failed for {phrase}: got {req.status}"

    def test_target_group_restricted_is_required(
        self, extractor: RequirementExtractor
    ) -> None:
        """Restricted target groups like 'Non-EU/EEA International Students' or country lists -> REQUIRED."""
        for phrase in [
            "Non-EU/EEA International Students",
            "Citizens from non-EU/EEA/EFTA countries",
            "International students from a country outside the EU/EEA.",
            "Women who are not United States citizens or permanent residents.",
            "Afghanistan, Angola, Bangladesh, Benin, Bhutan, Cambodia, Chad",
        ]:
            opp = {
                "title": "Regional Scholarship",
                "eligibility": {
                    "eligibility_text": f"Target group: {phrase}\nEligibility: Full time enrolment."
                },
                "description": "Scholarship for eligible applicants.",
            }
            res = extractor.extract_requirements(opp)
            req = res.get_first_by_category("nationality")
            assert req is not None, f"Failed for {phrase}"
            assert (
                req.status == RequirementStatus.REQUIRED
            ), f"Failed for {phrase}: got {req.status}"

    def test_target_group_external_defer_remains_unknown(
        self, extractor: RequirementExtractor
    ) -> None:
        """Target groups referencing external unlisted country sets ('from 155 countries') -> UNKNOWN."""
        opp = {
            "title": "Fulbright Foreign Student Program",
            "eligibility": {
                "eligibility_text": "Target group: International students from 155 countries around the world\nEligibility: Selection procedures vary by country."
            },
            "description": "Fulbright Foreign Student Program in the United States.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN

    def test_target_group_non_nationality_remains_unknown(
        self, extractor: RequirementExtractor
    ) -> None:
        """Target groups describing non-geographic criteria ('All enrolled students') -> UNKNOWN."""
        opp = {
            "title": "Berea College Scholarships",
            "eligibility": {
                "eligibility_text": "Target group: All enrolled students\nEligibility: Applicants must meet university entrance requirements."
            },
            "description": "Berea College scholarships for enrolled students.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("nationality")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN

    def test_explicit_residency_requirement(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Jordanian Fund",
            "description": "Applicants must be residents of Jordan at time of application.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("residency")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED


# ============================================================================
# 2. Education Level Tests
# ============================================================================


class TestEducationExtraction:
    def test_structured_study_levels(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Graduate Fellowship",
            "study_levels": ["Master", "PhD"],
            "description": "Fellowship for postgraduate students.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("education")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert "Master" in req.value["degree_levels"]
        assert "PhD" in req.value["degree_levels"]

    def test_text_study_level_fallback(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Undergraduate Award",
            "study_levels": [],
            "description": "Applicants must hold a bachelor's degree or equivalent.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("education")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert "Bachelor" in req.value["degree_levels"]

    def test_silent_education_is_unknown(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Community Workshop",
            "study_levels": [],
            "description": "A leadership and networking opportunity.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("education")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN


# ============================================================================
# 3. Field of Study & Noise Filtering Tests
# ============================================================================


class TestFieldOfStudyExtraction:
    def test_explicit_clean_academic_fields(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Tech Scholarship",
            "fields_of_study": ["Computer Science", "Software Engineering"],
            "description": "Funding for computer science majors.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("field_of_study")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert "Computer Science" in req.value["fields"]

    def test_geographic_and_scraper_noise_is_filtered(
        self, extractor: RequirementExtractor
    ) -> None:
        # "Germany", "Europe", "Masters Scholarships" should NOT become academic fields
        opp = {
            "title": "German Government Scholarship",
            "fields_of_study": [
                "Germany",
                "Europe",
                "Masters Scholarships",
                "Study in Germany",
            ],
            "description": "Study in Germany across various departments.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("field_of_study")
        assert req is not None
        # Noise was filtered out -> falls back to UNKNOWN
        assert req.status == RequirementStatus.UNKNOWN

    def test_open_to_all_fields_in_text(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Cambridge Scholarship",
            "fields_of_study": ["Masters Scholarships"],
            "description": "The scholarship is open to any subject available at the University of Cambridge.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("field_of_study")
        assert req is not None
        assert req.status == RequirementStatus.NOT_REQUIRED
        assert req.value == {"open_to_all": True}


# ============================================================================
# 4. GPA & Academic Performance Tests
# ============================================================================


class TestGPAExtraction:
    def test_numeric_gpa_threshold(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Merit Scholarship",
            "description": "Applicants must have a minimum GPA of 3.5 / 4.0 in previous studies.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("gpa")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["minimum"] == 3.5
        assert req.value["scale"] == 4.0
        assert req.value["type"] == "NUMERIC"
        assert req.operator == ">="

    def test_percentage_gpa_threshold(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Turkiye Burslari",
            "description": "الحد الأدنى للنجاح: 75% للماجستير والدكتوراه.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("gpa")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["minimum"] == 75.0
        assert req.value["scale"] == 100.0
        assert req.value["type"] == "PERCENTAGE"

    def test_honors_class_standing(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "UK Masters Award",
            "description": "Must hold at least an upper second-class 2:1 honours degree or top 10% class standing.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("gpa")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["type"] == "HONORS"

    def test_qualitative_academic_record(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Fellowship",
            "description": "Candidates must demonstrate an excellent academic record and high motivation.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("gpa")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["type"] == "QUALITATIVE"

    def test_silent_gpa_is_unknown_never_not_required(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Arts Grant",
            "description": "An arts residency in Paris.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("gpa")
        assert req is not None
        # Silence is NEVER NOT_REQUIRED
        assert req.status == RequirementStatus.UNKNOWN


# ============================================================================
# 5. Language Requirements & Compound OR Conditions Tests
# ============================================================================


class TestLanguageExtraction:
    def test_single_ielts_threshold(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "UK Program",
            "description": "Requirements: IELTS score of at least 6.5.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("language")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["test"] == "IELTS"
        assert req.value["min_score"] == 6.5

    def test_compound_or_tests_ielts_or_toefl(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "International Master",
            "description": "English requirement: IELTS 6.5 or TOEFL 80 minimum score.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("language")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.operator == "OR"
        assert req.conditions is not None
        assert req.conditions.operator == "OR"
        assert len(req.conditions.items) == 2

    def test_explicitly_no_language_certificate(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Exchange Program",
            "description": "No IELTS certificate is required for application.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("language")
        assert req is not None
        assert req.status == RequirementStatus.NOT_REQUIRED

    def test_silent_language_is_unknown(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Music Contest",
            "description": "Annual piano competition in Vienna.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("language")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN


# ============================================================================
# 6. Work & Research Experience Tests
# ============================================================================


class TestExperienceExtraction:
    def test_explicit_minimum_years(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Chevening Scholarship",
            "description": "Applicants must have at least 2 years of work experience (2,800 hours).",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("experience")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["minimum_years"] == 2

    def test_explicitly_no_experience_required(
        self, extractor: RequirementExtractor
    ) -> None:
        opp = {
            "title": "Fresh Graduate Internship",
            "description": "No previous work experience is required to apply.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("experience")
        assert req is not None
        assert req.status == RequirementStatus.NOT_REQUIRED

    def test_preferred_experience(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Research Fellowship",
            "description": "Previous research experience is preferred.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("experience")
        assert req is not None
        assert req.status == RequirementStatus.PREFERRED

    def test_silent_experience_is_unknown_no_inference_from_fellowship_title(
        self, extractor: RequirementExtractor
    ) -> None:
        # A fellowship title does NOT automatically mean experience is mandatory
        opp = {
            "title": "Postgraduate Fellowship",
            "opportunity_type": "fellowship",
            "description": "Fellowship supporting tuition and living costs.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("experience")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN


# ============================================================================
# 7. Age & False-Positive Rejection Tests
# ============================================================================


class TestAgeExtraction:
    def test_explicit_maximum_age(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Youth Leadership",
            "description": "Applicants must be under 30 years old at deadline.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("age")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["maximum"] == 30

    def test_explicit_age_range(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Exchange Program",
            "description": "Eligible candidates must be aged 18-25.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("age")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value["minimum"] == 18
        assert req.value["maximum"] == 25

    def test_birth_date_cutoff(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Swiss Government Fellowship",
            "description": "Applicants must be born after 31 December 1989.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("age")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert "31 December 1989" in req.value["birth_date_after"]

    def test_young_professionals_does_not_infer_numeric_age(
        self, extractor: RequirementExtractor
    ) -> None:
        # "young leaders" must NOT produce a hard numeric age limit
        opp = {
            "title": "Global Leaders Forum",
            "description": "Empowering young professionals and emerging leaders worldwide.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("age")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN


# ============================================================================
# 8. Skills & Program Description Disambiguation Tests
# ============================================================================


class TestSkillsExtraction:
    def test_applicant_skill_requirement(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Social Impact Award",
            "description": "Candidates must demonstrate leadership skills and community involvement.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("skills")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert "leadership skills" in req.value["skill"].lower()

    def test_program_curriculum_does_not_become_applicant_requirement(
        self, extractor: RequirementExtractor
    ) -> None:
        # "The program teaches leadership" describes program, not applicant requirement
        opp = {
            "title": "Bootcamp",
            "description": "The program teaches leadership skills and advanced analytics.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("skills")
        assert req is not None
        assert req.status == RequirementStatus.UNKNOWN


# ============================================================================
# 9. Additional Eligibility & Application Requirements Tests
# ============================================================================


class TestAdditionalRequirements:
    def test_gender_female_only(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Women in STEM",
            "description": "This prestigious scholarship is open to female applicants only.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("gender")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED
        assert req.value == {"gender": "female"}

    def test_financial_need_requirement(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "Need-Based Grant",
            "description": "Applicants must demonstrate financial need to qualify.",
        }
        res = extractor.extract_requirements(opp)
        req = res.get_first_by_category("financial_need")
        assert req is not None
        assert req.status == RequirementStatus.REQUIRED

    def test_application_documents(self, extractor: RequirementExtractor) -> None:
        opp = {
            "title": "PhD Scholarship",
            "description": "Application requirements: submit 2 letters of recommendation, a personal statement, and research proposal.",
        }
        res = extractor.extract_requirements(opp)
        app_reqs = res.get_by_category("application")
        assert len(app_reqs) >= 3
        doc_names = [r.value["document"] for r in app_reqs]
        assert "recommendation_letter" in doc_names
        assert "motivation_letter" in doc_names
        assert "research_proposal" in doc_names


# ============================================================================
# 10. CleanedOpportunityDTO Object Integration Test
# ============================================================================


class TestCleanedOpportunityDTOIntegration:
    def test_extract_from_cleaned_opportunity_dto(
        self, extractor: RequirementExtractor
    ) -> None:
        dto = CleanedOpportunityDTO(
            source_id=uuid4(),
            source_url="https://example.com/scholarship",
            title="Gates Cambridge Scholarship",
            study_levels=["Master", "PhD"],
            fields_of_study=["Scholarships", "Europe"],
            eligibility={"eligible_nationalities": ["all"]},
            description="Open to any subject available at the University of Cambridge. Minimum GPA of 3.7 / 4.0. English language requirement: IELTS 7.5.",
        )
        res = extractor.extract_requirements(dto)
        nat = res.get_first_by_category("nationality")
        assert nat is not None
        assert nat.status == RequirementStatus.NOT_REQUIRED

        edu = res.get_first_by_category("education")
        assert edu is not None
        assert edu.status == RequirementStatus.REQUIRED

        fos = res.get_first_by_category("field_of_study")
        assert fos is not None
        assert fos.status == RequirementStatus.NOT_REQUIRED

        gpa = res.get_first_by_category("gpa")
        assert gpa is not None
        assert gpa.status == RequirementStatus.REQUIRED
        assert gpa.value["minimum"] == 3.7

        lang = res.get_first_by_category("language")
        assert lang is not None
        assert lang.status == RequirementStatus.REQUIRED
        assert lang.value["min_score"] == 7.5
