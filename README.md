# AI Test Case Generator

An enterprise-grade full-stack solution for generating and managing test cases from requirement documents using RAG and LLMs.

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

1. Review the design documents
2. Choose backend and vector DB implementations
3. Build data model and API contract
4. Implement the UI review/approval flows
5. Add feedback and impact analysis services
