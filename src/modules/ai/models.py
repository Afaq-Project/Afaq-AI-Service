from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

EssayType = Literal[
    "motivation_letter",
    "personal_statement",
    "cv",
    "research_proposal",
    "other",
]


class LanguageSkill(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    level: str | None = Field(default=None, max_length=30)


class UserProfile(BaseModel):
    nationality: str | None = Field(default=None, max_length=100)
    country_of_residence: str | None = Field(default=None, max_length=100)
    education_level: str | None = Field(default=None, max_length=100)
    field_of_study: str | None = Field(default=None, max_length=200)
    gpa: float | None = Field(default=None, ge=0, le=100)
    gpa_scale: float | None = Field(default=None, gt=0, le=100)
    languages: list[LanguageSkill] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=50)
    experience_years: float | None = Field(default=None, ge=0, le=60)
    has_financial_need: bool | None = None


class EssayPoint(BaseModel):
    point: str
    evidence: str | None


class EssaySuggestion(BaseModel):
    suggestion: str
    priority: Literal["high", "medium", "low"]


class LanguageIssue(BaseModel):
    original: str
    correction: str
    explanation: str


class EssayReview(BaseModel):
    overall_assessment: str
    strengths: list[EssayPoint]
    weaknesses: list[EssayPoint]
    suggestions: list[EssaySuggestion]
    language_issues: list[LanguageIssue]
    fit_with_opportunity: str | None


@dataclass(frozen=True)
class ChatReply:
    conversation_id: str
    message_id: str
    answer: str
    status: Literal["ok", "declined"]
    created_at: datetime
    decline_reason: str | None = None
    official_source_url: str | None = None


@dataclass(frozen=True)
class ConversationHistory:
    conversation_id: str | None
    messages: list[object]
    has_more: bool
