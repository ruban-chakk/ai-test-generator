from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings, settings
from app.services.generation import (
    LanguageModel,
    OpenAICompatibleLanguageModel,
    PineconeVectorStore,
    VectorStore,
)


@dataclass(frozen=True)
class SemanticImpactMatch:
    vector_id: str
    score: float
    text: str
    metadata: dict[str, Any]


class SemanticImpactService:
    def __init__(self, language_model: LanguageModel, vector_store: VectorStore) -> None:
        self._language_model = language_model
        self._vector_store = vector_store

    async def search(
        self,
        source_text: str,
        *,
        project_id: str,
        top_k: int = 100,
    ) -> list[SemanticImpactMatch]:
        embedding = await self._language_model.embed(source_text)
        contexts = await self._vector_store.query(embedding, top_k=top_k, project_id=project_id)
        return [
            SemanticImpactMatch(
                vector_id=context.id,
                score=context.score,
                text=context.text,
                metadata=context.metadata,
            )
            for context in contexts
            if context.metadata.get("entity_type") == "test_case"
            and context.metadata.get("status") == "approved"
        ]


def build_semantic_impact_service(config: Settings = settings) -> SemanticImpactService:
    return SemanticImpactService(
        language_model=OpenAICompatibleLanguageModel(config),
        vector_store=PineconeVectorStore(config),
    )
