# AI Test Case Generator

An enterprise-grade full-stack solution for generating and managing test cases from requirement documents using RAG and LLMs.

## Implementation status

The end-to-end review workflow is implemented: database-backed authentication and project RBAC, manual/Jira/file
ingestion, OpenAI-compatible RAG generation, Pinecone indexing and semantic search, approval/versioning,
feedback-driven revision, impact analysis, audit history, and durable repository delivery. Repository delivery
supports a generic idempotent HTTP contract, Xray Cloud, and TestRail. Generic OIDC login, dependency probes,
outbox recovery controls, durable automated execution through a configured runner, component tests, and mocked
browser critical-path tests are also included. External features fail closed when their credentials are absent.

## Goal

Create an enterprise-ready system that:
- ingests requirements from Jira or files
- uses vector search over existing requirements and approved test cases
- generates test scenarios and test cases with metadata tags
- displays them in a reviewable web UI
- supports approval, versioning, and persistence to a repository + vector DB
- accepts multi-level feedback and revises generated cases
- performs impact analysis on new requirements
- includes governance, auditability, and scalability for enterprise usage

## What is included

- `design/implementation-plan.md` — overall architecture, workflow, and MVP strategy
- `design/data-model.md` — concrete entity definitions and relationships
- `design/ui-flows.md` — the UI experience, approval/review/feedback patterns

## Suggested tech stack

- Frontend: React
- Backend: Python (FastAPI recommended)
- Metadata DB: PostgreSQL
- Vector DB: Pinecone
- LLM + embeddings: OpenAI / Anthropic / Azure OpenAI
- Evaluation: OpenAI evals or custom automated validation

## Next steps

1. Calibrate semantic impact thresholds against labeled enterprise examples.
2. Expand browser coverage beyond the operations/import critical path.
3. Add Zephyr Cloud after validating a tenant-specific public API contract.
4. Add alert routing, rate limits, load tests, and disaster-recovery exercises.
5. Validate OIDC, Xray, and TestRail against the target enterprise tenants before production rollout.
