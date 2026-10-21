import asyncio

from app.services.generation import RetrievedContext
from app.services.impact import SemanticImpactService


class FakeLanguageModel:
    model = "embedding-test-model"

    async def embed(self, text: str) -> list[float]:
        assert "reset password" in text.lower()
        return [0.2, 0.8]

    async def generate(self, system_prompt: str, user_prompt: str) -> object:
        raise AssertionError("semantic search must not call chat generation")


class FakeVectorStore:
    async def upsert(self, vector_id: str, values: list[float], metadata: dict) -> None:
        raise AssertionError("impact search must not upsert")

    async def query(
        self,
        values: list[float],
        *,
        top_k: int,
        project_id: str | None,
    ) -> list[RetrievedContext]:
        assert values == [0.2, 0.8]
        assert top_k == 100
        assert project_id == "project-1"
        return [
            RetrievedContext(
                id="test_case:approved",
                score=0.91,
                text="Approved reset-password coverage",
                metadata={"entity_type": "test_case", "status": "approved"},
            ),
            RetrievedContext(
                id="feedback:ignored",
                score=0.99,
                text="Feedback context",
                metadata={"entity_type": "feedback", "status": "open"},
            ),
            RetrievedContext(
                id="test_case:draft",
                score=0.95,
                text="Draft coverage",
                metadata={"entity_type": "test_case", "status": "draft"},
            ),
        ]


def test_semantic_impact_search_returns_only_approved_project_cases() -> None:
    service = SemanticImpactService(FakeLanguageModel(), FakeVectorStore())

    matches = asyncio.run(
        service.search(
            "Users can reset passwords with an expiring link.",
            project_id="project-1",
        )
    )

    assert [match.vector_id for match in matches] == ["test_case:approved"]
    assert matches[0].score == 0.91
