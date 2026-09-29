"""Feed ranking service implementing deterministic Match % sorting for Afaq Matching Engine."""

import logging
from typing import Any

from src.modules.matching.models import (
    FeedRankingResultDTO,
    MatchScoreResultDTO,
    RankedOpportunityDTO,
    UserProfileDTO,
)
from src.modules.matching.services.hard_filter_service import HardFilterService
from src.modules.matching.services.match_calculator import MatchCalculator

logger = logging.getLogger(__name__)


def rank_opportunities(
    user_profile: UserProfileDTO,
    opportunities: list[dict[str, Any]],
    match_calculator: MatchCalculator | None = None,
    hard_filter_service: HardFilterService | None = None,
    filter_hard_eligibility: bool = True,
    enable_relaxation: bool = True,
) -> FeedRankingResultDTO:
    """Convenience function sorting and ranking opportunities by Match % descending."""
    ranker = FeedRanker(
        match_calculator=match_calculator,
        hard_filter_service=hard_filter_service,
    )
    return ranker.rank_opportunities(
        user_profile,
        opportunities,
        filter_hard_eligibility=filter_hard_eligibility,
        enable_relaxation=enable_relaxation,
    )


class FeedRanker:
    """Service providing deterministic feed ranking ordered by Match % descending.

    Enforces:
    - Preliminary matching flag: when is_matchable != True, matching is NOT blocked;
      preliminary results are calculated with available profile data and marked
      is_preliminary = True.
    - Hard-filter non-passing exclusion from standard feed.
    - Match % descending sort order.
    - Stable sorting on tie scores.
    - Zero-match relaxation fallback when standard feed is empty.
    - Core fields completeness indicator.
    - Clean separation of eligibility decision and match score.
    """

    def __init__(
        self,
        match_calculator: MatchCalculator | None = None,
        hard_filter_service: HardFilterService | None = None,
    ) -> None:
        self._calc = match_calculator or MatchCalculator()
        self._filter = hard_filter_service or HardFilterService()

    def sort_by_match_score(
        self,
        scored_items: list[tuple[dict[str, Any], MatchScoreResultDTO]],
    ) -> list[tuple[dict[str, Any], MatchScoreResultDTO]]:
        """Sorts pre-scored opportunities by Match % descending using stable sort."""
        return sorted(scored_items, key=lambda pair: pair[1].total_score, reverse=True)

    def rank_opportunities(
        self,
        user_profile: UserProfileDTO,
        opportunities: list[dict[str, Any]],
        filter_hard_eligibility: bool = True,
        enable_relaxation: bool = True,
    ) -> FeedRankingResultDTO:
        """Evaluates, filters, scores, and ranks opportunities for a user profile.

        Preliminary matching contract:
          - is_matchable == True  → normal/accurate matching, is_preliminary = False.
          - is_matchable != True  → preliminary matching using available data,
                                    is_preliminary = True. Matching is NEVER blocked.
        """
        user_id = str(user_profile.user_id) if user_profile.user_id else None
        core_fields_complete = bool(
            user_profile.nationality and user_profile.education_level
        )
        is_preliminary = user_profile.is_matchable is not True

        total_evaluated = len(opportunities)
        eligible: list[dict[str, Any]] = []

        if filter_hard_eligibility:
            for opp in opportunities:
                if self._filter.evaluate(user_profile, opp):
                    eligible.append(opp)
        else:
            eligible = list(opportunities)

        is_relaxed = False
        if filter_hard_eligibility and not eligible and enable_relaxation:
            # Zero-match relaxation: use all opportunities without hard filtering
            eligible = list(opportunities)
            is_relaxed = True

        # Score all eligible
        scored = self._calc.calculate_match_scores(user_profile, eligible)
        sorted_scored = self.sort_by_match_score(scored)

        ranked: list[RankedOpportunityDTO] = []
        for opp, score in sorted_scored:
            hard_result = self._filter.evaluate_detailed(user_profile, opp)
            ranked.append(
                RankedOpportunityDTO(
                    opportunity=opp,
                    match_score=score,
                    hard_filter_result=hard_result,
                    is_relaxed=is_relaxed,
                )
            )

        return FeedRankingResultDTO(
            user_id=user_id,
            ranked_opportunities=ranked,
            total_evaluated=total_evaluated,
            total_eligible=len(eligible),
            is_relaxed=is_relaxed,
            core_fields_complete=core_fields_complete,
            is_preliminary=is_preliminary,
        )
