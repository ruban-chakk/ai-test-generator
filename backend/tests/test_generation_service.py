import asyncio

import pytest

from app.core.config import Settings
from app.services.generation import (
    GeneratedDraft,
    GeneratedScenario,
    GeneratedStep,
    GeneratedTestCase,
    GenerationConfigurationError,
    GenerationService,
    RetrievedContext,
    build_generation_service,
)


class FakeLanguageModel:
    model = "test-model"

    def __init__(self) -> None:
        self.generated_prompts: list[tuple[str, str]] = []

    async def embed(self, text: str) -> list[float]:
        assert "Password reset" in text
        return [0.1, 0.2, 0.3]

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedDraft:
        self.generated_prompts.append((system_prompt, user_prompt))
        return GeneratedDraft(
            scenarios=[
                GeneratedScenario(
                    title="Reset an active account password",
                    description="Validate the supported password reset workflow.",
                    priority="high",
                    severity="major",
                    category="functional",
                    type="regression",
                    test_cases=[
                        GeneratedTestCase(
                            title="Reset with a valid one-time link",
                            description="A user resets a password with an unexpired link.",
                            prerequisite="An active account and reset link exist.",
                            priority="high",
                            severity="major",
                            category="functional",
                            type="positive",
                            steps=[
                                GeneratedStep(
                                    step_number=1,
                                    action="Open the unexpired password reset link.",
                                    expected_result="The password reset form is displayed.",
                                )
                            ],
                        )
                    ],
                )
            ]
        )


class FakeVectorStore:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[float], dict]] = []

    async def upsert(self, vector_id: str, values: list[float], metadata: dict) -> None:
        self.upserts.append((vector_id, values, metadata))

    async def query(
        self,
        values: list[float],
        *,
        top_k: int,
        project_id: str | None,
    ) -> list[RetrievedContext]:
        assert values == [0.1, 0.2, 0.3]
        assert top_k == 8
        assert project_id == "project-1"
        return [
            RetrievedContext(
                id="test-case:historical-1",
                score=0.91,
                text="Approved reset-link expiry coverage",
                metadata={"entity_type": "test_case"},
            )
        ]


def test_generation_service_embeds_retrieves_and_generates_structured_draft() -> None:
    language_model = FakeLanguageModel()
    vector_store = FakeVectorStore()
    service = GenerationService(language_model, vector_store)

    result = asyncio.run(
        service.generate(
            requirement_id="requirement-1",
            project_id="project-1",
            title="Password reset",
            description="A user must be able to reset a forgotten password.",
            external_id="AUTH-42",
        )
    )

    assert result.requirement_vector_id == "requirement:requirement-1"
    assert result.model == "test-model"
    assert result.draft.scenarios[0].test_cases[0].steps[0].step_number == 1
    assert vector_store.upserts[0][2]["project_id"] == "project-1"
    system_prompt, user_prompt = language_model.generated_prompts[0]
    assert "untrusted data" in system_prompt
    assert "Approved reset-link expiry coverage" in user_prompt


def test_generated_test_case_rejects_non_contiguous_steps() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        GeneratedTestCase(
            title="Validate reset link",
            description="Validate the reset link behavior.",
            priority="high",
            severity="major",
            category="functional",
            type="negative",
            steps=[
                GeneratedStep(
                    step_number=2,
                    action="Open an expired password reset link.",
                    expected_result="The link is rejected as expired.",
                )
            ],
        )


def test_feedback_generation_retrieves_context_without_overwriting_requirement_vector() -> None:
    language_model = FakeLanguageModel()
    vector_store = FakeVectorStore()
    service = GenerationService(language_model, vector_store)

    result = asyncio.run(
        service.generate_from_feedback(
            requirement_id="requirement-1",
            project_id="project-1",
            title="Password reset",
            description="A user must be able to reset a forgotten password.",
            external_id="AUTH-42",
            feedback_text="Add an expired-link boundary case.",
            target_context="Existing happy-path reset case.",
            action="revise",
        )
    )

    assert result.requirement_vector_id == "requirement:requirement-1"
    assert vector_store.upserts == []
    system_prompt, user_prompt = language_model.generated_prompts[0]
    assert "untrusted data" in system_prompt
    assert "Add an expired-link boundary case." in user_prompt
    assert "Approved reset-link expiry coverage" in user_prompt


def test_generation_service_fails_closed_without_provider_credentials() -> None:
    config = Settings(
        _env_file=None,
        llm_api_key="",
        pinecone_api_key="",
        pinecone_host="",
    )

    with pytest.raises(GenerationConfigurationError, match="LLM_API_KEY"):
        build_generation_service(config)
