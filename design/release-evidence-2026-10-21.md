# Release Evidence

**Evidence date:** 2026-10-21
**Branch:** `feature/complete-enterprise-workflows`
**Verified source commit:** `6229e6dde45022013086302ff0ac03e1c9421631` plus the uncommitted workspace changes listed below

## Outcome

The application contains the primary requirement-to-test workflow and the requested enterprise operations
capabilities. Local automated verification, a bounded load gate, and a database recovery drill pass. Production
certification is not complete because the configured Pinecone index uses a document schema, while the application
supplies embeddings and therefore requires a bring-your-own-vectors index.

## Capability evidence

| Capability | Implementation evidence | Verification evidence |
|---|---|---|
| Automated execution | Execution API, durable outbox delivery, immutable approved-version payloads, idempotency keys, and run status tracking | Backend execution and outbox tests in the full suite |
| Zephyr Cloud connector | Provider-specific authentication, deterministic version references, retry lookup, and step synchronization | Repository adapter tests in the full suite |
| Alert routing | Deduplicated database alerts and retry-safe webhook delivery | Alert/outbox tests and Operations component tests |
| Distributed rate limiting | PostgreSQL-backed counters shared by API replicas | Rate-limit tests in the full suite |
| Semantic calibration | Labeled dataset validation, applied thresholds, digest, confusion matrix, accuracy, and macro F1 evidence | Calibration tests in the full suite; real tenant labels still required |
| Tenant compliance/export | Project compliance profiles, pseudonymized actors, bounded exports, completeness flags, and SHA-256 digest | Compliance tests in the full suite |
| Frontend/browser coverage | Component tests plus Playwright critical paths, including three-mode Search | 8 component tests and 3 Playwright tests passed |
| Load/recovery tooling | Bounded load command and guarded PostgreSQL backup/restore drill | Local results below |
| Live workflow acceptance | Sanitized command covering create/index/generate/approve/index/impact with provider preflight | Mocked acceptance tests pass; real run is blocked by Pinecone configuration |
| Historical test-case ingestion | Bounded JSON/CSV parser, stable external identities, atomic scenario/case/step/version/approval/audit/outbox persistence, conflict detection, and Operations UI | Parser, PostgreSQL idempotency/atomicity, and Operations component tests |
| Vector reconciliation and immutable versions | Operator backfill command plus version-specific outbox events loaded from immutable snapshots | PostgreSQL backfill and outbox snapshot tests |

## Verification results

| Gate | Result |
|---|---|
| Backend suite | 71 tests passed |
| Frontend component suite | 3 files, 9 tests passed |
| Frontend production build | Passed; main JS 249.89 kB, CSS 16.72 kB |
| Playwright critical paths | 3 tests passed |
| Frontend dependency audit | 0 high-severity vulnerabilities reported |
| Python compilation | Passed |
| Alembic migration state | `20261021_0010 (head)` |
| Git whitespace validation | Passed |

## Performance and recovery

The local liveness load gate completed 1,000 requests with 1,000 successes and no failures at 660.37 requests per
second. Observed latency was 58.28 ms p50, 124.97 ms p95, and 136.92 ms p99.

The guarded PostgreSQL recovery drill restored 26 tables into the disposable `ai_test_gen_drill` database and
verified Alembic revision `20261021_0010`. Backup took 3.653 seconds and restore took 28.239 seconds. The disposable
database was removed after verification.

These measurements are local smoke evidence, not production capacity or disaster-recovery certification.

## External dependency acceptance

| Dependency | Observed state | Remaining action |
|---|---|---|
| LLM | Healthy | Exercise representative content and monitor cost/quality |
| Pinecone | Misconfigured | Create/select a dense 1536-dimension bring-your-own-vectors index without integrated embedding or document schema; update index name and host |
| Jira | Configured but unhealthy | Correct or validate tenant credentials/permissions and rerun the probe |
| Execution runner | Configured but unreachable | Deploy or correct the runner endpoint and rerun acceptance |
| OIDC | Not configured | Configure and test only if federated login is required |
| Xray, TestRail, Zephyr | Not configured | Configure and test the selected repository provider only |
| Alert webhook | Not live-certified | Configure the receiver and verify delivery/acknowledgement if external routing is required |

The original Pinecone health probe only checked the data-plane statistics endpoint and could therefore report the
document-schema index as healthy. The updated probe checks control-plane configuration, vector type, embedding
dimension, host ownership, readiness, and the data plane. Provider error bodies and credentials are not returned.

## Live workflow blocker

The attempted synthetic live workflow used a disposable PostgreSQL database and isolated Pinecone namespace. The
requirement indexing event failed before generation because Pinecone rejected the raw-vector upsert: document-schema
indexes require the document API. No vectors were written. The local process and worker were stopped and the
disposable database was removed.

After configuring a compatible index, run:

```bash
cd backend
LIVE_ACCEPTANCE_BASE_URL='https://testgen.example.com' \
LIVE_ACCEPTANCE_USERNAME='acceptance-admin' \
LIVE_ACCEPTANCE_PASSWORD='...' \
python scripts/live_workflow_acceptance.py \
  --project-id '<dedicated-project-uuid>' \
  --allow-retained-artifacts
```

The command checks LLM and Pinecone health before creating artifacts, intentionally retains successful synthetic
artifacts as evidence, and never includes credentials or provider response bodies in its output.

## Uncommitted workspace scope

The workspace includes the Search page and backend search changes, migrations through `20261021_0010`, historical
test-case ingestion, vector reconciliation and immutable requirement/test-case version indexing, the dated gaps and release-evidence
documents, Pinecone compatibility validation, and live-workflow acceptance tooling. Pre-existing
untracked `.postqode/` and root `scripts/` directories remain outside this evidence scope and must be reviewed before
any broad commit.
