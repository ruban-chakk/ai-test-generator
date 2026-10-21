import asyncio
import json

import httpx
import pytest

from scripts.live_workflow_acceptance import LiveWorkflowAcceptanceError, run_live_workflow


PROJECT_ID = "00000000-0000-0000-0000-000000000101"
REQUIREMENT_ID = "00000000-0000-0000-0000-000000000102"
REQUIREMENT_VERSION_ID = "00000000-0000-0000-0000-000000000107"
SCENARIO_ID = "00000000-0000-0000-0000-000000000103"
TEST_CASE_ID = "00000000-0000-0000-0000-000000000104"
IMPACT_ID = "00000000-0000-0000-0000-000000000105"
VERSION_ID = "00000000-0000-0000-0000-000000000106"


def test_live_workflow_certifies_index_generation_approval_and_impact() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/auth/token":
            assert b"password=acceptance-password" in request.content
            return httpx.Response(200, json={"access_token": "short-lived-token", "expires_in": 1800})
        assert request.headers["Authorization"] == "Bearer short-lived-token"
        if request.url.path == "/api/v1/operations/dependencies":
            return httpx.Response(
                200,
                json={
                    "status": "healthy",
                    "dependencies": [
                        {"name": "llm", "status": "healthy", "configured": True},
                        {"name": "pinecone", "status": "healthy", "configured": True},
                    ],
                },
            )
        if request.url.path == "/api/v1/projects":
            return httpx.Response(200, json={"id": PROJECT_ID})
        if request.url.path == "/api/v1/requirements" and request.method == "POST":
            payload = json.loads(request.content)
            assert payload["project_id"] == PROJECT_ID
            assert payload["source"] == "live_acceptance"
            return httpx.Response(200, json={"id": REQUIREMENT_ID})
        if request.url.path == f"/api/v1/requirements/{REQUIREMENT_ID}/versions":
            return httpx.Response(200, json=[{"id": REQUIREMENT_VERSION_ID, "version": 1}])
        if request.url.path == "/api/v1/operations/outbox":
            return httpx.Response(
                200,
                json=[
                    {
                        "event_type": "requirement_version.index_requested",
                        "aggregate_id": REQUIREMENT_VERSION_ID,
                        "status": "completed",
                    },
                    {
                        "event_type": "test_case_version.index_requested",
                        "aggregate_id": VERSION_ID,
                        "payload": {"test_case_id": TEST_CASE_ID, "version": 1},
                        "status": "completed",
                    },
                ],
            )
        if request.url.path == f"/api/v1/requirements/{REQUIREMENT_ID}/generate":
            return httpx.Response(
                200,
                json={
                    "scenarios": [
                        {"id": SCENARIO_ID, "test_cases": [{"id": TEST_CASE_ID}]},
                    ]
                },
            )
        if request.url.path in {
            f"/api/v1/requirements/{REQUIREMENT_ID}/approve",
            f"/api/v1/scenarios/{SCENARIO_ID}/approve",
        }:
            assert json.loads(request.content)["notes"].startswith("Automated live workflow acceptance")
            return httpx.Response(200, json={})
        if request.url.path == f"/api/v1/test_cases/{TEST_CASE_ID}/approve":
            assert json.loads(request.content)["notes"].startswith("Automated live workflow acceptance")
            return httpx.Response(200, json={"id": TEST_CASE_ID, "version": 1})
        if request.url.path == f"/api/v1/test_cases/{TEST_CASE_ID}/versions":
            return httpx.Response(200, json=[{"id": VERSION_ID, "version": 1}])
        if request.url.path == f"/api/v1/requirements/{REQUIREMENT_ID}" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "scenarios": [
                        {
                            "id": SCENARIO_ID,
                            "test_cases": [
                                {"id": TEST_CASE_ID, "repository_status": "indexed"},
                            ],
                        }
                    ]
                },
            )
        if request.url.path == "/api/v1/impact/analyze":
            payload = json.loads(request.content)
            assert payload["project_id"] == PROJECT_ID
            assert payload["context_ids"] == [REQUIREMENT_ID]
            return httpx.Response(
                200,
                json={
                    "id": IMPACT_ID,
                    "duplicates": [{"test_case_id": TEST_CASE_ID}],
                    "updates": [],
                    "deprecations": [],
                },
            )
        return httpx.Response(404)

    async def scenario():
        async with httpx.AsyncClient(
            base_url="https://acceptance.example",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await run_live_workflow(
                base_url="https://acceptance.example",
                username="acceptance-admin",
                password="acceptance-password",
                client=client,
            )

    result = asyncio.run(scenario())

    assert result.status == "verified"
    assert result.project_id == PROJECT_ID
    assert result.project_created is True
    assert result.requirement_indexed is True
    assert result.test_case_indexed is True
    assert result.impact_candidate_count == 1
    assert calls[-1] == ("POST", "/api/v1/impact/analyze")


def test_live_workflow_does_not_leak_provider_error_bodies() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "acceptance-password must never be logged"})

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://acceptance.example",
            transport=httpx.MockTransport(handler),
        ) as client:
            await run_live_workflow(
                base_url="https://acceptance.example",
                username="acceptance-admin",
                password="acceptance-password",
                project_id=PROJECT_ID,
                client=client,
            )

    with pytest.raises(LiveWorkflowAcceptanceError) as error:
        asyncio.run(scenario())
    assert "HTTP 401" in str(error.value)
    assert "acceptance-password" not in str(error.value)


def test_live_workflow_stops_before_writes_when_pinecone_is_misconfigured() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path == "/api/v1/auth/token":
            return httpx.Response(200, json={"access_token": "short-lived-token"})
        if request.url.path == "/api/v1/operations/dependencies":
            return httpx.Response(
                200,
                json={
                    "status": "degraded",
                    "dependencies": [
                        {"name": "llm", "status": "healthy", "configured": True},
                        {
                            "name": "pinecone",
                            "status": "misconfigured",
                            "configured": True,
                            "detail": "Index uses a document schema; a bring-your-own-vectors index is required",
                        },
                    ],
                },
            )
        return httpx.Response(500)

    async def scenario() -> None:
        async with httpx.AsyncClient(
            base_url="https://acceptance.example",
            transport=httpx.MockTransport(handler),
        ) as client:
            await run_live_workflow(
                base_url="https://acceptance.example",
                username="acceptance-admin",
                password="acceptance-password",
                client=client,
            )

    with pytest.raises(LiveWorkflowAcceptanceError, match="pinecone dependency is misconfigured"):
        asyncio.run(scenario())
    assert calls == [
        ("POST", "/api/v1/auth/token"),
        ("GET", "/api/v1/operations/dependencies"),
    ]
