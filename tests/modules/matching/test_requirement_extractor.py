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
        assert (
            res.get_first_by_category("nationality").status
            == RequirementStatus.NOT_REQUIRED
        )
        assert (
            res.get_first_by_category("education").status == RequirementStatus.REQUIRED
        )
        assert (
            res.get_first_by_category("field_of_study").status
            == RequirementStatus.NOT_REQUIRED
        )
        assert res.get_first_by_category("gpa").status == RequirementStatus.REQUIRED
        assert res.get_first_by_category("gpa").value["minimum"] == 3.7
        assert (
            res.get_first_by_category("language").status == RequirementStatus.REQUIRED
        )
        assert res.get_first_by_category("language").value["min_score"] == 7.5
