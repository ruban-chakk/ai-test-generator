import asyncio
import uuid

from app.services.indexing import IndexableArtifact, IndexingService
from app.services.outbox import FEEDBACK_INDEX_REQUESTED, enqueue_index_event


class FakeLanguageModel:
    model = "embedding-test-model"

    async def embed(self, text: str) -> list[float]:
        assert text == "Feedback asks for an expired-link boundary case."
        return [0.4, 0.5]

    async def generate(self, system_prompt: str, user_prompt: str) -> object:
        raise AssertionError("indexing must not invoke chat generation")


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[float], dict]] = []

    async def upsert(self, vector_id: str, values: list[float], metadata: dict) -> None:
        self.upserts.append((vector_id, values, metadata))

    async def query(self, values: list[float], *, top_k: int, project_id: str | None) -> list:
        raise AssertionError("indexing must not query the vector store")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)


def test_indexing_service_embeds_and_upserts_project_scoped_metadata() -> None:
    vector_store = FakeVectorStore()
    service = IndexingService(FakeLanguageModel(), vector_store)
    artifact = IndexableArtifact(
        vector_id="feedback:1",
        entity_type="feedback",
        entity_id="1",
        project_id="project-1",
        text="Feedback asks for an expired-link boundary case.",
        metadata={"feedback_type": "generate_new"},
    )

    asyncio.run(service.index(artifact))

    assert vector_store.upserts == [
        (
            "feedback:1",
            [0.4, 0.5],
            {
                "entity_type": "feedback",
                "entity_id": "1",
                "project_id": "project-1",
                "text": artifact.text,
                "feedback_type": "generate_new",
            },
        )
    ]


def test_outbox_event_contains_only_stable_identifiers_not_raw_content() -> None:
    session = FakeSession()
    feedback_id = uuid.uuid4()

    event = enqueue_index_event(
        session,  # type: ignore[arg-type]
        event_key=f"feedback.index:{feedback_id}",
        event_type=FEEDBACK_INDEX_REQUESTED,
        aggregate_type="feedback",
        aggregate_id=feedback_id,
    )

    assert session.added == [event]
    assert event.aggregate_id == feedback_id
    assert event.payload == {"schema_version": 1}
    assert "comment" not in event.payload
