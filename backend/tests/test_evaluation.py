import asyncio

from app.core.config import Settings
from app.services.evaluation import JudgeResult, TestCaseEvaluationService
from app.services.generation import RetrievedContext, _strict_json_schema


class FakeLanguageModel:
    model = "generation-model"

    def __init__(self) -> None:
        self.requested_model: str | None = None
        self.system_prompt = ""
        self.user_prompt = ""

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2]

    async def generate_structured(self, system_prompt, user_prompt, response_model, **kwargs):
        self.requested_model = kwargs["model"]
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return response_model.model_validate(
            {
                "score": 92,
                "status": "passed",
                "scores": {
                    "requirement_coverage": 95,
                    "grounding": 95,
                    "correctness": 94,
                    "completeness": 90,
                    "relevance": 96,
                    "hallucination_rate": 4,
                    "executability": 90,
                    "boundary_and_negative_coverage": 88,
                    "traceability": 92,
                },
                "justifications": {
                    "requirement_coverage": "The candidate covers the requested approval behavior.",
                    "grounding": "The expected result is supported by retrieved evidence.",
                    "correctness": "The expected behavior is consistent with the requirement.",
                    "completeness": "The material approval path is covered.",
                    "relevance": "Every step serves the refund approval scenario.",
                    "hallucination_rate": "Only supported requirement facts are asserted.",
                    "executability": "The action and expected result are directly testable.",
                    "boundary_and_negative_coverage": "The approval threshold boundary is exercised.",
                    "traceability": "The candidate maps to the stated refund requirement.",
                },
                "issues": [],
                "summary": "The case is grounded and executable.",
            }
        )


class FakeVectorStore:
    async def query(self, values, *, top_k, project_id):
        return [
            RetrievedContext(
                id="knowledge_document:doc-1",
                score=0.91,
                text="Refunds above the approval threshold require manager authorization.",
                metadata={
                    "entity_type": "knowledge_document",
                    "entity_id": "doc-1",
                    "parent_vector_id": "knowledge_document:doc-1",
                },
            )
        ]


def test_judge_schema_uses_fixed_strict_justification_fields() -> None:
    schema = _strict_json_schema(JudgeResult.model_json_schema())
    justification_schema = schema["$defs"]["JudgeJustifications"]

    assert justification_schema["additionalProperties"] is False
    assert set(justification_schema["required"]) == {
        "requirement_coverage",
        "grounding",
        "correctness",
        "completeness",
        "relevance",
        "hallucination_rate",
        "executability",
        "boundary_and_negative_coverage",
        "traceability",
    }


def test_judge_accepts_weighted_overall_score() -> None:
    # The API applies the configured weighted rubric after parsing. The LLM's
    # overall score therefore must not be rejected because it differs from a
    # naive arithmetic mean of the individual criteria.
    payload = {
        "score": 40,
        "status": "failed",
        "scores": {
            "requirement_coverage": 90,
            "grounding": 90,
            "correctness": 90,
            "completeness": 90,
            "relevance": 90,
            "hallucination_rate": 0,
            "executability": 90,
            "boundary_and_negative_coverage": 90,
            "traceability": 90,
        },
        "justifications": {
            criterion: "Evidence-based justification."
            for criterion in (
                "requirement_coverage",
                "grounding",
                "correctness",
                "completeness",
                "relevance",
                "hallucination_rate",
                "executability",
                "boundary_and_negative_coverage",
                "traceability",
            )
        },
        "issues": [],
        "summary": "The weighted rubric determines the final score.",
    }
    result = JudgeResult.model_validate(payload)
    assert result.score == 40


def test_llm_judge_uses_separate_model_and_retrieved_evidence() -> None:
    async def scenario() -> None:
        model = FakeLanguageModel()
        config = Settings(
            _env_file=None,
            llm_api_key="test-key",
            llm_model="generation-model",
            eval_llm_model="judge-model",
            eval_pass_score=80,
        )
        service = TestCaseEvaluationService(
            config=config,
            language_model=model,
            vector_store=FakeVectorStore(),
        )
        result = await service.evaluate(
            project_id="project-1",
            requirement_text="Managers approve large refunds.",
            scenario_text="Refund approval",
            test_case_text="Submit a large refund and verify manager authorization.",
        )

        assert isinstance(result.judgment, JudgeResult)
        assert result.judgment.status == "passed"
        assert result.model == "judge-model"
        assert model.requested_model == "judge-model"
        assert "integer percentage from 0 to 100" in model.system_prompt
        assert "knowledge_document:doc-1" in model.user_prompt

    asyncio.run(scenario())


def test_llm_judge_allows_requirement_grounded_issue_without_retrieved_citation() -> None:
    class RequirementGroundedIssueModel(FakeLanguageModel):
        async def generate_structured(self, system_prompt, user_prompt, response_model, **kwargs):
            return response_model.model_validate(
                {
                    "score": 72,
                    "status": "failed",
                    "scores": {
                        criterion: 72
                        for criterion in (
                            "requirement_coverage",
                            "grounding",
                            "correctness",
                            "completeness",
                            "relevance",
                            "hallucination_rate",
                            "executability",
                            "boundary_and_negative_coverage",
                            "traceability",
                        )
                    },
                    "justifications": {
                        criterion: "The requirement directly supports this assessment."
                        for criterion in (
                            "requirement_coverage",
                            "grounding",
                            "correctness",
                            "completeness",
                            "relevance",
                            "hallucination_rate",
                            "executability",
                            "boundary_and_negative_coverage",
                            "traceability",
                        )
                    },
                    "issues": [{
                        "criterion": "completeness",
                        "severity": "warning",
                        "message": "The candidate does not cover the required recovery path.",
                        "evidence_refs": [],
                    }],
                    "summary": "The candidate is missing a requirement-defined path.",
                }
            )

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            llm_api_key="test-key",
            llm_model="generation-model",
            eval_llm_model="judge-model",
            eval_pass_score=80,
            eval_require_citations=True,
        )
        result = await TestCaseEvaluationService(
            config=config,
            language_model=RequirementGroundedIssueModel(),
            vector_store=FakeVectorStore(),
        ).evaluate(
            project_id="project-1",
            requirement_text="The workflow must support recovery after a failed approval.",
            scenario_text="Approval recovery",
            test_case_text="Submit a refund and verify approval.",
        )
        assert result.judgment.issues[0].evidence_refs == []

    asyncio.run(scenario())
