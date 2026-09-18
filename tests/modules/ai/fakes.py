from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from src.modules.infrastructure.llm.anthropic_client import StructuredCompletion


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

    async def get_cleaned_by_id(self, opportunity_id: str) -> SimpleNamespace | None:
        return self._items.get(opportunity_id)


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

    def build(self, system_prompt: str) -> FakeAgent:
        self.prompts.append(system_prompt)
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
