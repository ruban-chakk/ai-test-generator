from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings, settings


class IntegrationConfigurationError(RuntimeError):
    """Raised when an external integration is not configured."""


class IntegrationProviderError(RuntimeError):
    """Raised when an external integration cannot complete a request."""


@dataclass(frozen=True)
class JiraIssue:
    key: str
    summary: str
    description: str
    issue_type: str | None
    status: str | None
    updated: str | None


@dataclass(frozen=True)
class RepositoryTestCase:
    id: str
    version: int
    requirement_id: str
    scenario_id: str
    title: str
    description: str
    prerequisite: str | None
    priority: str | None
    severity: str | None
    category: str | None
    test_type: str | None
    steps: list[dict[str, Any]]


class RepositoryClient(Protocol):
    async def upsert(
        self,
        test_case: RepositoryTestCase,
        *,
        repository: str,
        branch: str,
        idempotency_key: str,
    ) -> dict[str, Any]: ...


def _adf_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(part for item in value if (part := _adf_text(item))).strip()
    if isinstance(value, dict):
        own_text = value.get("text") if isinstance(value.get("text"), str) else ""
        child_text = _adf_text(value.get("content", []))
        return " ".join(part for part in [own_text.strip(), child_text] if part).strip()
    return ""


class JiraCloudClient:
    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.jira_base_url or not config.jira_email or not config.jira_api_token:
            raise IntegrationConfigurationError(
                "JIRA_BASE_URL, JIRA_EMAIL, and JIRA_API_TOKEN are required for Jira import"
            )
        self._base_url = config.jira_base_url.rstrip("/")
        self._email = config.jira_email
        self._token = config.jira_api_token
        self._timeout = config.jira_timeout_seconds
        self._client = client

    async def search_issues(self, jql: str, max_results: int = 100) -> list[JiraIssue]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        issues: list[JiraIssue] = []
        next_page_token: str | None = None
        try:
            while len(issues) < max_results:
                page_size = min(100, max_results - len(issues))
                payload: dict[str, Any] = {
                    "jql": jql,
                    "maxResults": page_size,
                    "fields": ["summary", "description", "issuetype", "status", "updated"],
                }
                if next_page_token:
                    payload["nextPageToken"] = next_page_token
                response = await self._request(client, payload)
                for raw_issue in response.get("issues", []):
                    fields = raw_issue.get("fields") or {}
                    key = str(raw_issue.get("key") or "").strip()
                    summary = str(fields.get("summary") or "").strip()
                    if not key or not summary:
                        continue
                    issues.append(
                        JiraIssue(
                            key=key,
                            summary=summary,
                            description=_adf_text(fields.get("description")),
                            issue_type=(fields.get("issuetype") or {}).get("name"),
                            status=(fields.get("status") or {}).get("name"),
                            updated=fields.get("updated"),
                        )
                    )
                next_page_token = response.get("nextPageToken")
                if not next_page_token or response.get("isLast") is True:
                    break
            return issues[:max_results]
        finally:
            if owns_client:
                await client.aclose()

    async def _request(self, client: httpx.AsyncClient, payload: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(1, 4):
            try:
                response = await client.post(
                    f"{self._base_url}/rest/api/3/search/jql",
                    auth=(self._email, self._token),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json=payload,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 3:
                        await asyncio.sleep(min(2 ** (attempt - 1), 4))
                        continue
                response.raise_for_status()
                parsed = response.json()
                if not isinstance(parsed, dict):
                    raise ValueError("Jira response is not an object")
                return parsed
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= 3:
                    raise IntegrationProviderError("Jira request failed after 3 attempts") from exc
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
            except (httpx.HTTPStatusError, ValueError) as exc:
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "invalid"
                raise IntegrationProviderError(f"Jira returned {status} response") from exc
        raise IntegrationProviderError("Jira request did not complete")


class TestRepositoryClient:
    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.test_repository_base_url or not config.test_repository_token:
            raise IntegrationConfigurationError(
                "TEST_REPOSITORY_BASE_URL and TEST_REPOSITORY_TOKEN are required for repository delivery"
            )
        self._base_url = config.test_repository_base_url.rstrip("/")
        self._token = config.test_repository_token
        self._timeout = config.test_repository_timeout_seconds
        self._client = client

    async def upsert(
        self,
        test_case: RepositoryTestCase,
        *,
        repository: str,
        branch: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        payload = {
            "repository": repository,
            "branch": branch,
            "test_case": {
                "id": test_case.id,
                "version": test_case.version,
                "requirement_id": test_case.requirement_id,
                "scenario_id": test_case.scenario_id,
                "title": test_case.title,
                "description": test_case.description,
                "prerequisite": test_case.prerequisite,
                "priority": test_case.priority,
                "severity": test_case.severity,
                "category": test_case.category,
                "type": test_case.test_type,
                "steps": test_case.steps,
            },
        }
        try:
            for attempt in range(1, 4):
                try:
                    response = await client.put(
                        f"{self._base_url}/test-cases/{test_case.id}",
                        headers={
                            "Authorization": f"Bearer {self._token}",
                            "Content-Type": "application/json",
                            "Idempotency-Key": idempotency_key,
                        },
                        json=payload,
                    )
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 3:
                            await asyncio.sleep(min(2 ** (attempt - 1), 4))
                            continue
                    response.raise_for_status()
                    parsed = response.json() if response.content else {}
                    return parsed if isinstance(parsed, dict) else {}
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    if attempt >= 3:
                        raise IntegrationProviderError("Test repository request failed after 3 attempts") from exc
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
                except (httpx.HTTPStatusError, ValueError) as exc:
                    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else "invalid"
                    raise IntegrationProviderError(f"Test repository returned {status} response") from exc
        finally:
            if owns_client:
                await client.aclose()
        raise IntegrationProviderError("Test repository request did not complete")


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    provider: str,
    **kwargs: Any,
) -> httpx.Response:
    for attempt in range(1, 4):
        try:
            response = await client.request(method, url, **kwargs)
            if (response.status_code == 429 or response.status_code >= 500) and attempt < 3:
                await asyncio.sleep(min(2 ** (attempt - 1), 4))
                continue
            response.raise_for_status()
            return response
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt >= 3:
                raise IntegrationProviderError(f"{provider} request failed after 3 attempts") from exc
            await asyncio.sleep(min(2 ** (attempt - 1), 4))
        except httpx.HTTPStatusError as exc:
            raise IntegrationProviderError(f"{provider} returned {exc.response.status_code} response") from exc
    raise IntegrationProviderError(f"{provider} request did not complete")


def _delivery_reference(test_case: RepositoryTestCase) -> str:
    return f"ATG-{test_case.id}-V{test_case.version}"


class TestRailRepositoryClient:
    """Publishes immutable approved versions while making worker retries idempotent."""

    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        if (
            not config.test_repository_base_url
            or not config.testrail_username
            or not config.testrail_api_key
            or config.testrail_project_id is None
            or config.testrail_section_id is None
        ):
            raise IntegrationConfigurationError(
                "TestRail requires TEST_REPOSITORY_BASE_URL, TESTRAIL_USERNAME, TESTRAIL_API_KEY, "
                "TESTRAIL_PROJECT_ID, and TESTRAIL_SECTION_ID"
            )
        self._base_url = config.test_repository_base_url.rstrip("/")
        self._username = config.testrail_username
        self._api_key = config.testrail_api_key
        self._project_id = config.testrail_project_id
        self._section_id = config.testrail_section_id
        self._suite_id = config.testrail_suite_id
        self._timeout = config.test_repository_timeout_seconds
        self._client = client

    async def upsert(
        self,
        test_case: RepositoryTestCase,
        *,
        repository: str,
        branch: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del repository, branch, idempotency_key
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        reference = _delivery_reference(test_case)
        auth = (self._username, self._api_key)
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        suite = f"&suite_id={self._suite_id}" if self._suite_id is not None else ""
        lookup_url = (
            f"{self._base_url}/index.php?/api/v2/get_cases/{self._project_id}"
            f"&refs={quote(reference, safe='')}{suite}&limit=2"
        )
        payload = {
            "title": test_case.title,
            "refs": reference,
            "custom_preconds": test_case.prerequisite or "",
            "custom_steps_separated": [
                {
                    "content": str(step.get("action") or ""),
                    "expected": str(step.get("expected_result") or ""),
                }
                for step in test_case.steps
            ],
        }
        try:
            lookup = await _request_with_retry(
                client, "GET", lookup_url, provider="TestRail", auth=auth, headers=headers
            )
            parsed = lookup.json()
            if isinstance(parsed, dict):
                cases = parsed.get("cases") or []
            elif isinstance(parsed, list):
                cases = parsed
            else:
                cases = []
            matching = [case for case in cases if str(case.get("refs") or "") == reference]
            if len(matching) > 1:
                raise IntegrationProviderError("TestRail returned duplicate delivery references")
            if matching:
                target = f"{self._base_url}/index.php?/api/v2/update_case/{matching[0]['id']}"
            else:
                target = f"{self._base_url}/index.php?/api/v2/add_case/{self._section_id}"
            response = await _request_with_retry(
                client, "POST", target, provider="TestRail", auth=auth, headers=headers, json=payload
            )
            result = response.json() if response.content else {}
            if not isinstance(result, dict):
                raise IntegrationProviderError("TestRail returned an invalid response")
            return result
        except (ValueError, KeyError, TypeError) as exc:
            raise IntegrationProviderError("TestRail returned an invalid response") from exc
        finally:
            if owns_client:
                await client.aclose()


class XrayCloudRepositoryClient:
    """Publishes one Xray Test per internal approved version using a deterministic Jira label."""

    def __init__(self, config: Settings = settings, client: httpx.AsyncClient | None = None) -> None:
        if not config.xray_client_id or not config.xray_client_secret:
            raise IntegrationConfigurationError("XRAY_CLIENT_ID and XRAY_CLIENT_SECRET are required")
        self._client_id = config.xray_client_id
        self._client_secret = config.xray_client_secret
        self._auth_url = config.xray_auth_url
        self._graphql_url = config.xray_graphql_url
        self._timeout = config.test_repository_timeout_seconds
        self._client = client

    async def upsert(
        self,
        test_case: RepositoryTestCase,
        *,
        repository: str,
        branch: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        del idempotency_key
        project_key = repository.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,31}", project_key):
            raise IntegrationConfigurationError("Xray delivery requires a valid Jira project key as repository")
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            auth_response = await _request_with_retry(
                client,
                "POST",
                self._auth_url,
                provider="Xray",
                json={"client_id": self._client_id, "client_secret": self._client_secret},
            )
            token_value = auth_response.json()
            token = token_value if isinstance(token_value, str) else token_value.get("token", "")
            if not token:
                raise IntegrationProviderError("Xray authentication returned no token")
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            reference = _delivery_reference(test_case).lower()
            lookup_query = """
                query ExistingDelivery($jql: String!) {
                  getTests(jql: $jql, limit: 2) { results { issueId jira(fields: [\"key\"]) } }
                }
            """
            jql = f'project = "{project_key}" AND labels = "{reference}"'
            lookup = await self._graphql(client, headers, lookup_query, {"jql": jql})
            results = ((lookup.get("data") or {}).get("getTests") or {}).get("results") or []
            if len(results) > 1:
                raise IntegrationProviderError("Xray returned duplicate delivery labels")
            if results:
                return {"created": False, "test": results[0], "reference": reference}

            mutation = """
                mutation CreateDelivery($steps: [CreateStepInput], $folderPath: String, $jira: JSON!) {
                  createTest(
                    testType: {name: \"Manual\"}, steps: $steps,
                    folderPath: $folderPath, jira: $jira
                  ) { test { issueId jira(fields: [\"key\"]) } warnings }
                }
            """
            variables = {
                "steps": [
                    {
                        "action": str(step.get("action") or ""),
                        "result": str(step.get("expected_result") or ""),
                    }
                    for step in test_case.steps
                ],
                "folderPath": branch.strip() or None,
                "jira": {
                    "fields": {
                        "summary": test_case.title,
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": test_case.description}],
                                }
                            ],
                        },
                        "project": {"key": project_key},
                        "labels": [reference],
                    }
                },
            }
            result = await self._graphql(client, headers, mutation, variables)
            created = (result.get("data") or {}).get("createTest")
            if not created or not created.get("test"):
                raise IntegrationProviderError("Xray did not create the test")
            return {"created": True, **created, "reference": reference}
        except (ValueError, TypeError, AttributeError) as exc:
            raise IntegrationProviderError("Xray returned an invalid response") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def _graphql(
        self,
        client: httpx.AsyncClient,
        headers: dict[str, str],
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        response = await _request_with_retry(
            client,
            "POST",
            self._graphql_url,
            provider="Xray",
            headers=headers,
            json={"query": query, "variables": variables},
        )
        parsed = response.json()
        if not isinstance(parsed, dict):
            raise IntegrationProviderError("Xray returned an invalid GraphQL response")
        if parsed.get("errors"):
            raise IntegrationProviderError("Xray GraphQL operation failed")
        return parsed


def build_test_repository_client(
    config: Settings = settings,
    client: httpx.AsyncClient | None = None,
) -> RepositoryClient:
    provider = config.test_repository_provider.strip().lower()
    if provider == "generic":
        return TestRepositoryClient(config, client)
    if provider in {"xray", "xray_cloud"}:
        return XrayCloudRepositoryClient(config, client)
    if provider == "testrail":
        return TestRailRepositoryClient(config, client)
    raise IntegrationConfigurationError(f"Unsupported TEST_REPOSITORY_PROVIDER: {provider}")
