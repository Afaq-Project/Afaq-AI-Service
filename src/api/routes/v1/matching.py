"""Matching API routes for Afaq AI Service."""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.dependencies import get_matching_service, require_api_key
from src.api.models.ai_responses import ErrorResponse
from src.api.models.matching_requests import (
    MatchCalculationRequest,
    MatchingFeedRequest,
)
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.matching.models import (
    FeedRankingResultDTO,
    MatchScoreResultDTO,
)
from src.modules.matching.services.matching_service import (
    MatchingService,
    OpportunityNotFoundError,
    UserProfileNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/matching",
    tags=["matching"],
    responses={
        401: {"description": "Invalid or missing API key"},
        404: {"model": ErrorResponse},
        422: {"description": "Validation or calculation input error"},
    },
)


@router.post(
    "/feed/{user_id}",
    response_model=FeedRankingResultDTO,
    summary="Generate ranked opportunity feed for a user",
    description="Retrieves the user profile and matches against all visible opportunities, "
    "returning ranked opportunities with eligibility and preliminary flags.",
)
async def get_matching_feed(
    user_id: UUID,
    body: MatchingFeedRequest | None = None,
    filter_hard_eligibility: bool = Query(
        default=True,
        description="Whether to filter out hard-ineligible opportunities.",
    ),
    enable_relaxation: bool = Query(
        default=True,
        description="Whether to fall back to zero-match relaxation if 0 opportunities pass hard filters.",
    ),
    limit: int | None = Query(
        default=50,
        ge=1,
        le=500,
        description="Maximum number of ranked opportunities to return.",
    ),
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: MatchingService = Depends(get_matching_service),
) -> FeedRankingResultDTO:
    """Generates a ranked feed of scholarship opportunities for the specified user."""
    effective_filter_hard = (
        body.filter_hard_eligibility if body is not None else filter_hard_eligibility
    )
    effective_relaxation = (
        body.enable_relaxation if body is not None else enable_relaxation
    )
    effective_limit = (
        body.limit if body is not None and body.limit is not None else limit
    )

    try:
        return await service.get_feed_for_user(
            user_id=user_id,
            filter_hard_eligibility=effective_filter_hard,
            enable_relaxation=effective_relaxation,
            limit=effective_limit,
        )
    except UserProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Failed to generate matching feed for user %s: %s", user_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate matching feed.",
        ) from exc


@router.post(
    "/calculate",
    response_model=MatchScoreResultDTO,
    summary="Calculate match score for a user-opportunity pair",
    description="Calculates deterministic match score and category breakdowns using Matching V1 engine.",
)
async def calculate_match_score(
    request: MatchCalculationRequest,
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: MatchingService = Depends(get_matching_service),
) -> MatchScoreResultDTO:
    """Calculates match score between a user profile and an opportunity."""
    try:
        return await service.calculate_match(
            user_id=request.user_id,
            user_profile=request.user_profile,
            opportunity_id=request.opportunity_id,
            opportunity=request.opportunity,
        )
    except UserProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except OpportunityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to calculate match score: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate match score.",
        ) from exc
