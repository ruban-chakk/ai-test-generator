# Development Phases

## Phase 0: Discovery and enterprise design
- Define enterprise user stories, success criteria, and compliance requirements.
- Finalize the data model for requirements, scenarios, test cases, feedback, approvals, and audit trails.
- Choose the stack: React, Python, PostgreSQL, Pinecone.
- Draft UI flows, API contracts, and security policies.
- Plan the initial RAG prompt templates, retrieval schema, and feedback semantics.

## Phase 1: Enterprise foundation
- Implement secure requirement ingestion from manual entry and Jira Cloud JQL.
- Build PostgreSQL schema and backend models with enterprise data governance.
- Add Pinecone integration for embedding storage and retrieval.
- Create a React UI for requirement review, scenario management, and traceability.
- Build the first LLM generation pipeline for scenarios and test cases.
- Store generated drafts in the database with status and audit metadata.

## Phase 2: Review, approval, and governance
- Prototype: Approval/rejection actions at requirement, scenario, and test case levels.
- Prototype: UI controls for approve/reject, version status, guardrail validation, and audit history.
- Implemented: Approved test cases are locked and indexed through a retryable transactional outbox.
- Implemented: Test case version snapshots and approval records are stored for traceability.
- Implemented: database-backed users, revocable bearer/HttpOnly-cookie sessions, authenticated audit actors,
  global RBAC, and project membership checks on requirement/test workflow endpoints.
- Implemented: Project-scoped approved cases are delivered through a credential-driven, idempotent HTTP repository adapter.
- Implemented: standards-based OIDC federation with signed browser state, nonce validation, domain allowlisting,
  and least-privilege optional provisioning.
- Implemented: retry-safe Xray Cloud and TestRail repository adapters in addition to the generic HTTP adapter.

## Phase 3: Feedback, quality, and traceability
- Prototype: Feedback modal and PostgreSQL persistence at requirement, scenario, and test case levels.
- Implemented: approved-case and feedback embedding/indexing through an idempotent transactional outbox worker.
- Implemented: Feedback-informed regeneration retrieves project-scoped vector context and produces schema-validated drafts.
- Prototype: Revision records and actions for new, revised, and deprecated cases.
- Implemented: Feedback history, resolution state, revision trace, and audit records.
- Prototype: Rule-based quality evaluation metrics and guardrail scores.

## Phase 4: Impact analysis and enterprise risk
- Implemented: project-scoped embedding similarity search and the 80% duplicate threshold.
- Prototype: Heuristic deprecation/update recommendations and risk/coverage scores.
- Implemented: Impact analysis results are surfaced in the requirement detail UI.
- Pending production work: calibrate semantic thresholds and deprecation classification against labeled data.

## Phase 5: Integration, scale, and compliance
- Implemented: Project-scoped Jira Cloud JQL ingestion with paginated issue upserts and vector-index outbox events.
- Implemented: Project-scoped repository sync queues per-case delivery events and records truthful queued/completed/failed status.
- Prototype: NLP cleanup, validation, quality scoring, metrics, and monitoring summaries.
- Prototype: Governance policy storage and operations UI.
- Implemented: real dependency probes, liveness/readiness endpoints, outbox inspection, and admin retry controls.
- Implemented: bounded file ingestion, project-scoped semantic search, component tests, and a browser critical path.
- Implemented: project-scoped automated execution of approved immutable test-case versions through a retryable,
  credential-driven runner contract, with durable run history and UI controls.
- Pending production work: alert routing, rate limiting, tenant-specific compliance controls, semantic calibration,
  expanded browser coverage, load testing, and recovery exercises.
