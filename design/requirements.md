# Requirements Document

## Project name
AI Test Case Generator for Enterprise Requirements

## Purpose
Build an enterprise-grade application that generates, reviews, approves, and manages software test cases from requirement documents using retrieval-augmented generation (RAG) and large language models (LLMs). The system must support auditability, versioning, feedback-driven revision, impact analysis, and integration with enterprise Jira and test case repositories.

## Stakeholders
- Product Managers
- QA Managers
- Test Engineers
- Development Teams
- Compliance and Governance Teams
- IT Operations

## Goals
- Automate generation of test scenarios and test cases from requirement descriptions.
- Reuse historical test cases and requirements through vector search.
- Provide a reviewable web UI for approval, rejection, and feedback.
- Store approved cases in a test case repository and index them in Pinecone.
- Track requirement, scenario, and test case relationships and versions.
- Enable impact analysis for new requirements.
- Support enterprise security, audit, and governance requirements.

## Scope
### In scope
- Requirement ingestion from Jira Cloud JQL, validated UTF-8 files, or manual entry.
- Generation of test plans, scenarios, and test cases with metadata tags.
- Review UI with approval/rejection at requirement, scenario, and test case levels.
- Feedback capture at requirement, scenario, and test case levels.
- Storing metadata and relationships in PostgreSQL.
- Storing embeddings and similarity search in Pinecone.
- Versioning and audit history for approved test cases.
- Impact analysis for duplicates, deprecations, and updates.

### Out of scope
- Domain-specific test automation code generation.
- Payment collection, invoicing, and external subscription billing. AI usage and calculated cost reporting are in scope.

## Functional requirements

### Requirement ingestion
- FR1: The system shall ingest Jira Cloud issues selected by JQL, accept manual requirements, or import bounded
  UTF-8 TXT, Markdown, CSV, and JSON files.
- FR2: The system shall normalize and clean requirement text for LLM processing.
- FR3: The system shall store requirement metadata, including source, external ID, title, and description.

### Test generation
- FR4: The system shall generate test scenarios and test cases from a requirement using RAG.
- FR5: The system shall include metadata tags for each scenario and test case: prerequisite, priority, severity, category, type.
- FR6: The system shall produce test case steps with numbered actions and expected results.
- FR7: The system shall persist generated content as draft until reviewed.
- FR7a: Every generated or manually edited test case shall enqueue an idempotent, version-bound quality evaluation
  without rolling back the saved draft when the judge is temporarily unavailable.
- FR7b: Authorized project users shall be able to manually edit test-case metadata and the complete ordered step list.
  Editing an approved case shall preserve its immutable approved snapshot and create a new draft version.

### Review and approval
- FR8: The system shall display requirements, scenarios, and test cases in a reviewable React UI.
- FR9: The system shall allow users to approve or reject at the requirement, scenario, and test case levels.
- FR10: The system shall record approval decisions and version each approved test case.
- FR11: The system shall push approved test cases to a test case repository and index them in Pinecone.

### Feedback
- FR12: The system shall provide a feedback button for requirements, scenarios, and test cases.
- FR13: The system shall open a feedback modal to capture user comments and intent.
- FR14: The system shall store feedback in PostgreSQL and as embeddings in Pinecone.
- FR15: The system shall use feedback context to revise or generate test cases in subsequent iterations.
- FR15a: A reviewer shall be able to submit a test-case evaluation and its metric evidence as feedback, regenerate
  the linked test case, and optionally run a new version-bound evaluation on the result.
- FR15b: DeepEval metric evidence shall be attached to LLM feedback only through an explicit reviewer checkbox.
  When unchecked, the feedback and regeneration prompt shall not contain the evaluation record or metric evidence.

### Impact analysis
- FR16: The system shall identify duplicate test cases based on similarity >= 80%.
- FR17: The system shall recommend existing test cases for deprecation when the new requirement makes them obsolete.
- FR18: The system shall recommend existing test cases for update when they overlap with the new requirement.
- FR19: The system shall present impact analysis results in the UI.

### Search and retrieval
- FR20: The system shall store searchable current-record embeddings for test cases in every workflow state and retain
  immutable approved-version embeddings for governed RAG retrieval.
- FR21: Test-case evidence supplied to test-case generation or regeneration shall be limited to approved test cases;
  requirements, feedback, and approved supporting evidence remain eligible under their own retrieval policies.
- FR22: The system shall support similarity search for duplicate detection and impact analysis.
- FR23: The web application shall provide project-scoped keyword, semantic, and hybrid search over requirements,
  test cases in every workflow state, and feedback. Users shall be able to select all, approved-only, or
  unapproved-only test cases. Hybrid ranking shall preserve evidence from both retrieval methods.
