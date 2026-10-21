from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

import httpx

from app.core.config import Settings
from app.services.health import DependencyProbe, probe_external_dependencies


async def run_acceptance_probes(
    config: Settings,
    client: httpx.AsyncClient | None = None,
) -> list[DependencyProbe]:
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=config.health_probe_timeout_seconds)
    try:
        probes = await probe_external_dependencies(config, http)
        oidc_configured = bool(config.oidc_enabled and config.oidc_jwks_uri)
        probes.append(
            await _probe_url(
                http,
                "oidc",
                oidc_configured,
                config.oidc_jwks_uri,
                {"Accept": "application/json"},
            )
        )
        runner_configured = bool(config.execution_runner_base_url and config.execution_runner_token)
        probes.append(
            await _probe_url(
                http,
                "execution_runner",
                runner_configured,
                f"{config.execution_runner_base_url.rstrip('/')}/health",
                {"Authorization": f"Bearer {config.execution_runner_token}"},
            )
        )
        return probes
    finally:
        if owns_client:
            await http.aclose()


async def _probe_url(
    client: httpx.AsyncClient,
    name: str,
    configured: bool,
    url: str,
    headers: dict[str, str],
) -> DependencyProbe:
    if not configured:
        return DependencyProbe(name=name, status="not_configured", configured=False)
    try:
        response = await client.get(url, headers=headers)
        status = "healthy" if response.is_success else "unhealthy"
    except httpx.HTTPError:
        status = "unreachable"
    return DependencyProbe(name=name, status=status, configured=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sanitized live-tenant acceptance probe.")
    parser.add_argument(
        "--require",
        default="llm,pinecone,jira,test_repository,oidc",
        help="Comma-separated dependencies that must be configured and healthy.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    required = {item.strip() for item in args.require.split(",") if item.strip()}
    probes = asyncio.run(run_acceptance_probes(Settings()))
    print(json.dumps([asdict(probe) for probe in probes], indent=2, sort_keys=True))
    failed = [probe.name for probe in probes if probe.name in required and probe.status != "healthy"]
    if failed:
        raise SystemExit(f"Live acceptance failed or is not configured: {', '.join(sorted(failed))}")


if __name__ == "__main__":
    main()
