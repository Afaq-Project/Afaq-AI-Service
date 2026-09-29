import json
from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SkillDTO(BaseModel):
    """In-memory representation of a user skill."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    name: str | None = None
    category: str | None = None
    proficiency: str | None = None


class LanguageDTO(BaseModel):
    """In-memory representation of a user language."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    name: str | None = None
    proficiency: str | None = None


class EducationDTO(BaseModel):
    """In-memory representation of a user education history record."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    degree: str | None = None
    major: str | None = None
    institution: str | None = None
    graduation_year: int | None = None
    gpa_normalized_4: float | None = None


class FieldOfStudyDTO(BaseModel):
    """In-memory representation of a user field of study."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    name: str | None = None
    category: str | None = None


def _parse_json_list(v: Any) -> list[Any]:
    if v is None:
        return []
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    if isinstance(v, list):
        return v
    return []


def _parse_json_dict(v: Any) -> dict[str, Any] | None:
    if v is None:
        return None
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    if isinstance(v, dict):
        return v
    return None


class TargetDegreeDTO(BaseModel):
    """In-memory representation of a user target degree preference."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    code: str | None = None
    name_en: str | None = None
    name_ar: str | None = None


class TargetMajorDTO(BaseModel):
    """In-memory representation of a user target major preference."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    name_en: str | None = None
    name_ar: str | None = None
    category_name: str | None = None


class TargetInstitutionDTO(BaseModel):
    """In-memory representation of a user target institution preference."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    name_en: str | None = None
    name_ar: str | None = None
    country_name: str | None = None


class SpecialStatusDTO(BaseModel):
    """In-memory representation of a user special status."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    name_en: str | None = None
    name_ar: str | None = None


