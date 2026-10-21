import asyncio
import json

import httpx

from app.core.config import Settings
from app.services.generation import PineconeVectorStore
from app.services.vector_maintenance import build_maintenance_plan


def test_maintenance_plan_finds_missing_and_orphan_vectors() -> None:
    plan = build_maintenance_plan(
        {"requirement:1", "test_case:2"},
        {"requirement:1", "feedback:orphan"},
        allow_orphan_detection=True,
    )

    assert plan.missing_ids == ("test_case:2",)
    assert plan.orphan_ids == ("feedback:orphan",)


def test_project_scoped_plan_never_marks_global_vectors_as_orphans() -> None:
    plan = build_maintenance_plan(
        {"requirement:1"},
        {"requirement:1", "requirement:another-project"},
        allow_orphan_detection=False,
    )

    assert plan.orphan_ids == ()


def test_pinecone_list_ids_follows_pagination_tokens() -> None:
    seen_tokens: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("paginationToken")
        seen_tokens.append(token)
        if token is None:
            payload = {"vectors": [{"id": "one"}], "pagination": {"next": "next-page"}}
        else:
            payload = {"vectors": [{"id": "two"}], "pagination": {}}
        return httpx.Response(200, content=json.dumps(payload).encode(), request=request)

    async def scenario() -> list[str]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            store = PineconeVectorStore(
                Settings(
                    _env_file=None,
                    pinecone_api_key="test-key",
                    pinecone_host="https://example.test",
                ),
                client,
            )
            return await store.list_vector_ids()

    assert asyncio.run(scenario()) == ["one", "two"]
    assert seen_tokens == [None, "next-page"]
