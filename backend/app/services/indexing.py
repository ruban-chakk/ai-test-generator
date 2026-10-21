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
class IndexableArtifact:
    vector_id: str
    entity_type: str
    entity_id: str
    project_id: str
    text: str
    metadata: dict[str, Any]


class IndexingService:
    def __init__(self, language_model: LanguageModel, vector_store: VectorStore) -> None:
        self._language_model = language_model
        self._vector_store = vector_store

    async def index(self, artifact: IndexableArtifact) -> None:
        values = await self._language_model.embed(artifact.text)
        metadata = {
            "entity_type": artifact.entity_type,
            "entity_id": artifact.entity_id,
            "project_id": artifact.project_id,
            "text": artifact.text,
            **artifact.metadata,
        }
        await self._vector_store.upsert(artifact.vector_id, values, metadata)


def build_indexing_service(config: Settings = settings) -> IndexingService:
    return IndexingService(
        language_model=OpenAICompatibleLanguageModel(config),
        vector_store=PineconeVectorStore(config),
    )
