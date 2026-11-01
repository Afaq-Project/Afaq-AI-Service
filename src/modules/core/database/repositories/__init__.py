"""Database repositories package."""

from src.modules.core.database.repositories.match_score_repository import (
    MatchScoreRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)

__all__ = [
    "MatchScoreRepository",
    "OpportunityRepository",
]
