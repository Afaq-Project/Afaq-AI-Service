"""High-level Matching orchestration service for Afaq AI Matching Engine.

Provides unified interface for feed generation and individual match score calculations
connecting UserProfileReader, OpportunityRepository, FeedRanker, MatchCalculator, and MatchScoreRepository.
"""

import logging
from typing import Any
from uuid import UUID

from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.matching.models import (
    FeedRankingResultDTO,
    MatchScoreResultDTO,
    UserProfileDTO,
)
from src.modules.matching.services.feed_ranker import FeedRanker
from src.modules.matching.services.match_calculator import MatchCalculator
from src.modules.matching.services.user_profile_reader import UserProfileReader

logger = logging.getLogger(__name__)


class UserProfileNotFoundError(Exception):
    """Raised when a user profile cannot be found in the database view."""

    code = "user_profile_not_found"


class OpportunityNotFoundError(Exception):
    """Raised when an opportunity cannot be found in the database."""

    code = "opportunity_not_found"


def _to_dict(record: Any) -> dict[str, Any]:
    """Converts a Prisma record or Pydantic model to a standard dictionary."""
    if hasattr(record, "model_dump"):
        return record.model_dump()
    if hasattr(record, "dict"):
        return record.dict()
    if isinstance(record, dict):
        return record
    return dict(record)


class MatchingService:
    """Orchestrates matching calculations and personalized feed ranking."""

    def __init__(
        self,
        profile_reader: UserProfileReader,
        opportunity_repo: OpportunityRepository,
        match_score_repo: MatchScoreRepository | None = None,
        feed_ranker: FeedRanker | None = None,
        match_calculator: MatchCalculator | None = None,
    ) -> None:
        self._profile_reader = profile_reader
        self._opportunity_repo = opportunity_repo
        self._match_score_repo = match_score_repo
        self._feed_ranker = feed_ranker or FeedRanker()
        self._match_calculator = match_calculator or MatchCalculator()

    async def get_feed_for_user(
        self,
        user_id: UUID | str,
        filter_hard_eligibility: bool = True,
        enable_relaxation: bool = True,
        limit: int | None = None,
    ) -> FeedRankingResultDTO:
        """Retrieves user profile and returns ranked opportunities feed."""
        profile = await self._profile_reader.get_profile_by_user_id(user_id)
        if profile is None:
            raise UserProfileNotFoundError(
                f"User profile with ID '{user_id}' was not found."
            )

        # Retrieve eligible opportunities from repository within visibility window
        raw_opps = await self._opportunity_repo.find_within_visibility_window()
        opportunities = [_to_dict(opp) for opp in raw_opps]

        result = self._feed_ranker.rank_opportunities(
            user_profile=profile,
            opportunities=opportunities,
            filter_hard_eligibility=filter_hard_eligibility,
            enable_relaxation=enable_relaxation,
        )

        if limit is not None and limit > 0:
            result.ranked_opportunities = result.ranked_opportunities[:limit]

        return result

    async def calculate_match(
        self,
        user_id: UUID | str | None = None,
        user_profile: UserProfileDTO | None = None,
        opportunity_id: UUID | str | None = None,
        opportunity: dict[str, Any] | None = None,
    ) -> MatchScoreResultDTO:
        """Calculates match score between a user profile and an opportunity."""
        # 1. Resolve Profile
        profile: UserProfileDTO | None = user_profile
        if profile is None and user_id is not None:
            profile = await self._profile_reader.get_profile_by_user_id(user_id)
            if profile is None:
                raise UserProfileNotFoundError(
                    f"User profile with ID '{user_id}' was not found."
                )

        if profile is None:
            raise ValueError(
                "Either 'user_id' or 'user_profile' must be provided for match calculation."
            )

        # 2. Resolve Opportunity
        opp_data: dict[str, Any] | None = opportunity
        if opp_data is None and opportunity_id is not None:
            opp_record = await self._opportunity_repo.get_cleaned_by_id(
                str(opportunity_id)
            )
            if opp_record is None:
                raise OpportunityNotFoundError(
                    f"Opportunity with ID '{opportunity_id}' was not found."
                )
            opp_data = _to_dict(opp_record)

        if opp_data is None:
            raise ValueError(
                "Either 'opportunity_id' or 'opportunity' must be provided for match calculation."
            )

        return self._match_calculator.calculate_match_score(profile, opp_data)

    async def persist_match_score(
        self,
        user_id: UUID | str,
        opportunity_id: UUID | str,
        match_score: MatchScoreResultDTO,
        calculation_version: int = 1,
    ) -> Any:
        """Persists a calculated match score to the Opportunities database."""
        if self._match_score_repo is None:
            raise RuntimeError(
                "MatchScoreRepository is not configured on MatchingService."
            )
        return await self._match_score_repo.save_match_score(
            user_id=user_id,
            opportunity_id=opportunity_id,
            match_score=match_score,
            calculation_version=calculation_version,
        )
