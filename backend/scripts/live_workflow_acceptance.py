from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

import httpx


class LiveWorkflowAcceptanceError(RuntimeError):
    """Raised when a live workflow step cannot be certified."""


@dataclass(frozen=True)
class LiveWorkflowResult:
    run_id: str
    project_id: str
    project_created: bool
    requirement_id: str
    scenario_id: str
    test_case_id: str
    requirement_indexed: bool
    test_case_indexed: bool
    impact_analysis_id: str
    impact_candidate_count: int
    duration_seconds: float
    status: str = "verified"
    artifacts_retained: bool = True


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        raise LiveWorkflowAcceptanceError(f"{method} {path} could not reach the application") from exc
    if not response.is_success:
        raise LiveWorkflowAcceptanceError(f"{method} {path} failed with HTTP {response.status_code}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise LiveWorkflowAcceptanceError(f"{method} {path} returned invalid JSON") from exc


async def _wait_for_outbox_event(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    event_type: str,
    aggregate_id: str,
    max_wait_seconds: float,
    poll_seconds: float,
    sleeper: Callable[[float], Awaitable[None]],
) -> None:
    deadline = time.monotonic() + max_wait_seconds
    while True:
        events = await _request_json(
            client,
            "GET",
            "/api/v1/operations/outbox?limit=200",
            headers=headers,
        )
        for event in events:
            if event.get("event_type") != event_type or str(event.get("aggregate_id")) != aggregate_id:
                continue
            status = event.get("status")
            if status == "completed":
                return
            if status == "failed":
                raise LiveWorkflowAcceptanceError(
                    f"Outbox event {event_type} for {aggregate_id} failed"
                )
        if time.monotonic() >= deadline:
            raise LiveWorkflowAcceptanceError(
                f"Timed out waiting for {event_type} for {aggregate_id}"
            )
        await sleeper(poll_seconds)


def _first_generated_case(requirement: dict[str, Any]) -> tuple[str, str]:
    scenarios = requirement.get("scenarios") or []
    if not scenarios:
        raise LiveWorkflowAcceptanceError("Generation returned no test scenarios")
    scenario = scenarios[0]
    test_cases = scenario.get("test_cases") or []
    if not test_cases:
        raise LiveWorkflowAcceptanceError("Generation returned no test cases")
    return str(scenario["id"]), str(test_cases[0]["id"])


def _indexed_test_case(requirement: dict[str, Any], test_case_id: str) -> bool:
    for scenario in requirement.get("scenarios") or []:
        for test_case in scenario.get("test_cases") or []:
            if str(test_case.get("id")) == test_case_id:
                return test_case.get("repository_status") in {"indexed", "synced"}
    return False


async def _require_healthy_generation_dependencies(
    client: httpx.AsyncClient,
    headers: dict[str, str],
) -> None:
    summary = await _request_json(
        client,
        "GET",
        "/api/v1/operations/dependencies",
        headers=headers,
    )
    dependencies = {
        dependency.get("name"): dependency
        for dependency in (summary.get("dependencies") or [])
        if isinstance(dependency, dict)
    }
    for name in ("llm", "pinecone"):
        dependency = dependencies.get(name)
        status = dependency.get("status") if dependency else "missing"
        if status == "healthy":
            continue
        detail = dependency.get("detail") if dependency else None
        suffix = f": {detail}" if detail else ""
        raise LiveWorkflowAcceptanceError(
            f"{name} dependency is {status}{suffix}"
        )


async def run_live_workflow(
    *,
    base_url: str,
    username: str,
    password: str,
    project_id: str | None = None,
    max_wait_seconds: float = 120.0,
    poll_seconds: float = 2.0,
    client: httpx.AsyncClient | None = None,
    sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> LiveWorkflowResult:
    """Exercise the real API, provider, worker, and database workflow with synthetic data.

    The generated project and artifacts are intentionally retained as acceptance evidence.
    Run this only in a dedicated acceptance project or disposable environment.
    """

    if not username.strip() or not password:
        raise LiveWorkflowAcceptanceError("Live acceptance username and password are required")
    if max_wait_seconds <= 0 or poll_seconds <= 0:
        raise LiveWorkflowAcceptanceError("Wait and poll durations must be positive")
    if project_id is not None:
        try:
            project_id = str(uuid.UUID(project_id))
        except ValueError as exc:
            raise LiveWorkflowAcceptanceError("project_id must be a UUID") from exc

    run_id = uuid.uuid4().hex[:12]
    started = time.perf_counter()
    owns_client = client is None
    http = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=60.0)
    try:
        token_payload = await _request_json(
            http,
            "POST",
            "/api/v1/auth/token",
            data={"username": username, "password": password},
        )
        token = token_payload.get("access_token") if isinstance(token_payload, dict) else None
        if not token:
            raise LiveWorkflowAcceptanceError("Authentication response did not contain an access token")
        headers = {"Authorization": f"Bearer {token}"}
        await _require_healthy_generation_dependencies(http, headers)

        project_created = project_id is None
        if project_id is None:
            project = await _request_json(
                http,
                "POST",
                "/api/v1/projects",
                headers=headers,
                json={
                    "name": f"Live acceptance {run_id}",
                    "description": "Synthetic project retained as live workflow acceptance evidence.",
                    "status": "active",
                },
            )
            project_id = str(project["id"])

        description = (
            "A signed-in user requests a password reset. The application must issue a single-use link, "
            "reject expired or previously used links, preserve the existing password after rejection, and "
            "record an audit event without exposing the token."
        )
        requirement = await _request_json(
            http,
            "POST",
            "/api/v1/requirements",
            headers=headers,
            json={
                "project_id": project_id,
                "external_id": f"ATG-LIVE-{run_id.upper()}",
                "title": "Secure password reset acceptance",
                "description": description,
                "source": "live_acceptance",
            },
        )
        requirement_id = str(requirement["id"])
        requirement_versions = await _request_json(
            http,
            "GET",
            f"/api/v1/requirements/{requirement_id}/versions",
            headers=headers,
        )
        if not requirement_versions:
            raise LiveWorkflowAcceptanceError("Created requirement version was not visible through the API")
        await _wait_for_outbox_event(
            http,
            headers,
            event_type="requirement_version.index_requested",
            aggregate_id=str(requirement_versions[0]["id"]),
            max_wait_seconds=max_wait_seconds,
            poll_seconds=poll_seconds,
            sleeper=sleeper,
        )

        generated = await _request_json(
            http,
            "POST",
            f"/api/v1/requirements/{requirement_id}/generate",
            headers=headers,
        )
        scenario_id, test_case_id = _first_generated_case(generated)
        approval = {"notes": f"Automated live workflow acceptance {run_id}"}
        await _request_json(
            http,
            "POST",
            f"/api/v1/requirements/{requirement_id}/approve",
            headers=headers,
            json=approval,
        )
        await _request_json(
            http,
            "POST",
            f"/api/v1/scenarios/{scenario_id}/approve",
            headers=headers,
            json=approval,
        )
        approved_test_case = await _request_json(
            http,
            "POST",
            f"/api/v1/test_cases/{test_case_id}/approve",
            headers=headers,
            json=approval,
        )
        versions = await _request_json(
            http,
            "GET",
            f"/api/v1/test_cases/{test_case_id}/versions",
            headers=headers,
        )
        approved_version = next(
            (
                version
                for version in versions
                if version.get("version") == approved_test_case.get("version")
            ),
            None,
        )
        if not approved_version:
            raise LiveWorkflowAcceptanceError("Approved test-case version was not visible through the API")
        await _wait_for_outbox_event(
            http,
            headers,
            event_type="test_case_version.index_requested",
            aggregate_id=str(approved_version["id"]),
            max_wait_seconds=max_wait_seconds,
            poll_seconds=poll_seconds,
            sleeper=sleeper,
        )

        indexed_requirement = await _request_json(
            http,
            "GET",
            f"/api/v1/requirements/{requirement_id}",
            headers=headers,
        )
        if not _indexed_test_case(indexed_requirement, test_case_id):
            raise LiveWorkflowAcceptanceError("Indexed test case status was not visible through the API")

        impact = await _request_json(
            http,
            "POST",
            "/api/v1/impact/analyze",
            headers=headers,
            json={
                "project_id": project_id,
                "context_ids": [requirement_id],
                "text": description,
                "created_by": "live-acceptance",
            },
        )
        candidate_count = sum(
            len(impact.get(field) or []) for field in ("duplicates", "updates", "deprecations")
        )
        return LiveWorkflowResult(
            run_id=run_id,
            project_id=project_id,
            project_created=project_created,
            requirement_id=requirement_id,
            scenario_id=scenario_id,
            test_case_id=test_case_id,
            requirement_indexed=True,
            test_case_indexed=True,
            impact_analysis_id=str(impact["id"]),
            impact_candidate_count=candidate_count,
            duration_seconds=round(time.perf_counter() - started, 3),
        )
    finally:
        if owns_client:
            await http.aclose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Certify the live requirement-to-impact workflow using retained synthetic artifacts."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("LIVE_ACCEPTANCE_BASE_URL", "http://127.0.0.1:8000"),
    )
    parser.add_argument("--project-id", default=os.getenv("LIVE_ACCEPTANCE_PROJECT_ID") or None)
    parser.add_argument("--username", default=os.getenv("LIVE_ACCEPTANCE_USERNAME", ""))
    parser.add_argument("--password-env", default="LIVE_ACCEPTANCE_PASSWORD")
    parser.add_argument("--max-wait-seconds", type=float, default=120.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument(
        "--allow-retained-artifacts",
        action="store_true",
        help="Acknowledge that the synthetic project/requirement remains as acceptance evidence.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.allow_retained_artifacts:
        raise SystemExit("Pass --allow-retained-artifacts and use a dedicated acceptance project or environment")
    password = os.getenv(args.password_env, "")
    result = asyncio.run(
        run_live_workflow(
            base_url=args.base_url,
            username=args.username,
            password=password,
            project_id=args.project_id,
            max_wait_seconds=args.max_wait_seconds,
            poll_seconds=args.poll_seconds,
        )
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
