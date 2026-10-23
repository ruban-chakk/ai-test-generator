from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError, model_validator

from app.core.config import Settings, settings
from app.services.prompts import DEFAULT_PROMPTS, IMMUTABLE_GUARDRAIL, PromptTemplate, render_prompt


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


class GenerationConfigurationError(RuntimeError):
    """Raised when generation dependencies have not been configured."""


class GenerationProviderError(RuntimeError):
    """Raised when a configured external provider cannot complete a request."""


def _strict_json_schema(value: Any) -> Any:
    """Normalize Pydantic JSON Schema for OpenAI strict structured outputs."""

    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: _strict_json_schema(item) for key, item in value.items()}
    if normalized.get("type") == "object" or "properties" in normalized:
        properties = normalized.get("properties") or {}
        normalized["additionalProperties"] = False
        normalized["required"] = list(properties)
    return normalized


class GeneratedStep(BaseModel):
    step_number: int = Field(ge=1)
    action: str = Field(min_length=8)
    expected_result: str = Field(min_length=8)


class GeneratedTestCase(BaseModel):
    title: str = Field(min_length=5)
    description: str = Field(min_length=12)
    prerequisite: str | None = None
    priority: Literal["low", "medium", "high", "critical"]
    severity: Literal["minor", "major", "critical"]
    category: str
    type: str
    steps: list[GeneratedStep] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_step_numbers(self) -> "GeneratedTestCase":
        numbers = [step.step_number for step in self.steps]
        if len(numbers) != len(set(numbers)):
            raise ValueError("test case step numbers must be unique")
        if sorted(numbers) != list(range(1, len(numbers) + 1)):
            raise ValueError("test case step numbers must be contiguous starting at 1")
        return self


class GeneratedScenario(BaseModel):
    title: str = Field(min_length=5)
    description: str = Field(min_length=12)
    priority: Literal["low", "medium", "high", "critical"]
    severity: Literal["minor", "major", "critical"]
    category: str
    type: str
    test_cases: list[GeneratedTestCase] = Field(min_length=1)


class GeneratedDraft(BaseModel):
    scenarios: list[GeneratedScenario] = Field(min_length=1)


@dataclass(frozen=True)
class RetrievedContext:
    id: str
    score: float
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class GenerationResult:
    draft: GeneratedDraft
    requirement_vector_id: str
    retrieved_context: list[RetrievedContext]
    model: str
    retrieval_mode: str = "hybrid"
    input_tokens: int = 0
    output_tokens: int = 0


def _retrieval_key(context: RetrievedContext) -> tuple[str, str]:
    metadata = context.metadata
    entity_type = str(metadata.get("entity_type") or "unknown")
    entity_id = str(
        metadata.get("entity_id")
        or metadata.get("test_case_id")
        or metadata.get("requirement_id")
        or metadata.get("target_id")
        or metadata.get("parent_vector_id")
        or context.id
    )
    return entity_type, entity_id


def rerank_generation_contexts(
    query: str,
    semantic_contexts: list[RetrievedContext],
    keyword_contexts: list[RetrievedContext] | None = None,
    *,
    exclude_parent_vector_id: str | None = None,
    limit: int = 8,
    semantic_weight: float = 0.65,
    keyword_weight: float = 0.25,
    source_weight: float = 0.10,
) -> list[RetrievedContext]:
    """Fuse retrieval evidence, weight trusted artifact types, and collapse chunks."""

    query_tokens = set(re.findall(r"[a-z0-9_./:-]+", query.lower()))
    source_priority = {
        "test_case": 1.0,
        "knowledge_document": 0.9,
        "requirement": 0.8,
        "feedback": 0.6,
    }
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for source, contexts in (("semantic", semantic_contexts), ("keyword", keyword_contexts or [])):
        for context in contexts:
            parent_id = str(context.metadata.get("parent_vector_id") or context.id)
            if exclude_parent_vector_id and parent_id == exclude_parent_vector_id:
                continue
            key = _retrieval_key(context)
            group = groups.setdefault(
                key,
                {"semantic": 0.0, "keyword": 0.0, "contexts": [], "metadata": {}},
            )
            score = max(0.0, min(1.0, float(context.score)))
            group[source] = max(group[source], score)
            group["contexts"].append(context)
            group["metadata"].update(context.metadata)

    ranked: list[tuple[float, RetrievedContext]] = []
    for (entity_type, entity_id), group in groups.items():
        candidates = sorted(group["contexts"], key=lambda item: item.score, reverse=True)
        unique_text: list[str] = []
        chunk_ids: list[str] = []
        for candidate in candidates:
            if candidate.text not in unique_text:
                unique_text.append(candidate.text)
                chunk_ids.append(candidate.id)
            if len(unique_text) == 2:
                break
        combined_text = "\n\n".join(unique_text)[:6000]
        text_tokens = set(re.findall(r"[a-z0-9_./:-]+", combined_text.lower()))
        lexical_overlap = len(query_tokens & text_tokens) / max(1, len(query_tokens))
        semantic_score = float(group["semantic"])
        keyword_score = max(float(group["keyword"]), lexical_overlap)
        weighted_source = source_priority.get(entity_type, 0.5)
        score = (
            semantic_weight * semantic_score
            + keyword_weight * keyword_score
            + source_weight * weighted_source
        )
        metadata = {
            **group["metadata"],
            "entity_type": entity_type,
            "entity_id": entity_id,
            "semantic_score": round(semantic_score, 4),
            "keyword_score": round(keyword_score, 4),
            "source_weight": weighted_source,
            "matched_chunk_ids": chunk_ids,
            "retrieval_mode": "hybrid",
        }
        ranked.append(
            (
                score,
                RetrievedContext(
                    id=str(metadata.get("parent_vector_id") or candidates[0].id),
                    score=round(score, 4),
                    text=combined_text,
                    metadata=metadata,
                ),
            )
        )
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    return [context for _, context in ranked[:limit]]


