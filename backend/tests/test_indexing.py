import asyncio
import uuid

from app.core.config import Settings
from app.services.indexing import IndexableArtifact, IndexingService, logical_chunks
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
        self.deletes: list[list[str]] = []

    async def upsert(self, vector_id: str, values: list[float], metadata: dict) -> None:
        self.upserts.append((vector_id, values, metadata))

    async def delete(self, vector_ids: list[str]) -> None:
        self.deletes.append(vector_ids)

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
                "parent_vector_id": "feedback:1",
                "chunk_index": 0,
                "chunk_count": 1,
                "text": artifact.text,
                "feedback_type": "generate_new",
            },
        )
    ]


def test_logical_chunking_preserves_segments_and_removes_stale_children() -> None:
    class ChunkLanguageModel:
        model = "embedding-test-model"

        async def embed(self, text: str) -> list[float]:
            return [float(len(text))]

        async def generate(self, system_prompt: str, user_prompt: str) -> object:
            raise AssertionError("indexing must not invoke generation")

    segments = (
        "Test case: TC-1 — Reset a password",
        "Step 1: " + "open reset link " * 18 + "\nExpected: form is displayed",
        "Step 2: " + "submit a new password " * 18 + "\nExpected: password is changed",
    )
    text = "\n\n".join(segments)
    chunks = logical_chunks(text, segments, target_tokens=35, max_tokens=55, overlap_tokens=5)
    assert len(chunks) >= 2
    assert all("Test case: TC-1" in chunk for chunk in chunks)
    assert any("Expected:" in chunk for chunk in chunks)

    vector_store = FakeVectorStore()
    service = IndexingService(
        ChunkLanguageModel(),
        vector_store,
        Settings(
            _env_file=None,
            vector_chunking_enabled=True,
            vector_chunk_target_tokens=35,
            vector_chunk_max_tokens=55,
            vector_chunk_overlap_tokens=5,
        ),
    )
    artifact = IndexableArtifact(
        vector_id="test_case:1:v2",
        entity_type="test_case",
        entity_id=str(uuid.uuid4()),
        project_id=str(uuid.uuid4()),
        text=text,
        logical_segments=segments,
        existing_vector_ids=("test_case:1:v2", "test_case:1:v2:chunk:99"),
        metadata={"version": 2},
    )

    result = asyncio.run(service.index(artifact))

    assert result.chunks[0].vector_id == "test_case:1:v2"
    assert len(result.chunks) == len(chunks)
    assert vector_store.deletes == [["test_case:1:v2:chunk:99"]]
    assert all(item[2]["chunk_count"] == len(chunks) for item in vector_store.upserts)


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
