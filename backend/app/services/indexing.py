from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable

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
    logical_segments: tuple[str, ...] = ()
    existing_vector_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexedChunk:
    vector_id: str
    chunk_index: int
    chunk_count: int
    content_sha256: str


@dataclass(frozen=True)
class IndexingResult:
    chunks: tuple[IndexedChunk, ...]
    deleted_vector_ids: tuple[str, ...]


def _token_count(text: str) -> int:
    # Provider tokenizers vary. This deterministic approximation keeps the
    # boundary provider-neutral and deliberately below embedding limits.
    return len(re.findall(r"\S+", text))


def _window_text(text: str, *, maximum: int, overlap: int) -> list[str]:
    words = re.findall(r"\S+", text)
    if len(words) <= maximum:
        return [text.strip()] if text.strip() else []
    step = max(1, maximum - overlap)
    return [" ".join(words[start : start + maximum]) for start in range(0, len(words), step)]


def logical_chunks(
    text: str,
    logical_segments: Iterable[str] = (),
    *,
    enabled: bool = True,
    target_tokens: int = 700,
    max_tokens: int = 1000,
    overlap_tokens: int = 80,
) -> tuple[str, ...]:
    """Build stable chunks while preserving supplied semantic boundaries."""

    normalized_text = text.strip()
    if not normalized_text:
        return ()
    maximum = max(64, max_tokens)
    target = min(maximum, max(32, target_tokens))
    overlap = min(max(0, overlap_tokens), target - 1)
    if not enabled or _token_count(normalized_text) <= maximum:
        return (normalized_text,)

    raw_segments = [segment.strip() for segment in logical_segments if segment and segment.strip()]
    if not raw_segments:
        raw_segments = [
            part.strip()
            for part in re.split(r"\n\s*\n|(?m)(?=^#{1,6}\s+)", normalized_text)
            if part.strip()
        ]
    expanded: list[str] = []
    for segment in raw_segments:
        expanded.extend(_window_text(segment, maximum=maximum, overlap=overlap))

    chunks: list[str] = []
    pending: list[str] = []
    pending_tokens = 0
    for segment in expanded:
        size = _token_count(segment)
        if pending and pending_tokens + size > target:
            chunks.append("\n\n".join(pending))
            pending = []
            pending_tokens = 0
        pending.append(segment)
        pending_tokens += size
        if pending_tokens >= target:
            chunks.append("\n\n".join(pending))
            pending = []
            pending_tokens = 0
    if pending:
        chunks.append("\n\n".join(pending))

    # Repeat a compact identity segment so a retrieved child remains useful on
    # its own. Step action/expectation segments stay intact whenever possible.
    identity = raw_segments[0] if raw_segments and _token_count(raw_segments[0]) <= 80 else ""
    if identity and len(chunks) > 1:
        contextualized = [chunks[0]]
        for chunk in chunks[1:]:
            if chunk.startswith(identity):
                contextualized.append(chunk)
                continue
            allowed = maximum - _token_count(identity)
            trimmed = _window_text(chunk, maximum=max(32, allowed), overlap=0)[0]
            contextualized.append(f"{identity}\n\n{trimmed}")
        chunks = contextualized
    return tuple(chunk for chunk in chunks if chunk.strip())


class IndexingService:
    def __init__(
        self,
        language_model: LanguageModel,
        vector_store: VectorStore,
        config: Settings | None = None,
    ) -> None:
        self._language_model = language_model
        self._vector_store = vector_store
        self._config = config or Settings(_env_file=None)

    async def index(self, artifact: IndexableArtifact) -> IndexingResult:
        texts = logical_chunks(
            artifact.text,
            artifact.logical_segments,
            enabled=self._config.vector_chunking_enabled,
            target_tokens=self._config.vector_chunk_target_tokens,
            max_tokens=self._config.vector_chunk_max_tokens,
            overlap_tokens=self._config.vector_chunk_overlap_tokens,
        )
        if not texts:
            raise ValueError("indexable artifact text is empty")
        chunk_count = len(texts)
        indexed: list[IndexedChunk] = []
        desired_ids: set[str] = set()
        for index, chunk_text in enumerate(texts):
            vector_id = artifact.vector_id if index == 0 else f"{artifact.vector_id}:chunk:{index}"
            desired_ids.add(vector_id)
            values = await self._language_model.embed(chunk_text)
            metadata = {
                "entity_type": artifact.entity_type,
                "entity_id": artifact.entity_id,
                "project_id": artifact.project_id,
                "parent_vector_id": artifact.vector_id,
                "chunk_index": index,
                "chunk_count": chunk_count,
                "text": chunk_text,
                **artifact.metadata,
            }
            await self._vector_store.upsert(vector_id, values, metadata)
            indexed.append(
                IndexedChunk(
                    vector_id=vector_id,
                    chunk_index=index,
                    chunk_count=chunk_count,
                    content_sha256=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
                )
            )

        stale_ids = tuple(sorted(set(artifact.existing_vector_ids) - desired_ids))
        if stale_ids:
            await self._vector_store.delete(list(stale_ids))
        return IndexingResult(chunks=tuple(indexed), deleted_vector_ids=stale_ids)


def build_indexing_service(config: Settings = settings) -> IndexingService:
    return IndexingService(
        language_model=OpenAICompatibleLanguageModel(config),
        vector_store=PineconeVectorStore(config),
        config=config,
    )
