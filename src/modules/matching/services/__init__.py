"""Matching services package."""

from src.modules.matching.services.hard_filter_service import (
    OPEN_TO_ALL_NATIONALITIES,
    HardFilterService,
    evaluate_hard_filters,
    filter_by_hard_eligibility,
    passes_education_filter,
    passes_nationality_filter,
)
from src.modules.matching.services.lifecycle_service import (
    RETENTION_WINDOW_DAYS,
    filter_opportunities_by_lifecycle,
    is_opportunity_active,
    is_opportunity_closed,
    is_within_visibility_window,
)
from src.modules.matching.services.user_profile_reader import UserProfileReader

__all__ = [
    "HardFilterService",
    "OPEN_TO_ALL_NATIONALITIES",
    "RETENTION_WINDOW_DAYS",
    "UserProfileReader",
    "evaluate_hard_filters",
    "filter_by_hard_eligibility",
    "filter_opportunities_by_lifecycle",
    "is_opportunity_active",
    "is_opportunity_closed",
    "is_within_visibility_window",
    "passes_education_filter",
    "passes_nationality_filter",
]
