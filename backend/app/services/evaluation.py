from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import Settings, settings
from app.services.generation import (
    OpenAICompatibleLanguageModel,
    PineconeVectorStore,
    GenerationProviderError,
    RetrievedContext,
    rerank_generation_contexts,
)
from app.services.prompts import DEFAULT_PROMPTS, IMMUTABLE_GUARDRAIL, PromptTemplate, render_prompt


class JudgeScores(BaseModel):
    requirement_coverage: int = Field(ge=0, le=100)
    grounding: int = Field(ge=0, le=100)
    correctness: int = Field(ge=0, le=100)
    completeness: int = Field(ge=0, le=100)
    relevance: int = Field(ge=0, le=100)
    hallucination_rate: int = Field(ge=0, le=100)
    executability: int = Field(ge=0, le=100)
    boundary_and_negative_coverage: int = Field(ge=0, le=100)
    traceability: int = Field(ge=0, le=100)


class JudgeJustifications(BaseModel):
    requirement_coverage: str = Field(min_length=1)
    grounding: str = Field(min_length=1)
    correctness: str = Field(min_length=1)
    completeness: str = Field(min_length=1)
    relevance: str = Field(min_length=1)
    hallucination_rate: str = Field(min_length=1)
    executability: str = Field(min_length=1)
    boundary_and_negative_coverage: str = Field(min_length=1)
    traceability: str = Field(min_length=1)


class JudgeIssue(BaseModel):
    criterion: str = Field(min_length=1)
    severity: Literal["warning", "error"]
    message: str = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)


class JudgeResult(BaseModel):
    score: int = Field(ge=0, le=100)
    status: Literal["passed", "failed"]
    scores: JudgeScores
    justifications: JudgeJustifications
    issues: list[JudgeIssue] = Field(default_factory=list)
    summary: str = Field(min_length=1)


@dataclass(frozen=True)
class EvaluationResult:
    judgment: JudgeResult
    retrieved_context: list[RetrievedContext]
    model: str
    rubric_version: str
    input_tokens: int = 0
    output_tokens: int = 0


class TestCaseEvaluationService:
    __test__ = False

    def __init__(
        self,
        config: Settings = settings,
        language_model: OpenAICompatibleLanguageModel | None = None,
        vector_store: PineconeVectorStore | None = None,
        prompt_templates: dict[str, PromptTemplate] | None = None,
    ) -> None:
        self._config = config
        self._language_model = language_model or OpenAICompatibleLanguageModel(config)
        self._vector_store = vector_store or PineconeVectorStore(config)
        self._prompt_templates = {**DEFAULT_PROMPTS, **(prompt_templates or {})}

    async def evaluate(
        self,
        *,
        project_id: str,
        requirement_text: str,
        scenario_text: str,
        test_case_text: str,
        keyword_contexts: list[RetrievedContext] | None = None,
    ) -> EvaluationResult:
        query = (
            f"Requirement:\n{requirement_text}\n\nScenario:\n{scenario_text}\n\n"
            f"Candidate test case:\n{test_case_text}"
        )
        embedding = await self._language_model.embed(query)
        semantic_contexts = await self._vector_store.query(
            embedding,
            top_k=self._config.rag_candidate_limit,
            project_id=project_id,
        )
        contexts = rerank_generation_contexts(
            query,
            semantic_contexts,
            keyword_contexts,
            limit=self._config.rag_context_limit,
            semantic_weight=self._config.rag_semantic_weight,
            keyword_weight=self._config.rag_keyword_weight,
            source_weight=self._config.rag_source_weight,
        )
        evidence = "\n\n".join(
            f"[E{index}; vector_id={item.id}; score={item.score:.3f}]\n{item.text}"
            for index, item in enumerate(contexts, start=1)
        ) or "No retrieved project evidence."
        prompt = self._prompt_templates["test_case_evaluation"]
        system_prompt = f"{IMMUTABLE_GUARDRAIL}\n\n{prompt.system_template}"
        user_prompt = render_prompt(
            prompt.user_template,
            {
                "rubric_version": self._config.eval_rubric_version,
                "requirement_text": requirement_text,
                "scenario_text": scenario_text,
                "test_case_text": test_case_text,
                "evidence": evidence,
            },
        )
        model = self._config.eval_llm_model.strip() or self._config.llm_model
        judgment = await self._language_model.generate_structured(
            system_prompt,
            user_prompt,
            JudgeResult,
            schema_name="test_case_evaluation",
            temperature=prompt.temperature if prompt.temperature is not None else 0.0,
            model=model,
        )
        if contexts and self._config.eval_require_citations:
            valid_refs = {f"E{index}" for index in range(1, len(contexts) + 1)}
            for issue in judgment.issues:
                # Evidence citations are required when an issue relies on
                # retrieved project context, but issues can also be grounded
                # directly in the requirement or candidate test case.  The
                # prompt explicitly allows an empty list for those issues;
                # reject only references that are present but invalid.
                if issue.evidence_refs and not set(issue.evidence_refs).issubset(valid_refs):
                    raise GenerationProviderError(
                        "LLM judge returned an issue with invalid evidence citations"
                    )
        server_status = "passed" if judgment.score >= self._config.eval_pass_score else "failed"
        judgment = judgment.model_copy(update={"status": server_status})
        input_tokens, output_tokens = getattr(self._language_model, "consume_usage", lambda: (0, 0))()
        return EvaluationResult(
            judgment=judgment,
            retrieved_context=contexts,
            model=model,
            rubric_version=self._config.eval_rubric_version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def build_test_case_evaluation_service(
    config: Settings = settings,
    prompt_templates: dict[str, PromptTemplate] | None = None,
) -> TestCaseEvaluationService:
    return TestCaseEvaluationService(config=config, prompt_templates=prompt_templates)
