"""Request DTOs for Matching API endpoints."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from src.modules.matching.models import UserProfileDTO


class UserMatchRequest(BaseModel):
    """Request model to trigger matching for a specific user."""

    user_id: UUID = Field(
        ..., description="UUID of the user to match against active opportunities"
    )


class OpportunityMatchRequest(BaseModel):
    """Request model to trigger matching for a newly discovered opportunity."""

    opportunity_id: UUID = Field(
        ..., description="UUID of the opportunity to match against relevant users"
    )


class FullRematchRequest(BaseModel):
    """Request model to trigger a full rematch across all users and opportunities."""

    batch_size: int = Field(
        default=100, ge=1, le=1000, description="Batch size for user profile processing"
    )


class MatchingFeedRequest(BaseModel):
    """Optional configuration for personalized feed ranking request."""

    filter_hard_eligibility: bool = Field(
        default=True,
        description="Whether to apply hard eligibility filters before ranking.",
    )
    enable_relaxation: bool = Field(
        default=True,
        description="Whether to fall back to zero-match relaxation if 0 opportunities are eligible.",
    )
    limit: int | None = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of ranked opportunities to return.",
    )


class MatchCalculationRequest(BaseModel):
    """Request payload for individual user-opportunity match calculation."""

    user_id: UUID | None = Field(
        default=None,
        description="ID of the user to load profile from the read-only database view.",
    )
    user_profile: UserProfileDTO | None = Field(
        default=None,
        description="Direct in-memory UserProfileDTO payload.",
    )
    opportunity_id: UUID | str | None = Field(
        default=None,
        description="ID of the cleaned opportunity to load from the database.",
    )
    opportunity: dict[str, Any] | None = Field(
        default=None,
        description="Direct in-memory opportunity dictionary payload.",
    )
