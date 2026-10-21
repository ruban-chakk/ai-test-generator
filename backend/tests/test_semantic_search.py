import asyncio

from app.services.generation import RetrievedContext
from app.services.search import SearchMatch, SemanticSearchService, fuse_search_matches


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
    assert results[0].semantic_score == 0.94
    assert "project_id" not in results[0].metadata


def test_hybrid_search_fuses_rankings_and_preserves_component_evidence() -> None:
    semantic = [
        SearchMatch("vector-a", "requirement", "a", "Semantic first", "A", 0.95, {}, semantic_score=0.95),
        SearchMatch("vector-b", "requirement", "b", "Shared", "B", 0.80, {}, semantic_score=0.80),
    ]
    keyword = [
        SearchMatch(
            "vector-b",
            "requirement",
            "b",
            "Shared current title",
            "B current",
            0.90,
            {"external_id": "REQ-42"},
            keyword_score=0.90,
            matched_fields=("external ID",),
        ),
        SearchMatch("vector-c", "test_case", "c", "Keyword second", "C", 0.70, {}, keyword_score=0.70),
    ]

    results = fuse_search_matches(semantic, keyword, limit=3)

    assert [result.entity_id for result in results] == ["b", "a", "c"]
    assert results[0].semantic_score == 0.80
    assert results[0].keyword_score == 0.90
    assert results[0].matched_fields == ("external ID",)
    assert results[0].title == "Shared current title"
