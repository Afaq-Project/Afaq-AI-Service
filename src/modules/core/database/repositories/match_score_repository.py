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

    async def upsert_score(
        self,
        user_id: str,
        opportunity_id: str,
        score_pct: int,
        score_breakdown: dict[str, Any] | None = None,
        calculation_version: int = 1,
    ) -> Any:
        """Upserts a single MatchScore record respecting @@unique([user_id, opportunity_id])."""
        breakdown_json = Json(score_breakdown or {})
        now = datetime.now(UTC)

        return await self._db.matchscore.upsert(
            where={
                "user_id_opportunity_id": {
                    "user_id": str(user_id),
                    "opportunity_id": str(opportunity_id),
                }
            },
            data={
                "create": {
                    "user_id": str(user_id),
                    "opportunity_id": str(opportunity_id),
                    "score_pct": score_pct,
                    "score_breakdown": breakdown_json,
                    "calculation_version": calculation_version,
                    "calculated_at": now,
                },
                "update": {
                    "score_pct": score_pct,
                    "score_breakdown": breakdown_json,
                    "calculation_version": calculation_version,
                    "calculated_at": now,
                },
            },
        )

    async def upsert_many_scores(
        self,
        scores: list[dict[str, Any]],
    ) -> int:
        """Upserts a list of match scores into the database.

        Each dict in scores must contain:
          - user_id: str
          - opportunity_id: str
          - score_pct: int
          - score_breakdown: dict[str, Any] (optional)
          - calculation_version: int (optional, default 1)

        Returns:
          Number of records processed.
        """
        count = 0
        for item in scores:
            user_id = item["user_id"]
            opportunity_id = item["opportunity_id"]
            score_pct = item["score_pct"]
            score_breakdown = item.get("score_breakdown") or {}
            calc_version = item.get("calculation_version", 1)

            await self.upsert_score(
                user_id=user_id,
                opportunity_id=opportunity_id,
                score_pct=score_pct,
                score_breakdown=score_breakdown,
                calculation_version=calc_version,
            )
            count += 1

        logger.info("Successfully upserted %d match score records", count)
        return count

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

    async def find_by_opportunity_id(
        self, opportunity_id: UUID | str, limit: int = 100
    ) -> list[Any]:
        """Finds match scores for a given opportunity ordered by score descending."""
        return await self._db.matchscore.find_many(
            where={"opportunity_id": str(opportunity_id)},
            order={"score_pct": "desc"},
            take=limit,
        )
