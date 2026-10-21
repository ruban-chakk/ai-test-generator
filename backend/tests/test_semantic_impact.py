import asyncio

from app.services.generation import RetrievedContext
from app.schemas import ImpactCandidate
from app.services.impact import SemanticImpactService
from app.api.routes import DEFAULT_IMPACT_SCORING_RULES, _evidence_scores


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


def test_impact_scores_are_evidence_based_and_explainable() -> None:
    candidate = ImpactCandidate(
        test_case_id="11111111-1111-1111-1111-111111111111",
        requirement_id="22222222-2222-2222-2222-222222222222",
        scenario_id="33333333-3333-3333-3333-333333333333",
        title="Reset password",
        status="approved",
        repository_status="indexed",
        similarity=0.8,
        recommended_action="review_update",
        reason="overlap",
        severity="critical",
    )

    coverage, risk, evidence = _evidence_scores(
        [],
        [],
        [candidate],
        change_evidence={"change_magnitude": 0.5},
        rules=DEFAULT_IMPACT_SCORING_RULES,
    )

    assert coverage == 52
    assert risk == 36
    assert evidence["coverage"]["candidate_count"] == 1
    assert evidence["risk"] == {
        "uncovered": 0.0,
        "updates": 14.4,
        "deprecations": 0,
        "critical_severity": 12.0,
        "historical_change": 10.0,
    }
