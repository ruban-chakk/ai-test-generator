import asyncio
import uuid

from app.api.routes import _enqueue_current_test_case_index


class FakeSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.events = []

    async def scalar(self, _statement):
        return self.existing

    def add(self, event):
        self.events.append(event)


def test_current_case_index_event_is_idempotent_for_existing_key() -> None:
    async def scenario() -> None:
        case = type(
            "Case",
            (),
            {"id": uuid.uuid4(), "version": 1, "status": "superseded"},
        )()
        existing = uuid.uuid4()
        session = FakeSession(existing=existing)

        await _enqueue_current_test_case_index(session, case)

        assert session.events == []

    asyncio.run(scenario())


def test_current_case_index_event_is_created_when_key_is_new() -> None:
    async def scenario() -> None:
        case = type(
            "Case",
            (),
            {"id": uuid.uuid4(), "version": 2, "status": "updated"},
        )()
        session = FakeSession()

        await _enqueue_current_test_case_index(session, case)

        assert len(session.events) == 1
        assert session.events[0].event_key == f"test_case.current_index:{case.id}:v2:updated"

    asyncio.run(scenario())
