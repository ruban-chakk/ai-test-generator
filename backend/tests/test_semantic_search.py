import asyncio

from app.services.generation import RetrievedContext
from app.services.search import SemanticSearchService


class FakeLanguageModel:
    model = "search-model"

    async def embed(self, text: str) -> list[float]:
        assert text == "expired reset link"
        return [0.1, 0.2]

    async def generate(self, system_prompt: str, user_prompt: str):
        raise AssertionError("search must not call generation")


class FakeVectorStore:
    async def upsert(self, vector_id: str, values: list[float], metadata: dict) -> None:
        raise AssertionError("search must not upsert")

    async def query(self, values: list[float], *, top_k: int, project_id: str | None):
        assert project_id == "project-1"
        assert top_k == 20
        return [
            RetrievedContext(
                id="test_case:1:v1",
                score=0.94,
                text="Reject an expired reset link without changing credentials.",
                metadata={
                    "entity_type": "test_case",
                    "entity_id": "case-1",
                    "project_id": "project-1",
                    "title": "Expired reset link",
                    "status": "approved",
                },
            ),
            RetrievedContext(
                id="feedback:1",
                score=0.85,
                text="Add a boundary case.",
                metadata={"entity_type": "feedback", "entity_id": "feedback-1", "project_id": "project-1"},
            ),
        ]


def test_semantic_search_filters_types_and_removes_project_metadata() -> None:
    service = SemanticSearchService(FakeLanguageModel(), FakeVectorStore())
    results = asyncio.run(
        service.search("expired reset link", project_id="project-1", entity_type="test_case", limit=5)
    )
    assert len(results) == 1
    assert results[0].entity_id == "case-1"
    assert results[0].score == 0.94
    assert "project_id" not in results[0].metadata
