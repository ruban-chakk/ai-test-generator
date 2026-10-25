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
- Every endpoint below requires authentication. Global roles are `reviewer`, `tester`, `test_lead`,
  `product_manager`, `approver`, and `admin`; project
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
- `POST /test-cases/import-file` — import bounded historical test cases from JSON or CSV after their referenced
  requirements exist. Stable requirement/scenario/case external identities make identical reimports idempotent;
  conflicting content is rejected. Each case, step set, immutable version, approval record, audit record, and
  version-index outbox event is committed atomically.
- `GET /requirements/{requirement_id}` — retrieve a requirement, nested scenarios, cases, and steps.
- `GET /requirements/{requirement_id}/versions` — list immutable requirement content snapshots and their stable
  versioned vector identifiers.
- `POST /requirements/{requirement_id}/generate` — run configured OpenAI-compatible generation with
  project-filtered Pinecone retrieval and persist a schema-validated draft. Returns `503` if unconfigured and `502`
  on provider failure; it never substitutes canned output. Every generated test case atomically queues a durable,
  version-bound quality evaluation.
- `POST /requirements/{requirement_id}/scenarios`, `POST /scenarios/{scenario_id}/test_cases`, and
  `POST /test_cases/{test_case_id}/steps` — manually add draft artifacts.

## Review, feedback, and quality

- `POST /requirements/{id}/approve|reject`
- `POST /scenarios/{id}/approve|reject`
- `POST /test_cases/{id}/approve|reject`
- `POST /requirements/{id}/test-cases/bulk-approve` — apply the same staged approval operation to all cases in a
  requirement, one scenario, or an explicit `test_case_ids` selection. Returns per-case `approved`, `in_review`,
  `blocked`, or `failed` outcomes; evaluation gates and separation-of-duties rules remain enforced per case.
- `GET /test_cases/{id}/versions`
- `POST /feedback`, `GET /feedback?target_level=&target_id=`
- `POST /feedback` accepts an optional `quality_evaluation_id`; the evaluation must belong to the same target.
- The web UI sends `quality_evaluation_id` only when the reviewer explicitly checks `Include DeepEval evaluation
  data with this feedback`. When unchecked, no evaluation record, metrics, justifications, or issues enter the
  revision prompt.
- `POST /feedback/revise` — resolve feedback. `revise` and `generate_new` call the configured structured generator
  with the requirement, current target, linked DeepEval evidence, feedback, and project-scoped retrieved context. Deprecation requires an
  approver. Processing the same feedback again returns its existing resolution.
- `GET /revisions`, `GET /approvals`, `GET /audit`
- `GET|PUT /projects/{project_id}/approval-workflow` — read or configure ordered, role-bound approval stages and
  the version-bound evaluation gate. Policy updates affect new workflow runs; active runs retain their snapshot.
- `GET /test_cases/{test_case_id}/approval-workflow` — inspect the evaluation, current stage, decisions, and exact
  content digest for the current test-case version.
- Test-case `approve` and `reject` actions now record a decision at the current stage. Repository/index delivery is
  queued only after a passing evaluation and completion of every required approval stage.
- `POST|GET /projects/{project_id}/knowledge-documents` — add/list project-scoped supporting text that is chunked,
  embedded, and retrieved as untrusted evidence by feedback revision and LLM evaluation.
- `GET /validate/{target_level}/{target_id}`, `POST /quality/{target_level}/{target_id}`, `GET /quality`
- `PUT /test_cases/{test_case_id}` — replace editable metadata and the complete ordered step list using an
  `expected_version` optimistic-concurrency check. A successful edit creates a new draft version, preserves prior
  immutable approved snapshots, writes audit evidence, and queues automatic evaluation.

Approved cases are locked and versioned. Vector indexing is queued in the same PostgreSQL transaction through the
outbox; it is not a synchronous database-plus-provider dual write. The worker indexes the immutable approved
version snapshot under `test_case:<case-id>:v<version>`, so later edits cannot alter historical vector content.
Automatic evaluation uses the same outbox with `test_case.quality_evaluation_requested`; the resulting evaluation
stores a unique `source_event_id`, so worker retries cannot create duplicate judge records.

