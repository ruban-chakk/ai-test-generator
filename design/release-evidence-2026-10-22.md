# Release Evidence

**Evidence date:** 2026-10-22
**Branch:** `feature/complete-enterprise-workflows`

## Automated gates

| Gate | Result |
|---|---|
| Backend suite with PostgreSQL | 88 passed |
| Frontend component suite | 3 files, 9 tests passed |
| Frontend production build | Passed; JS 267.31 kB, CSS 17.50 kB |
| Python compilation | Passed |
| Docker Compose validation | Passed |
| Alembic migration | `20261022_0017` applied |

## Live workflow evidence

The acceptance command used the configured OpenAI-compatible LLM and the BYOV Pinecone index. It created a
disposable project and retained the project artifacts as audit evidence. The temporary administrator credential
was removed immediately after the run.

| Field | Evidence |
|---|---|
| Status | verified |
| Run ID | `5acf8ff0bd9a` |
| Duration | 25.262 seconds |
| Project | `2992312a-3ee8-4c45-8331-1e2c0ca776f4` |
| Requirement | `041f6ac4-c38c-40fb-a758-9255a2cbee09` |
| Scenario | `cdb5bd45-e271-4b76-8cb0-513b82150c79` |
| Test case | `4f9155a6-d00f-4a67-9779-bf3b08deb4ac` |
| Impact analysis | `8ffa5540-9ecd-41e5-9ac9-aa38d9ea1cdf` |
| Requirement indexed | yes |
| Approved test case indexed | yes |
| Impact candidates | 1 |

The first live attempt exposed a real strict-structured-output incompatibility: OpenAI rejected the raw Pydantic
schema because nested objects did not explicitly disallow additional properties. The generation adapter now
normalizes every nested object to OpenAI's strict schema contract; a direct provider request and the full live
workflow both passed afterward.

## Pinecone reconciliation evidence

The live full-namespace maintenance audit reported:

- dimension: 1536;
- total vectors: 3;
- PostgreSQL expected vectors: 3;
- missing vectors: 0;
- orphan vectors: 0; and
- estimated raw dense-vector bytes: 18,432.

This is inventory/storage evidence, not a provider invoice or cost forecast.

## Capability evidence added in this release

- streamed, checkpointed, retryable mapped-import jobs;
- logical parent/child vector chunks with durable lifecycle tracking;
- hybrid generation retrieval and source-aware reranking;
- immutable mapping revisions and rollback;
- typed/validated custom fields with selective semantic weighting;
- requirement and test-case delta update policies;
- unresolved test-case staging and automatic story-link reconciliation;
- scheduled Jira delta synchronization;
- historical requirement comparison and explainable impact scoring;
- paginated fuzzy/stemmed search, synonyms, tuning policy, saved searches, judgments, analytics, and custom facets;
- scheduled vector drift repair, guarded orphan cleanup, and usage estimates; and
- removal of generation-time direct vector writes in favor of the transactional outbox.

## Remaining release conditions

Core generation and impact analysis are certified for this configured environment. Production sign-off still
requires the tenant-specific labeled dataset and whichever optional integrations the deployment will enable.
See [gaps-2026-10-22.md](gaps-2026-10-22.md).
