"""Matching services package."""

from src.modules.matching.services.feed_ranker import FeedRanker, rank_opportunities
from src.modules.matching.services.hard_filter_service import HardFilterService
from src.modules.matching.services.lifecycle_service import (
    RETENTION_WINDOW_DAYS,
    filter_opportunities_by_lifecycle,
    is_opportunity_active,
    is_opportunity_closed,
    is_within_visibility_window,
)
from src.modules.matching.services.match_calculator import MatchCalculator
from src.modules.matching.services.opportunity_requirements_matcher import (
    OpportunityRequirementsMatcher,
    OpportunityRequirementsMatchResult,
    RequirementMatchDecision,
    SingleRequirementEvaluation,
)
from src.modules.matching.services.requirement_extractor import RequirementExtractor
from src.modules.matching.services.user_profile_reader import UserProfileReader

__all__ = [
    "RETENTION_WINDOW_DAYS",
    "FeedRanker",
    "HardFilterService",
    "MatchCalculator",
    "OpportunityRequirementsMatchResult",
    "OpportunityRequirementsMatcher",
    "RequirementExtractor",
    "RequirementMatchDecision",
    "SingleRequirementEvaluation",
    "UserProfileReader",
    "filter_opportunities_by_lifecycle",
    "is_opportunity_active",
    "is_opportunity_closed",
    "is_within_visibility_window",
    "rank_opportunities",
]
