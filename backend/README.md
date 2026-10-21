# Backend Setup

## Install dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e '.[test]'
```

## Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The Compose PostgreSQL service is exposed on host port `5433` by default to avoid colliding with a locally
installed PostgreSQL. Override it with `POSTGRES_PORT`; containers continue to use port `5432` internally.

## Environment

Copy `.env.example` to `.env` and configure the database and Pinecone values.

Generation requires an OpenAI-compatible chat/embedding endpoint and a Pinecone index host. Configure
`LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, `EMBEDDING_MODEL`, `PINECONE_API_KEY`, and `PINECONE_HOST`.
`PINECONE_HOST` must be the data-plane host for an existing index; Compose does not emulate Pinecone locally.
The generation endpoint returns `503` when providers are not configured and `502` when a configured provider
fails; it never substitutes hard-coded generated content.

Set `AUTH_JWT_SECRET` to at least 32 random characters. Create the first administrator after applying the
database migration:

```bash
python scripts/create_user.py --username admin --email admin@example.com --role admin
```

The browser uses an HttpOnly, SameSite session cookie. API automation may send the access token returned by
`POST /api/v1/auth/token` as a Bearer token. Running the user script with `--reset-existing` revokes that
user's existing sessions.

Generic OIDC login is enabled with `OIDC_ENABLED=true` plus explicit issuer, client, authorization, token, and
JWKS settings. Configure `OIDC_ALLOWED_EMAIL_DOMAINS` before enabling optional auto-provisioning. Provisioned
users receive the reviewer role; identity-provider claims cannot grant application roles or project membership.

File ingestion accepts only bounded UTF-8 `.txt`, `.md`, `.csv`, and `.json` documents. Configure
`UPLOAD_MAX_BYTES` and `UPLOAD_MAX_REQUIREMENTS`. The importer validates structure, rejects binary content,
stores only normalized requirements and a content hash, and never persists the raw uploaded document.

Approved test cases and submitted feedback are indexed through a transactional outbox. Run one batch locally:

```bash
python scripts/process_outbox.py --once
```

Or run the continuous worker with Compose after configuring the LLM and Pinecone credentials:

```bash
docker compose --profile workers up -d indexer
```

Outbox rows contain only stable entity identifiers; the worker loads current canonical content from PostgreSQL.
Pinecone upserts use stable vector IDs, so recovery after a worker crash or duplicate delivery is idempotent.

## External integrations

Jira Cloud import uses the enhanced `POST /rest/api/3/search/jql` API with JQL pagination. Configure
`JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`; imported issues are upserted by project and Jira issue key,
then queued for vector indexing. Jira text is treated as untrusted content and credentials are never persisted in
run, audit, or outbox records.

Repository delivery is asynchronous and uses the same outbox worker. Configure `TEST_REPOSITORY_BASE_URL` and
`TEST_REPOSITORY_TOKEN`, leaving `TEST_REPOSITORY_PROVIDER=generic`. The adapter sends an authenticated
`PUT {TEST_REPOSITORY_BASE_URL}/test-cases/{test_case_id}` request with this contract:

```json
{
  "repository": "qa-cases",
  "branch": "main",
  "test_case": {
    "id": "uuid",
    "version": 1,
    "requirement_id": "uuid",
    "scenario_id": "uuid",
    "title": "...",
    "description": "...",
    "prerequisite": null,
    "priority": "high",
    "severity": "major",
    "category": "security",
    "type": "negative",
    "steps": [{"step_number": 1, "action": "...", "expected_result": "..."}]
  }
}
```

The request carries `Authorization: Bearer ...` and a stable `Idempotency-Key`. The receiving repository service
must implement idempotent upsert semantics for that key. HTTP 429, 5xx, timeouts, and network failures are retried;
the sync run is only marked complete after every queued delivery succeeds.

For Xray Cloud, set `TEST_REPOSITORY_PROVIDER=xray_cloud`, `XRAY_CLIENT_ID`, and `XRAY_CLIENT_SECRET`.
The `repository` field in the sync request is the Jira project key and `branch` is the optional Xray repository
folder. Each internal test-case version gets a deterministic Jira label; retry lookup occurs before `createTest`.

For TestRail, set `TEST_REPOSITORY_PROVIDER=testrail`, `TEST_REPOSITORY_BASE_URL`, `TESTRAIL_USERNAME`,
`TESTRAIL_API_KEY`, `TESTRAIL_PROJECT_ID`, `TESTRAIL_SECTION_ID`, and optionally `TESTRAIL_SUITE_ID`.
The adapter looks up a deterministic reference before calling `add_case` or `update_case`, preventing ordinary
worker retries from creating duplicate cases.

