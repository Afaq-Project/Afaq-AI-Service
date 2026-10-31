"""Matching API routes for Afaq AI Service."""

import logging
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from src.api.dependencies import get_matching_service, require_api_key
from src.api.models.ai_responses import ErrorResponse
from src.api.models.matching_requests import (
    FullRematchRequest,
    MatchCalculationRequest,
    MatchingFeedRequest,
    OpportunityMatchRequest,
    UserMatchRequest,
)
from src.api.models.matching_responses import (
    FullRematchResponse,
    OpportunityMatchResponse,
    UserMatchResponse,
)
from src.modules.core.auth.models import ApiKeyInfo
from src.modules.matching.models import (
    FeedRankingResultDTO,
    MatchScoreResultDTO,
)
from src.modules.matching.services.matching_service import (
    MatchingService,
    OpportunityNotFoundError,
    UserNotFoundError,
    UserProfileNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/matching",
    tags=["matching"],
    responses={
        401: {"description": "Invalid or missing API key"},
        404: {"model": ErrorResponse},
    },
)


async def _run_full_rematch_background(
    service: MatchingService, batch_size: int, operation_id: str
) -> None:
    """Executes full rematching in the background task and logs the outcome."""
    try:
        logger.info("Starting background full rematch %s", operation_id)
        await service.full_rematch(batch_size=batch_size)
        logger.info("Background full rematch %s finished successfully", operation_id)
    except Exception:
        logger.exception("Background full rematch %s failed", operation_id)


@router.post(
    "/user",
    response_model=UserMatchResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid user ID"},
        401: {"description": "Invalid or missing API key"},
        404: {"description": "User profile not found"},
    },
)
async def match_user_endpoint(
    request: UserMatchRequest,
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: MatchingService = Depends(get_matching_service),
) -> UserMatchResponse:
    """Matches a specific user against active opportunities and persists scores."""
    logger.info(
        "User matching requested for user %s by %s", request.user_id, key_info.name
    )
    try:
        result = await service.match_user(request.user_id)
    except (UserNotFoundError, UserProfileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("User matching failed for user %s", request.user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Matching calculation failed: {exc}",
        ) from exc

    return UserMatchResponse(
        status="success",
        operation_id=result["operation_id"],
        user_id=result["user_id"],
        matches_count=result["matches_count"],
        total_evaluated=result["total_evaluated"],
        total_eligible=result["total_eligible"],
        is_preliminary=result["is_preliminary"],
        message="User matching completed successfully.",
    )


@router.post(
    "/opportunity",
    response_model=OpportunityMatchResponse,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"description": "Invalid opportunity ID"},
        401: {"description": "Invalid or missing API key"},
        404: {"description": "Opportunity not found"},
    },
)
async def match_opportunity_endpoint(
    request: OpportunityMatchRequest,
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: MatchingService = Depends(get_matching_service),
) -> OpportunityMatchResponse:
    """Matches a newly discovered opportunity against all relevant users and persists scores."""
    logger.info(
        "Opportunity matching requested for opportunity %s by %s",
        request.opportunity_id,
        key_info.name,
    )
    try:
        result = await service.match_opportunity(request.opportunity_id)
    except OpportunityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception(
            "Opportunity matching failed for opportunity %s", request.opportunity_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Opportunity matching failed: {exc}",
        ) from exc

    return OpportunityMatchResponse(
        status=result.get("status", "success"),
        operation_id=result.get("operation_id", str(uuid4())),
        opportunity_id=result["opportunity_id"],
        users_evaluated=result["users_evaluated"],
        matches_persisted=result["matches_persisted"],
        message="Opportunity matching completed successfully.",
    )


@router.post(
    "/full-rematch",
    response_model=FullRematchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        401: {"description": "Invalid or missing API key"},
        409: {"description": "Full rematch operation is already in progress"},
    },
)
async def full_rematch_endpoint(
    background_tasks: BackgroundTasks,
    request: FullRematchRequest = FullRematchRequest(),
    key_info: ApiKeyInfo = Depends(require_api_key),
    service: MatchingService = Depends(get_matching_service),
) -> FullRematchResponse:
    """Triggers a full rematch across all users and active opportunities in the background."""
    if service.is_rematch_running:
        logger.warning(
            "Full rematch requested by %s rejected: operation already in progress",
            key_info.name,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Full rematch operation is already in progress.",
        )

    operation_id = str(uuid4())
    logger.info(
        "Full rematch requested by %s: operation_id=%s, batch_size=%d",
        key_info.name,
        operation_id,
        request.batch_size,
    )

    background_tasks.add_task(
        _run_full_rematch_background,
        service,
        request.batch_size,
        operation_id,
    )

    return FullRematchResponse(
        status="accepted",
        operation_id=operation_id,
        message="Full rematch operation started in background; a webhook will be sent on completion.",
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
    except (UserProfileNotFoundError, UserNotFoundError) as exc:
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
    except (UserProfileNotFoundError, UserNotFoundError) as exc:
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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Failed to calculate match score: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to calculate match score.",
        ) from exc
