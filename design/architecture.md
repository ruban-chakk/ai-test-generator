# Technical Architecture

## Overview

This project is an enterprise-grade AI test case generation platform built with:
- React frontend for a rich review and approval experience
- Python backend for orchestration, API, and data workflows
- PostgreSQL for structured metadata and audit data
- Pinecone for embeddings-based retrieval and similarity search
- LLM provider for embeddings and generation
- Docker for local PostgreSQL and application services; Pinecone is an externally provisioned data-plane service

The architecture is designed for enterprise quality, auditability, and scalability.

## Core components

### 1. Frontend

The React frontend is the primary user interface and supports:
- requirement review, navigation, and search
- test scenario and test case discovery
- approval/rejection workflows
- feedback capture
- impact analysis dashboards
- audit history and version tracking

The UI exposes a rich card-based experience with collapsible hierarchies, tag chips, status indicators, and contextual action menus.

### 2. Backend API

The Python backend is responsible for:
- ingesting requirements from Jira Cloud JQL or manual entry
- storing metadata in PostgreSQL
- coordinating LLM-driven generation and RAG retrieval
- writing and updating Pinecone embeddings
- handling approvals, feedback, versioning, and audit logs
- serving REST endpoints for the React UI

A recommended implementation is FastAPI with an async PostgreSQL client and a Pinecone client for vector operations.

### 3. Data layer

#### PostgreSQL

PostgreSQL stores:
- Requirements, scenarios, test cases, and steps
- Feedback entries
- Approval records and version history
- User and role information
- Audit logs and operation metadata
- Organizations, scoped memberships, invitations, project cost centers, effective AI configuration, and usage cost records

#### Pinecone

Pinecone stores embeddings for:
- requirements
- test scenarios
- test cases
- feedback items

The vector store enables retrieval-based generation, duplicate detection, and impact analysis.

### 4. LLM/RAG pipeline

The AI pipeline includes:
- embedding generation for requirement text and historical test artifacts
- retrieval of closest relevant documents from Pinecone
- prompt assembly using retrieved context and requirement data
- generation of test scenarios, cases, and steps
- embedding generated and edited test cases into a current-record Search projection in every workflow state
- retaining immutable approved-version vectors as the only test-case evidence eligible for generation RAG

The pipeline supports feedback-informed revision by including user feedback and approved test cases as retrieval context.
Dedicated Search is intentionally broader: it queries current test-case projections across all states and can filter
them to approved or unapproved records without weakening the generation retrieval boundary.

### 5. Integrations

The initial enterprise design includes:
- Jira Cloud JQL ingestion through the REST API
- Test case repository persistence for approved cases
- Xray Cloud, TestRail, and Zephyr Cloud adapters publish immutable approved versions using stable delivery references

## Data flow

1. Requirement ingestion: user uploads or imports a requirement.
2. Requirement is stored in PostgreSQL and embedded into Pinecone.
3. Generation pipeline retrieves relevant history from Pinecone.
4. LLM generates test scenarios and test cases.
5. Drafts are saved in PostgreSQL with `draft` status.
6. UI renders draft results for review.
7. User approves/rejects cases and submits feedback.
8. Approved cases are versioned, persisted to repository, and indexed in Pinecone.
9. Impact analysis uses Pinecone similarity search against approved artifacts.

## Deployment and containerization

A Docker Compose environment should provision:
- `postgres` for metadata storage
- an externally provisioned Pinecone index configured by data-plane host
- optional backend and frontend services for development

This keeps the enterprise stack reproducible in development and testing.

## Security and governance

Key enterprise capabilities:
- role-based access control for review and approval actions
- audit logging for every generation, approval, feedback, and data change
- secure storage and transport for sensitive requirement/test data
- versioning of approved test cases for traceability
- feedback traceability from requirement to test case revisions
- non-inheriting app, organization, and project administrator scopes enforced by API authorization checks
- secret references instead of raw provider credentials in browser-visible configuration records
- single-use invitation tokens stored only as SHA-256 hashes and returned only at creation time

## Administration and AI cost

Configuration resolves from project to organization to application scope. A lower scope can override model names,
vector routing, evaluation weights, and pricing, but it never gains permission to mutate a higher scope. Provider usage
is persisted with organization, project, actor, operation, model, input/output tokens, the applied rate snapshot,
pricing source, and calculated micro-dollar cost. Scoped rates override a versioned catalog fallback; unknown models
remain visibly unpriced. The cost ledger is authoritative for dashboards; browser calculations are presentation-only.

DeepEval feedback links directly to the immutable quality-evaluation record. Revision generation receives the target,
requirement, linked metric evidence, reviewer instruction, and project RAG context. Regeneration and subsequent
evaluation remain separate durable commands so a judge outage cannot roll back an already completed revision.
The browser must explicitly opt in before linking that evaluation; ordinary feedback has no evaluation foreign key and
the revision prompt receives no DeepEval payload. New generated versions and manual edits atomically enqueue a
`test_case.quality_evaluation_requested` outbox event. The worker records the source event on the evaluation with a
unique constraint, making retries idempotent while keeping draft persistence independent of the external judge.

Manual editing uses optimistic version checks and replaces the full ordered step collection in one database transaction.
An edit resets the mutable case to draft, invalidates its prior approval workflow, and queues evaluation; immutable
approved `test_case_versions` remain unchanged for audit and repository traceability.

## Scalability considerations

- Pinecone handles growth in embedding volume and similarity search.
- PostgreSQL indexes and partitioning support large metadata volumes.
- The service architecture should separate UI, API, and vector lookup for horizontal scaling.
- Audit logs and history data should be archivable to reduce hot storage cost.

## Operational monitoring

- Monitor API latency, queue times, LLM call success, and vector search performance.
- Alert on failed generation, feedback processing, or indexing operations.
- Track repository sync success and Pinecone index health.
### Prompt and configuration governance

Prompt templates are stored as versioned `PromptConfiguration` records with
application, organization, and project scopes. Runtime resolution is
project-first, then organization, then application default. Configuration
mutations are committed with an `AuditLog` row containing actor, timestamp,
scope, old value, and new value in the same transaction. The resolver is used
by generation, feedback regeneration, and LLM-as-judge evaluation.
