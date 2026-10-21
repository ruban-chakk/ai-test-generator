import asyncio

import httpx

from app.core.config import Settings
from app.services.health import probe_external_dependencies


def test_dependency_probes_report_health_without_exposing_credentials() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "repository.example":
            return httpx.Response(503)
        if request.url.host == "api.pinecone.io":
            if request.headers["X-Pinecone-API-Version"] == "2026-07":
                return httpx.Response(200, json={"schema": None})
            return httpx.Response(
                200,
                json={
                    "dimension": 1536,
                    "vector_type": "dense",
                    "host": "pinecone.example",
                    "status": {"ready": True},
                },
            )
        return httpx.Response(200, json={})

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            llm_api_key="llm-secret",
            llm_base_url="https://llm.example/v1",
            pinecone_api_key="pinecone-secret",
            pinecone_host="https://pinecone.example",
            jira_base_url="https://jira.example",
            jira_email="service@example.com",
            jira_api_token="jira-secret",
            test_repository_base_url="https://repository.example/api",
            test_repository_token="repository-secret",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probes = await probe_external_dependencies(config, client)
        assert {probe.name: probe.status for probe in probes} == {
            "llm": "healthy",
            "pinecone": "healthy",
            "jira": "healthy",
            "test_repository": "unhealthy",
        }
        serialized = repr(probes)
        for secret in ["llm-secret", "pinecone-secret", "jira-secret", "repository-secret"]:
            assert secret not in serialized

    asyncio.run(scenario())


def test_pinecone_document_index_is_reported_as_misconfigured() -> None:
    seen_hosts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_hosts.append(request.url.host or "")
        return httpx.Response(
            200,
            json={
                "schema": {
                    "fields": {
                        "embedding": {"type": "dense_vector", "dimension": 1536},
                    }
                }
            },
        )

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            pinecone_api_key="pinecone-secret",
            pinecone_host="https://pinecone.example",
            pinecone_index_name="document-index",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probes = await probe_external_dependencies(config, client)
        pinecone = next(probe for probe in probes if probe.name == "pinecone")
        assert pinecone.status == "misconfigured"
        assert "bring-your-own-vectors" in (pinecone.detail or "")
        assert seen_hosts.count("pinecone.example") == 0

    asyncio.run(scenario())


def test_unconfigured_dependencies_do_not_make_network_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    async def scenario() -> None:
        config = Settings(_env_file=None)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probes = await probe_external_dependencies(config, client)
        assert all(probe.status == "not_configured" for probe in probes)

    asyncio.run(scenario())
