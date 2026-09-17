"""Feed ranking service implementing deterministic Match % sorting for Afaq Matching Engine."""

from typing import Any

from src.modules.matching.models import (
    EligibilityDecision,
    FeedRankingResultDTO,
    MatchScoreResultDTO,
    RankedOpportunityDTO,
)
from src.modules.matching.services.hard_filter_service import HardFilterService
from src.modules.matching.services.match_calculator import MatchCalculator


def rank_opportunities(
    user_profile: Any,
    opportunities: list[Any],
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
    - Hard-filter non-passing exclusion from standard feed (Task 6).
    - Match % descending sort order (Task 9).
    - Stable sorting on tie scores (no invented tie-breaker).
    - Zero-match relaxation fallback when standard feed is empty (Task 12).
    - Core fields completeness indicator (Task 14).
    - Clean separation of eligibility vs ranking.
    """

    def __init__(
        self,
        match_calculator: MatchCalculator | None = None,
        hard_filter_service: HardFilterService | None = None,
    ) -> None:
        self.match_calculator = match_calculator or MatchCalculator()
        self.hard_filter_service = hard_filter_service or HardFilterService()

    def sort_by_match_score(
        self,
        scored_items: list[tuple[Any, MatchScoreResultDTO]],
    ) -> list[RankedOpportunityDTO]:
        """Sorts pre-scored opportunities by Match % descending using stable sort."""
        # Python's list.sort / sorted is Timsort (guaranteed stable)
        sorted_items = sorted(
            scored_items,
            key=lambda pair: pair[1].score_pct,
            reverse=True,
        )

        ranked: list[RankedOpportunityDTO] = []
        for idx, (opp, score) in enumerate(sorted_items, start=1):
            ranked.append(
                RankedOpportunityDTO(
                    opportunity=opp,
                    match_score=score,
                    rank=idx,
                )
            )
        return ranked

    def rank_opportunities(
        self,
        user_profile: Any,
        opportunities: list[Any],
        filter_hard_eligibility: bool = True,
        enable_relaxation: bool = True,
    ) -> FeedRankingResultDTO:
        """Evaluates, filters, scores, and ranks opportunities for a user profile.

        If standard hard filtering results in 0 eligible opportunities and
        `enable_relaxation` is True, zero-match relaxation is triggered: hard
        filters are relaxed and closest opportunities are scored and ranked with
        `is_relaxed=True`.
        """
        core_complete = getattr(user_profile, "core_fields_complete", True)
        if callable(core_complete):
            core_complete = core_complete()

        if not opportunities:
            return FeedRankingResultDTO(
                items=[],
                total_eligible=0,
                is_relaxed=False,
                core_fields_complete=bool(core_complete),
            )

        eligible_opportunities: list[Any] = []
        is_relaxed = False

        # 1. Standard Hard-Filter Eligibility Gate
        if filter_hard_eligibility:
            for opp in opportunities:
                hard_result = self.hard_filter_service.evaluate_detailed(
                    user_profile, opp
                )
                if hard_result.decision != EligibilityDecision.INELIGIBLE:
                    eligible_opportunities.append(opp)

            # 2. Zero-Match Relaxation Fallback (Task 12)
            if not eligible_opportunities and enable_relaxation:
                eligible_opportunities = list(opportunities)
                is_relaxed = True
        else:
            eligible_opportunities = list(opportunities)

        if not eligible_opportunities:
            return FeedRankingResultDTO(
                items=[],
                total_eligible=0,
                is_relaxed=False,
                core_fields_complete=bool(core_complete),
            )

        # 3. Score Opportunities
        scored_pairs: list[tuple[Any, MatchScoreResultDTO]] = []
        for opp in eligible_opportunities:
            score = self.match_calculator.calculate_match_score(user_profile, opp)
            scored_pairs.append((opp, score))

        # 4. Sort by Match % Descending
        ranked_items = self.sort_by_match_score(scored_pairs)

        return FeedRankingResultDTO(
            items=ranked_items,
            total_eligible=len(ranked_items),
            is_relaxed=is_relaxed,
            core_fields_complete=bool(core_complete),
        )