## Search and semantic impact

- `GET /search?project_id=&query=&mode=&entity_type=&test_case_approval=&limit=` — project-filtered search over
  requirements, current test cases in every workflow state, and feedback. `test_case_approval` is `all` (default),
  `approved`, or `unapproved`, and applies only to test-case results. `mode` is `semantic` (the backward-compatible
  API default), `keyword`, or `hybrid`.
  Keyword mode uses PostgreSQL full-text search against canonical records. Hybrid mode uses reciprocal-rank fusion
  to combine PostgreSQL keyword ranks with Pinecone semantic ranks without treating their raw scores as comparable.

- `GET /requirements/{requirement_id}/impact`
- `POST /impact/analyze` with `project_id`, `text`, and optional project-consistent `context_ids`.
- `GET /impact`
- `POST /impact/test_cases/{id}/deprecate|review-update`

The service uses embedding cosine scores from Pinecone. Project approvers can submit labeled duplicate/update/
unrelated examples through `POST /impact/calibrations`; an explicit apply flag activates measured project
thresholds. Deprecation recommendations remain conservative and require human review.

- `POST /impact/calibrations` — evaluate an idempotently identified labeled dataset and optionally apply thresholds.
- `GET /impact/calibrations?project_id=` — list aggregate calibration evidence without retaining raw labels.

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
configured generic HTTP, Xray Cloud, TestRail, or Zephyr Cloud adapter; completion is recorded only after all deliveries succeed.

- `GET /integrations/runs` and `GET /integrations/test-repo/sync` are admin-only run history endpoints.

## Operations

- `POST /nlp/cleanup` — deterministic text cleanup.
- `POST /evals/run`, `GET /evals` — rule-based quality suite and history.
- `GET /monitoring/summary` — database counters.
- `GET /operations/dependencies` — sanitized live provider probes.
- `GET /operations/outbox`, `POST /operations/outbox/{id}/retry` — inspect and safely retry delivery failures.
- `python scripts/backfill_vectors.py [--project-id <uuid>] [--all]` — operator command that reconciles missing
  requirement, feedback, approved-case, and immutable-version indexing events without calling providers in the
  database transaction.
- `GET /operations/alerts`, `POST /operations/alerts/{id}/acknowledge` — project-aware failure notifications,
  delivery state, and acknowledgement evidence.
- `POST /governance/policies`, `GET /governance/policies` — governance policy storage.
- `GET|PUT /compliance/projects/{project_id}/profile` — project frameworks, retention, export, pseudonymization,
  and mandatory approval-note controls.
- `GET /compliance/projects/{project_id}/evidence` — bounded, retention-aware, SHA-256-addressed evidence export with explicit `is_complete` and `truncated_sections` metadata.
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

Live provider acceptance requires tenant credentials and is run with `scripts/acceptance_probe.py`; secrets and
tenant-specific acceptance results are deliberately not committed.
# Configurable imports

- `GET /api/v1/import-mappings?project_id={uuid}` lists reusable project-scoped mapping profiles.
- `POST /api/v1/import-mappings` creates a validated requirement or test-case mapping profile.
- `PUT /api/v1/import-mappings/{profile_id}` updates a profile without changing its artifact type.
- `POST /api/v1/imports/mapped/preview` validates a JSON/CSV file and returns mapped samples and bounded issues.
- `POST /api/v1/imports/mapped` imports the previewed format into canonical PostgreSQL records and queues vector events.

Mapping transforms are selected from an allow-list (`string`, case normalization, integer/version conversion,
ISO/Excel dates, Jira-style references, and numbered test steps). Profiles never contain executable expressions.
### Scoped prompt configuration

Administrators can manage the three prompt purposes (`test_case_generation`,
`feedback_regeneration`, and `test_case_evaluation`) through:

- `GET/PUT /api/v1/admin/prompt-config/{prompt_key}?scope_type=app|organization|project&scope_id=...`

Published values resolve project > organization > application defaults. Every
write increments the prompt version and records `old_value`, `new_value`, the
actor, and timestamp in the audit log. Prompt placeholders must be declared in
the `variables` list; platform safety instructions are always prepended.
