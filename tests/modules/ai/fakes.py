from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

from src.modules.infrastructure.llm.base import StructuredCompletion


def make_opportunity(**overrides: Any) -> SimpleNamespace:
    data: dict[str, Any] = {
        "id": "opp-1",
        "title": "Chevening Scholarship",
        "organization": "UK Government",
        "opportunity_type": "scholarship",
        "country": "United Kingdom",
        "location": "United Kingdom",
        "is_remote": False,
        "funding_type": "fully_funded",
        "deadline": datetime(2026, 11, 5, tzinfo=UTC),
        "study_levels": ["Master"],
        "fields_of_study": [],
        "eligibility": {"min_experience_years": 2, "degree": "Bachelor"},
        "application_url": "https://www.chevening.org/apply",
        "source_url": "https://almin7.com/chevening",
        "description": "Fully funded one-year master's degree in the UK.",
        "status": "cleaned",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeOpportunityRepository:

    def __init__(self, opportunities: list[SimpleNamespace] | None = None) -> None:
        self._items = {o.id: o for o in (opportunities or [])}
        self.searches: list[dict[str, Any]] = []
        self.search_error: Exception | None = None

    async def get_cleaned_by_id(self, opportunity_id: str) -> SimpleNamespace | None:
        return self._items.get(opportunity_id)

    async def search_visible(self, **kwargs: Any) -> list[SimpleNamespace]:
        self.searches.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        query = (kwargs.get("query") or "").strip().casefold()
        found = [
            item
            for item in self._items.values()
            if not query or query in str(item.title).casefold()
        ]
        return found[: kwargs.get("limit") or 5]


class FakeMatchScoreRepository:

    def __init__(self, scores: dict[str, list[SimpleNamespace]] | None = None) -> None:
        self._scores = scores or {}
        self.calls: list[tuple[str, str]] = []

    async def get_for_user(self, user_id: str, opportunity_id: str) -> Any | None:
        self.calls.append((user_id, opportunity_id))
        return next(
            (
                s
                for s in self._scores.get(user_id, [])
                if s.opportunity_id == opportunity_id
            ),
            None,
        )

    async def top_for_user(self, user_id: str, limit: int = 5) -> list[Any]:
        self.calls.append((user_id, f"top:{limit}"))
        ranked = sorted(
            self._scores.get(user_id, []), key=lambda s: s.score_pct, reverse=True
        )
        return ranked[:limit]


def make_score(
    opportunity_id: str = "opp-1",
    score_pct: int = 72,
    title: str = "Chevening Scholarship",
    **overrides: Any,
) -> SimpleNamespace:
    data: dict[str, Any] = {
        "opportunity_id": opportunity_id,
        "score_pct": score_pct,
        "score_breakdown": {"field_of_study": 80, "skills": 65},
        "calculated_at": datetime(2026, 9, 1, tzinfo=UTC),
        "opportunity": SimpleNamespace(title=title),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class FakeConversationRepository:

    def __init__(self) -> None:
        self.conversations: list[SimpleNamespace] = []
        self.messages: list[SimpleNamespace] = []
        self._clock = datetime(2026, 9, 1, tzinfo=UTC)

    async def find(self, user_id, opportunity_id, application_id=None):
        return next(
            (
                c
                for c in self.conversations
                if c.user_id == user_id
                and c.opportunity_id == opportunity_id
                and c.application_id == application_id
            ),
            None,
        )

    async def get_or_create(self, user_id, opportunity_id, application_id=None):
        existing = await self.find(user_id, opportunity_id, application_id)
        if existing is not None:
            return existing
        conversation = SimpleNamespace(
            id=f"conv-{len(self.conversations) + 1}",
            user_id=user_id,
            opportunity_id=opportunity_id,
            application_id=application_id,
        )
        self.conversations.append(conversation)
        return conversation

    async def add_message(self, conversation_id, *, role, content, status="ok", **meta):
        self._clock += timedelta(seconds=1)
        record = SimpleNamespace(
            id=f"msg-{len(self.messages) + 1}",
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=status,
            created_at=self._clock,
            **{
                "decline_reason": None,
                "model": None,
                "input_tokens": None,
                "output_tokens": None,
                "latency_ms": None,
                **meta,
            },
        )
        self.messages.append(record)
        return record

    async def update_message(self, message_id, **fields):
        record = next(m for m in self.messages if m.id == message_id)
        for key, value in fields.items():
            setattr(record, key, value)
        return record

    async def get_recent_messages(self, conversation_id, limit):
        matching = [
            m
            for m in self.messages
            if m.conversation_id == conversation_id and m.status in ("ok", "declined")
        ]
        return matching[-limit:]

    async def list_messages(self, conversation_id, limit, before=None):
        matching = [
            m
            for m in self.messages
            if m.conversation_id == conversation_id
            and m.status != "failed"
            and (before is None or m.created_at < before)
        ]
        return matching[-limit:]

    def by_role(self, role: str) -> list[SimpleNamespace]:
        return [m for m in self.messages if m.role == role]


class ToolCallingFakeModel(GenericFakeChatModel):

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolCallingFakeModel":
        return self


def model_calling(
    *calls: tuple[str, dict[str, Any]], final: str = "تم الاطلاع على البيانات."
) -> ToolCallingFakeModel:
    requested = [
        {"name": name, "args": args, "id": f"call-{index}"}
        for index, (name, args) in enumerate(calls)
    ]
    messages = [
        AIMessage(content="", tool_calls=requested),
        AIMessage(content=final),
    ]
    return ToolCallingFakeModel(messages=iter(messages))


def tool_messages(result: dict[str, Any]) -> list[str]:
    return [
        str(m.content) for m in result.get("messages", []) if isinstance(m, ToolMessage)
    ]


class FakeAgent:

    def __init__(
        self, result: dict[str, Any] | None = None, error: Exception | None = None
    ):
        self.result = result or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, user_input, *, principal=None, run_id=None, config=None):
        self.calls.append({"input": user_input, "principal": principal})
        if self.error is not None:
            raise self.error
        return self.result


class FakeAgentFactory:

    def __init__(self, agent: FakeAgent) -> None:
        self.agent = agent
        self.prompts: list[str] = []
        self.tools: list[list[Any]] = []

    def build(self, system_prompt: str, tools: Any = ()) -> FakeAgent:
        self.prompts.append(system_prompt)
        self.tools.append(list(tools))
        return self.agent


class FakeStructuredGenerator:

    def __init__(self, output: Any = None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate(self, *, system, prompt, output_type):
        self.calls.append(
            {"system": system, "prompt": prompt, "output_type": output_type}
        )
        if self.error is not None:
            raise self.error
        return StructuredCompletion(
            output=self.output,
            model="claude-opus-5",
            input_tokens=1200,
            output_tokens=450,
            latency_ms=900,
        )
