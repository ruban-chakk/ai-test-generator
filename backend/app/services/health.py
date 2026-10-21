from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx

from app.core.config import Settings, settings


@dataclass(frozen=True)
class DependencyProbe:
    name: str
    status: str
    configured: bool


async def probe_external_dependencies(
    config: Settings = settings,
    client: httpx.AsyncClient | None = None,
) -> list[DependencyProbe]:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=config.health_probe_timeout_seconds)
    repository_probe = _repository_probe(config, http)
    probes = [
        _probe(
            http,
            "llm",
            bool(config.llm_api_key and config.llm_base_url),
            "GET",
            f"{config.llm_base_url.rstrip('/')}/models",
            {"Authorization": f"Bearer {config.llm_api_key}"},
        ),
        _probe(
            http,
            "pinecone",
            bool(config.pinecone_api_key and config.pinecone_host),
            "POST",
            f"{config.pinecone_host.rstrip('/')}/describe_index_stats",
            {"Api-Key": config.pinecone_api_key, "Content-Type": "application/json"},
            json={},
        ),
        _probe(
            http,
            "jira",
            bool(config.jira_base_url and config.jira_email and config.jira_api_token),
            "GET",
            f"{config.jira_base_url.rstrip('/')}/rest/api/3/myself",
            {"Accept": "application/json"},
            auth=(config.jira_email, config.jira_api_token),
        ),
        repository_probe,
    ]
    try:
        return list(await asyncio.gather(*probes))
    finally:
        if owns_client:
            await http.aclose()


def _repository_probe(config: Settings, client: httpx.AsyncClient):
    provider = config.test_repository_provider.strip().lower()
    if provider in {"xray", "xray_cloud"}:
        return _probe(
            client,
            "test_repository",
            bool(config.xray_client_id and config.xray_client_secret),
            "POST",
            config.xray_auth_url,
            {"Content-Type": "application/json"},
            json={"client_id": config.xray_client_id, "client_secret": config.xray_client_secret},
        )
    if provider == "testrail":
        configured = bool(
            config.test_repository_base_url
            and config.testrail_username
            and config.testrail_api_key
            and config.testrail_project_id is not None
        )
        return _probe(
            client,
            "test_repository",
            configured,
            "GET",
            f"{config.test_repository_base_url.rstrip('/')}/index.php?/api/v2/get_project/{config.testrail_project_id}",
            {"Accept": "application/json"},
            auth=(config.testrail_username, config.testrail_api_key),
        )
    return _probe(
        client,
        "test_repository",
        bool(config.test_repository_base_url and config.test_repository_token),
        "GET",
        f"{config.test_repository_base_url.rstrip('/')}/health",
        {"Authorization": f"Bearer {config.test_repository_token}"},
    )


async def _probe(
    client: httpx.AsyncClient,
    name: str,
    configured: bool,
    method: str,
    url: str,
    headers: dict[str, str],
    **kwargs,
) -> DependencyProbe:
    if not configured:
        return DependencyProbe(name=name, status="not_configured", configured=False)
    try:
        response = await client.request(method, url, headers=headers, **kwargs)
        status = "healthy" if response.is_success else "unhealthy"
    except httpx.HTTPError:
        status = "unreachable"
    return DependencyProbe(name=name, status=status, configured=True)
