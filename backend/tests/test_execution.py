import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.services.execution import (
    ExecutableTestCase,
    ExecutionConfigurationError,
    ExecutionProviderError,
    TestExecutionClient as ExecutionClient,
)


def executable_case() -> ExecutableTestCase:
    return ExecutableTestCase(
        id="case-id",
        version=2,
        title="Reject expired token",
        description="Expired reset tokens cannot change credentials.",
        prerequisite="An expired token exists.",
        steps=[
            {"step_number": 1, "action": "Open the expired token", "expected_result": "Access is rejected"}
        ],
    )


def test_execution_client_sends_idempotent_contract_and_accepts_terminal_result() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "status": "passed",
                "external_run_id": "runner-42",
                "result": {"duration_ms": 87, "steps_passed": 1},
            },
        )

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            execution_runner_base_url="https://runner.example/api/v1",
            execution_runner_token="runner-secret",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await ExecutionClient(config, client).execute(
                executable_case(), environment="staging", idempotency_key="stable-key"
            )
        assert result.status == "passed"
        assert result.external_run_id == "runner-42"
        request = captured["request"]
        assert isinstance(request, httpx.Request)
        assert request.url.path == "/api/v1/executions"
        assert request.headers["Idempotency-Key"] == "stable-key"
        assert request.headers["Authorization"] == "Bearer runner-secret"
        assert captured["payload"]["environment"] == "staging"  # type: ignore[index]

    asyncio.run(scenario())


def test_execution_client_fails_closed_for_unconfigured_or_nonterminal_runner() -> None:
    with pytest.raises(ExecutionConfigurationError):
        ExecutionClient(Settings(_env_file=None))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"status": "running", "external_run_id": "runner-42"})

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            execution_runner_base_url="https://runner.example",
            execution_runner_token="runner-secret",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ExecutionProviderError, match="invalid"):
                await ExecutionClient(config, client).execute(
                    executable_case(), environment="staging", idempotency_key="stable-key"
                )

    asyncio.run(scenario())
