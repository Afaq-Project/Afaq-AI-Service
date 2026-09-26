import logging
import time
from datetime import datetime

from langchain_core.messages import HumanMessage

from src.modules.core.database.repositories.conversation_repository import (
    ConversationRepository,
)
from src.modules.core.database.repositories.opportunity_repository import (
    OpportunityRepository,
)
from src.modules.infrastructure.llm.anthropic_client import translate_error

from .chat_agent import (
    ChatAgentFactory,
    redacted_user_text,
    to_chat_messages,
    token_usage,
)
from .constants import Locale, blocked_message, decline_message
from .eligibility import EligibilityGuard
from .exceptions import OpportunityNotFoundError
from .models import ChatReply, ConversationHistory, UserProfile
from .prompts import build_chat_system_prompt

logger = logging.getLogger(__name__)


class ChatService:

    def __init__(
        self,
        conversations: ConversationRepository,
        opportunities: OpportunityRepository,
        agents: ChatAgentFactory,
        eligibility: EligibilityGuard | None = None,
        history_limit: int = 20,
    ) -> None:
        self._conversations = conversations
        self._opportunities = opportunities
        self._agents = agents
        self._eligibility = eligibility or EligibilityGuard()
        self._history_limit = history_limit

    async def send_message(
        self,
        *,
        user_id: str,
        opportunity_id: str,
        message: str,
        locale: Locale = "ar",
        profile: UserProfile | None = None,
        application_id: str | None = None,
    ) -> ChatReply:
        opportunity = await self._opportunities.get_cleaned_by_id(opportunity_id)
        if opportunity is None:
            raise OpportunityNotFoundError(opportunity_id)

        conversation = await self._conversations.get_or_create(
            user_id, opportunity_id, application_id
        )
        history = await self._conversations.get_recent_messages(
            conversation.id, self._history_limit
        )
        user_record = await self._conversations.add_message(
            conversation.id, role="user", content=message
        )
        source_url = opportunity.application_url or opportunity.source_url or None

        reason = self._eligibility.check_before_answer(message, opportunity)
        if reason is not None:
            logger.info(
                "Declined question in conversation %s before model call: %s",
                conversation.id,
                reason,
            )
            return await self._decline(conversation.id, reason, source_url, locale)

        agent = self._agents.build(
            build_chat_system_prompt(opportunity, profile, locale)
        )
        started = time.perf_counter()
        try:
            result = await agent.ainvoke(
                {
                    "messages": [
                        *to_chat_messages(history),
                        HumanMessage(content=message),
                    ]
                },
                principal={"id": user_id, "roles": ["student"]},
            )
        except Exception as exc:
            error = translate_error(exc)
            logger.error(
                "Chat model call failed in conversation %s (%s): %s",
                conversation.id,
                error.code,
                exc,
            )
            await self._conversations.add_message(
                conversation.id,
                role="assistant",
                content="",
                status="failed",
                decline_reason=error.code,
            )
            raise error from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if result.get("blocked"):
            logger.warning(
                "Guardrail blocked message in conversation %s: %s",
                conversation.id,
                result.get("block_reason"),
            )
            await self._conversations.update_message(user_record.id, status="blocked")
            stored = await self._conversations.add_message(
                conversation.id,
                role="assistant",
                content=blocked_message(locale),
                status="blocked",
                decline_reason="guardrail_blocked",
            )
            return ChatReply(
                conversation_id=conversation.id,
                message_id=stored.id,
                answer=stored.content,
                status="declined",
                decline_reason="guardrail_blocked",
                created_at=stored.created_at,
            )

        redacted = redacted_user_text(result)
        if redacted is not None and redacted != message:
            await self._conversations.update_message(user_record.id, content=redacted)

        answer = str(result.get("output") or "").strip()
        if self._eligibility.is_unanswerable(answer):
            return await self._decline(
                conversation.id, "insufficient_data", source_url, locale
            )

        input_tokens, output_tokens = token_usage(result)
        stored = await self._conversations.add_message(
            conversation.id,
            role="assistant",
            content=answer,
            model=result.get("model"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )
        logger.info(
            "Chat reply in conversation %s: model=%s in=%s out=%s latency=%dms",
            conversation.id,
            result.get("model"),
            input_tokens,
            output_tokens,
            latency_ms,
        )
        return ChatReply(
            conversation_id=conversation.id,
            message_id=stored.id,
            answer=answer,
            status="ok",
            official_source_url=source_url,
            created_at=stored.created_at,
        )

    async def get_history(
        self,
        *,
        user_id: str,
        opportunity_id: str,
        application_id: str | None = None,
        limit: int = 50,
        before: datetime | None = None,
    ) -> ConversationHistory:
        conversation = await self._conversations.find(
            user_id, opportunity_id, application_id
        )
        if conversation is None:
            return ConversationHistory(
                conversation_id=None, messages=[], has_more=False
            )

        records = await self._conversations.list_messages(
            conversation.id, limit + 1, before
        )
        has_more = len(records) > limit
        return ConversationHistory(
            conversation_id=conversation.id,
            messages=records[-limit:] if has_more else records,
            has_more=has_more,
        )

    async def _decline(
        self,
        conversation_id: str,
        reason: str,
        source_url: str | None,
        locale: str,
    ) -> ChatReply:
        stored = await self._conversations.add_message(
            conversation_id,
            role="assistant",
            content=decline_message(locale, source_url),
            status="declined",
            decline_reason=reason,
        )
        return ChatReply(
            conversation_id=conversation_id,
            message_id=stored.id,
            answer=stored.content,
            status="declined",
            decline_reason=reason,
            official_source_url=source_url,
            created_at=stored.created_at,
        )
