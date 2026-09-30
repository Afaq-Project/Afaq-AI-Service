from typing import Any, cast

from prisma import Prisma


class MatchScoreRepository:

    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def get_for_user(self, user_id: str, opportunity_id: str) -> Any | None:
        return await self._db.matchscore.find_first(
            where=cast(Any, {"user_id": user_id, "opportunity_id": opportunity_id}),
            include=cast(Any, {"opportunity": True}),
        )

    async def top_for_user(self, user_id: str, limit: int = 5) -> list[Any]:
        return await self._db.matchscore.find_many(
            where=cast(Any, {"user_id": user_id}),
            order=cast(Any, {"score_pct": "desc"}),
            take=max(1, min(limit, 20)),
            include=cast(Any, {"opportunity": True}),
        )
