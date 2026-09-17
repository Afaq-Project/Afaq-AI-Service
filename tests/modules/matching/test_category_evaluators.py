"""Unit tests for Safe V1 category evaluators in Afaq AI Matching Engine."""

from src.modules.matching.models import (
    ConfidenceLevel,
    ExtractedRequirement,
    RequirementStatus,
    UserProfileDTO,
)
from src.modules.matching.services.category_evaluators import (
    evaluate_experience,
    evaluate_field_of_study,
    evaluate_gpa,
    evaluate_language,
    evaluate_skills,
)

# ============================================================================
# 1. FIELD OF STUDY EVALUATOR TESTS (30% weight)
# ============================================================================


class TestEvaluateFieldOfStudy:
    def test_no_requirement_returns_neutral(self):
        user = UserProfileDTO(
            user_id="u1", fields_of_study=[{"name": "Computer Science"}]
        )
        res = evaluate_field_of_study(user, None)
        assert res.category == "field_of_study"
        assert res.weight == 0.30
        assert res.score_pct is None
        assert res.is_applicable is False
        assert res.is_computable is False

    def test_not_required_status_returns_neutral(self):
        user = UserProfileDTO(
            user_id="u1", fields_of_study=[{"name": "Computer Science"}]
        )
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.NOT_REQUIRED,
            value={"fields": ["any"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_required_exact_match(self):
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Computer Science"}],
            educations=[{"degree": "Bachelor", "major": "Software Engineering"}],
        )
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.REQUIRED,
            value={"fields": ["Computer Science", "Data Science"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct == 100.0
        assert res.is_applicable is True
        assert res.is_computable is True
        assert "Computer Science" in str(res.user_data_used)

    def test_required_mismatch(self):
        user = UserProfileDTO(
            user_id="u1",
            fields_of_study=[{"name": "Fine Arts"}],
            educations=[{"degree": "Bachelor", "major": "Painting"}],
        )
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.REQUIRED,
            value={"fields": ["Computer Science", "Electrical Engineering"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True
        assert res.is_computable is True

    def test_required_missing_user_data_scores_zero(self):
        user = UserProfileDTO(user_id="u1", fields_of_study=[], educations=[])
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.REQUIRED,
            value={"fields": ["Computer Science"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True
        assert res.is_computable is True
        assert "missing from profile" in res.reason

    def test_preferred_missing_user_data_is_neutral(self):
        user = UserProfileDTO(user_id="u1", fields_of_study=[], educations=[])
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.PREFERRED,
            value={"fields": ["Computer Science"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False
        assert res.is_computable is True
        assert "neutral" in res.reason

    def test_preferred_matched_scores_full(self):
        user = UserProfileDTO(
            user_id="u1", fields_of_study=[{"name": "Computer Science"}]
        )
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.PREFERRED,
            value={"fields": ["Computer Science"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct == 100.0
        assert res.is_applicable is True

    def test_preferred_mismatch_scores_zero(self):
        user = UserProfileDTO(user_id="u1", fields_of_study=[{"name": "History"}])
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.PREFERRED,
            value={"fields": ["Computer Science"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True

    def test_filters_non_academic_tokens(self):
        user = UserProfileDTO(user_id="u1", fields_of_study=[{"name": "All"}])
        req = ExtractedRequirement(
            category="field_of_study",
            status=RequirementStatus.REQUIRED,
            value={"fields": ["All Fields", "General"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_field_of_study(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False


# ============================================================================
# 2. SKILLS / INTERESTS EVALUATOR TESTS (25% weight)
# ============================================================================


class TestEvaluateSkills:
    def test_no_skills_requirement_returns_neutral(self):
        user = UserProfileDTO(user_id="u1", skills=[{"name": "Python"}])
        res = evaluate_skills(user, None)
        assert res.category == "skills"
        assert res.weight == 0.25
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_required_exact_match_all_skills(self):
        user = UserProfileDTO(
            user_id="u1",
            skills=[{"name": "Python"}, {"name": "Docker"}, {"name": "SQL"}],
        )
        req = ExtractedRequirement(
            category="skills",
            status=RequirementStatus.REQUIRED,
            value={"skills": ["Python", "Docker"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_skills(user, req)
        assert res.score_pct == 100.0
        assert res.is_applicable is True
        assert res.is_computable is True

    def test_required_partial_skills_match(self):
        user = UserProfileDTO(
            user_id="u1",
            skills=[{"name": "Python"}, {"name": "Git"}],
        )
        req = ExtractedRequirement(
            category="skills",
            status=RequirementStatus.REQUIRED,
            value={"skills": ["Python", "Docker", "Kubernetes", "AWS"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_skills(user, req)
        # 1 of 4 matched = 25.0%
        assert res.score_pct == 25.0
        assert res.is_applicable is True

    def test_required_zero_skills_match(self):
        user = UserProfileDTO(
            user_id="u1",
            skills=[{"name": "Graphic Design"}],
        )
        req = ExtractedRequirement(
            category="skills",
            status=RequirementStatus.REQUIRED,
            value={"skills": ["Python", "Docker"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_skills(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True

    def test_required_missing_user_skills(self):
        user = UserProfileDTO(user_id="u1", skills=[])
        req = ExtractedRequirement(
            category="skills",
            status=RequirementStatus.REQUIRED,
            value={"skills": ["Python"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_skills(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True
        assert "missing from profile" in res.reason

    def test_preferred_missing_user_skills_is_neutral(self):
        user = UserProfileDTO(user_id="u1", skills=[])
        req = ExtractedRequirement(
            category="skills",
            status=RequirementStatus.PREFERRED,
            value={"skills": ["Python"]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_skills(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False


# ============================================================================
# 3. GPA EVALUATOR TESTS (20% weight)
# ============================================================================


class TestEvaluateGPA:
    def test_no_gpa_requirement_returns_neutral(self):
        user = UserProfileDTO(user_id="u1", educations=[{"gpa_normalized_4": 3.8}])
        res = evaluate_gpa(user, None)
        assert res.category == "gpa"
        assert res.weight == 0.20
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_required_gpa_meets_threshold(self):
        user = UserProfileDTO(user_id="u1", educations=[{"gpa_normalized_4": 3.6}])
        req = ExtractedRequirement(
            category="gpa",
            status=RequirementStatus.REQUIRED,
            value={"min_gpa_normalized_4": 3.5, "raw_threshold": "3.5 / 4.0"},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_gpa(user, req)
        assert res.score_pct == 100.0
        assert res.is_applicable is True
        assert res.is_computable is True

    def test_required_gpa_below_threshold_zero_curve(self):
        user = UserProfileDTO(user_id="u1", educations=[{"gpa_normalized_4": 3.2}])
        req = ExtractedRequirement(
            category="gpa",
            status=RequirementStatus.REQUIRED,
            value={"min_gpa_normalized_4": 3.5, "raw_threshold": "3.5 / 4.0"},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_gpa(user, req)
        # MUST BE 0.0 — No below-threshold partial curve!
        assert res.score_pct == 0.0
        assert res.is_applicable is True

    def test_required_gpa_missing_user_gpa(self):
        user = UserProfileDTO(user_id="u1", educations=[{"degree": "Bachelor"}])
        req = ExtractedRequirement(
            category="gpa",
            status=RequirementStatus.REQUIRED,
            value={"min_gpa_normalized_4": 3.0},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_gpa(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True
        assert "missing from profile" in res.reason

    def test_preferred_gpa_missing_user_gpa_is_neutral(self):
        user = UserProfileDTO(user_id="u1", educations=[])
        req = ExtractedRequirement(
            category="gpa",
            status=RequirementStatus.PREFERRED,
            value={"min_gpa_normalized_4": 3.5},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_gpa(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_qualitative_gpa_uncomputable(self):
        user = UserProfileDTO(user_id="u1", educations=[{"gpa_normalized_4": 3.8}])
        req = ExtractedRequirement(
            category="gpa",
            status=RequirementStatus.REQUIRED,
            value={"text": "Competitive GPA required"},
            confidence=ConfidenceLevel.MEDIUM,
        )
        res = evaluate_gpa(user, req)
        assert res.is_computable is False
        assert res.is_applicable is False
        assert res.score_pct is None
        assert "Qualitative GPA" in res.reason


# ============================================================================
# 4. LANGUAGE EVALUATOR TESTS (15% weight)
# ============================================================================


class TestEvaluateLanguage:
    def test_no_language_requirement_returns_neutral(self):
        user = UserProfileDTO(
            user_id="u1", languages=[{"name": "English", "proficiency": "c1"}]
        )
        res = evaluate_language(user, None)
        assert res.category == "language"
        assert res.weight == 0.15
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_required_language_meets_proficiency(self):
        user = UserProfileDTO(
            user_id="u1",
            languages=[{"name": "English", "proficiency": "c1"}],
        )
        req = ExtractedRequirement(
            category="language",
            status=RequirementStatus.REQUIRED,
            value={"languages": [{"name": "English", "min_proficiency": "b2"}]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_language(user, req)
        assert res.score_pct == 100.0
        assert res.is_applicable is True
        assert res.is_computable is True

    def test_required_language_below_proficiency(self):
        user = UserProfileDTO(
            user_id="u1",
            languages=[{"name": "English", "proficiency": "a2"}],
        )
        req = ExtractedRequirement(
            category="language",
            status=RequirementStatus.REQUIRED,
            value={"languages": [{"name": "English", "min_proficiency": "b2"}]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_language(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True

    def test_required_language_missing_from_user(self):
        user = UserProfileDTO(
            user_id="u1",
            languages=[{"name": "Arabic", "proficiency": "native"}],
        )
        req = ExtractedRequirement(
            category="language",
            status=RequirementStatus.REQUIRED,
            value={"languages": [{"name": "English", "min_proficiency": "b2"}]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_language(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True
        assert ("does not include" in res.reason) or (
            "missing from profile" in res.reason
        )

    def test_preferred_language_missing_from_user_is_neutral(self):
        user = UserProfileDTO(user_id="u1", languages=[])
        req = ExtractedRequirement(
            category="language",
            status=RequirementStatus.PREFERRED,
            value={"languages": [{"name": "French", "min_proficiency": "b1"}]},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_language(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False


# ============================================================================
# 5. EXPERIENCE EVALUATOR TESTS (10% weight)
# ============================================================================


class TestEvaluateExperience:
    def test_no_experience_requirement_returns_neutral(self):
        user = UserProfileDTO(user_id="u1", experience_level="3")
        res = evaluate_experience(user, None)
        assert res.category == "experience"
        assert res.weight == 0.10
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_required_numeric_experience_meets(self):
        user = UserProfileDTO(user_id="u1", experience_level="4")
        req = ExtractedRequirement(
            category="experience",
            status=RequirementStatus.REQUIRED,
            value={"min_years": 3},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_experience(user, req)
        assert res.score_pct == 100.0
        assert res.is_applicable is True
        assert res.is_computable is True

    def test_required_numeric_experience_below(self):
        user = UserProfileDTO(user_id="u1", experience_level="1")
        req = ExtractedRequirement(
            category="experience",
            status=RequirementStatus.REQUIRED,
            value={"min_years": 3},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_experience(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True

    def test_required_experience_missing_user_data(self):
        user = UserProfileDTO(user_id="u1", experience_level=None)
        req = ExtractedRequirement(
            category="experience",
            status=RequirementStatus.REQUIRED,
            value={"min_years": 2},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_experience(user, req)
        assert res.score_pct == 0.0
        assert res.is_applicable is True
        assert "missing from profile" in res.reason

    def test_preferred_experience_missing_user_data_is_neutral(self):
        user = UserProfileDTO(user_id="u1", experience_level=None)
        req = ExtractedRequirement(
            category="experience",
            status=RequirementStatus.PREFERRED,
            value={"min_years": 2},
            confidence=ConfidenceLevel.HIGH,
        )
        res = evaluate_experience(user, req)
        assert res.score_pct is None
        assert res.is_applicable is False

    def test_qualitative_experience_uncomputable(self):
        user = UserProfileDTO(user_id="u1", experience_level="mid")
        req = ExtractedRequirement(
            category="experience",
            status=RequirementStatus.REQUIRED,
            value={"text": "Senior level leadership experience required"},
            confidence=ConfidenceLevel.MEDIUM,
        )
        res = evaluate_experience(user, req)
        assert res.is_computable is False
        assert res.is_applicable is False
        assert res.score_pct is None
        assert "Qualitative experience" in res.reason
