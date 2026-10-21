# AI Test Case Generator

An enterprise-grade full-stack solution for generating and managing test cases from requirement documents using RAG and LLMs.

## Implementation status

The end-to-end review workflow is implemented: database-backed authentication and project RBAC, manual/Jira/file
ingestion, OpenAI-compatible RAG generation, Pinecone indexing, keyword/semantic/hybrid search, approval/versioning,
feedback-driven revision, calibrated impact analysis, audit history, and durable repository delivery. Repository
delivery supports a generic idempotent HTTP contract, Xray Cloud, TestRail, and Zephyr Cloud. Generic OIDC login,
dependency probes, outbox recovery controls, durable automated execution, routed operational alerts, shared API
rate limits, project compliance evidence, component tests, and browser critical-path tests are also included.
Historical test cases can be imported in bulk from JSON/CSV, including resumable 250 MB streamed jobs. Logical
vector chunking, scheduled drift repair, unresolved-reference staging, configurable typed mappings, hybrid RAG,
search learning, and independently indexed immutable requirement and approved-case versions are included.
External features fail closed when their credentials are absent.

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
- `design/gaps-2026-10-22.md` — current implemented capabilities and remaining external validation gaps
- `design/release-evidence-2026-10-22.md` — current automated and live-provider verification evidence

## Suggested tech stack

- Frontend: React
- Backend: Python (FastAPI recommended)
- Metadata DB: PostgreSQL
- Vector DB: Pinecone
- LLM + embeddings: OpenAI / Anthropic / Azure OpenAI
- Evaluation: OpenAI evals or custom automated validation

## Production acceptance

The codebase includes sanitized dependency acceptance probes, a bounded load gate, and a guarded PostgreSQL
backup/restore drill. Run these against the target deployment and a disposable recovery database before release.
Real OIDC, Xray/TestRail/Zephyr, Pinecone, Jira, LLM, and runner credentials are intentionally not stored here;
tenant owners must supply them for live acceptance.