def _approved_test_case_contexts(
    contexts: list[RetrievedContext],
) -> list[RetrievedContext]:
    """Keep non-test evidence, but fail closed for unapproved test cases."""

    return [
        context
        for context in contexts
        if str(context.metadata.get("entity_type") or "") != "test_case"
        or str(context.metadata.get("status") or "").lower() == "approved"
    ]


class LanguageModel(Protocol):
    model: str

    async def embed(self, text: str) -> list[float]: ...

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedDraft: ...


class VectorStore(Protocol):
    async def upsert(self, vector_id: str, values: list[float], metadata: dict[str, Any]) -> None: ...

    async def delete(self, vector_ids: list[str]) -> None: ...

    async def query(
        self,
        values: list[float],
        *,
        top_k: int,
        project_id: str | None,
    ) -> list[RetrievedContext]: ...


class OpenAICompatibleLanguageModel:
    def __init__(self, config: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.llm_api_key:
            raise GenerationConfigurationError("LLM_API_KEY is required for test-case generation")
        self.model = config.llm_model
        self._embedding_model = config.embedding_model
        self._api_key = config.llm_api_key
        self._base_url = config.llm_base_url.rstrip("/")
        self._timeout = config.provider_timeout_seconds
        self._max_attempts = max(1, config.provider_max_attempts)
        self._client = client
        self._input_tokens = 0
        self._output_tokens = 0

    def consume_usage(self) -> tuple[int, int]:
        usage = (self._input_tokens, self._output_tokens)
        self._input_tokens = 0
        self._output_tokens = 0
        return usage

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            for attempt in range(1, self._max_attempts + 1):
                try:
                    response = await client.post(f"{self._base_url}{path}", headers=headers, json=payload)
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < self._max_attempts:
                            await asyncio.sleep(min(2 ** (attempt - 1), 4))
                            continue
                    response.raise_for_status()
                    response_payload = response.json()
                    usage = response_payload.get("usage") if isinstance(response_payload, dict) else None
                    if isinstance(usage, dict):
                        self._input_tokens += int(usage.get("prompt_tokens") or usage.get("input_tokens") or usage.get("total_tokens") or 0)
                        self._output_tokens += int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
                    return response_payload
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= self._max_attempts:
                        raise GenerationProviderError(f"LLM provider request failed after {attempt} attempts") from exc
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                except httpx.HTTPStatusError as exc:
                    raise GenerationProviderError(
                        f"LLM provider returned HTTP {exc.response.status_code}"
                    ) from exc
        finally:
            if owns_client:
                await client.aclose()
        raise GenerationProviderError("LLM provider request did not complete")

    async def embed(self, text: str) -> list[float]:
        payload = await self._post(
            "/embeddings",
            {"model": self._embedding_model, "input": text},
        )
        try:
            values = payload["data"][0]["embedding"]
            return [float(value) for value in values]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationProviderError("Embedding provider returned an invalid response") from exc

    async def generate(self, system_prompt: str, user_prompt: str) -> GeneratedDraft:
        return await self.generate_structured(
            system_prompt,
            user_prompt,
            GeneratedDraft,
            schema_name="generated_test_draft",
            temperature=0.2,
        )

    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredModel],
        *,
        schema_name: str,
        temperature: float = 0.0,
        model: str | None = None,
    ) -> StructuredModel:
        schema = _strict_json_schema(response_model.model_json_schema())
        payload = await self._post(
            "/chat/completions",
            {
                "model": model or self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
            },
        )
        try:
            content = payload["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
            return response_model.model_validate(parsed)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise GenerationProviderError("LLM provider returned an invalid structured response") from exc


class PineconeVectorStore:
    def __init__(self, config: Settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.pinecone_api_key or not config.pinecone_host:
            raise GenerationConfigurationError(
                "PINECONE_API_KEY and PINECONE_HOST are required for RAG generation"
            )
        self._api_key = config.pinecone_api_key
        self._host = config.pinecone_host.rstrip("/")
        self._namespace = config.pinecone_namespace
        self._timeout = config.provider_timeout_seconds
        self._client = client

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.post(
                f"{self._host}{path}",
                headers={"Api-Key": self._api_key, "Content-Type": "application/json"},
                json=payload,
            )
            if not response.is_success:
                provider_message = response.text.lower()
                if response.status_code == 400 and "document schema" in provider_message:
                    raise GenerationConfigurationError(
                        "The configured Pinecone index uses a document schema. "
                        "Create a bring-your-own-vectors index without integrated embedding for this application."
                    )
                if response.status_code == 400 and "dimension" in provider_message:
                    raise GenerationConfigurationError(
                        "The configured Pinecone index dimension does not match the embedding model output."
                    )
            response.raise_for_status()
            return response.json() if response.content else {}
        except GenerationConfigurationError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise GenerationProviderError("Pinecone request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            response = await client.get(
                f"{self._host}{path}",
                headers={"Api-Key": self._api_key, "Content-Type": "application/json"},
                params=params,
            )
            response.raise_for_status()
            return response.json() if response.content else {}
        except (httpx.HTTPError, ValueError) as exc:
            raise GenerationProviderError("Pinecone request failed") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def upsert(self, vector_id: str, values: list[float], metadata: dict[str, Any]) -> None:
        await self._post(
            "/vectors/upsert",
            {
                "namespace": self._namespace,
                "vectors": [{"id": vector_id, "values": values, "metadata": metadata}],
            },
        )

    async def delete(self, vector_ids: list[str]) -> None:
        if not vector_ids:
            return
        await self._post(
            "/vectors/delete",
            {"namespace": self._namespace, "ids": vector_ids},
        )

    async def list_vector_ids(self, *, page_size: int = 100) -> list[str]:
        vector_ids: list[str] = []
        token: str | None = None
        while True:
            params: dict[str, Any] = {
                "namespace": self._namespace,
                "limit": min(max(1, page_size), 100),
            }
            if token:
                params["paginationToken"] = token
            payload = await self._get("/vectors/list", params)
            for item in payload.get("vectors", []):
                if isinstance(item, dict) and item.get("id"):
                    vector_ids.append(str(item["id"]))
            pagination = payload.get("pagination") or {}
            token = pagination.get("next") if isinstance(pagination, dict) else None
            if not token:
                return vector_ids

    async def describe_stats(self) -> dict[str, Any]:
        return await self._post("/describe_index_stats", {"filter": {}})

    async def query(
        self,
        values: list[float],
        *,
        top_k: int,
        project_id: str | None,
    ) -> list[RetrievedContext]:
        payload: dict[str, Any] = {
            "namespace": self._namespace,
            "vector": values,
            "topK": top_k,
            "includeMetadata": True,
        }
        if project_id:
            payload["filter"] = {"project_id": {"$eq": project_id}}
        result = await self._post("/query", payload)
        contexts: list[RetrievedContext] = []
        for match in result.get("matches", []):
            metadata = match.get("metadata") or {}
            text = metadata.get("text")
            if isinstance(text, str) and text.strip():
                contexts.append(
                    RetrievedContext(
                        id=str(match.get("id", "")),
                        score=float(match.get("score", 0.0)),
                        text=text,
                        metadata=metadata,
                    )
                )
        return contexts


class GenerationService:
    def __init__(
        self,
        language_model: LanguageModel,
        vector_store: VectorStore,
        config: Settings | None = None,
        prompt_templates: dict[str, PromptTemplate] | None = None,
    ) -> None:
        self._language_model = language_model
        self._vector_store = vector_store
        self._config = config or Settings(_env_file=None)
        self._prompt_templates = {**DEFAULT_PROMPTS, **(prompt_templates or {})}

    async def generate(
        self,
        *,
        requirement_id: str,
        project_id: str | None,
        title: str,
        description: str,
        external_id: str | None,
        requirement_version: int = 1,
        keyword_contexts: list[RetrievedContext] | None = None,
    ) -> GenerationResult:
        source_text = f"Title: {title}\nDescription: {description}"
        embedding = await self._language_model.embed(source_text)
        vector_id = f"requirement:{requirement_id}:v{requirement_version}"
        semantic_contexts = await self._vector_store.query(
            embedding,
            top_k=self._config.rag_candidate_limit,
            project_id=project_id,
        )
        semantic_contexts = _approved_test_case_contexts(semantic_contexts)
        keyword_contexts = _approved_test_case_contexts(keyword_contexts or [])
        contexts = rerank_generation_contexts(
            source_text,
            semantic_contexts,
            keyword_contexts,
            exclude_parent_vector_id=vector_id,
            limit=self._config.rag_context_limit,
            semantic_weight=self._config.rag_semantic_weight,
            keyword_weight=self._config.rag_keyword_weight,
            source_weight=self._config.rag_source_weight,
        )
        context_text = "\n\n".join(
            f"[Historical context {index + 1}; score={item.score:.3f}]\n{item.text}"
            for index, item in enumerate(contexts)
            if item.id != vector_id
        ) or "No relevant historical context was retrieved."
        prompt = self._prompt_templates["test_case_generation"]
        values = {"external_id": external_id or "none", "source_text": source_text, "context_text": context_text}
        system_prompt = f"{IMMUTABLE_GUARDRAIL}\n\n{prompt.system_template}"
        user_prompt = render_prompt(prompt.user_template, values)
        draft = await self._language_model.generate(system_prompt, user_prompt)
        input_tokens, output_tokens = getattr(self._language_model, "consume_usage", lambda: (0, 0))()
        return GenerationResult(
            draft=draft,
            requirement_vector_id=vector_id,
            retrieved_context=contexts,
            model=self._language_model.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def generate_from_feedback(
        self,
        *,
        requirement_id: str,
        project_id: str | None,
        title: str,
        description: str,
        external_id: str | None,
        feedback_text: str,
        target_context: str,
        action: str,
        requirement_version: int = 1,
        keyword_contexts: list[RetrievedContext] | None = None,
    ) -> GenerationResult:
        query_text = (
            f"Requirement title: {title}\nRequirement description: {description}\n"
            f"Current target: {target_context}\nReviewer feedback: {feedback_text}"
        )
        embedding = await self._language_model.embed(query_text)
        semantic_contexts = await self._vector_store.query(
            embedding,
            top_k=self._config.rag_candidate_limit,
            project_id=project_id,
        )
        semantic_contexts = _approved_test_case_contexts(semantic_contexts)
        keyword_contexts = _approved_test_case_contexts(keyword_contexts or [])
        contexts = rerank_generation_contexts(
            query_text,
            semantic_contexts,
            keyword_contexts,
            exclude_parent_vector_id=f"requirement:{requirement_id}:v{requirement_version}",
            limit=self._config.rag_context_limit,
            semantic_weight=self._config.rag_semantic_weight,
            keyword_weight=self._config.rag_keyword_weight,
            source_weight=self._config.rag_source_weight,
        )
        context_text = "\n\n".join(
            f"[Historical context {index + 1}; score={item.score:.3f}]\n{item.text}"
            for index, item in enumerate(contexts)
        ) or "No relevant historical context was retrieved."
        prompt = self._prompt_templates["feedback_regeneration"]
        values = {
            "action": action,
            "external_id": external_id or "none",
            "title": title,
            "description": description,
            "target_context": target_context,
            "feedback_text": feedback_text,
            "context_text": context_text,
        }
        system_prompt = f"{IMMUTABLE_GUARDRAIL}\n\n{prompt.system_template}"
        user_prompt = render_prompt(prompt.user_template, values)
        draft = await self._language_model.generate(system_prompt, user_prompt)
        input_tokens, output_tokens = getattr(self._language_model, "consume_usage", lambda: (0, 0))()
        return GenerationResult(
            draft=draft,
            requirement_vector_id=f"requirement:{requirement_id}:v{requirement_version}",
            retrieved_context=contexts,
            model=self._language_model.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def build_generation_service(
    config: Settings = settings,
    prompt_templates: dict[str, PromptTemplate] | None = None,
) -> GenerationService:
    provider = config.llm_provider.strip().lower()
    if provider not in {"openai", "openai-compatible"}:
        raise GenerationConfigurationError(f"Unsupported LLM_PROVIDER: {config.llm_provider}")
    return GenerationService(
        language_model=OpenAICompatibleLanguageModel(config),
        vector_store=PineconeVectorStore(config),
        config=config,
        prompt_templates=prompt_templates,
    )