class TestResultDTO(BaseModel):
    """In-memory representation of a user standardized test result."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    id: UUID | str | None = None
    test_id: UUID | str | None = None
    test_name: str | None = None
    score: float | None = None
    test_date: date | None = None


class UserProfileDTO(BaseModel):
    """Lightweight in-memory DTO for user profile data from current database schema.

    Represents normalized user profile data and supports legacy fallback reads.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    user_id: UUID | str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    nationality_id: UUID | str | None = None
    education_level: str | None = None
    education_level_id: UUID | str | None = None
    current_country: str | None = None
    country_of_residence_id: UUID | str | None = None
    current_city: str | None = None
    current_city_id: UUID | str | None = None
    phone: str | None = None
    experience_level: str | None = None
    has_financial_need: bool | None = None
    career_goals: str | None = None
    profile_photo_url: str | None = None
    completion_pct: int | None = None
    """Profile completeness percentage (0–100). Informational metadata only.
    Calculated and owned by the external profile system. Never used in Match Score."""

    matching_version: int | None = 1

    is_matchable: bool | None = None
    """Whether the user profile is ready and allowed to enter matching.
    Sourced from user_profiles.is_matchable (boolean NOT NULL DEFAULT false).
    - True  → user is allowed to enter the matching pipeline.
    - False → user must be excluded before MatchCalculator runs.
    - None  → view did not return the column (upgrade pending); treated conservatively
              by FeedRanker as NOT matchable to avoid incorrect score delivery.
    The threshold and logic are owned by the external profile system / Admin.
    Afaq does NOT recalculate this value."""

    bio: str | None = None
    experiences: list[str] = Field(default_factory=list)
    preferences: dict[str, Any] | None = None
    is_draft: bool | None = None

    skills: list[SkillDTO] = Field(default_factory=list)
    languages: list[LanguageDTO] = Field(default_factory=list)
    educations: list[EducationDTO] = Field(default_factory=list)
    fields_of_study: list[FieldOfStudyDTO] = Field(default_factory=list)
    target_degrees: list[TargetDegreeDTO] = Field(default_factory=list)
    target_majors: list[TargetMajorDTO] = Field(default_factory=list)
    target_institutions: list[TargetInstitutionDTO] = Field(default_factory=list)
    special_statuses: list[SpecialStatusDTO] = Field(default_factory=list)
    test_results: list[TestResultDTO] = Field(default_factory=list)

    @field_validator("skills", mode="before")
    @classmethod
    def _validate_skills(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("languages", mode="before")
    @classmethod
    def _validate_languages(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("educations", mode="before")
    @classmethod
    def _validate_educations(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("fields_of_study", mode="before")
    @classmethod
    def _validate_fields_of_study(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("target_degrees", mode="before")
    @classmethod
    def _validate_target_degrees(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("target_majors", mode="before")
    @classmethod
    def _validate_target_majors(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("target_institutions", mode="before")
    @classmethod
    def _validate_target_institutions(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("special_statuses", mode="before")
    @classmethod
    def _validate_special_statuses(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("test_results", mode="before")
    @classmethod
    def _validate_test_results(cls, v: Any) -> list[Any]:
        return _parse_json_list(v)

    @field_validator("experiences", mode="before")
    @classmethod
    def _validate_experiences(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, list):
            return [str(x) for x in v if x is not None]
        if isinstance(v, str):
            return [v]
        return []

    @field_validator("preferences", mode="before")
    @classmethod
    def _validate_preferences(cls, v: Any) -> dict[str, Any] | None:
        return _parse_json_dict(v)


# ---------------------------------------------------------------------------
# Requirement extraction models
# ---------------------------------------------------------------------------

from enum import StrEnum  # noqa: E402


class RequirementStatus(StrEnum):
    """Status of a scholarship requirement."""

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


class RequirementType(StrEnum):
    """Type of a scholarship requirement."""

    NATIONALITY = "nationality"
    EDUCATION = "education"
    GPA = "gpa"
    LANGUAGE = "language"
    EXPERIENCE = "experience"
    FIELD_OF_STUDY = "field_of_study"
    AGE = "age"
    GENDER = "gender"
    FINANCIAL_NEED = "financial_need"
    SKILLS = "skills"  # kept for backward-compat but not used in new 25% category
    APPLICATION = "application"
    UNKNOWN = "unknown"


class RequirementCondition(StrEnum):
    """Condition/operator for a numeric or comparison requirement."""

    GTE = "gte"  # >=
    LTE = "lte"  # <=
    EQ = "eq"  # ==
    IN = "in"  # value is in a list
    NOT_IN = "not_in"  # value is NOT in a list


class RequirementScope(StrEnum):
    """Whether this requirement is about the applicant or the program."""

    APPLICANT = "applicant"
    PROGRAM = "program"


class ConfidenceLevel(StrEnum):
    """Confidence level of requirement extraction."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class ExtractedRequirement(BaseModel):
    """A single extracted and normalized requirement from a scholarship.

    Represents one discrete criterion that can be compared against a user profile.
    """

    model_config = ConfigDict(extra="ignore")

    req_type: RequirementType
    """Category/field of this requirement."""

    status: RequirementStatus = RequirementStatus.UNKNOWN
    """Whether this is REQUIRED, PREFERRED, NOT_REQUIRED, or UNKNOWN."""

    condition: RequirementCondition | None = None
    """Comparison operator when applicable (>=, <=, IN, etc.)."""

    value: Any = None
    """Normalized value (string, float, list of strings, etc.)."""

    raw_value: str | None = None
    """Original text snippet this was extracted from."""

    description: str | None = None
    """Human-readable summary of this requirement."""

    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    """Confidence level of the extraction."""

    scope: RequirementScope = RequirementScope.APPLICANT
    """Whether this applies to the applicant or the program."""


class OpportunityRequirementsDTO(BaseModel):
    """Structured requirements extracted from a scholarship opportunity.

    Produced by RequirementExtractor from CleanedOpportunityDTO/dict.
    Consumed by HardFilterService and MatchCalculator.
    """

    model_config = ConfigDict(extra="ignore")

    opportunity_id: str | None = None
    title: str | None = None
    requirements: list[ExtractedRequirement] = Field(default_factory=list)

    def by_type(self, req_type: RequirementType) -> list["ExtractedRequirement"]:
        """Returns all requirements of a given type."""
        return [r for r in self.requirements if r.req_type == req_type]

    def required_by_type(
        self, req_type: RequirementType
    ) -> list["ExtractedRequirement"]:
        """Returns REQUIRED requirements of a given type."""
        return [
            r
            for r in self.requirements
            if r.req_type == req_type and r.status == RequirementStatus.REQUIRED
        ]

    def preferred_by_type(
        self, req_type: RequirementType
    ) -> list["ExtractedRequirement"]:
        """Returns PREFERRED requirements of a given type."""
        return [
            r
            for r in self.requirements
            if r.req_type == req_type and r.status == RequirementStatus.PREFERRED
        ]


# ---------------------------------------------------------------------------
# Hard-filter result models
# ---------------------------------------------------------------------------


class EligibilityDecision(StrEnum):
    """Hard eligibility decision for a user-opportunity pair."""

    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class CriterionEvaluation(BaseModel):
    """Result of evaluating a single hard-eligibility criterion."""

    model_config = ConfigDict(extra="ignore")

    criterion: str
    decision: EligibilityDecision
    reason: str
    requirement: ExtractedRequirement | None = None


class HardFilterResultDTO(BaseModel):
    """Detailed hard-filter evaluation result for a user-opportunity pair."""

    model_config = ConfigDict(extra="ignore")

    is_eligible: bool
    """True when user is NOT hard-excluded (ELIGIBLE or UNKNOWN)."""

    decision: EligibilityDecision
    criteria: list[CriterionEvaluation] = Field(default_factory=list)
    failure_reasons: list[str] = Field(default_factory=list)
    unknown_reasons: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Match score models
# ---------------------------------------------------------------------------

# Weights: Field of Study 30%, Opportunity Requirements Match 25%, GPA 20%,
# Language 15%, Experience 10%. Skills category replaced by ORM.
MATCH_SCORE_WEIGHTS: dict[str, float] = {
    "field_of_study": 30.0,
    "opportunity_requirements": 25.0,
    "gpa": 20.0,
    "language": 15.0,
    "experience": 10.0,
}

# Nationalities considered globally open — these do NOT mean Palestine is ineligible
OPEN_TO_ALL_NATIONALITIES: frozenset[str] = frozenset(
    {
        "all nationalities",
        "any nationality",
        "all countries",
        "open to all",
        "international students",
        "all international students",
        "worldwide",
        "global",
    }
)


class CategoryScoreDTO(BaseModel):
    """Score and explanation for a single matching category."""

    model_config = ConfigDict(extra="ignore")

    category: str
    weight: float
    score: float | None = None
    """0–100 score within this category; None = not evaluated (neutral)."""

    is_applicable: bool = True
    """False when the category was not applicable (neutral, not penalised)."""

    reason: str = ""
    """Human-readable explanation of the score."""


class MatchScoreResultDTO(BaseModel):
    """Full match score result for a user-opportunity pair."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    opportunity_id: str | None = None
    total_score: float
    """Weighted total match percentage (0–100)."""

    requirements_coverage_pct: float | None = None
    """Percentage of active scholarship nominal weights evaluated (metadata only)."""

    category_scores: list[CategoryScoreDTO] = Field(default_factory=list)
    calculated_at: str | None = None
    is_preliminary: bool = False
    """True when is_matchable is False or None, indicating matching was performed
    with incomplete profile data and results are preliminary."""


# ---------------------------------------------------------------------------
# Feed ranking models
# ---------------------------------------------------------------------------


class RankedOpportunityDTO(BaseModel):
    """A single ranked opportunity with its match score and eligibility result."""

    model_config = ConfigDict(extra="ignore")

    opportunity: dict[str, Any]
    match_score: MatchScoreResultDTO
    hard_filter_result: HardFilterResultDTO
    is_relaxed: bool = False
    """True when included via zero-match relaxation."""


class FeedRankingResultDTO(BaseModel):
    """Result of ranking a batch of opportunities for a user."""

    model_config = ConfigDict(extra="ignore")

    user_id: str | None = None
    ranked_opportunities: list[RankedOpportunityDTO] = Field(default_factory=list)
    total_evaluated: int = 0
    total_eligible: int = 0
    is_relaxed: bool = False
    core_fields_complete: bool = True
    is_preliminary: bool = False
    """True when is_matchable is False or None, indicating the user profile is
    incomplete and results are preliminary. Matching is NOT blocked."""
