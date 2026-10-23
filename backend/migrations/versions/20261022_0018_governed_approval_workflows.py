"""Add RAG knowledge documents and version-bound approval workflows.

Revision ID: 20261022_0018
Revises: 20261022_0017
Create Date: 2026-10-22
"""
from alembic import op


revision = "20261022_0018"
down_revision = "20261022_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          title varchar(500) NOT NULL,
          content text NOT NULL,
          source varchar(64) NOT NULL DEFAULT 'manual',
          status varchar(32) NOT NULL DEFAULT 'pending_index',
          vector_id varchar(512),
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_project ON knowledge_documents(project_id);
        CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status ON knowledge_documents(status);

        CREATE TABLE IF NOT EXISTS approval_workflow_runs (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          test_case_id uuid NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
          test_case_version integer NOT NULL,
          content_sha256 varchar(64) NOT NULL,
          policy_snapshot jsonb NOT NULL,
          status varchar(32) NOT NULL DEFAULT 'awaiting_evaluation',
          current_stage integer NOT NULL DEFAULT 0,
          quality_evaluation_id uuid REFERENCES quality_evaluations(id) ON DELETE SET NULL,
          created_by varchar(255) NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          completed_at timestamptz,
          CONSTRAINT uq_approval_workflow_artifact UNIQUE (test_case_id, test_case_version, content_sha256),
          CONSTRAINT ck_approval_workflow_stage CHECK (current_stage >= 0)
        );
        CREATE INDEX IF NOT EXISTS idx_approval_workflow_runs_project ON approval_workflow_runs(project_id);
        CREATE INDEX IF NOT EXISTS idx_approval_workflow_runs_case ON approval_workflow_runs(test_case_id);
        CREATE INDEX IF NOT EXISTS idx_approval_workflow_runs_status ON approval_workflow_runs(status);

        CREATE TABLE IF NOT EXISTS approval_workflow_decisions (
          id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          workflow_run_id uuid NOT NULL REFERENCES approval_workflow_runs(id) ON DELETE CASCADE,
          stage_index integer NOT NULL,
          stage_name varchar(255) NOT NULL,
          decision varchar(32) NOT NULL,
          decided_by varchar(255) NOT NULL,
          decided_role varchar(64) NOT NULL,
          notes text,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_approval_workflow_stage_actor UNIQUE (workflow_run_id, stage_index, decided_by),
          CONSTRAINT ck_approval_workflow_decision CHECK (decision IN ('approved', 'rejected')),
          CONSTRAINT ck_approval_workflow_decision_stage CHECK (stage_index >= 0)
        );
        CREATE INDEX IF NOT EXISTS idx_approval_workflow_decisions_run
          ON approval_workflow_decisions(workflow_run_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS approval_workflow_decisions")
    op.execute("DROP TABLE IF EXISTS approval_workflow_runs")
    op.execute("DROP TABLE IF EXISTS knowledge_documents")
