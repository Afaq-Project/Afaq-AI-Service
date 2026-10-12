import logging
from datetime import UTC, datetime
from typing import Any

from prisma import Json, Prisma

logger = logging.getLogger(__name__)


class MatchScoreRepository:
    """Repository for persisting and querying MatchScore records in PostgreSQL via Prisma."""

    def __init__(self, db: Prisma) -> None:
        self._db = db

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
                    "user_id": user_id,
                    "opportunity_id": opportunity_id,
                }
            },
            data={
                "create": {
                    "user_id": user_id,
                    "opportunity_id": opportunity_id,
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

    async def find_by_user_id(self, user_id: str) -> list[Any]:
        """Retrieves all MatchScore records for a given user_id."""
        return await self._db.matchscore.find_many(
            where={"user_id": user_id},
            order={"score_pct": "desc"},
        )

    async def find_by_opportunity_id(self, opportunity_id: str) -> list[Any]:
        """Retrieves all MatchScore records for a given opportunity_id."""
        return await self._db.matchscore.find_many(
            where={"opportunity_id": opportunity_id},
            order={"score_pct": "desc"},
        )
