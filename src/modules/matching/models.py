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
