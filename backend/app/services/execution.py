from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, settings


class ExecutionConfigurationError(RuntimeError):
    """Raised when no test runner is configured."""


class ExecutionProviderError(RuntimeError):
    """Raised when a configured runner cannot produce a trusted terminal result."""


@dataclass(frozen=True)
class ExecutableTestCase:
    id: str
    version: int
    title: str
    description: str
    prerequisite: str | None
    steps: list[dict[str, Any]]


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    external_run_id: str | None
    summary: dict[str, Any]


class TestExecutionClient:
    TERMINAL_STATUSES = {"passed", "failed"}

    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.execution_runner_base_url or not config.execution_runner_token:
            raise ExecutionConfigurationError(
                "EXECUTION_RUNNER_BASE_URL and EXECUTION_RUNNER_TOKEN are required for automated execution"
            )
        self._base_url = config.execution_runner_base_url.rstrip("/")
        self._token = config.execution_runner_token
        self._timeout = config.execution_runner_timeout_seconds
        self._client = client

    async def execute(
        self,
        test_case: ExecutableTestCase,
        *,
        environment: str,
        idempotency_key: str,
    ) -> ExecutionResult:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        payload = {
            "environment": environment,
            "test_case": {
                "id": test_case.id,
                "version": test_case.version,
                "title": test_case.title,
                "description": test_case.description,
                "prerequisite": test_case.prerequisite,
                "steps": test_case.steps,
            },
        }
        try:
            for attempt in range(1, 4):
                try:
                    response = await client.post(
                        f"{self._base_url}/executions",
                        headers={
                            "Authorization": f"Bearer {self._token}",
                            "Content-Type": "application/json",
                            "Idempotency-Key": idempotency_key,
                        },
                        json=payload,
                    )
                    if (response.status_code == 429 or response.status_code >= 500) and attempt < 3:
                        await asyncio.sleep(min(2 ** (attempt - 1), 4))
                        continue
                    response.raise_for_status()
                    parsed = response.json()
                    if not isinstance(parsed, dict):
                        raise ValueError("runner response is not an object")
                    status = str(parsed.get("status") or "").lower()
                    if status not in self.TERMINAL_STATUSES:
                        raise ValueError("runner did not return a terminal status")
                    summary = parsed.get("result") or {}
                    if not isinstance(summary, dict):
                        raise ValueError("runner result is not an object")
                    return ExecutionResult(
                        status=status,
                        external_run_id=str(parsed["external_run_id"]) if parsed.get("external_run_id") else None,
                        summary=summary,
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= 3:
                        raise ExecutionProviderError("Test runner request failed after 3 attempts") from exc
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                except (httpx.HTTPStatusError, ValueError) as exc:
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "invalid"
                    raise ExecutionProviderError(f"Test runner returned {status} response") from exc
        finally:
            if owns_client:
                await client.aclose()
        raise ExecutionProviderError("Test runner request did not complete")
