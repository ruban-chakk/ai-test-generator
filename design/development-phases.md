# Development Phases

## Phase 0: Discovery and enterprise design
- Define enterprise user stories, success criteria, and compliance requirements.
- Finalize the data model for requirements, scenarios, test cases, feedback, approvals, and audit trails.
- Choose the stack: React, Python, PostgreSQL, Pinecone.
- Draft UI flows, API contracts, and security policies.
- Plan the initial RAG prompt templates, retrieval schema, and feedback semantics.

## Phase 1: Enterprise foundation
- Implement secure requirement ingestion from file/Jira folder.
- Build PostgreSQL schema and backend models with enterprise data governance.
- Add Pinecone integration for embedding storage and retrieval.
- Create a React UI for requirement review, scenario management, and traceability.
- Build the first LLM generation pipeline for scenarios and test cases.
- Store generated drafts in the database with status and audit metadata.

## Phase 2: Review, approval, and governance
- Completed: Approval/rejection actions at requirement, scenario, and test case levels.
- Completed: UI controls for approve/reject, version status, guardrail validation, and audit history.
- Completed: Approved test cases are locked, assigned repository metadata, and prepared for vector indexing with stable vector IDs.
- Completed: Approved test case version snapshots and approval records are stored for traceability.
- Completed: Test case repository persistence workflow and change control guardrails are in place.

## Phase 3: Feedback, quality, and traceability
- Completed: Feedback modal for requirement, scenario, and test case comments.
- Completed: Feedback is stored in PostgreSQL with stable vector IDs for later retrieval embedding.
- Completed: Revision pipeline processes feedback context into traceable revision records.
- Completed: Feedback actions support generating new cases, revising existing content, and deprecating outdated cases.
- Completed: Feedback history, resolution state, revision trace, and audit trail are captured for continuous improvement.
- Completed: Quality evaluation metrics and guardrail scores are stored for generated and reviewed content.

## Phase 4: Impact analysis and enterprise risk
- Add similarity search across existing approved test cases.
- Define duplicate thresholds (80%) and identify candidate duplicates.
- Build deprecation/update recommendation logic.
- Surface impact analysis results in the UI.
- Automate new requirement comparison against approved repository content.
- Add risk and coverage insights for enterprise stakeholders.

## Phase 5: Integration, scale, and compliance
- Add Jira import automation and repository sync.
- Improve NLP cleanup for messy requirement text.
- Harden the LLM pipeline and add automated evals for quality.
- Add analytics, logging, performance optimizations, and operational monitoring.
- Implement security, compliance, and enterprise governance features.
- Refine UI usability and expand user permissions/workflows.