For Zephyr Cloud, set `TEST_REPOSITORY_PROVIDER=zephyr_cloud`, `ZEPHYR_API_TOKEN`, and optionally
`ZEPHYR_BASE_URL`. The repository value supplied by the sync request is the Zephyr project key. Each immutable
approved version uses a stable `ATG-...-V...` reference; retries find that version and overwrite its step script
instead of creating another test case.

The admin operations API exposes sanitized dependency status and outbox retry controls. `/health/live` is a
process check; `/health/ready` includes a database query. Provider probes never return credentials or response
bodies.

## Automated execution

Configure `EXECUTION_RUNNER_BASE_URL`, `EXECUTION_RUNNER_TOKEN`, and optionally
`EXECUTION_RUNNER_TIMEOUT_SECONDS`. Approvers can queue approved, immutable test-case versions through
`POST /api/v1/executions`. Delivery uses the transactional outbox and sends:

```json
{
  "environment": "staging",
  "test_case": {
    "id": "uuid",
    "version": 2,
    "title": "...",
    "description": "...",
    "prerequisite": "...",
    "steps": [{"step_number": 1, "action": "...", "expected_result": "..."}]
  }
}
```

The runner endpoint is `POST {EXECUTION_RUNNER_BASE_URL}/executions`. It receives bearer authentication and a
stable `Idempotency-Key`, and must return a terminal `passed` or `failed` status, an optional `external_run_id`,
and a JSON `result`. Network/provider failures are retried without storing provider response bodies; exhausted
deliveries become `error` runs and remain visible to operations staff.

Execution failures and retry-exhausted outbox events create deduplicated alerts in PostgreSQL. Configure
`ALERT_WEBHOOK_URL`, `ALERT_WEBHOOK_TOKEN`, and optionally `ALERT_WEBHOOK_TIMEOUT_SECONDS` to route them to an
external incident receiver. Webhook delivery is itself outbox-backed and retry-safe; alerts remain visible and
acknowledgeable through `/api/v1/operations/alerts` even when no webhook is configured or delivery fails.

Rate limits use shared PostgreSQL counters, so limits apply across API replicas rather than resetting per process.
Configure `API_RATE_LIMIT_PER_MINUTE`, `AUTH_RATE_LIMIT_PER_MINUTE`, and `RATE_LIMIT_ENABLED`. Authenticated limits
are keyed by a one-way hash of user ID; password and OIDC entry limits are keyed by a one-way hash of the direct
client address. Exceeded requests return `429` with `Retry-After: 60`.

## Database migration

Apply all managed migrations with Alembic:

```bash
alembic upgrade head
```

The baseline migration is intentionally idempotent so it can adopt databases initialized by the earlier SQL
workflow. It has no destructive automatic downgrade; production rollback requires restoring a verified backup
into a replacement database.

## Tests

```bash
pytest -q tests
```

PostgreSQL integration tests use `TEST_POSTGRES_DSN`; tests that require it skip when the variable is absent.

## Calibration and compliance

Project approvers can submit at least ten labeled semantic scores to `/api/v1/impact/calibrations`. All three
labels (`duplicate`, `update`, `unrelated`) are required. The service records the dataset digest, distribution,
thresholds, confusion matrix, accuracy, and macro F1, but not the raw labeled rows. Applying a run activates its
ordered thresholds for subsequent impact analysis.

Project compliance profiles control framework labels, evidence retention, export enablement, stable actor
pseudonymization, and mandatory approval notes. Evidence exports are project-scoped, bounded, SHA-256 addressed,
and logged in the audit trail. Every export reports `is_complete` and `truncated_sections`; consumers must not
treat a truncated response as a complete audit package.

## Load, recovery, and live acceptance

Run a bounded latency gate against liveness or an authenticated standard-query endpoint:

```bash
python scripts/load_smoke.py --url http://127.0.0.1:8000/health/live --requests 1000 --concurrency 50
```

The recovery drill only permits a distinct local database whose name ends in `_drill`. It replaces objects in
that disposable target, verifies the restored schema and Alembic revision, and prints a redacted JSON report:

```bash
DR_SOURCE_DSN='postgresql://...' DR_TARGET_DSN='postgresql://.../ai_test_gen_drill' \
  python scripts/disaster_recovery_drill.py --allow-target-reset
```

With tenant credentials present in the normal environment, run the sanitized provider gate:

```bash
python scripts/acceptance_probe.py --require llm,pinecone,jira,test_repository,oidc
```
