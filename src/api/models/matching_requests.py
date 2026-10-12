from uuid import UUID

from pydantic import BaseModel, Field


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
