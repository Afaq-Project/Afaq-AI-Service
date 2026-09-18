from datetime import datetime
from typing import Any

from prisma import Prisma

HISTORY_STATUSES = ("ok", "declined")
VISIBLE_STATUSES = ("ok", "declined", "blocked")


class ConversationRepository:

    def __init__(self, db: Prisma) -> None:
        self._db = db

    async def find(
        self,
        user_id: str,
        opportunity_id: str,
        application_id: str | None = None,
    ) -> Any | None:
        return await self._db.conversation.find_first(
            where={
                "user_id": user_id,
                "opportunity_id": opportunity_id,
                "application_id": application_id,
            },
            order={"created_at": "asc"},
        )

    async def get_or_create(
        self,
        user_id: str,
        opportunity_id: str,
        application_id: str | None = None,
    ) -> Any:
        existing = await self.find(user_id, opportunity_id, application_id)
        if existing is not None:
            return existing

        data: dict[str, Any] = {"user_id": user_id, "opportunity_id": opportunity_id}
        if application_id is not None:
            data["application_id"] = application_id
        return await self._db.conversation.create(data=data)  # type: ignore[arg-type]

    async def add_message(
        self,
        conversation_id: str,
        *,
        role: str,
        content: str,
        status: str = "ok",
        decline_reason: str | None = None,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> Any:
        data: dict[str, Any] = {
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "status": status,
        }
        optional = {
            "decline_reason": decline_reason,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        }
        data.update(
            {key: value for key, value in optional.items() if value is not None}
        )
        return await self._db.conversationmessage.create(data=data)  # type: ignore[arg-type]

    async def update_message(self, message_id: str, **fields: Any) -> Any:
        return await self._db.conversationmessage.update(
            where={"id": message_id},
            data=fields,  # type: ignore[arg-type]
        )

    async def get_recent_messages(self, conversation_id: str, limit: int) -> list[Any]:
        records = await self._db.conversationmessage.find_many(
            where={
                "conversation_id": conversation_id,
                "status": {"in": list(HISTORY_STATUSES)},
            },
            order={"created_at": "desc"},
            take=limit,
        )
        return list(reversed(records))

    async def list_messages(
        self,
        conversation_id: str,
        limit: int,
        before: datetime | None = None,
    ) -> list[Any]:
        where: dict[str, Any] = {
            "conversation_id": conversation_id,
            "status": {"in": list(VISIBLE_STATUSES)},
        }
        if before is not None:
            where["created_at"] = {"lt": before}

        records = await self._db.conversationmessage.find_many(
            where=where,  # type: ignore[arg-type]
            order={"created_at": "desc"},
            take=limit,
        )
        return list(reversed(records))
