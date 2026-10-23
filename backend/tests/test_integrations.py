import asyncio
import base64
import json

import httpx
import pytest

from app.core.config import Settings
from app.services.integrations import (
    IntegrationConfigurationError,
    JiraCloudClient,
    RepositoryTestCase,
    TestRailRepositoryClient as RailRepositoryClient,
    TestRepositoryClient as RepositoryClient,
    XrayCloudRepositoryClient as XrayRepositoryClient,
    ZephyrCloudRepositoryClient as ZephyrRepositoryClient,
    build_test_repository_client,
)


def repository_case() -> RepositoryTestCase:
    return RepositoryTestCase(
        id="case-id",
        version=3,
        requirement_id="requirement-id",
        scenario_id="scenario-id",
        title="Reject expired token",
        description="An expired token cannot reset a password.",
        prerequisite="A user exists",
        priority="high",
        severity="major",
        category="security",
        test_type="negative",
        steps=[{"step_number": 1, "action": "Open expired token", "expected_result": "Request is rejected"}],
    )


def test_jira_client_uses_enhanced_search_and_parses_adf_pages() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        page = len(requests)
        assert request.url.path == "/rest/api/3/search/jql"
        assert payload["fields"] == ["summary", "description", "issuetype", "status", "updated"]
        if page == 1:
            assert "nextPageToken" not in payload
            return httpx.Response(
                200,
                json={
                    "issues": [
                        {
                            "key": "QA-101",
                            "fields": {
                                "summary": "Reset password",
                                "description": {
                                    "type": "doc",
                                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Use an expiring link."}]}],
                                },
                                "issuetype": {"name": "Story"},
                                "status": {"name": "Ready"},
                                "updated": "2026-10-20T10:00:00.000+0000",
                            },
                        }
                    ],
                    "nextPageToken": "page-two",
                    "isLast": False,
                },
            )
        assert payload["nextPageToken"] == "page-two"
        return httpx.Response(
            200,
            json={
                "issues": [{"key": "QA-102", "fields": {"summary": "Audit password resets"}}],
                "isLast": True,
            },
        )

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            jira_base_url="https://tenant.atlassian.net",
            jira_email="service@example.com",
            jira_api_token="secret-token",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            issues = await JiraCloudClient(settings, client).search_issues("project = QA", max_results=2)
        assert [issue.key for issue in issues] == ["QA-101", "QA-102"]
        assert issues[0].description == "Use an expiring link."
        credentials = base64.b64decode(requests[0].headers["Authorization"].removeprefix("Basic ")).decode()
        assert credentials == "service@example.com:secret-token"

    asyncio.run(scenario())


def test_repository_client_sends_idempotent_upsert_contract() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"external_id": "case-42"})

    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            test_repository_base_url="https://repository.example/api/v1",
            test_repository_token="repository-secret",
        )
        test_case = repository_case()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await RepositoryClient(settings, client).upsert(
                test_case,
                repository="qa-cases",
                branch="main",
                idempotency_key="stable-delivery-key",
            )
        request = captured["request"]
        assert isinstance(request, httpx.Request)
        assert request.method == "PUT"
        assert request.url.path == "/api/v1/test-cases/case-id"
        assert request.headers["Idempotency-Key"] == "stable-delivery-key"
        assert request.headers["Authorization"] == "Bearer repository-secret"
        assert captured["payload"]["test_case"]["version"] == 3  # type: ignore[index]
        assert result == {"external_id": "case-42"}

    asyncio.run(scenario())


def test_testrail_adapter_creates_then_updates_by_stable_reference() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "get_cases" in str(request.url):
            return httpx.Response(200, json={"cases": []})
        assert "add_case/17" in str(request.url)
        payload = json.loads(request.content)
        assert payload["refs"] == "ATG-case-id-V3"
        assert payload["custom_steps_separated"][0]["expected"] == "Request is rejected"
        return httpx.Response(200, json={"id": 91, **payload})

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            test_repository_provider="testrail",
            test_repository_base_url="https://tenant.testrail.io",
            testrail_username="qa@example.com",
            testrail_api_key="secret",
            testrail_project_id=8,
            testrail_section_id=17,
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = build_test_repository_client(config, client)
            assert isinstance(adapter, RailRepositoryClient)
            result = await adapter.upsert(repository_case(), repository="ignored", branch="ignored", idempotency_key="key")
        assert result["id"] == 91
        assert len(requests) == 2
        assert "refs=ATG-case-id-V3" in str(requests[0].url)

    asyncio.run(scenario())


def test_xray_adapter_reuses_existing_version_label() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/authenticate"):
            return httpx.Response(200, json="xray-token")
        payload = json.loads(request.content)
        assert payload["variables"]["jql"] == 'project = "QA" AND labels = "atg-case-id-v3"'
        return httpx.Response(
            200,
            json={"data": {"getTests": {"results": [{"issueId": "10001", "jira": {"key": "QA-22"}}]}}},
        )

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            test_repository_provider="xray_cloud",
            xray_client_id="client-id",
            xray_client_secret="client-secret",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = build_test_repository_client(config, client)
            assert isinstance(adapter, XrayRepositoryClient)
            result = await adapter.upsert(repository_case(), repository="QA", branch="/generated", idempotency_key="key")
        assert result["created"] is False
        assert result["test"]["issueId"] == "10001"
        assert len(requests) == 2
        assert requests[1].headers["Authorization"] == "Bearer xray-token"

    asyncio.run(scenario())


def test_zephyr_adapter_creates_case_and_overwrites_steps_with_stable_reference() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer zephyr-token"
        if request.method == "GET":
            assert request.url.params["projectKey"] == "QA"
            return httpx.Response(200, json={"values": [], "isLast": True, "total": 0})
        if request.url.path.endswith("/testcases"):
            payload = json.loads(request.content)
            assert payload["name"] == "[ATG-case-id-V3] Reject expired token"
            assert payload["labels"] == ["ai-test-generator", "atg-case-id-v3"]
            return httpx.Response(201, json={"key": "QA-T42", "name": payload["name"]})
        payload = json.loads(request.content)
        assert request.url.path.endswith("/testcases/QA-T42/teststeps")
        assert payload["mode"] == "OVERWRITE"
        assert payload["items"][0]["inline"]["expectedResult"] == "Request is rejected"
        return httpx.Response(204)

    async def scenario() -> None:
        config = Settings(
            _env_file=None,
            test_repository_provider="zephyr_cloud",
            zephyr_api_token="zephyr-token",
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = build_test_repository_client(config, client)
            assert isinstance(adapter, ZephyrRepositoryClient)
            result = await adapter.upsert(
                repository_case(), repository="QA", branch="/generated", idempotency_key="delivery-key"
            )
        assert result == {"created": True, "key": "QA-T42", "reference": "ATG-case-id-V3"}
        assert len(requests) == 3

    asyncio.run(scenario())


def test_integration_clients_fail_closed_without_credentials() -> None:
    settings = Settings(_env_file=None)
    with pytest.raises(IntegrationConfigurationError):
        JiraCloudClient(settings)
    with pytest.raises(IntegrationConfigurationError):
        RepositoryClient(settings)
