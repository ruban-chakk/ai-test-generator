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
The index must be a bring-your-own-vectors dense index without integrated embedding or a document schema. Its
dimension must equal `EMBEDDING_DIMENSION` (`1536` for the default `text-embedding-3-small` model), and its metric
should be cosine. The dependency probe validates the index type, dimension, host, readiness, and data plane before
live workflow acceptance starts.
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
`UPLOAD_MAX_BYTES`, `UPLOAD_MAX_REQUIREMENTS`, and `UPLOAD_MAX_TEST_CASES`. The importer validates structure, rejects binary content,
stores only normalized requirements and a content hash, and never persists the raw uploaded document.

Historical test cases can be imported from the Operations page or `POST /api/v1/test-cases/import-file`. Import
their referenced requirements first; each case identifies one by `requirement_external_id`. JSON accepts an array
or an object with a `test_cases` array. CSV uses the same fields, with `steps` encoded as a JSON array. A minimal
JSON record is:

```json
{
  "external_id": "TC-101",
  "requirement_external_id": "REQ-10",
  "scenario_external_id": "SC-10",
  "scenario_title": "Password reset links",
  "scenario_description": "Validate secure password reset link handling.",
  "title": "Reject an expired reset link",
  "description": "An expired link must not change credentials.",
  "priority": "high",
  "severity": "major",
  "status": "approved",
  "version": 3,
  "approved_at": "2025-01-02T03:04:05Z",
  "approved_by": "legacy-reviewer",
  "steps": [
    {
      "step_number": 1,
      "action": "Open an expired password reset link.",
      "expected_result": "The application rejects the expired link."
    }
  ]
}
```

External IDs are unique within a requirement. Reimporting identical content is a no-op for canonical records;
reusing an identity with different content returns a conflict instead of silently overwriting an approved case.
The import transaction stores the case, steps, immutable version, approval evidence, audit record, and vector
outbox event atomically. Provider calls remain asynchronous.

The project Search page supports `hybrid`, `semantic`, and `keyword` modes through `GET /api/v1/search`.
Semantic mode uses project-filtered Pinecone retrieval. Keyword mode uses PostgreSQL full-text search over
requirements, approved test cases, and feedback. Hybrid mode combines both ranked lists with reciprocal-rank
fusion and returns the semantic score, keyword score, and matched fields as ranking evidence. Keyword retrieval
uses English stemming and typo-tolerant trigram matching. Search supports offset pagination, project synonym/RRF
policies, typed custom-field filters and facets, saved searches, click/relevance judgments, analytics, and automatic
keyword fallback when the semantic provider is unavailable. Apply the latest Alembic migration to install the
supporting GIN indexes and `pg_trgm` extension.

Approved test cases and submitted feedback are indexed through a transactional outbox. Run one batch locally:

```bash
python scripts/process_outbox.py --once
```

Or run the continuous worker with Compose after configuring the LLM and Pinecone credentials:

```bash
docker compose --profile workers up -d indexer
```

Outbox rows contain only stable entity identifiers. Requirement and feedback events load current canonical content;
requirement and approved-case events load immutable version snapshots. Pinecone upserts use stable versioned vector
IDs, so older requirement and approved test-case versions remain searchable and recovery after a worker crash or
duplicate delivery is idempotent. Jira content changes increment the requirement version; unchanged issues are not
re-indexed.

To queue vectors for existing PostgreSQL records that never received an indexing event, run the idempotent
reconciliation command. By default it selects requirements and feedback without vector IDs plus approved test cases
that are not marked indexed. `--all` deliberately requeues every vectorizable record and is useful after rebuilding
or replacing a Pinecone index:

```bash
python scripts/backfill_vectors.py --project-id '<project-uuid>'
python scripts/backfill_vectors.py --project-id '<project-uuid>' --all
python scripts/process_outbox.py --once
```

The command only commits canonical vector identifiers, audit evidence, and outbox intents. Provider calls remain in
the worker, so a database transaction is never coupled to a Pinecone request.

Logical requirement sections and test steps are embedded as bounded parent/child chunks. The durable
`vector_chunks` inventory reconciles stale children whenever content shrinks. Run a one-off namespace audit or the
scheduled worker to detect missing/orphan vectors and capture Pinecone vector-count/storage estimates:

```bash
python scripts/maintain_vectors.py --no-repair-missing
python scripts/maintain_vectors.py --repair-missing
# Only for a namespace exclusively owned by this app:
python scripts/maintain_vectors.py --repair-missing --delete-orphans
```

Compose's `vector-maintenance` worker repeats this audit using `VECTOR_MAINTENANCE_INTERVAL_SECONDS`. Orphan
deletion defaults off and is rejected for project-scoped audits.

## External integrations

Jira Cloud import uses the enhanced `POST /rest/api/3/search/jql` API with JQL pagination. Configure
`JIRA_BASE_URL`, `JIRA_EMAIL`, and `JIRA_API_TOKEN`; imported issues are upserted by project and Jira issue key,
then queued for vector indexing. Jira text is treated as untrusted content and credentials are never persisted in
run, audit, or outbox records. The Operations page can create durable Jira delta schedules; run the
`integration-scheduler` Compose worker to process them.

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
python scripts/acceptance_probe.py --require llm,pinecone,jira,xray,testrail,zephyr,oidc,execution_runner
```

To certify the complete API and worker path, use a dedicated acceptance project or disposable environment. The
command creates synthetic artifacts and intentionally retains them as audit evidence. Supply the password through
an environment variable so it is not exposed in command history:

```bash
LIVE_ACCEPTANCE_BASE_URL='https://testgen.example.com' \
LIVE_ACCEPTANCE_USERNAME='acceptance-admin' \
LIVE_ACCEPTANCE_PASSWORD='...' \
python scripts/live_workflow_acceptance.py \
  --project-id '<dedicated-project-uuid>' \
  --allow-retained-artifacts
```

The command verifies requirement creation and indexing, live LLM generation, requirement/scenario/test-case
approval, approved-case indexing, and impact analysis. It fails if the outbox worker does not complete either
indexing event within the configured wait period and never includes credentials or provider response bodies in
its report.

# Company-specific import mappings

The Operations page can save project-scoped mapping profiles for JSON or CSV requirements and historical test cases.
Use **Preview mapping** before import. Canonical fields are validated, selected custom fields are retained in PostgreSQL,
and their text is included in the immutable embedding artifact sent through the transactional outbox.

Mapped imports default to a 10 MB source limit and 20,000 mapped records. Configure these with
`MAPPED_UPLOAD_MAX_BYTES` and `MAPPED_IMPORT_MAX_RECORDS`.

For larger top-level JSON arrays, JSONL/NDJSON, or CSV files, queue a resumable import job. Files are streamed into a
private spool, processed transactionally in checkpointed batches, and removed only after completion. Defaults are
250 MB, 1,000,000 records, and 250 records per transaction (`MAPPED_JOB_*`). Mapping profiles are immutable,
versioned, and rollbackable; a job freezes the selected revision. Typed custom fields support required/default,
enum, regex, length, index, and semantic-weight policies.

Set test-case `options.unresolved_reference_policy` to `stage` to preserve records whose story key is not yet
present. They appear in Operations and automatically reconcile when a later mapped or Jira requirement delta
introduces that key. `skip` remains available when intentional data loss is acceptable; `reject` fails the import.
