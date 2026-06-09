# AI Test Case Generator - Implementation Plan

## Overview

This system combines RAG with LLM generation and a human-in-the-loop review workflow to produce enterprise-grade test cases from requirement documents. The focus is on:
- requirement-centric generation
- scenario and test-case metadata
- multi-level feedback
- approval + versioned persistence
- duplicate / impact analysis
- governance, auditability, and security for enterprise operations

## Core architecture

1. Requirement ingestion
2. Vector retrieval of existing requirements and approved test cases
3. LLM generation of scenarios and test cases
4. Review UI for approval, rejection, and feedback
5. Approved persistence to test repo and vector DB
6. Impact analysis for duplicates, deprecations, and updates

## Data model summary

- Requirements link to test scenarios and test cases
- Test scenarios are grouped under requirements
- Test cases are grouped under test scenarios
- Feedback can attach to requirements, scenarios, or cases
- Approved test cases are versioned
- Both metadata and vector embeddings are stored

## RAG and generation flow

1. User submits or ingests a requirement.
2. Backend creates a requirement record and embeds the text.
3. Vector retrieval finds matching requirements and approved test cases.
4. Retrieved context is fed into the LLM prompt.
5. LLM returns:
   - a test plan outline
   - scenarios
   - test cases with tags and steps
6. Generated content is stored in draft status.
7. UI displays the generated draft for review.

## Approval workflow

1. A requirement is reviewed in the UI.
2. Users can approve or reject at three levels:
   - requirement/test plan
   - scenario
   - individual test case
3. Approval actions for a test case:
   - mark as `approved`
   - version and lock the approved version
   - save to test case repository
   - index into vector DB
4. Rejection or revision keeps the case in draft until reworked.
5. The requirement itself is also added to the vector DB after generation.

## Feedback workflow

1. A feedback button opens a modal on the requirement, scenario, or test case.
2. Feedback entries include:
   - target level (requirement / scenario / test case)
   - comment text
   - intent (revise / generate new / deprecate / accept)
3. Feedback is persisted in both RDBMS and vector DB.
4. The LLM pipeline re-runs generation with feedback context.
5. The system can:
   - update existing test cases
   - generate new cases
   - revise scenarios
   - deprecate outdated cases

## Impact analysis flow

For a new requirement, the system should answer:
1. Are there duplicate test cases? (similarity >= 80%)
2. Which existing test cases should be deprecated?
3. Which existing test cases should be updated?

Implementation:
- compute embeddings for the new requirement and generated cases
- search against approved test cases
- apply similarity thresholds
- use an LLM to classify candidates as duplicate / deprecated / update

## Implementation phases

See `design/development-phases.md` for a detailed enterprise-grade roadmap.

### Phase 1: Foundation
- Requirement ingestion and enterprise metadata model
- Pinecone vector search and PostgreSQL persistence
- React/Python review UI
- Secure user authentication and access controls
- Audit logging for generation and review events

### Phase 2: Review and governance
- Completed: Approval and rejection actions across requirement, scenario, and test case levels
- Completed: Versioning, history, and audit trails for approved test cases
- Completed: Feedback capture, tracking, and enterprise reporting surfaces
- Completed: Data validation and guardrails to minimize hallucination

### Phase 3: Feedback and adaptation
- Feedback-driven revision pipeline
- Multi-level feedback semantics and workflow
- Enterprise feedback history and traceability
- Metrics and quality evaluation for generated content

### Phase 4: Impact analysis and compliance
- Duplicate / deprecate / update recommendations
- Requirement impact analysis for risk and coverage
- Policy controls for depreciation and retention
- Integration with enterprise evaluation and governance tooling

### Phase 5: Integration and scale
- Jira import automation and test repo synchronization
- Enterprise NLP cleanup and validation
- Performance, horizontal scale, and Pinecone optimization
- Security, compliance, and operational monitoring
