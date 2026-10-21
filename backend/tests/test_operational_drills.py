import asyncio

import httpx
import pytest

from scripts.disaster_recovery_drill import (
    is_known_transaction_timeout_warning,
    redacted_dsn,
    validate_drill_target,
)
from scripts.load_smoke import percentile, run_load
from scripts.acceptance_probe import run_acceptance_probes
from app.core.config import Settings


def test_load_smoke_measures_success_and_latency() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"status": "ok"}))
    result = asyncio.run(
        run_load("https://service.example/health/live", requests=25, concurrency=5, transport=transport)
    )
    assert result.successes == 25
    assert result.failures == 0
    assert result.p95_ms >= 0
    assert percentile([1, 2, 3, 4], 0.95) == 4


def test_recovery_drill_rejects_nonisolated_or_same_target_and_redacts_password() -> None:
    source = "postgresql+asyncpg://admin:source-secret@localhost:5432/application"
    with pytest.raises(ValueError, match="must differ"):
        validate_drill_target(source, source)
    with pytest.raises(ValueError, match="end in _drill"):
        validate_drill_target(source, "postgresql://admin:secret@localhost:5432/application_copy")
    with pytest.raises(ValueError, match="isolated local"):
        validate_drill_target(source, "postgresql://admin:secret@production.example:5432/application_drill")
    validate_drill_target(source, "postgresql://admin:target-secret@localhost:5432/application_drill")
    assert "source-secret" not in redacted_dsn(source)
    assert "***" in redacted_dsn(source)
    assert is_known_transaction_timeout_warning(
        'pg_restore: error: ERROR: unrecognized configuration parameter "transaction_timeout"\n'
        'pg_restore: warning: errors ignored on restore: 1'
    )
    assert not is_known_transaction_timeout_warning("pg_restore: error: permission denied")


def test_acceptance_probe_reports_all_configured_dependencies_without_exposing_secrets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    config = Settings(
        _env_file=None,
        llm_api_key="llm-secret",
        pinecone_api_key="pinecone-secret",
        pinecone_host="https://pinecone.example",
        jira_base_url="https://jira.example",
        jira_email="qa@example.com",
        jira_api_token="jira-secret",
        test_repository_base_url="https://repository.example",
        test_repository_token="repo-secret",
        xray_client_id="xray-client",
        xray_client_secret="xray-secret",
        testrail_username="testrail-user",
        testrail_api_key="testrail-secret",
        testrail_project_id=42,
        zephyr_api_token="zephyr-secret",
        oidc_enabled=True,
        oidc_jwks_uri="https://identity.example/jwks",
        execution_runner_base_url="https://runner.example",
        execution_runner_token="runner-secret",
    )

    async def scenario() -> list:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await run_acceptance_probes(config, client)

    probes = asyncio.run(scenario())
    assert {probe.name for probe in probes} == {
        "llm", "pinecone", "jira", "xray", "testrail", "zephyr", "oidc", "execution_runner"
    }
    assert all(probe.status == "healthy" for probe in probes)
    assert "secret" not in repr(probes)
