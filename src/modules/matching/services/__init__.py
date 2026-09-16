"""Matching services package."""

from src.modules.matching.services.lifecycle_service import (
    RETENTION_WINDOW_DAYS,
    filter_opportunities_by_lifecycle,
    is_opportunity_active,
    is_opportunity_closed,
    is_within_visibility_window,
)
from src.modules.matching.services.user_profile_reader import UserProfileReader

__all__ = [
    "RETENTION_WINDOW_DAYS",
    "UserProfileReader",
    "filter_opportunities_by_lifecycle",
    "is_opportunity_active",
    "is_opportunity_closed",
    "is_within_visibility_window",
]