- FR24: The system shall bulk-import historical test cases, scenarios, and steps with stable external identities,
  atomic audit evidence, conflict detection, and asynchronous vector indexing.
- FR25: The system shall reconcile missing vector-index events from canonical PostgreSQL records and index each
  approved test-case version from its immutable snapshot.
- FR26: The system shall support reusable project-scoped import mapping profiles for company-specific JSON and CSV
  requirement and historical test-case formats, with preview, allow-listed transforms, custom fields, audit evidence,
  and transactional vector-index intents.
- FR27: The system shall isolate administration into app, organization, and project scopes. App administrators have
  complete application control; organization and project administrators cannot grant themselves or others a higher scope.
- FR28: Organizations shall contain users and multiple projects. Every project shall belong to one organization and
  carry a cost-center identifier.
- FR29: Authorized administrators shall create users, issue expiring single-use invitations, and assign global,
  organization, and project roles through server-enforced policies.
- FR30: Authorized administrators shall configure generation, judge, embedding, and vector-store settings at app,
  organization, or project scope without exposing raw credentials to the browser.
- FR31: The system shall record provider token usage, immutable rate snapshot, pricing source, and calculated cost per
  organization, project, operation, user, and model, and expose scoped cost summaries and unpriced-model warnings.
- FR32: Every generated test-case evaluation shall expose weighted requirement coverage, grounding, correctness,
  completeness, relevance, hallucination rate, executability, boundary/negative coverage, and traceability metrics
  with red/amber/green status and evidence-based justification.

## Non-functional requirements

### Performance
- NFR1: The backend shall respond to UI requests within 2 seconds for standard queries.
- NFR2: Vector similarity search shall return results within 500ms for up to 10k indexed items.

### Security
- NFR3: The system shall authenticate users and enforce role-based access control.
- NFR4: The system shall protect requirement and test case data at rest and in transit.
- NFR5: The system shall log all approval and feedback actions for audit.

### Scalability
- NFR6: The system shall scale to support multiple teams and thousands of requirements/test cases.
- NFR7: The system shall support adding new embeddings and reindexing without downtime.

### Reliability and auditability
- NFR8: The system shall preserve version history for all approved test cases.
- NFR9: The system shall persist all feedback and review decisions for traceability.
- NFR10: The system shall gracefully handle failed LLM calls and provide retry paths.

### Usability
- NFR11: The UI shall present requirement, scenario, and test case hierarchies clearly.
- NFR12: The UI shall make approval and feedback actions easy to perform.
- NFR13: The system shall clearly label draft, approved, deprecated, and updated statuses.

## Data model summary
- Requirement -> TestScenario -> TestCase -> TestCaseStep
- Feedback associated to Requirement, TestScenario, or TestCase
- ApprovalRecord associated to Requirement, TestScenario, or TestCase
- Embeddings stored in Pinecone for Requirement, TestScenario, TestCase, Feedback
- Metadata stored in PostgreSQL for all entities, versions, and audit actions

## User stories
- As a QA manager, I want to generate test cases from a requirement so I can reduce manual test design effort.
- As a product owner, I want to review and approve generated test cases so quality is controlled.
- As a tester, I want to provide feedback on a test case so the generator improves future output.
- As an architect, I want duplicate and deprecation recommendations so I can maintain test coverage efficiently.
- As a compliance lead, I want audit history for approvals and feedback so I can prove governance.

## Acceptance criteria
- AC1: A requirement document can be ingested and stored with metadata.
- AC2: The system can generate draft test scenarios and test cases for that requirement.
- AC3: A user can view and approve test cases in the UI.
- AC4: Approved test cases are versioned and indexed in Pinecone.
- AC5: Feedback can be captured and used to rerun generation.
- AC6: The system can identify duplicate cases with similarity >= 80%.
- AC7: Approval and feedback actions are auditable.

## Risks and assumptions
- Requirements may be poorly written and may need NLP cleanup.
- LLM-generated content may hallucinate, so human review is required.
- Similarity thresholds may require tuning for actual enterprise data.
- Pinecone costs and indexing limits must be managed for scale.
- Vendor APIs and tenant custom fields must be validated before each production rollout.

## Next steps
- Review and validate requirements with stakeholders.
- Define technical architecture and API contracts.
- Implement schema, backend, and UI components aligned with enterprise needs.
- Build LLM prompt templates and retrieval pipelines.
- Test with real requirement documents and iteratively refine similarity rules.
