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
- embedding and indexing of generated output for future retrieval

The pipeline supports feedback-informed revision by including user feedback and approved test cases as retrieval context.

### 5. Integrations

The initial enterprise design includes:
- Jira Cloud JQL ingestion through the REST API
- Test case repository persistence for approved cases
- Xray Cloud and TestRail adapters publish immutable approved versions; Zephyr remains a future integration

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

## Scalability considerations

- Pinecone handles growth in embedding volume and similarity search.
- PostgreSQL indexes and partitioning support large metadata volumes.
- The service architecture should separate UI, API, and vector lookup for horizontal scaling.
- Audit logs and history data should be archivable to reduce hot storage cost.

## Operational monitoring

- Monitor API latency, queue times, LLM call success, and vector search performance.
- Alert on failed generation, feedback processing, or indexing operations.
- Track repository sync success and Pinecone index health.
