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


def test_unconfigured_dependencies_do_not_make_network_requests() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected request to {request.url}")

    async def scenario() -> None:
        config = Settings(_env_file=None)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probes = await probe_external_dependencies(config, client)
        assert all(probe.status == "not_configured" for probe in probes)

    asyncio.run(scenario())
