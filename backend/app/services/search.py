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
class SemanticSearchMatch:
    vector_id: str
    entity_type: str
    entity_id: str
    title: str
    text: str
    score: float
    metadata: dict[str, Any]


class SemanticSearchService:
    def __init__(self, language_model: LanguageModel, vector_store: VectorStore) -> None:
        self._language_model = language_model
        self._vector_store = vector_store

    async def search(
        self,
        query: str,
        *,
        project_id: str,
        entity_type: str | None = None,
        limit: int = 20,
    ) -> list[SemanticSearchMatch]:
        embedding = await self._language_model.embed(query)
        contexts = await self._vector_store.query(
            embedding,
            top_k=min(max(limit * 4, 20), 200),
            project_id=project_id,
        )
        matches: list[SemanticSearchMatch] = []
        for context in contexts:
            metadata = context.metadata
            current_type = str(metadata.get("entity_type") or "")
            current_id = str(metadata.get("entity_id") or metadata.get("requirement_id") or "")
            if not current_type or not current_id or (entity_type and current_type != entity_type):
                continue
            title = str(metadata.get("title") or metadata.get("external_id") or current_type.replace("_", " ").title())
            matches.append(
                SemanticSearchMatch(
                    vector_id=context.id,
                    entity_type=current_type,
                    entity_id=current_id,
                    title=title,
                    text=context.text[:1000],
                    score=context.score,
                    metadata={
                        key: value
                        for key, value in metadata.items()
                        if key not in {"text", "project_id"}
                    },
                )
            )
            if len(matches) >= limit:
                break
        return matches


def build_semantic_search_service(config: Settings = settings) -> SemanticSearchService:
    return SemanticSearchService(
        OpenAICompatibleLanguageModel(config),
        PineconeVectorStore(config),
    )
