import json
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RequirementStatus(StrEnum):
    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNKNOWN = "UNKNOWN"


OPEN_TO_ALL_NATIONALITIES = {
    "all",
    "all nationalities",
    "international",
    "any nationality",
    "جميع الجنسيات",
    "كافة الجنسيات",
    "مفتوح للجميع",
}


class RequirementType(StrEnum):
    ELIGIBILITY = "ELIGIBILITY"
    APPLICATION = "APPLICATION"
    LIFECYCLE = "LIFECYCLE"


class RequirementScope(StrEnum):
    SCHOLARSHIP = "SCHOLARSHIP"
    ADMISSION = "ADMISSION"
    PROGRAM = "PROGRAM"
    APPLICATION = "APPLICATION"
    UNKNOWN = "UNKNOWN"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class RequirementCondition(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    operator: str  # "AND", "OR"
    items: list[Any] = Field(default_factory=list)


class ExtractedRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    category: str
    status: RequirementStatus = RequirementStatus.UNKNOWN
    requirement_type: RequirementType = RequirementType.ELIGIBILITY
    scope: RequirementScope = RequirementScope.UNKNOWN
    value: Any = None
    operator: str | None = None
    conditions: RequirementCondition | None = None
    evidence: str | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.LOW
    source_field: str | None = None
    conflict: bool = False


class OpportunityRequirementsDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    opportunity_id: UUID | str | None = None
    requirements: list[ExtractedRequirement] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _collect_category_kwarg_requirements(cls, data: Any) -> Any:
        if isinstance(data, dict):
            reqs = list(data.get("requirements") or [])
            for cat in (
                "field_of_study",
                "skills",
                "gpa",
                "language",
                "experience",
                "nationality",
                "education",
                "age",
            ):
                if cat in data and data[cat] is not None:
                    if isinstance(data[cat], ExtractedRequirement):
                        reqs.append(data[cat])
                    elif isinstance(data[cat], dict):
                        reqs.append(ExtractedRequirement(**data[cat]))
            data["requirements"] = reqs
        return data

    def get_by_category(self, category: str) -> list[ExtractedRequirement]:
        return [r for r in self.requirements if r.category == category]

    def get_first_by_category(self, category: str) -> ExtractedRequirement | None:
        for r in self.requirements:
            if r.category == category:
                return r
        return None

    @property
    def field_of_study(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("field_of_study")

    @property
    def skills(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("skills")

    @property
    def gpa(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("gpa")

    @property
    def language(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("language")

    @property
    def experience(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("experience")

    @property
    def nationality(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("nationality")

    @property
    def education(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("education")

    @property
    def age(self) -> ExtractedRequirement | None:
        return self.get_first_by_category("age")


class EligibilityDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class CriterionEvaluation(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    category: str
    decision: EligibilityDecision
    requirement_status: RequirementStatus
    reason: str
    evidence: str | None = None
    confidence: ConfidenceLevel = ConfidenceLevel.LOW


class HardFilterResultDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", from_attributes=True)

    decision: EligibilityDecision = EligibilityDecision.UNKNOWN
    is_eligible: bool = True
    criteria: dict[str, CriterionEvaluation] = Field(default_factory=dict)
    failure_reasons: list[str] = Field(default_factory=list)
    unknown_reasons: list[str] = Field(default_factory=list)
    requirements: OpportunityRequirementsDTO | None = None


MATCH_SCORE_WEIGHTS: dict[str, float] = {
    "field_of_study": 0.30,
    "skills": 0.25,
    "gpa": 0.20,
    "language": 0.15,
    "experience": 0.10,
}


class CategoryScoreDTO(BaseModel):
    """Detailed score evaluation for an individual scoring category."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    category: str  # "field_of_study", "skills", "gpa", "language", "experience"
    weight: float  # e.g. 0.30
    score_pct: float | None = None  # 0.0 to 100.0, or None if inactive/uncomputable
    weighted_score: float = 0.0  # (score_pct / 100.0) * weight if active
    is_computable: bool = True
    is_applicable: bool = True  # True if entered active denominator D
    status: RequirementStatus
    reason: str
    extracted_requirement: ExtractedRequirement | None = None
    user_data_used: Any = None


class MatchScoreResultDTO(BaseModel):
    """Complete explainable match calculation payload mapping to Prisma MatchScore."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    user_id: UUID | str | None = None
    opportunity_id: UUID | str | None = None
    score_pct: int = 0  # Final normalized rounded integer (0 - 100)
    raw_score: float = 0.0  # Exact unrounded float
    coverage_pct: float = 0.0  # Sum of active weights / 1.00 (e.g. 65.0%)
    calculation_version: int = 1
    categories: dict[str, CategoryScoreDTO] = Field(default_factory=dict)
    applicable_categories: list[str] = Field(default_factory=list)
    uncomputable_categories: list[str] = Field(default_factory=list)
    missing_user_categories: list[str] = Field(default_factory=list)
    silent_opportunity_categories: list[str] = Field(default_factory=list)
    calculated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RankedOpportunityDTO(BaseModel):
    """Represents a scored and ranked opportunity in the personalized feed."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    opportunity: Any
    match_score: MatchScoreResultDTO
    rank: int = 1


class FeedRankingResultDTO(BaseModel):
    """Complete ranked opportunities feed payload."""

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    items: list[RankedOpportunityDTO] = Field(default_factory=list)
    total_eligible: int = 0
    is_relaxed: bool = False
    core_fields_complete: bool = True


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


class UserProfileDTO(BaseModel):
    """Lightweight in-memory DTO for user profile read from read-only view.

    This DTO represents the user profile data retrieved from public.v_user_full_profile
    and is never persisted locally in the Afaq database.
    """

    model_config = ConfigDict(extra="ignore", from_attributes=True)

    user_id: UUID | str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    date_of_birth: date | None = None
    nationality: str | None = None
    education_level: str | None = None
    current_country: str | None = None
    current_city: str | None = None
    phone: str | None = None
    experience_level: str | None = None
    has_financial_need: bool | None = None
    career_goals: str | None = None
    profile_photo_url: str | None = None
    completion_pct: int | None = None
    preferences: dict[str, Any] | None = None
    is_draft: bool | None = None

    skills: list[SkillDTO] = Field(default_factory=list)
    languages: list[LanguageDTO] = Field(default_factory=list)
    educations: list[EducationDTO] = Field(default_factory=list)
    fields_of_study: list[FieldOfStudyDTO] = Field(default_factory=list)

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

    @field_validator("preferences", mode="before")
    @classmethod
    def _validate_preferences(cls, v: Any) -> dict[str, Any] | None:
        return _parse_json_dict(v)

    @property
    def core_fields_complete(self) -> bool:
        """Determines if the core profile fields required for matching are populated."""
        return bool(
            self.nationality
            and str(self.nationality).strip()
            and self.education_level
            and str(self.education_level).strip()
            and len(self.fields_of_study) > 0
            and len(self.skills) > 0
        )
