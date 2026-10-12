from pydantic import BaseModel, Field


class UserMatchResponse(BaseModel):
    """Response model for user matching operation."""

    status: str = "success"
    operation_id: str
    user_id: str
    matches_count: int = Field(ge=0)
    total_evaluated: int = Field(ge=0)
    total_eligible: int = Field(ge=0)
    is_preliminary: bool = False
    message: str = "User matching completed successfully."


class OpportunityMatchResponse(BaseModel):
    """Response model for new opportunity matching operation."""

    status: str = "success"
    operation_id: str
    opportunity_id: str
    users_evaluated: int = Field(ge=0)
    matches_persisted: int = Field(ge=0)
    message: str = "Opportunity matching completed successfully."


class FullRematchResponse(BaseModel):
    """Response model for full rematch operation."""

    status: str = "accepted"
    operation_id: str
    message: str = (
        "Full rematch operation started in background; a webhook will be sent on completion."
    )
