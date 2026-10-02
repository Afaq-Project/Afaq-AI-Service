"""Repository for storing and querying computed Match Scores in Afaq database."""

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from prisma import Json, Prisma
from src.modules.matching.models import MatchScoreResultDTO

logger = logging.getLogger(__name__)


class MatchScoreRepository:
    """Handles persistence and retrieval of match scores in Opportunities database."""

    def __init__(self, db: Prisma) -> None:
        self._db = db

    def prepare_upsert_payload(
        self,
        user_id: UUID | str,
        opportunity_id: UUID | str,
        match_score: MatchScoreResultDTO,
        calculation_version: int = 1,
    ) -> dict[str, Any]:
        """Prepares a validated upsert dictionary payload for Prisma matchscore operations."""
        uid = str(user_id)
        oid = str(opportunity_id)
        score_int = int(round(match_score.total_score))

        breakdown = [
            cat.model_dump() if hasattr(cat, "model_dump") else cat.dict()
            for cat in match_score.category_scores
        ]

        if match_score.calculated_at:
            try:
                calc_dt = datetime.fromisoformat(match_score.calculated_at)
            except Exception:
                calc_dt = datetime.now(UTC)
        else:
            calc_dt = datetime.now(UTC)

        return {
            "where": {
                "user_id_opportunity_id": {
                    "user_id": uid,
                    "opportunity_id": oid,
                }
            },
            "data": {
                "create": {
                    "user_id": uid,
                    "opportunity_id": oid,
                    "score_pct": score_int,
                    "score_breakdown": Json(breakdown),
                    "calculation_version": calculation_version,
                    "calculated_at": calc_dt,
                },
                "update": {
                    "score_pct": score_int,
                    "score_breakdown": Json(breakdown),
                    "calculation_version": calculation_version,
                    "calculated_at": calc_dt,
                },
            },
        }

    async def save_match_score(
        self,
        user_id: UUID | str,
        opportunity_id: UUID | str,
        match_score: MatchScoreResultDTO,
        calculation_version: int = 1,
    ) -> Any:
        """Upserts a single match score for a user and opportunity."""
        payload = self.prepare_upsert_payload(
            user_id=user_id,
            opportunity_id=opportunity_id,
            match_score=match_score,
            calculation_version=calculation_version,
        )
        return await self._db.matchscore.upsert(
            where=payload["where"],  # type: ignore[arg-type]
            data=payload["data"],  # type: ignore[arg-type]
        )

    async def find_by_user_and_opportunity(
        self, user_id: UUID | str, opportunity_id: UUID | str
    ) -> Any | None:
        """Finds an existing match score for a given user and opportunity."""
        return await self._db.matchscore.find_unique(
            where={
                "user_id_opportunity_id": {
                    "user_id": str(user_id),
                    "opportunity_id": str(opportunity_id),
                }
            }
        )

    async def find_by_user_id(self, user_id: UUID | str, limit: int = 100) -> list[Any]:
        """Finds match scores for a given user ordered by score descending."""
        return await self._db.matchscore.find_many(
            where={"user_id": str(user_id)},
            order={"score_pct": "desc"},
            take=limit,
        )
