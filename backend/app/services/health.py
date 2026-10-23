from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

from app.core.config import Settings, settings


@dataclass(frozen=True)
class DependencyProbe:
    name: str
    status: str
    configured: bool
    detail: str | None = None


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
        _pinecone_probe(config, http),
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
    if provider in {"zephyr", "zephyr_cloud", "zephyr_scale"}:
        return _probe(
            client,
            "test_repository",
            bool(config.zephyr_base_url and config.zephyr_api_token),
            "GET",
            f"{config.zephyr_base_url.rstrip('/')}/projects",
            {"Authorization": f"Bearer {config.zephyr_api_token}", "Accept": "application/json"},
        )
    return _probe(
        client,
        "test_repository",
        bool(config.test_repository_base_url and config.test_repository_token),
        "GET",
        f"{config.test_repository_base_url.rstrip('/')}/health",
        {"Authorization": f"Bearer {config.test_repository_token}"},
    )


async def _pinecone_probe(config: Settings, client: httpx.AsyncClient) -> DependencyProbe:
    configured = bool(config.pinecone_api_key and config.pinecone_host and config.pinecone_index_name)
    if not configured:
        return DependencyProbe(name="pinecone", status="not_configured", configured=False)
    control_url = f"{config.pinecone_control_plane_url.rstrip('/')}/indexes/{config.pinecone_index_name}"
    base_headers = {"Api-Key": config.pinecone_api_key, "Accept": "application/json"}
    try:
        schema_response = await client.get(
            control_url,
            headers={**base_headers, "X-Pinecone-API-Version": config.pinecone_api_version},
        )
        if not schema_response.is_success:
            return DependencyProbe(
                name="pinecone",
                status="unhealthy",
                configured=True,
                detail=f"Index configuration check returned HTTP {schema_response.status_code}",
            )
        schema_payload = schema_response.json()
        if schema_payload.get("schema"):
            return DependencyProbe(
                name="pinecone",
                status="misconfigured",
                configured=True,
                detail="Index uses a document schema; a bring-your-own-vectors index is required",
            )

        index_response = await client.get(
            control_url,
            headers={**base_headers, "X-Pinecone-API-Version": "2025-10"},
        )
        if not index_response.is_success:
            return DependencyProbe(
                name="pinecone",
                status="unhealthy",
                configured=True,
                detail=f"Index description returned HTTP {index_response.status_code}",
            )
        index = index_response.json()
        if index.get("embed"):
            return DependencyProbe(
                name="pinecone",
                status="misconfigured",
                configured=True,
                detail="Index has integrated embedding enabled; a bring-your-own-vectors index is required",
            )
        if index.get("vector_type") != "dense":
            return DependencyProbe(
                name="pinecone",
                status="misconfigured",
                configured=True,
                detail="Index must use dense vectors",
            )
        if index.get("dimension") != config.embedding_dimension:
            return DependencyProbe(
                name="pinecone",
                status="misconfigured",
                configured=True,
                detail=(
                    f"Index dimension {index.get('dimension')} does not match configured embedding dimension "
                    f"{config.embedding_dimension}"
                ),
            )
        configured_host = urlsplit(config.pinecone_host).hostname
        described_host = urlsplit(f"https://{str(index.get('host') or '').removeprefix('https://')}").hostname
        if configured_host != described_host:
            return DependencyProbe(
                name="pinecone",
                status="misconfigured",
                configured=True,
                detail="PINECONE_HOST does not belong to PINECONE_INDEX_NAME",
            )
        if not (index.get("status") or {}).get("ready", False):
            return DependencyProbe(
                name="pinecone",
                status="unhealthy",
                configured=True,
                detail="Index is not ready",
            )
        stats_response = await client.post(
            f"{config.pinecone_host.rstrip('/')}/describe_index_stats",
            headers={"Api-Key": config.pinecone_api_key, "Content-Type": "application/json"},
            json={},
        )
        if not stats_response.is_success:
            return DependencyProbe(
                name="pinecone",
                status="unhealthy",
                configured=True,
                detail=f"Index data-plane check returned HTTP {stats_response.status_code}",
            )
        return DependencyProbe(name="pinecone", status="healthy", configured=True)
    except (httpx.HTTPError, ValueError):
        return DependencyProbe(
            name="pinecone",
            status="unreachable",
            configured=True,
            detail="Index configuration or data plane could not be reached",
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
