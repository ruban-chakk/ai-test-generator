# Implemented API specification

Base URL: `/api/v1`. JSON responses are returned directly rather than inside a resource envelope.

## Authentication and authorization

- `GET /auth/config` advertises whether enterprise SSO is enabled.
- `GET /auth/oidc/login` and `GET /auth/oidc/callback` implement generic OIDC authorization-code login with
  signed state, nonce validation, issuer/audience/signature checks, and optional allowlisted auto-provisioning.
- `POST /auth/token` accepts OAuth2 password-form fields and sets a revocable HttpOnly, SameSite session cookie.
- `GET /auth/me` returns the authenticated database user.
- `POST /auth/logout` revokes the current token version and clears the cookie.
- Automation may use the returned JWT as a Bearer token.
- Every endpoint below requires authentication. Global roles are `reviewer`, `approver`, and `admin`; project
  memberships further restrict project resources. Browser state-changing cookie requests are Origin checked.
- Client fields such as `created_by`, `requested_by`, and `approved_by` are compatibility inputs only. The server
  always attributes state changes to the authenticated principal.

## Projects and requirements

- `GET /projects` — list projects visible to the caller, with requirement/test-case counts.
- `POST /projects` — create a project (global admin).
- `GET /projects/{project_id}/members` — list memberships (project admin).
- `PUT /projects/{project_id}/members` — add or update a membership (project admin).
- `GET /requirements?project_id=&status=&source=&search=&limit=&offset=` — list visible requirements.
- `POST /requirements` — create a project-scoped requirement.
- `POST /requirements/import-file` — import bounded UTF-8 TXT, Markdown, CSV, or JSON requirements; file content
  is treated as untrusted and raw documents are not retained.
- `GET /requirements/{requirement_id}` — retrieve a requirement, nested scenarios, cases, and steps.
- `POST /requirements/{requirement_id}/generate` — run configured OpenAI-compatible generation with
  project-filtered Pinecone retrieval and persist a schema-validated draft. Returns `503` if unconfigured and `502`
  on provider failure; it never substitutes canned output.
- `POST /requirements/{requirement_id}/scenarios`, `POST /scenarios/{scenario_id}/test_cases`, and
  `POST /test_cases/{test_case_id}/steps` — manually add draft artifacts.

## Review, feedback, and quality

- `POST /requirements/{id}/approve|reject`
- `POST /scenarios/{id}/approve|reject`
- `POST /test_cases/{id}/approve|reject`
- `GET /test_cases/{id}/versions`
- `POST /feedback`, `GET /feedback?target_level=&target_id=`
- `POST /feedback/revise` — resolve feedback. `revise` and `generate_new` call the configured structured generator
  with the requirement, current target, feedback, and project-scoped retrieved context. Deprecation requires an
  approver. Processing the same feedback again returns its existing resolution.
- `GET /revisions`, `GET /approvals`, `GET /audit`
- `GET /validate/{target_level}/{target_id}`, `POST /quality/{target_level}/{target_id}`, `GET /quality`

Approved cases are locked and versioned. Vector indexing is queued in the same PostgreSQL transaction through the
outbox; it is not a synchronous database-plus-provider dual write.

## Semantic impact

- `GET /search?project_id=&query=&entity_type=&limit=` — project-filtered semantic search over indexed artifacts.

- `GET /requirements/{requirement_id}/impact`
- `POST /impact/analyze` with `project_id`, `text`, and optional project-consistent `context_ids`.
- `GET /impact`
- `POST /impact/test_cases/{id}/deprecate|review-update`

The service uses embedding cosine scores from Pinecone. Duplicate classification uses a `0.80` threshold; update
and deprecation recommendations remain heuristics that require human review and dataset calibration.

## External integrations

### `POST /integrations/jira/import`

Admin-only body:

```json
{"project_id":"uuid","jql":"project = QA ORDER BY updated DESC","max_results":100}
```

The adapter calls Jira Cloud `POST /rest/api/3/search/jql`, follows `nextPageToken`, upserts by
`(project_id, issue_key)`, and queues vector indexing. The response is an integration run with truthful
`running`, `completed`, or `failed` state.

### `POST /integrations/test-repo/sync`

Approver/admin body:

```json
{"project_id":"uuid","repository":"qa-cases","branch":"main"}
```

The endpoint queues approved cases and returns a repository sync run. The outbox worker delivers through the
configured generic HTTP, Xray Cloud, or TestRail adapter; completion is recorded only after all deliveries succeed.

- `GET /integrations/runs` and `GET /integrations/test-repo/sync` are admin-only run history endpoints.

## Operations

- `POST /nlp/cleanup` — deterministic text cleanup.
- `POST /evals/run`, `GET /evals` — rule-based quality suite and history.
- `GET /monitoring/summary` — database counters.
- `GET /operations/dependencies` — sanitized live provider probes.
- `GET /operations/outbox`, `POST /operations/outbox/{id}/retry` — inspect and safely retry delivery failures.
- `POST /governance/policies`, `GET /governance/policies` — governance policy storage.
- `GET /repository/test_cases` — list cases visible to the caller.

Outside the API prefix, `GET /health/live` is a process liveness check and `GET /health/ready` verifies database
readiness.

## Automated execution

- `GET /executions/candidates?project_id=` — approved test-case versions visible to the caller.
- `POST /executions` — queue one or more approved cases for an environment using a caller-generated request UUID.
- `GET /executions?project_id=&status=&limit=` and `GET /executions/{run_id}` — project-scoped run history.

Execution delivery is transactional-outbox backed. The configured runner receives a stable idempotency key and
must return a terminal result; the application records passed, failed, or exhausted-provider-error state.

## Error semantics

- `401`: missing, invalid, expired, or revoked authentication.
- `403`: authenticated but insufficient global/project role or rejected Origin.
- `404`: absent or non-visible resource (used to avoid project enumeration).
- `409`: locked/conflicting state.
- `422`: invalid input or governance validation failure.
- `502`: configured external provider failed.
- `503`: required external provider or secret is not configured.

Not implemented: Zephyr Cloud delivery, alert routing, distributed rate limiting,
tenant-specific compliance exports, semantic threshold calibration, load certification, and disaster-recovery drills.
