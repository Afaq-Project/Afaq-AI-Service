from datetime import UTC, datetime
from types import SimpleNamespace

from src.modules.core.database.repositories.conversation_repository import (
    ConversationRepository,
)


class RecordingTable:

    def __init__(self, find_first=None, find_many=None):
        self.find_first_result = find_first
        self.find_many_result = find_many or []
        self.calls: list[tuple[str, dict]] = []

    async def find_first(self, **kwargs):
        self.calls.append(("find_first", kwargs))
        return self.find_first_result

    async def find_many(self, **kwargs):
        self.calls.append(("find_many", kwargs))
        return list(self.find_many_result)

    async def create(self, data):
        self.calls.append(("create", {"data": data}))
        return SimpleNamespace(id="new-id", **data)

    async def update(self, where, data):
        self.calls.append(("update", {"where": where, "data": data}))
        return SimpleNamespace(**where, **data)


class FakeDb:

    def __init__(self, conversation=None, messages=None):
        self.conversation = conversation or RecordingTable()
        self.conversationmessage = messages or RecordingTable()


class TestConversations:
    async def test_find_filters_by_owner_and_context(self):
        db = FakeDb()
        await ConversationRepository(db).find("user-1", "opp-1")

        name, kwargs = db.conversation.calls[0]
        assert name == "find_first"
        assert kwargs["where"] == {
            "user_id": "user-1",
            "opportunity_id": "opp-1",
            "application_id": None,
        }

    async def test_get_or_create_returns_existing(self):
        existing = SimpleNamespace(id="conv-1")
        db = FakeDb(conversation=RecordingTable(find_first=existing))

        result = await ConversationRepository(db).get_or_create("user-1", "opp-1")

        assert result is existing
        assert [name for name, _ in db.conversation.calls] == ["find_first"]

    async def test_get_or_create_creates_with_application(self):
        db = FakeDb()

        result = await ConversationRepository(db).get_or_create(
            "user-1", "opp-1", "app-1"
        )

        assert result.id == "new-id"
        _, kwargs = db.conversation.calls[-1]
        assert kwargs["data"] == {
            "user_id": "user-1",
            "opportunity_id": "opp-1",
            "application_id": "app-1",
        }


class TestMessages:
    async def test_add_message_skips_empty_metadata(self):
        db = FakeDb()

        await ConversationRepository(db).add_message(
            "conv-1", role="assistant", content="hi", input_tokens=10
        )

        _, kwargs = db.conversationmessage.calls[0]
        assert kwargs["data"] == {
            "conversation_id": "conv-1",
            "role": "assistant",
            "content": "hi",
            "status": "ok",
            "input_tokens": 10,
        }

    async def test_update_message(self):
        db = FakeDb()

        await ConversationRepository(db).update_message("msg-1", status="blocked")

        _, kwargs = db.conversationmessage.calls[0]
        assert kwargs == {"where": {"id": "msg-1"}, "data": {"status": "blocked"}}

    async def test_recent_messages_are_oldest_first(self):
        newest = SimpleNamespace(id="m2")
        oldest = SimpleNamespace(id="m1")
        db = FakeDb(messages=RecordingTable(find_many=[newest, oldest]))

        result = await ConversationRepository(db).get_recent_messages("conv-1", 20)

        assert [m.id for m in result] == ["m1", "m2"]
        _, kwargs = db.conversationmessage.calls[0]
        assert kwargs["take"] == 20
        assert kwargs["order"] == {"created_at": "desc"}
        assert kwargs["where"]["status"] == {"in": ["ok", "declined"]}

    async def test_list_messages_with_cursor(self):
        db = FakeDb()
        before = datetime(2026, 9, 1, tzinfo=UTC)

        await ConversationRepository(db).list_messages("conv-1", 51, before)

        _, kwargs = db.conversationmessage.calls[0]
        assert kwargs["where"]["created_at"] == {"lt": before}
        assert kwargs["where"]["status"] == {"in": ["ok", "declined", "blocked"]}
        assert kwargs["take"] == 51
